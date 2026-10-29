# Copyright 2026 SV1TSD
# Licensed under the GNU General Public License, version 3 or later.
"""Radtel RT-400 clone driver, based on CPS IL, USB capture, and live backups.

Standalone CHIRP module: no local helper modules or external data files needed.
Only OEM-observed addresses are uploaded. Unedited raw bytes are preserved.
"""
import logging
import struct
import time
from decimal import Decimal, InvalidOperation

from chirp import chirp_common, directory, errors, memmap
from chirp.settings import (RadioSettings, RadioSetting, RadioSettingGroup,
                            RadioSettingValueBoolean, RadioSettingValueInteger,
                            RadioSettingValueList, RadioSettingValueString)

LOG = logging.getLogger(__name__)
MAGIC = b'PROGRAMJC81U'
IDENT = bytes.fromhex('0136018004000520')
BLOCK_SIZE = 64
IMAGE_SIZE = 0xB300
ADDRESSES = (tuple(range(0, 0x2000, 64)) + (0x8000, 0x9000) +
             tuple(range(0xA000, 0xA140, 64)) +
             tuple(range(0xB000, 0xB300, 64)))
DCS_CODES = (
    23,
    25,
    26,
    31,
    32,
    36,
    43,
    47,
    51,
    53,
    54,
    65,
    71,
    72,
    73,
    74,
    114,
    115,
    116,
    122,
    125,
    131,
    132,
    134,
    143,
    145,
    152,
    155,
    156,
    162,
    165,
    172,
    174,
    205,
    212,
    223,
    225,
    226,
    243,
    244,
    245,
    246,
    251,
    252,
    255,
    261,
    263,
    265,
    266,
    271,
    274,
    306,
    311,
    315,
    325,
    331,
    332,
    343,
    346,
    351,
    356,
    364,
    365,
    371,
    411,
    412,
    413,
    423,
    431,
    432,
    445,
    446,
    452,
    454,
    455,
    462,
    464,
    465,
    466,
    503,
    506,
    516,
    523,
    526,
    532,
    546,
    565,
    606,
    612,
    624,
    627,
    631,
    632,
    645,
    654,
    662,
    664,
    703,
    712,
    723,
    731,
    732,
    734,
    743,
    754)
PTT_ID = ['Off', 'Beginning', 'End', 'Both']
SCRAMBLER = ['Off', 'Scrambler 1', 'Scrambler 2']
FHSS = ['Off', 'DCP 1', 'DCP 2', 'DCP 3']
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]


class _NamedPowerLevel(chirp_common.PowerLevel):
    """Distinct hardware selections without inventing unmeasured wattages."""

    def __eq__(self, other):
        if isinstance(other, chirp_common.PowerLevel):
            return str(self) == str(other)
        return False

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(str(self))


# Equal nominal dBm values in the base class must not collapse H/L/M choices.
POWER_LEVELS = [_NamedPowerLevel(x) for x in ('High', 'Low', 'Medium')]
DTMF_CHARS = '0123456789ABCD*#'
KEYS = ['None', 'FM radio', 'Scan', 'Frequency search', 'Flashlight',
        'Weather', 'Monitor', 'SOS', 'PTT B']
KEY_CODES = [255, 7, 28, 29, 8, 12, 5, 3, 1]
DRIVER_REVISION = '2026-10-29.3'
AIRBAND = (108000000, 136000000)
TX_BANDS = [(136000000, 174000000), (220000000, 235000000),
            (350000000, 390000000), (400000000, 470000000)]
_NAME_CHARSET = None


def _name_charset():
    global _NAME_CHARSET
    if _NAME_CHARSET is None:
        chars = [chr(i) for i in range(32, 127)]
        for first in range(0xA1, 0xF8):
            for second in range(0xA1, 0xFF):
                try:
                    chars.append(bytes([first, second]).decode('gb2312'))
                except UnicodeDecodeError:
                    pass
        _NAME_CHARSET = ''.join(chars)
    return _NAME_CHARSET


def _frequency(raw):
    if raw in (b'\xff' * 4, b'\x00' * 4):
        return 0
    if len(raw) != 4 or any((b & 15) > 9 or b >> 4 > 9 for b in raw):
        raise errors.InvalidDataError('Invalid RT-400 BCD frequency')
    return int(''.join('%02x' % b for b in reversed(raw))) * 10


