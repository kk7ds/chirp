# Copyright 2026 SV1TSD
# Licensed under the GNU General Public License, version 3 or later.
"""Radtel RT-400 clone driver, based on CPS IL, USB capture, and live backups.

Uses the RT-470X_BT clone protocol with an RT-400 memory map and settings.
Only OEM-observed addresses are uploaded. Unedited raw bytes are preserved.
"""
import logging
import time
from decimal import Decimal, InvalidOperation

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.drivers import mml_jc8810
from chirp.settings import (RadioSettings, RadioSetting, RadioSettingGroup,
                            RadioSettingValueBoolean, RadioSettingValueInteger,
                            RadioSettingValueList, RadioSettingValueString)

LOG = logging.getLogger(__name__)
_FAMILY = mml_jc8810.RT470XPlusRadio
MAGIC = _FAMILY._magic
IDENT, = _FAMILY._fingerprint
BLOCK_SIZE = _FAMILY.BLOCK_SIZE
IMAGE_SIZE = _FAMILY._memsize
ADDRESSES = tuple(address for start, end in _FAMILY._ranges
                  for address in range(start, end, BLOCK_SIZE))
DCS_CODES = mml_jc8810.DTCS
PTT_ID = ['Off', 'Beginning', 'End', 'Both']
SCRAMBLER = ['Off', 'Scrambler 1', 'Scrambler 2']
FHSS = ['Off', 'DCP 1', 'DCP 2', 'DCP 3']
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]


# Nominal levels support power matching when importing other radios.
# Order is the device encoding: High=0, Low=1, Medium=2.
POWER_LEVELS = [chirp_common.PowerLevel('High', watts=6),
                chirp_common.PowerLevel('Low', watts=1),
                chirp_common.PowerLevel('Medium', watts=3)]
DTMF_CHARS = '0123456789ABCD*#'
KEYS = ['Off', 'Radio', 'Tx Power', 'Scan', 'Search', 'Light',
        'NOAA', 'Monitor', 'SOS', 'Spectrum', 'PTT B']
KEY_CODES = [255, 7, 10, 28, 29, 8, 12, 5, 3, 36, 1]
DRIVER_REVISION = '2026-11-11.1'
AIRBAND = (108000000, 136000000)
TX_BANDS = [(136000000, 174000000), (220000000, 235000000),
            (350000000, 390000000), (400000000, 470000000)]

MEM_FORMAT = """
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 signal_group;
  u8 pttid;
  u8 scrambler:4, power:4;
  u8 reserved_flag7:1, narrow:1, fhss:2, bcl:1, scan:1,
     reserved_flag1:1, learning:1;
  ul24 fhss_code;
  u8 fhss_marker;
  char name[12];
} memory[256];

#seekto 0x8000;
struct {
  u8 frequency[8];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 reserved0[2];
  u8 reserved_dir:2, direction:2, signal_group:4;
  u8 reserved1;
  u8 scrambler:4, power:4;
  u8 reserved_flag7:1, bandwidth:1, fhss:2, reserved_flags:4;
  u8 reserved2;
  u8 reserved_step:4, step:4;
  u8 offset[7];
  u8 reserved3[5];
} vfo[2];

#seekto 0x9000;
struct {
  u8 reserved_sql:4, sql:4;
  u8 reserved_save:6, save:2;
  u8 reserved_vox:4, vox:4;
  u8 reserved_backlight:4, backlight:4;
  u8 tdr;
  u8 reserved_tot:4, tot:4;
  u8 beep;
  u8 reserved_voice:7, voice:1;
  u8 reserved_language:7, language:1;
  u8 reserved_sidetone:6, sidetone:2;
  u8 reserved_scan:4, scan:4;
  u8 reserved_pttid:6, global_pttid:2;
  u8 reserved_id_delay:4, id_delay:4;
  u8 reserved_display_a:4, display_a:4;
  u8 reserved_display_b:4, display_b:4;
  u8 stop_busy;
  u8 reserved_keylock:6, keylock:2;
  u8 reserved_alarm:4, alarm:4;
  u8 alarm_sound;
  u8 reserved_tdr_tx:4, tdr_tx:4;
  u8 reserved_tail:7, tail:1;
  u8 reserved_repeater_tail:4, repeater_tail:4;
  u8 reserved_repeater_detect:4, repeater_detect:4;
  u8 roger;
  u8 reserved_18;
  u8 fm_radio;
  u8 reserved_work_b:3, work_b:1, reserved_work_a:3, work_a:1;
  u8 locked;
  u8 reserved_poweron:7, poweron:1;
  u8 reserved_1d;
  u8 reserved_burst:6, burst:2;
  u8 reserved_1f;
  u8 reserved_vox_delay:4, vox_delay:4;
  u8 reserved_menu_exit:4, menu_exit:4;
  u8 reserved_tail_code:7, tail_code:1;
  u8 reserved_23[4];
  u8 weather;
  u8 reserved_28;
  u8 reserved_tone_save:4, tone_save:4;
  u8 local_id;
  u8 side_short;
  u8 side_long;
  u8 side2_short;
  u8 unused_top_key;
  u8 side2_long;
  u8 rx_tail;
  u8 reserved_31[15];
} settings;

#seekto 0xA000;
struct {
  u8 ani_code[5];
  u8 reserved05;
  u8 reserved_pttid:6, ani_pttid:2;
  u8 reserved_send:4, dtmf_send:4;
  u8 reserved_pause:4, dtmf_pause:4;
  u8 reserved09[23];
  struct {
    u8 code[5];
    u8 reserved[11];
  } groups[18];
} dtmf;

#seekto 0xB000;
struct {
  struct {
    u8 code[3];
  } ids[60];
  u8 reserved_b4[12];
  struct {
    char name[16];
  } names[30];
  u8 reserved_2a0[96];
} contacts;
"""

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


def _frequency(field):
    raw = field.get_raw()
    if raw in (b'\xff' * 4, b'\x00' * 4):
        return 0
    if any((value & 15) > 9 or value >> 4 > 9 for value in raw):
        raise errors.InvalidDataError('Invalid RT-400 BCD frequency')
    return int(field) * 10


def _validate_frequency(hz):
    if not isinstance(hz, int) or hz < 0 or hz > 999999990 or hz % 10:
        raise errors.InvalidValueError('Frequency must have 10 Hz resolution')


def _tone(word):
    word = int(word)
    if word in (0, 65535):
        return ('', None, None)
    if word < 256:
        if word > 2 * len(DCS_CODES):
            raise errors.InvalidDataError('Unknown RT-400 DCS index')
        return ('DTCS', DCS_CODES[(word - 1) % len(DCS_CODES)],
                'N' if word <= len(DCS_CODES) else 'R')
    return ('Tone', word / 10.0, None)


def _tone_word(tone):
    mode, value, polarity = tone
    if not mode:
        return 0
    if mode == 'DTCS':
        if value not in DCS_CODES or polarity not in ('N', 'R'):
            raise errors.UnsupportedToneError('Unsupported DCS code/polarity')
        return (DCS_CODES.index(value) + 1 +
                (len(DCS_CODES) if polarity == 'R' else 0))
    if mode == 'Tone':
        n = Decimal(str(value)) * 10
        if n != int(n) or not 256 <= n < 65535:
            raise errors.UnsupportedToneError('Invalid CTCSS tone')
        return int(n)
    raise errors.UnsupportedToneError('Unsupported tone mode')


def _display_tone(field):
    try:
        return _tone(field)
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
    if any(int(b) > 9 for b in raw):
        raise errors.InvalidDataError('Unrecognized VFO decimal digits')
    return int(''.join(str(int(b)) for b in raw)) * multiplier