def _frequency_bytes(hz):
    if not isinstance(hz, int) or hz < 0 or hz > 999999990 or hz % 10:
        raise errors.InvalidValueError('Frequency must have 10 Hz resolution')
    digits = '%08d' % (hz // 10)
    return bytes(int(digits[i:i + 2], 16) for i in (6, 4, 2, 0))


def _tone(raw):
    word = struct.unpack('<H', raw)[0]
    if word in (0, 65535):
        return ('', None, None)
    if word < 256:
        if word > 210:
            raise errors.InvalidDataError('Unknown RT-400 DCS index')
        return ('DTCS', DCS_CODES[(word - 1) % 105],
                'N' if word <= 105 else 'R')
    return ('Tone', word / 10.0, None)


def _tone_bytes(tone):
    mode, value, polarity = tone
    if not mode:
        return b'\x00\x00'
    if mode == 'DTCS':
        if value not in DCS_CODES or polarity not in ('N', 'R'):
            raise errors.UnsupportedToneError('Unsupported DCS code/polarity')
        word = DCS_CODES.index(value) + 1 + (105 if polarity == 'R' else 0)
    elif mode == 'Tone':
        n = Decimal(str(value)) * 10
        if n != int(n) or not 256 <= n < 65535:
            raise errors.UnsupportedToneError('Invalid CTCSS tone')
        word = int(n)
    else:
        raise errors.UnsupportedToneError('Unsupported tone mode')
    return struct.pack('<H', word)


def _display_tone(raw):
    try:
        return _tone(raw)
    except errors.InvalidDataError:
        LOG.warning('Unrecognized tone word; retaining its raw bytes')
        return ('', None, None)


def _name(raw):
    raw = raw.split(b'\xff', 1)[0].split(b'\x00', 1)[0]
    return raw.decode('gb2312', errors='replace').replace('\ufffd', '?')


def _name_bytes(text, size):
    try:
        data = text.encode('gb2312')
    except UnicodeEncodeError as exc:
        raise errors.InvalidValueError(
            'Name is not representable in GB2312') from exc
    if len(data) > size:
        raise errors.InvalidValueError('Name exceeds %i encoded bytes' % size)
    return data.ljust(size, b'\xff')


def _dtmf(raw):
    chars = []
    for b in raw:
        if b == 255:
            break
        if b >= len(DTMF_CHARS):
            raise errors.InvalidDataError('Unrecognized DTMF symbol')
        chars.append(DTMF_CHARS[b])
    return ''.join(chars)


def _dtmf_bytes(text, size):
    text = text.upper()
    if len(text) > size or any(c not in DTMF_CHARS for c in text):
        raise errors.InvalidValueError('Invalid DTMF code')
    return bytes(DTMF_CHARS.index(c) for c in text).ljust(size, b'\xff')


def _digits(raw, multiplier):
    if any(b > 9 for b in raw):
        raise errors.InvalidDataError('Unrecognized VFO decimal digits')
    return int(''.join(str(b) for b in raw)) * multiplier


def _digit_bytes(text, count, multiplier):
    try:
        n = Decimal(str(text)) * 1000000 / multiplier
    except InvalidOperation as exc:
        raise errors.InvalidValueError('Enter a frequency in MHz') from exc
    if not n.is_finite() or n != int(n) or not 0 <= n < 10 ** count:
        raise errors.InvalidValueError('Invalid frequency or resolution')
    return bytes(int(c) for c in ('%0*d' % (count, int(n))))


class _Protocol:
    def __init__(self, pipe):
        self.pipe = pipe
        self.entered = False
        self.received_any = False

    def send(self, data):
        count = self.pipe.write(data)
        if count not in (None, len(data)):
            raise errors.RadioError('Short write to the programming cable')
        if hasattr(self.pipe, 'flush'):
            self.pipe.flush()

    def receive(self, count):
        data = bytearray()
        deadline = time.monotonic() + 2.0
        while len(data) < count:
            chunk = self.pipe.read(count - len(data))
            if chunk:
                self.received_any = True
                data.extend(chunk)
            if time.monotonic() >= deadline and len(data) < count:
                if not self.received_any:
                    raise errors.RadioNoResponse()
                raise errors.RadioError('Incomplete reply from the RT-400')
        return bytes(data)

    def enter(self):
        self.pipe.baudrate = 57600
        self.pipe.bytesize = 8
        self.pipe.parity = 'N'
        self.pipe.stopbits = 1
        self.pipe.timeout = 0.1
        self.pipe.write_timeout = 2
        self.pipe.xonxoff = False
        self.pipe.rtscts = False
        self.pipe.dsrdtr = False
        self.pipe.rts = False
        self.pipe.dtr = False
        # Late exit ACKs must not be mistaken for the new handshake ACK.
        time.sleep(0.15)
        if hasattr(self.pipe, 'reset_input_buffer'):
            self.pipe.reset_input_buffer()
        self.send(MAGIC)
        if self.receive(1) != b'\x06':
            raise errors.RadioError(
                'RT-400 rejected the programming handshake')
        self.entered = True
        self.send(b'F')
        if self.receive(8) != IDENT:
            raise errors.RadioError(
                'Radio identity does not match this RT-400 driver')

    def read_block(self, address):
        header = b'R' + struct.pack('>HB', address, BLOCK_SIZE)
        self.send(header)
        response = self.receive(68)
        if response[:4] != header:
            raise errors.RadioError('Wrong block header at 0x%04X' % address)
        time.sleep(0.003)
        return response[4:]

    def write_block(self, address, data):
        if address not in ADDRESSES or len(data) != BLOCK_SIZE:
            raise errors.RadioError('Refusing a write outside the RT-400 map')
        self.send(b'W' + struct.pack('>HB', address, BLOCK_SIZE) + data)
        if self.receive(1) != b'\x06':
            raise errors.RadioError('RT-400 rejected block 0x%04X' % address)
        time.sleep(0.003)

    def finish_read(self):
        if self.entered:
            self.send(b'E')
            self.entered = False
            time.sleep(0.25)


# Byte, mask, label and CPS menu order. Reserved bits remain untouched.
GENERAL = [
    ('sql', 0x00, 0x0F, 'Squelch', [str(i) for i in range(10)]),
    ('save', 0x01, 0x03, 'Battery saver', ['Off', 'Normal', 'Super', 'Deep']),
    ('vox', 0x02, 0x0F, 'VOX', ['Off'] + [str(i) for i in range(1, 10)]),
    ('backlight', 0x03, 0x0F, 'Backlight', ['Always on', '5 s', '10 s', '15 s',
                                            '20 s', '30 s', '1 min',
                                            '2 min', '3 min']),
    ('tot', 0x05, 0x0F, 'Transmit timeout', [
     'Off'] + ['%i s' % i for i in range(30, 241, 30)]),
    ('voice', 0x07, 0x01, 'Voice prompts', ['Off', 'On']),
    ('language', 0x08, 0x01, 'Voice language', ['English', 'Chinese']),
    ('sidetone', 0x09, 0x03, 'DTMF sidetone',
     ['Off', 'Keys', 'ANI', 'Keys and ANI']),
    ('scan', 0x0A, 0x0F, 'Scan resume', ['Time', 'Carrier', 'Search']),
    ('global_pttid', 0x0B, 0x03, 'Global PTT-ID', PTT_ID),
    ('id_delay', 0x0C, 0x0F, 'PTT-ID delay',
     ['0 ms', '100 ms', '200 ms', '400 ms', '600 ms', '800 ms', '1000 ms']),
    ('display_a', 0x0D, 0x0F, 'Display A', [
     'Name', 'Frequency', 'Channel number']),
    ('display_b', 0x0E, 0x0F, 'Display B', [
     'Name', 'Frequency', 'Channel number']),
    ('keylock', 0x10, 0x03, 'Automatic keypad lock',
     ['Off', '5 s', '10 s', '15 s']),
    ('alarm', 0x11, 0x0F, 'Alarm mode', [
     'Local', 'Transmit sound', 'Transmit code']),
    ('tdr_tx', 0x13, 0x0F, 'Dual-watch transmit selection', ['Off', 'A', 'B']),
    ('tail', 0x14, 0x01, 'Squelch tail elimination', ['Off', 'On']),
    ('repeater_tail', 0x15, 0x0F, 'Repeater tail elimination',
     ['Off'] + ['%i ms' % i for i in range(100, 1001, 100)]),
    ('repeater_detect', 0x16, 0x0F, 'Repeater tail detection',
     ['Off'] + ['%i ms' % i for i in range(100, 1001, 100)]),
    ('roger', 0x17, 0xFF, 'End-of-transmission sound',
     ['Off', 'Beep', '1200 Hz tone']),
    ('work_a', 0x1A, 0x01, 'Operating mode A', ['VFO', 'Channel']),
    ('work_b', 0x1A, 0x10, 'Operating mode B', ['VFO', 'Channel']),
    ('poweron', 0x1C, 0x01, 'Power-on display', ['Logo', 'Battery voltage']),
    ('burst', 0x1E, 0x03, 'Tone-burst frequency',
     ['1000 Hz', '1450 Hz', '1750 Hz', '2100 Hz']),
    ('vox_delay',
     0x20,
     0x0F,
     'VOX delay',
     ['0.5s',
      '0.6s',
      '0.7s',
      '0.8s',
      '0.9s',
      '1.0s',
      '1.1s',
      '1.2s',
      '1.3s',
      '1.4s',
      '1.5s',
      '1.6s',
      '1.7s',
      '1.8s',
      '1.9s',
      '2.0s']),
    ('menu_exit', 0x21, 0x0F, 'Menu timeout', [
     '%i s' % i for i in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60)]),
    ('tail_code', 0x22, 0x01, 'Tail elimination code', ['55 Hz', '62.5 Hz']),
    ('tone_save', 0x29, 0x0F, 'Scanned tone save target',
     ['Both', 'Transmit', 'Receive']),
    ('local_id', 0x2A, 0xFF, 'Local ANI entry',
     [str(i) for i in range(1, 61)]),
]
BOOL_SETTINGS = [
    ('tdr', 0x04, 'Dual watch', False),
    ('beep', 0x06, 'Keypad beep', False),
    ('stop_busy', 0x0F, 'Stop transmission on busy channel', False),
    ('alarm_sound', 0x12, 'Alarm sound', False),
    ('fm_radio', 0x19, 'FM broadcast receiver', True),
    ('locked', 0x1B, 'Keypad locked', False),
    ('rx_tail', 0x30, 'Receive-end tail option', False),
]