def _digit_values(text, count, multiplier):
    try:
        n = Decimal(str(text)) * 1000000 / multiplier
    except InvalidOperation as exc:
        raise errors.InvalidValueError('Enter a frequency in MHz') from exc
    if not n.is_finite() or n != int(n) or not 0 <= n < 10 ** count:
        raise errors.InvalidValueError('Invalid frequency or resolution')
    return [int(c) for c in ('%0*d' % (count, int(n)))]


class _Protocol:
    def __init__(self, pipe):
        self.pipe = pipe
        self.entered = False
        self.received_any = False

    def write(self, data):
        count = self.pipe.write(data)
        if count not in (None, len(data)):
            raise errors.RadioError('Short write to the programming cable')
        if hasattr(self.pipe, 'flush'):
            self.pipe.flush()

    def read(self, count):
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

    def enter(self, radio):
        self.pipe.baudrate = radio.BAUD_RATE
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
        self.write(radio._magic)
        if self.read(1) != mml_jc8810.CMD_ACK:
            raise errors.RadioError(
                'RT-400 rejected the programming handshake')
        self.entered = True
        self.write(b'F')
        if self.read(8) not in radio._fingerprint:
            raise errors.RadioError(
                'Radio identity does not match this RT-400 driver')

    def finish_read(self):
        if self.entered:
            self.write(b'E')
            self.entered = False
            time.sleep(0.25)


# Settings UI labels and menu order; MEM_FORMAT defines storage types.
GENERAL = [
    ('sql', 'Squelch', [str(i) for i in range(10)]),
    ('save', 'Battery saver', ['Off', 'Normal', 'Super', 'Deep']),
    ('vox', 'VOX', ['Off'] + [str(i) for i in range(1, 10)]),
    ('backlight', 'Backlight', ['Always on', '5 s', '10 s',
     '15 s', '20 s', '30 s', '1 min', '2 min', '3 min']),
    ('tot', 'Transmit timeout', [
     'Off', '30 s', '60 s', '120 s', '240 s', '480 s']),
    ('voice', 'Voice prompts', ['Off', 'On']),
    ('language', 'Voice language', ['English', 'Chinese']),
    ('sidetone', 'DTMF sidetone', ['Off', 'Keys', 'ANI', 'Keys and ANI']),
    ('scan', 'Scan resume', ['Time', 'Carrier', 'Search']),
    ('global_pttid', 'Global PTT-ID', PTT_ID),
    ('id_delay', 'PTT-ID delay',
     ['0 ms', '100 ms', '200 ms', '400 ms', '600 ms', '800 ms', '1000 ms']),
    ('display_a', 'Display A', ['Name', 'Frequency', 'Channel number']),
    ('display_b', 'Display B', ['Name', 'Frequency', 'Channel number']),
    ('keylock', 'Automatic keypad lock', ['Off', '5 s', '10 s', '15 s']),
    ('alarm', 'Alarm mode', ['Local', 'Transmit sound', 'Transmit code']),
    ('tdr_tx', 'Dual-watch transmit selection', ['Off', 'A', 'B']),
    ('tail', 'Squelch tail elimination', ['Off', 'On']),
    ('repeater_tail', 'Repeater tail elimination', [
     'Off'] + ['%i ms' % i for i in range(100, 1001, 100)]),
    ('repeater_detect', 'Repeater tail detection', [
     'Off'] + ['%i ms' % i for i in range(100, 1001, 100)]),
    ('roger', 'End-of-transmission sound', ['Off', 'Beep', '1200 Hz tone']),
    ('work_a', 'Operating mode A', ['VFO', 'Channel']),
    ('work_b', 'Operating mode B', ['VFO', 'Channel']),
    ('poweron', 'Power-on display', ['Logo', 'Battery voltage']),
    ('burst', 'Tone-burst frequency',
     ['1000 Hz', '1450 Hz', '1750 Hz', '2100 Hz']),
    ('vox_delay', 'VOX delay',
     ['%.1fs' % (value / 10) for value in range(5, 21)]),
    ('menu_exit', 'Menu timeout', ['%i s' % i for i in (
        5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60)]),
    ('tail_code', 'Tail elimination code', ['55 Hz', '62.5 Hz']),
    ('tone_save', 'Scanned tone save target', ['Both', 'Transmit', 'Receive']),
    ('local_id', 'Local ANI entry', [str(i) for i in range(1, 61)]),
]
BOOL_SETTINGS = [
    ('tdr', 'Dual watch', False),
    ('beep', 'Keypad beep', False),
    ('stop_busy', 'Stop transmission on busy channel', False),
    ('alarm_sound', 'Alarm sound', False),
    ('fm_radio', 'FM broadcast receiver', True),
    ('locked', 'Keypad locked', False),
    ('rx_tail', 'Receive-end tail option', False),
]


@directory.register
class RadtelRT400Radio(mml_jc8810.RT470XPlusRadio):
    VENDOR = 'Radtel'
    MODEL = 'RT-400'
    HARDWARE_FLOW = False
    POWER_LEVELS = POWER_LEVELS

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = ('RT-400 driver based on the JJCC-7700 CPS. '
                                'Keep an original download before editing.')
        prompts.pre_download = (
            'WARNING: EXPERIMENTAL. USE AT OWN RISK ! \n'
            'Turn the RT-400 on and connect the programming cable. \n'
            'After upload, restart the radio before downloading again.')
        prompts.pre_upload = (
            'Keep an original download. After upload completes, switch the '
            'RT-400 off and on. Download again to independently verify edits.')
        return prompts

    def process_mmap(self):
        if len(self._mmap) != IMAGE_SIZE:
            raise errors.InvalidDataError(
                'RT-400 image must contain 0xB300 bytes')
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        # CHIRP asks repeatedly while drawing and editing the memory grid.
        # These capabilities do not depend on the image or selected channel.
        cached = getattr(self, '_rt400_features', None)
        if cached is not None:
            return cached
        rf = super().get_features()
        rf.has_nostep_tuning = True
        rf.valid_characters = _name_charset()
        rf.valid_modes = ['FM', 'NFM', 'AM']
        rf.valid_cross_modes = rf.valid_cross_modes + ['Tone->']
        rf.valid_tuning_steps = STEPS
        self._rt400_features = rf
        return rf

    def _status(self, message, current, maximum=147):
        status = chirp_common.Status()
        status.msg, status.cur, status.max = message, current, maximum
        self.status_fn(status)

    def _download(self, message):
        protocol = _Protocol(self.pipe)
        data = bytearray(b'\xff' * IMAGE_SIZE)
        primary = None
        try:
            protocol.enter(self)
            for index, address in enumerate(ADDRESSES, 1):
                block = mml_jc8810._read_block(
                    self, address, self.BLOCK_SIZE, serial=protocol)
                data[address:address + self.BLOCK_SIZE] = block
                time.sleep(0.003)
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
                protocol.enter(self)
                # Reproduce the complete observed CPS upload sequence.
                for index, address in enumerate(ADDRESSES, 1):
                    mml_jc8810._write_block(
                        self, address, self.BLOCK_SIZE_UP, serial=protocol)
                    time.sleep(0.003)
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

    def _channel(self, number):
        if not isinstance(number, int) or not 1 <= number <= 256:
            raise errors.InvalidMemoryLocation(
                'Channel must be between 1 and 256')
        return self._memobj.memory[number - 1]

    def get_raw_memory(self, number):
        return self._channel(number).get_raw().hex(' ')

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

    def _extras(self, record):
        group = RadioSettingGroup('extra', 'Channel options')
        for name, label, choices in (
                ('pttid', 'PTT-ID', PTT_ID),
                ('signal_group', 'DTMF group',
                 [str(i) for i in range(1, 16)]),
                ('scrambler', 'Scrambler', SCRAMBLER),
                ('fhss', 'FHSS / DCP', FHSS)):
            setting, _ = self._enum(
                name, label, int(getattr(record, name)), choices)
            group.append(setting)
        for name, label in (('bcl', 'Busy-channel lockout'),
                            ('learning', 'FHSS learning')):
            group.append(RadioSetting(name, label,
                                      RadioSettingValueBoolean(
                                          bool(getattr(record, name)))))
        code = ('%06X' % int(record.fhss_code)
                if record.fhss_marker == 0xA0 else '')
        group.append(RadioSetting(
            'fhss_code', 'FHSS code', RadioSettingValueString(
                0, 6, code, autopad=False, charset='0123456789abcdefABCDEF')))
        return group

    def get_memory(self, number):
        record = self._channel(number)
        mem = chirp_common.Memory(number=number)
        if record.rx_freq.get_raw() in (b'\xff' * 4, b'\x00' * 4):
            mem.empty = True
            return mem
        mem.freq = _frequency(record.rx_freq)
        tx = _frequency(record.tx_freq)
        if not tx:
            mem.duplex = 'off'
            mem.offset = 0
        else:
            chirp_common.split_to_offset(mem, mem.freq, tx)
        mem.name = _name(record.name.get_raw()).rstrip()
        mem.mode = 'AM' if AIRBAND[0] <= mem.freq < AIRBAND[1] else (
            'NFM' if record.narrow else 'FM')
        mem.skip = '' if record.scan else 'S'
        power = int(record.power)
        mem.power = POWER_LEVELS[power if power < len(POWER_LEVELS) else 0]
        chirp_common.split_tone_decode(mem, _display_tone(record.tx_tone),
                                       _display_tone(record.rx_tone))
        mem.extra = self._extras(record)
        return mem

    def validate_memory(self, mem):
        messages = chirp_common.CloneModeRadio.validate_memory(self, mem)
        if mem.empty:
            return messages
        try:
            _name_bytes(mem.name, 12)
            _validate_frequency(mem.freq)
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
        record = self._channel(mem.number)
        if mem.empty:
            record.fill_raw(b'\xff')
            return
        original = self.get_memory(mem.number)
        before = record.get_raw()
        new = original.empty
        try:
            if new:
                record.fill_raw(b'\xff')
                for name in ('signal_group', 'pttid', 'scrambler', 'power',
                             'reserved_flag7', 'narrow', 'fhss', 'bcl',
                             'reserved_flag1', 'learning'):
                    setattr(record, name, 0)
                record.scan = 1
            if new or mem.freq != original.freq:
                _validate_frequency(mem.freq)
                record.rx_freq = mem.freq // 10
            tx = self._tx_frequency(mem)
            if tx < 0:
                raise errors.InvalidValueError(
                    'Transmit frequency is negative')
            if new or tx != self._tx_frequency(original):
                if tx:
                    _validate_frequency(tx)
                    record.tx_freq = tx // 10
                else:
                    record.tx_freq.fill_raw(b'\xff')
            if new or mem.name != original.name:
                record.name.set_raw(_name_bytes(mem.name, 12))
            if new or mem.power != original.power:
                if mem.power is None:
                    record.power = 0
                elif mem.power in POWER_LEVELS:
                    record.power = POWER_LEVELS.index(mem.power)
                else:
                    raise errors.InvalidValueError(
                        'Select High, Low, or Medium power')
            if new or mem.mode != original.mode:
                if not AIRBAND[0] <= mem.freq < AIRBAND[1]:
                    if mem.mode not in ('FM', 'NFM', 'AM'):
                        raise errors.InvalidValueError('Unsupported mode')
                    record.narrow = mem.mode == 'NFM'
            if new or mem.skip != original.skip:
                record.scan = mem.skip != 'S'
            tx_tone, rx_tone = chirp_common.split_tone_encode(mem)
            old_tx, old_rx = (chirp_common.split_tone_encode(original)
                              if not new else (None, None))
            if new or tx_tone != old_tx:
                record.tx_tone = _tone_word(tx_tone)
            if new or rx_tone != old_rx:
                record.rx_tone = _tone_word(rx_tone)
            old_extra = ({item.get_name(): item for item in original.extra}
                         if not new else {})
            for setting in mem.extra or []:
                name = setting.get_name()
                if (name in old_extra and
                        str(setting.value) == str(old_extra[name].value)):
                    continue
                if name in ('pttid', 'signal_group', 'scrambler', 'fhss'):
                    label = str(setting.value)
                    value = (int(label.split('0x', 1)[1].rstrip(')'), 16)
                             if label.startswith('Unknown (0x')
                             else int(setting.value))
                    setattr(record, name, value)
                elif name in ('bcl', 'learning'):
                    setattr(record, name, bool(setting.value))
                elif name == 'fhss_code':
                    text = str(setting.value).strip()
                    if text:
                        if (len(text) != 6 or
                                any(c not in '0123456789abcdefABCDEF'
                                    for c in text)):
                            raise errors.InvalidValueError(
                                'FHSS code must be empty or 6 hex digits')
                        record.fhss_code = int(text, 16)
                        record.fhss_marker = 0xA0
                    else:
                        record.fhss_code = 0xFFFFFF
                        record.fhss_marker = 0xFF
        except Exception:
            record.set_raw(before)
            raise

    def _add_enum(self, group, name, label, field, choices, codes=None):
        setting, raw_codes = self._enum(
            name, label, int(field), choices, codes)
        setting.set_apply_callback(
            lambda item: field.set_value(raw_codes[int(item.value)]))
        group.append(setting)

    def _add_bool(self, group, name, label, field, inverted=False):
        current = bool(field) ^ inverted
        setting = RadioSetting(name, label, RadioSettingValueBoolean(current))
        setting.set_apply_callback(
            lambda item: field.set_value(int(bool(item.value) ^ inverted)))
        group.append(setting)

    def _add_string(self, group, name, label, field,
                    decoder, encoder, charset):
        raw = field.get_raw()
        size = field.size() // 8
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
        setting.set_apply_callback(
            lambda item: field.set_raw(encoder(str(item.value), size)))
        group.append(setting)

    def _add_tone(self, group, name, label, field):
        labels = ['Off'] + ['%.1f' % tone for tone in chirp_common.TONES]
        codes = [0] + [_tone_word(('Tone', tone, None))
                       for tone in chirp_common.TONES]
        for polarity, suffix in (('N', 'N'), ('R', 'I')):
            for code in DCS_CODES:
                labels.append('D%03i%s' % (code, suffix))
                codes.append(_tone_word(('DTCS', code, polarity)))
        raw = int(field)
        if raw == 0xFFFF:
            index = 0
        elif raw in codes:
            index = codes.index(raw)
        else:
            labels.append('Unknown (0x%04X)' % raw)
            codes.append(raw)
            index = len(codes) - 1
        setting = RadioSetting(
            name, label, RadioSettingValueList(labels, current_index=index))
        setting.set_apply_callback(
            lambda item: field.set_value(codes[int(item.value)]))
        group.append(setting)

    def _vfo_settings(self, which):
        vfo = self._memobj.vfo[which]
        prefix = 'vfo_%s' % ('a' if which == 0 else 'b')
        group = RadioSettingGroup(prefix,
                                  'VFO ' + ('A' if which == 0 else 'B'))
        # These are unpacked decimal digits (one digit per byte), not BCD.
        for name, label, count, multiplier in (
                ('frequency', 'Frequency (MHz)', 8, 10),
                ('offset', 'Offset (MHz)', 7, 100)):
            field = getattr(vfo, name)
            try:
                current = '%.5f' % (_digits(field, multiplier) / 1000000)
            except errors.InvalidDataError:
                current = ''
            value = RadioSettingValueString(
                0, 16, current, autopad=False, charset='0123456789.')
            setting = RadioSetting(prefix + '_' + name, label, value)

            def apply(item, target=field, size=count, unit=multiplier):
                values = _digit_values(str(item.value), size, unit)
                if size == 7 and values[0] != 0:
                    raise errors.InvalidValueError(
                        'VFO offset must be below 100 MHz')
                target.set_value(values)
            setting.set_apply_callback(apply)
            group.append(setting)
        self._add_tone(group, prefix + '_rx_tone', 'Receive tone', vfo.rx_tone)
        self._add_tone(group, prefix + '_tx_tone',
                       'Transmit tone', vfo.tx_tone)
        for name, label, choices in (
                ('direction', 'Offset direction', ['Off', '+', '-']),
                ('signal_group', 'DTMF group',
                 [str(i) for i in range(1, 16)]),
                ('power', 'Power', ['High', 'Low', 'Medium']),
                ('scrambler', 'Scrambler', SCRAMBLER),
                ('bandwidth', 'Bandwidth', ['Wide', 'Narrow']),
                ('fhss', 'FHSS / DCP', FHSS),
                ('step', 'Tuning step', ['%g kHz' % step for step in STEPS])):
            self._add_enum(group, prefix + '_' + name, label,
                           getattr(vfo, name), choices)
        return group

    def get_settings(self):
        basic = RadioSettingGroup('basic', 'General')
        cfg = self._memobj.settings
        for name, label, choices in GENERAL:
            self._add_enum(basic, name, label, getattr(cfg, name), choices)
        for name, label, inverted in BOOL_SETTINGS:
            self._add_bool(basic, name, label, getattr(cfg, name), inverted)
        # PTT B is only supported on Side key 1 short press. The unused
        # Top-key byte remains mapped as reserved and is never edited.
        for name, count in (('side_short', 11), ('side_long', 10),
                            ('side2_short', 10), ('side2_long', 10)):
            self._add_enum(basic, name, name.replace('_', ' ').title(),
                           getattr(cfg, name), KEYS[:count],
                           codes=KEY_CODES[:count])
        weather = RadioSetting(
            'weather', 'Weather selection',
            RadioSettingValueInteger(0, 255, int(cfg.weather)))
        weather.set_doc('Stored radio selection; preserved independently '
                        'of the CPS default.')
        weather.set_apply_callback(
            lambda item: cfg.weather.set_value(int(item.value)))
        basic.append(weather)
        dtmf = RadioSettingGroup('dtmf', 'DTMF')
        signal = self._memobj.dtmf
        self._add_string(dtmf, 'ani_code', 'ANI transmit code',
                         signal.ani_code, _dtmf, _dtmf_bytes, DTMF_CHARS)
        self._add_enum(dtmf, 'ani_pttid', 'ANI PTT-ID',
                       signal.ani_pttid, PTT_ID)
        for name, label in (('dtmf_send', 'DTMF digit duration'),
                            ('dtmf_pause', 'DTMF digit gap')):
            self._add_enum(dtmf, name, label, getattr(signal, name),
                           ['50 ms', '100 ms', '200 ms', '300 ms', '500 ms'])
        for index, entry in enumerate(signal.groups):
            self._add_string(dtmf, 'dtmf_%i' % index,
                             'DTMF group %i' % (index + 1), entry.code,
                             _dtmf, _dtmf_bytes, DTMF_CHARS)
        contacts = RadioSettingGroup('contacts', 'ANI contacts')
        stored = self._memobj.contacts
        for index, contact in enumerate(stored.ids):
            entry = RadioSettingGroup('contact_%i' % index,
                                      'Contact %i' % (index + 1))
            self._add_string(entry, 'contact_id_%i' % index, 'ID',
                             contact.code, _dtmf, _dtmf_bytes, DTMF_CHARS)
            if index >= 30:
                self._add_string(entry, 'contact_name_%i' % index, 'Name',
                                 stored.names[index - 30].name,
                                 _name, _name_bytes, _name_charset())
            contacts.append(entry)
        return RadioSettings(basic, self._vfo_settings(0),
                             self._vfo_settings(1), dtmf, contacts)

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
            # Keep the map object so existing UI callbacks still target it
            # when the user corrects an invalid value and retries Apply.
            self._mmap.set(0, before)
            raise