@directory.register
class RadtelRT400Radio(chirp_common.CloneModeRadio):
    VENDOR = 'Radtel'
    MODEL = 'RT-400'
    BAUD_RATE = 57600
    HARDWARE_FLOW = False
    _memsize = IMAGE_SIZE

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = ('RT-400 driver based on the JJCC-7700 CPS. '
                                'Keep an original download before editing.')
        prompts.pre_download = (
            'Turn the RT-400 on and connect the programming cable. '
            'After upload, restart the radio before downloading again.')
        prompts.pre_upload = (
            'Keep an original download. After upload completes, switch the '
            'RT-400 off and on. Download again to independently verify edits.')
        return prompts

    @classmethod
    def match_model(cls, filedata, filename):
        # Native CHIRP images are identified by their metadata, not size
        # guesses.
        return False

    def process_mmap(self):
        if len(self._mmap) != IMAGE_SIZE:
            raise errors.InvalidDataError(
                'RT-400 image must contain 0xB300 bytes')

    def get_features(self):
        # CHIRP asks repeatedly while drawing and editing the memory grid.
        # These capabilities do not depend on the image or selected channel.
        cached = getattr(self, '_rt400_features', None)
        if cached is not None:
            return cached
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_settings = True
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.can_odd_split = True
        rf.memory_bounds = (1, 256)
        rf.valid_name_length = 12
        rf.valid_characters = _name_charset()
        rf.valid_modes = ['FM', 'NFM', 'AM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_cross_modes = ['Tone->Tone', 'Tone->DTCS', 'DTCS->Tone',
                                'DTCS->DTCS', '->Tone', '->DTCS',
                                'DTCS->', 'Tone->']
        rf.valid_dtcs_codes = list(DCS_CODES)
        rf.valid_tuning_steps = STEPS
        # Encoding/CPS entry limits; validate_memory warns outside published
        # bands.
        rf.valid_bands = [(18000000, 1000000000)]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = ['', 'S']
        self._rt400_features = rf
        return rf

    def _get(self, address, length=1):
        return bytes(self._mmap.get(address, length))

    def _put(self, address, data):
        self._mmap.set(address, bytes(data))

    def _bits(self, address, value, mask=255):
        old = self._get(address)[0]
        self._put(address, bytes([(old & (255 ^ mask)) | (value & mask)]))

    def _status(self, message, current, maximum=147):
        status = chirp_common.Status()
        status.msg, status.cur, status.max = message, current, maximum
        self.status_fn(status)

    def _download(self, message):
        protocol = _Protocol(self.pipe)
        data = bytearray(b'\xff' * IMAGE_SIZE)
        primary = None
        try:
            protocol.enter()
            for index, address in enumerate(ADDRESSES, 1):
                data[address:address + 64] = protocol.read_block(address)
                self._status(message, index)
            return bytes(data)
        except Exception as exc:
            primary = exc
            raise
        finally:
            try:
                protocol.finish_read()
            except Exception:
                if primary is None:
                    raise
                LOG.warning('Could not exit RT-400 read mode after an error')

    def sync_in(self):
        try:
            data = self._download('Reading RT-400')
            self._mmap = memmap.MemoryMapBytes(data)
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError('Unable to read RT-400: %s' % exc) from exc

    def sync_out(self):
        self.process_mmap()
        target = self._mmap.get_packed()
        try:
            current = self._download('Checking RT-400 before upload')
            if all(current[a:a + 64] == target[a:a + 64] for a in ADDRESSES):
                self._status('RT-400 already matches this image', 147)
                return
            time.sleep(0.15)
            protocol = _Protocol(self.pipe)
            try:
                protocol.enter()
                # Reproduce the complete observed CPS upload sequence.
                for index, address in enumerate(ADDRESSES, 1):
                    protocol.write_block(address, target[address:address + 64])
                    self._status('Writing RT-400', index)
            finally:
                # The hardware accepts a new clone session only after restart.
                # Match the CPS: close after the final ACK; do not send E.
                self.pipe.close()
            self._status('Upload complete; restart the RT-400', 147)
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                'Unable to upload RT-400: %s' %
                exc) from exc

    @staticmethod
    def _location(number):
        if not isinstance(number, int) or not 1 <= number <= 256:
            raise errors.InvalidMemoryLocation(
                'Channel must be between 1 and 256')
        return (number - 1) * 32

    def get_raw_memory(self, number):
        return self._get(self._location(number), 32).hex(' ')

    @staticmethod
    def _enum(name, label, current, choices, codes=None):
        codes = list(range(len(choices))) if codes is None else list(codes)
        choices = list(choices)
        if current not in codes:
            choices.append('Unknown (0x%02X)' % current)
            codes.append(current)
        value = RadioSettingValueList(
            choices, current_index=codes.index(current))
        setting = RadioSetting(name, label, value)
        # Standard apply callbacks use the explicit raw-code mapping below.
        return setting, codes

    def _extras(self, raw):
        group = RadioSettingGroup('extra', 'Channel options')
        fields = [('pttid', 'PTT-ID', raw[13], PTT_ID),
                  ('signal_group', 'DTMF group', raw[12], [
                   str(i) for i in range(1, 16)]),
                  ('scrambler', 'Scrambler', raw[14] >> 4, SCRAMBLER),
                  ('fhss', 'FHSS / DCP', (raw[15] >> 4) & 3, FHSS)]
        for name, label, value, choices in fields:
            setting, _ = self._enum(name, label, value, choices)
            group.append(setting)
        for name, label, mask in (('bcl', 'Busy-channel lockout', 8),
                                  ('learning', 'FHSS learning', 1)):
            group.append(RadioSetting(name, label,
                                      RadioSettingValueBoolean(
                                          bool(raw[15] & mask))))
        code = raw[16:19][::-1].hex().upper() if raw[19] == 0xA0 else ''
        group.append(RadioSetting(
            'fhss_code', 'FHSS code', RadioSettingValueString(
                0, 6, code, autopad=False, charset='0123456789abcdefABCDEF')))
        return group

    def get_memory(self, number):
        raw = self._get(self._location(number), 32)
        mem = chirp_common.Memory()
        mem.number = number
        if raw[:4] in (b'\xff' * 4, b'\x00' * 4):
            mem.empty = True
            return mem
        mem.freq = _frequency(raw[:4])
        tx = _frequency(raw[4:8])
        if not tx:
            mem.duplex = 'off'
            mem.offset = 0
        else:
            chirp_common.split_to_offset(mem, mem.freq, tx)
        mem.name = _name(raw[20:32]).rstrip()
        mem.mode = 'AM' if AIRBAND[0] <= mem.freq < AIRBAND[1] else (
            'NFM' if raw[15] & 64 else 'FM')
        mem.skip = '' if raw[15] & 4 else 'S'
        index = raw[14] & 15
        mem.power = POWER_LEVELS[index if index < 3 else 0]
        chirp_common.split_tone_decode(mem, _display_tone(raw[10:12]),
                                       _display_tone(raw[8:10]))
        mem.extra = self._extras(raw)
        return mem

    def validate_memory(self, mem):
        messages = super().validate_memory(mem)
        if mem.empty:
            return messages
        try:
            _name_bytes(mem.name, 12)
            _frequency_bytes(mem.freq)
        except errors.InvalidValueError as exc:
            messages.append(chirp_common.ValidationError(str(exc)))
        air = AIRBAND[0] <= mem.freq < AIRBAND[1]
        if air and mem.mode != 'AM':
            messages.append(chirp_common.ValidationWarning(
                'Frequency in this range requires AM mode'))
        elif not air and mem.mode == 'AM':
            messages.append(chirp_common.ValidationWarning(
                'Frequency in this range must not be AM mode'))
        tx = self._tx_frequency(mem)
        if tx and not any(lo <= tx <= hi for lo, hi in TX_BANDS):
            messages.append(chirp_common.ValidationWarning(
                'Transmit frequency is outside the '
                'manufacturer-published transmit bands'))
        return messages

    @staticmethod
    def _tx_frequency(mem):
        if mem.duplex == 'off':
            return 0
        if mem.duplex == 'split':
            return mem.offset
        if mem.duplex == '+':
            return mem.freq + mem.offset
        if mem.duplex == '-':
            return mem.freq - mem.offset
        return mem.freq

    def set_memory(self, mem):
        address = self._location(mem.number)
        if mem.empty:
            self._put(address, b'\xff' * 32)
            return
        original = self.get_memory(mem.number)
        new = original.empty
        raw = bytearray(self._get(address, 32) if not new else b'\xff' * 32)
        if new:
            raw[12:16] = bytes([0, 0, 0, 4])
        if new or mem.freq != original.freq:
            raw[:4] = _frequency_bytes(mem.freq)
        tx = self._tx_frequency(mem)
        if tx < 0:
            raise errors.InvalidValueError('Transmit frequency is negative')
        if new or tx != self._tx_frequency(original):
            raw[4:8] = _frequency_bytes(tx) if tx else b'\xff' * 4
        if new or mem.name != original.name:
            raw[20:32] = _name_bytes(mem.name, 12)
        if new or str(mem.power) != str(original.power):
            labels = [str(p) for p in POWER_LEVELS]
            if mem.power is not None and str(mem.power) not in labels:
                raise errors.InvalidValueError(
                    'Select High, Low, or Medium power')
            power = labels.index(
                str(mem.power)) if mem.power is not None else 0
            # FIX: combine the power nibble with the existing scrambler nibble.
            raw[14] = (raw[14] & 240) | power
        if new or mem.mode != original.mode:
            if not AIRBAND[0] <= mem.freq < AIRBAND[1]:
                if mem.mode not in ('FM', 'NFM', 'AM'):
                    raise errors.InvalidValueError('Unsupported mode')
                raw[15] = (raw[15] & 191) | (64 if mem.mode == 'NFM' else 0)
        if new or mem.skip != original.skip:
            raw[15] = (raw[15] & 251) | (0 if mem.skip == 'S' else 4)
        tx_tone, rx_tone = chirp_common.split_tone_encode(mem)
        old_tx, old_rx = chirp_common.split_tone_encode(
            original) if not new else (None, None)
        if new or tx_tone != old_tx:
            raw[10:12] = _tone_bytes(tx_tone)
        if new or rx_tone != old_rx:
            raw[8:10] = _tone_bytes(rx_tone)
        old_extra = {
            s.get_name(): s for s in original.extra} if not new else {}
        for setting in mem.extra or []:
            name = setting.get_name()
            if name in old_extra and str(
                    setting.value) == str(old_extra[name].value):
                continue
            if name in ('pttid', 'signal_group', 'scrambler', 'fhss'):
                label = str(setting.value)
                raw_value = (int(label.split('0x', 1)[1].rstrip(')'), 16)
                             if label.startswith('Unknown (0x')
                             else int(setting.value))
                if name == 'pttid':
                    raw[13] = raw_value
                elif name == 'signal_group':
                    raw[12] = raw_value
                elif name == 'scrambler':
                    raw[14] = (raw[14] & 15) | (raw_value << 4)
                elif name == 'fhss':
                    raw[15] = (raw[15] & 207) | (raw_value << 4)
            elif name in ('bcl', 'learning'):
                mask = 8 if name == 'bcl' else 1
                raw[15] = (
                    raw[15] & (
                        255 ^ mask)) | (
                    mask if bool(
                        setting.value) else 0)
            elif name == 'fhss_code':
                text = str(setting.value).strip()
                if text and len(text) != 6:
                    raise errors.InvalidValueError(
                        'FHSS code must be empty or six hex digits')
                # FIX: preserve all six digits, including bit 7 of the first
                # byte.
                raw[16:20] = bytes.fromhex(
                    text)[::-1] + b'\xa0' if text else b'\xff' * 4
        self._put(address, raw)

    def _add_enum(self, group, name, label, address,
                  choices, mask=255, codes=None):
        shift = (mask & -mask).bit_length() - 1
        current = (self._get(address)[0] & mask) >> shift
        setting, raw_codes = self._enum(name, label, current, choices, codes)

        def apply(item):
            self._bits(address, raw_codes[int(item.value)] << shift, mask)
        setting.set_apply_callback(apply)
        group.append(setting)

    def _add_bool(self, group, name, label, address, inverted=False):
        current = bool(self._get(address)[0]) ^ inverted
        setting = RadioSetting(name, label, RadioSettingValueBoolean(current))
        setting.set_apply_callback(lambda item: self._put(
            address, bytes([int(bool(item.value) ^ inverted)])))
        group.append(setting)

    def _add_string(self, group, name, label, address,
                    size, decoder, encoder, charset):
        raw = self._get(address, size)
        try:
            current = decoder(raw)
        except errors.InvalidDataError:
            value = RadioSettingValueString(
                0, 80, 'Unrecognized data: ' + raw.hex(), autopad=False)
            value.set_mutable(False)
            group.append(RadioSetting(name, label, value))
            return
        value = RadioSettingValueString(
            0, size, current, autopad=False, charset=charset)
        setting = RadioSetting(name, label, value)
        setting.set_apply_callback(lambda item: self._put(
            address, encoder(str(item.value), size)))
        group.append(setting)

    def _add_tone(self, group, name, label, address):
        labels = ['Off'] + ['%.1f' % t for t in chirp_common.TONES]
        codes = [b'\0\0'] + [_tone_bytes(('Tone', t, None))
                             for t in chirp_common.TONES]
        for polarity, suffix in (('N', 'N'), ('R', 'I')):
            for code in DCS_CODES:
                labels.append('D%03i%s' % (code, suffix))
                codes.append(_tone_bytes(('DTCS', code, polarity)))
        raw = self._get(address, 2)
        if raw == b'\xff\xff':
            index = 0
        elif raw in codes:
            index = codes.index(raw)
        else:
            labels.append('Unknown (' + raw.hex() + ')')
            codes.append(raw)
            index = len(codes) - 1
        setting = RadioSetting(
            name, label, RadioSettingValueList(
                labels, current_index=index))
        setting.set_apply_callback(
            lambda item: self._put(address, codes[int(item.value)]))
        group.append(setting)

    def _vfo_settings(self, which):
        base = 0x8000 + which * 32
        prefix = 'vfo_%s' % ('a' if which == 0 else 'b')
        group = RadioSettingGroup(prefix,
                                  'VFO ' + ('A' if which == 0 else 'B'))
        for name, label, offset, count, multiplier in (
                ('frequency', 'Frequency (MHz)', 0, 8, 10),
                ('offset', 'Offset (MHz)', 20, 7, 100)):
            raw = self._get(base + offset, count)
            try:
                current = '%.5f' % (_digits(raw, multiplier) / 1000000)
            except errors.InvalidDataError:
                current = ''
            value = RadioSettingValueString(
                0, 16, current, autopad=False, charset='0123456789.')
            setting = RadioSetting(prefix + '_' + name, label, value)

            def apply(item, address=base + offset,
                      size=count, unit=multiplier):
                data = _digit_bytes(str(item.value), size, unit)
                if size == 7 and data[0] != 0:
                    raise errors.InvalidValueError(
                        'VFO offset must be below 100 MHz')
                self._put(address, data)
            setting.set_apply_callback(apply)
            group.append(setting)
        self._add_tone(group, prefix + '_rx_tone', 'Receive tone', base + 8)
        self._add_tone(group, prefix + '_tx_tone', 'Transmit tone', base + 10)
        for name, label, offset, mask, choices in (
                ('direction', 'Offset direction', 14, 0x30, ['Off', '+', '-']),
                ('signal_group', 'DTMF group', 14,
                 15, [str(i) for i in range(1, 16)]),
                ('power', 'Power', 16, 15, ['High', 'Low', 'Medium']),
                ('scrambler', 'Scrambler', 16, 240, SCRAMBLER),
                ('bandwidth', 'Bandwidth', 17, 64, ['Wide', 'Narrow']),
                ('fhss', 'FHSS / DCP', 17, 48, FHSS),
                ('step', 'Tuning step', 19, 15,
                 ['%g kHz' % x for x in STEPS])):
            self._add_enum(
                group,
                prefix +
                '_' +
                name,
                label,
                base +
                offset,
                choices,
                mask)
        return group

    def get_settings(self):
        basic = RadioSettingGroup('basic', 'General')
        for name, offset, mask, label, choices in GENERAL:
            self._add_enum(basic, name, label, 0x9000 + offset, choices, mask)
        for name, offset, label, inverted in BOOL_SETTINGS:
            self._add_bool(basic, name, label, 0x9000 + offset, inverted)
        # Keep physical addresses explicit: 0x902E is an unused CPS field,
        # not a Top key. Removing it must not shift Side 2 long to that byte.
        for name, address, count in (
                ('side_short', 0x902B, 9),
                ('side_long', 0x902C, 8),
                ('side2_short', 0x902D, 8),
                ('side2_long', 0x902F, 8)):
            self._add_enum(basic, name, name.replace('_', ' ').title(),
                           address, KEYS[:count], codes=KEY_CODES[:count])
        weather = RadioSetting(
            'weather',
            'Weather selection',
            RadioSettingValueInteger(
                0,
                255,
                self._get(0x9027)[0]))
        weather.set_doc(
            'Stored firmware selection; preserved '
            'independently of the CPS default.')
        weather.set_apply_callback(lambda item: self._put(
            0x9027, bytes([int(item.value)])))
        basic.append(weather)
        dtmf = RadioSettingGroup('dtmf', 'DTMF')
        self._add_string(
            dtmf,
            'ani_code',
            'ANI transmit code',
            0xA000,
            5,
            _dtmf,
            _dtmf_bytes,
            DTMF_CHARS)
        self._add_enum(dtmf, 'ani_pttid', 'ANI PTT-ID', 0xA006, PTT_ID, 3)
        for offset, name, label in (
                (7, 'dtmf_send', 'DTMF digit duration'),
                (8, 'dtmf_pause', 'DTMF digit gap')):
            self._add_enum(dtmf, name, label, 0xA000 + offset,
                           ['50 ms', '100 ms', '200 ms',
                            '300 ms', '500 ms'], 15)
        for index in range(18):
            self._add_string(dtmf, 'dtmf_%i' % index,
                             'DTMF group %i' % (index + 1),
                             0xA020 + index * 16, 5, _dtmf,
                             _dtmf_bytes, DTMF_CHARS)
        contacts = RadioSettingGroup('contacts', 'ANI contacts')
        for index in range(60):
            entry = RadioSettingGroup(
                'contact_%i' %
                index, 'Contact %i' %
                (index + 1))
            self._add_string(entry, 'contact_id_%i' % index, 'ID',
                             0xB000 + index * 3,
                             3, _dtmf, _dtmf_bytes, DTMF_CHARS)
            if index >= 30:
                self._add_string(entry, 'contact_name_%i' % index, 'Name',
                                 0xB0C0 + (index - 30) * 16, 16, _name,
                                 _name_bytes, _name_charset())
            contacts.append(entry)
        return RadioSettings(basic, self._vfo_settings(
            0), self._vfo_settings(1), dtmf, contacts)

    def set_settings(self, settings):
        before = self._mmap.get_packed()
        try:
            for setting in settings.walk():
                if isinstance(setting, RadioSetting) and setting.changed():
                    if not setting.has_apply_callback():
                        raise errors.InvalidValueError(
                            'Setting cannot be changed')
                    setting.run_apply_callback()
        except Exception:
            self._mmap = memmap.MemoryMapBytes(before)
            raise
