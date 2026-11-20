# Copyright 2026 Justin Overfelt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""BridgeCom Systems BCM-220 mobile radio

Clone protocol (38400 8N1, as used by "BCM Radio Programmer" 2.3):

  wake up:      AA, wait 1s, AA, wait 1s
  enter mode:   37 AA (read) or 36 AA (write)   -> 55
  per block n:  BB n_lo n_hi                     -> AA
    read:       AA  -> 256 data bytes + sum(data) & 0xFF
    write:      256 data bytes + (-sum(data)) & 0xFF  -> AA
  finish:       EE (radio reboots)

The memory is 40 blocks of 256 bytes: radio-wide settings in the first
block, then 250 channels of 40 bytes each.  That is 16 bytes more than
the radio clones, so the last channel only has 12 characters of name.

Frequencies 219.0-220.0 MHz may only be used for data in the US.  The
vendor software forces such channels to be "Data only" (microphone audio
disabled, TX audio comes from the accessory connector), and so does this
driver.

The radio keeps some state of its own in otherwise unused bytes: settings
byte 0x5d and the 12 padding bytes at the end of channel records.  The
vendor software zeroes all of these on every upload.  Writing back stale
values downloaded earlier can make the radio drop channels from the
in-use bitmap at the next power on (seen with a non-empty scan list), so
this driver clears them before uploading too.
"""

import logging
import time

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import (MemSetting, RadioSetting, RadioSettingGroup,
                            RadioSettings, RadioSettingValueBoolean,
                            RadioSettingValueInteger, RadioSettingValueList,
                            RadioSettingValueString)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  u8 unknown0;
  u8 unknown1:1,
     beeps:1,
     scan_unmute_carrier:1,   // 1: CARRIER, 0: DECODE
     vfo_wide:1,              // VFO defaults are not exposed
     cos_decode:1,            // 1: DECODE, 0: CARRIER
     unknown2:3;
  char password[10];
  u8 model;                   // 0: BCM-220, 1: BCM-144, 2: BCM-440
  u8 squelch;                 // 1-9
  u8 vfo_offset;              // 0: -1.6 MHz, 1: 0, 2: +1.6 MHz (VFO)
  u8 vfo_step;
  u8 vfo_rxtone;
  u8 vfo_txtone;
  ul16 tot;                   // seconds
  ul16 vfo_power;
  ul16 scan_speed;            // ms
  ul16 scan_hang;             // ms
  ul16 scan_wait;             // ms
  bit used[256];              // channel is in use
  bit scanlist[256];          // channel is in the scan list
  u8 apo;                     // hours - 1
  u8 radio_state;             // written by the radio itself
} settings;

#seekto 0x0100;
struct {
  ul32 rxfreq;                // Hz
  ul32 txfreq;                // Hz
  u8 rxtone;
  u8 txtone;
  u8 unknown1:1,
     wide:1,
     data:1,
     scan:1,
     unknown2:4;
  u8 power;
  char name[16];
  u8 unknown3[12];
} memory[249];

// The radio clones 0x2800 bytes, which ends 16 bytes short of the end of
// the 250th 40-byte record, so only 12 characters of its name exist.
struct {
  ul32 rxfreq;
  ul32 txfreq;
  u8 rxtone;
  u8 txtone;
  u8 unknown1:1,
     wide:1,
     data:1,
     scan:1,
     unknown2:4;
  u8 power;
  char name[12];
} last_memory;
"""

BLOCK_SIZE = 0x100
NUM_BLOCKS = 40
MEM_SIZE = BLOCK_SIZE * NUM_BLOCKS
# Serial timeout, set once per session
TIMEOUT = 3
NUM_CHANNELS = 250
NAME_LENGTH = 16
# Settings byte 0x0c says which radio of the BCM family this is
MODEL_OFFSET = 0x0c
MODEL_NAMES = {0: 'BCM-220', 1: 'BCM-144', 2: 'BCM-440'}
# The last channel is cut short by the end of the clone area (see MEM_FORMAT)
LAST_NAME_LENGTH = 12

CMD_READ = 0x37
CMD_WRITE = 0x36
CMD_ADDR = 0xBB
CMD_RESET = 0xEE
ACK_MODE = b'\x55'
ACK_EXIT = b'\x00'
ACK = b'\xAA'

# Tone codes: 0 is none, then CTCSS, then DCS normal and DCS inverted
# (The radio has the old tone set, but not 69.3.)
CTCSS_TONES = [t for t in chirp_common.OLD_TONES if t != 69.3]
DCS_CODES = [23, 25, 26, 31, 32, 43, 47, 51, 54, 65, 71, 72, 73, 74, 114,
             115, 116, 125, 131, 132, 134, 143, 152, 155, 156, 162, 165, 172,
             174, 205, 223, 226, 243, 244, 245, 251, 261, 263, 265, 271, 306,
             311, 315, 331, 343, 346, 351, 364, 365, 371, 411, 412, 413, 423,
             431, 432, 445, 464, 465, 466, 503, 506, 516, 532, 546, 565, 606,
             612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723, 731, 732,
             734, 743, 754]
DCS_BASE = 1 + len(CTCSS_TONES)
DCS_INV_BASE = DCS_BASE + len(DCS_CODES)
TONE_CODES = DCS_INV_BASE + len(DCS_CODES)

POWER_LEVELS = [chirp_common.PowerLevel("5W", watts=5),
                chirp_common.PowerLevel("10W", watts=10),
                chirp_common.PowerLevel("20W", watts=20),
                chirp_common.PowerLevel("30W", watts=30)]

DATA_BAND = (219000000, 220000000)
VOICE_BAND = (222000000, 225000000)

# The radio stores the index into these lists
APO_LIST = ["%i Hours" % h for h in range(1, 13)]
# raw bit 1 is DECODE for the COS output ...
COS_LIST = ["CARRIER", "DECODE"]
# ... but CARRIER for the scan unmute condition
SCAN_UNMUTE_LIST = ["DECODE", "CARRIER"]
NAME_CHARSET = (chirp_common.CHARSET_UPPER_NUMERIC +
                "abcdefghijklmnopqrstuvwxyz-/")
PASSWORD_CHARSET = chirp_common.CHARSET_ALPHANUMERIC


def is_data_freq(freq):
    return DATA_BAND[0] <= freq <= DATA_BAND[1]


def _tx_freq(mem):
    """Compute the full TX frequency for a memory"""
    if mem.duplex == 'split':
        return mem.offset
    if mem.duplex == '+':
        return mem.freq + mem.offset
    if mem.duplex == '-':
        return mem.freq - mem.offset
    return mem.freq


def decode_tone(code):
    """Return (mode, value, polarity) for a radio tone code"""
    if 1 <= code < DCS_BASE:
        return 'Tone', CTCSS_TONES[code - 1], None
    elif DCS_BASE <= code < DCS_INV_BASE:
        return 'DTCS', DCS_CODES[code - DCS_BASE], 'N'
    elif DCS_INV_BASE <= code < TONE_CODES:
        return 'DTCS', DCS_CODES[code - DCS_INV_BASE], 'R'
    return '', None, None


def encode_tone(mode, value, polarity):
    if mode == 'Tone':
        return 1 + CTCSS_TONES.index(value)
    elif mode == 'DTCS':
        base = DCS_INV_BASE if polarity == 'R' else DCS_BASE
        return base + DCS_CODES.index(value)
    return 0


def _send(radio, data):
    radio.pipe.write(bytes(data))


def _recv(radio, length, what):
    """Read exactly length bytes, or fail"""
    data = radio.pipe.read(length)
    if len(data) != length:
        LOG.debug('Wanted %i bytes for %s, got %r', length, what, data)
        raise errors.RadioError('Timeout waiting for %s' % what)
    return data


def _expect(radio, ack, what):
    resp = _recv(radio, len(ack), what)
    if resp != ack:
        LOG.debug('Expected %r for %s, got %r', ack, what, resp)
        raise errors.RadioError('Radio did not acknowledge %s' % what)


def _enter_mode(radio, cmd):
    radio.pipe.timeout = TIMEOUT
    radio.pipe.dtr = False
    radio.pipe.rts = False
    # The vendor software sends two wake-up bytes a second apart, and the
    # radio ignores the mode command without them.
    for i in range(2):
        _send(radio, [ACK[0]])
        time.sleep(1)
    _send(radio, [cmd, ACK[0]])
    try:
        _expect(radio, ACK_MODE, 'the mode command')
    except errors.RadioError:
        raise errors.RadioError('Radio did not respond. Check the cable '
                                'and that the radio is powered on.')


def _send_address(radio, block):
    _send(radio, [CMD_ADDR, block & 0xFF, block >> 8])
    _expect(radio, ACK, 'block %i address' % block)


def _exit(radio):
    # The radio reboots, and answers with a single zero byte first
    _send(radio, [CMD_RESET])
    resp = radio.pipe.read(1)
    if resp != ACK_EXIT:
        LOG.debug('Unexpected reply to reset: %r', resp)


def _check_model(radio, block0):
    """Refuse a radio that identifies as a different BCM model

    The BCM-144, BCM-220 and BCM-440 share one protocol and memory layout
    but have different bands, so this driver's band plan would be wrong for
    the others. Values the vendor software does not define are let through.
    """
    model = block0[MODEL_OFFSET]
    if model in MODEL_NAMES and model != radio._model_code:
        raise errors.RadioError(
            'This radio identifies as a %s, not a %s. It is not supported '
            'by this driver.' % (MODEL_NAMES[model], radio.MODEL))


def do_download(radio):
    status = chirp_common.Status()
    status.msg = 'Cloning from radio'
    status.max = NUM_BLOCKS
    data = b''
    _enter_mode(radio, CMD_READ)
    try:
        for block in range(NUM_BLOCKS):
            _send_address(radio, block)
            _send(radio, ACK)
            chunk = _recv(radio, BLOCK_SIZE + 1, 'block %i' % block)
            if sum(chunk[:BLOCK_SIZE]) & 0xFF != chunk[BLOCK_SIZE]:
                raise errors.RadioError('Bad checksum in block %i' % block)
            if block == 0:
                _check_model(radio, chunk)
            data += chunk[:BLOCK_SIZE]
            status.cur = block + 1
            radio.status_fn(status)
    finally:
        _exit(radio)
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = 'Cloning to radio'
    status.max = NUM_BLOCKS
    _enter_mode(radio, CMD_WRITE)
    try:
        for block in range(NUM_BLOCKS):
            _send_address(radio, block)
            chunk = radio.get_mmap()[block * BLOCK_SIZE:
                                     (block + 1) * BLOCK_SIZE]
            _send(radio, chunk + bytes([(-sum(chunk)) & 0xFF]))
            _expect(radio, ACK, 'block %i data' % block)
            status.cur = block + 1
            radio.status_fn(status)
    finally:
        _exit(radio)


@directory.register
class BCM220Radio(chirp_common.CloneModeRadio):
    """BridgeCom Systems BCM-220"""
    VENDOR = 'BridgeCom'
    MODEL = 'BCM-220'
    BAUD_RATE = 38400

    _memsize = MEM_SIZE
    _model_code = 0

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver was written from the vendor programming software '
            'and has been tested on one radio. Please keep a saved copy of '
            'your first download.')
        rp.info = (
            'Channels between 219.0 and 220.0 MHz are always "Data only": '
            'the radio disables microphone audio on them, as required in '
            'the US. Data only can also be enabled for 222-225 MHz '
            'channels.')
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_tuning_step = False
        rf.has_comment = False
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'Tone->DTCS', 'DTCS->Tone',
                                'DTCS->', '->Tone', '->DTCS', 'DTCS->DTCS']
        rf.valid_tones = CTCSS_TONES
        rf.valid_dtcs_codes = DCS_CODES
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_duplexes = ['', '-', '+', 'split']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = ['', 'S']
        rf.valid_name_length = 16
        rf.valid_characters = NAME_CHARSET
        rf.valid_bands = [DATA_BAND, VOICE_BAND]
        rf.memory_bounds = (1, NUM_CHANNELS)
        rf.can_odd_split = True
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Download failed')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def _clear_radio_state(self):
        # See the module docstring: the vendor software never sends the
        # radio's own state back, and doing so can corrupt the channel list.
        if self._memobj is None:
            return
        self._memobj.settings.radio_state = 0
        for mem in self._memobj.memory:
            mem.unknown3.fill_raw(b'\x00')

    def sync_out(self):
        self._clear_radio_state()
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Upload failed')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _get_mem(self, number):
        if number == NUM_CHANNELS:
            return self._memobj.last_memory
        return self._memobj.memory[number - 1]

    def get_raw_memory(self, number):
        return repr(self._get_mem(number))

    def _is_used(self, index):
        return bool(self._memobj.settings.used[index])

    def get_memory(self, number):
        index = number - 1
        _mem = self._get_mem(number)
        mem = chirp_common.Memory(number)

        if not self._is_used(index) or int(_mem.rxfreq) == 0:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq)
        txfreq = int(_mem.txfreq)
        chirp_common.split_to_offset(mem, mem.freq, txfreq)
        mem.name = str(_mem.name).rstrip(' \x00')
        mem.mode = 'FM' if _mem.wide else 'NFM'
        mem.power = POWER_LEVELS[min(int(_mem.power), len(POWER_LEVELS) - 1)]
        mem.skip = '' if self._memobj.settings.scanlist[index] else 'S'

        txmode, txval, txpol = decode_tone(int(_mem.txtone))
        rxmode, rxval, rxpol = decode_tone(int(_mem.rxtone))
        chirp_common.split_tone_decode(mem, (txmode, txval, txpol),
                                       (rxmode, rxval, rxpol))

        mem.extra = RadioSettingGroup('extra', 'Extra')
        data = RadioSetting('data', 'Data only (no mic audio)',
                            RadioSettingValueBoolean(bool(_mem.data)))
        data.set_doc('Disable microphone audio; transmit audio comes from '
                     'the accessory connector. Always on for 219-220 MHz.')
        mem.extra.append(data)
        return mem

    def set_memory(self, mem):
        index = mem.number - 1
        _mem = self._get_mem(mem.number)
        settings = self._memobj.settings

        was_used = self._is_used(index) and int(_mem.rxfreq) != 0

        if mem.empty:
            # Leave never-used slots alone; the radio keeps stray bytes in
            # some of them.
            if was_used:
                _mem.fill_raw(b'\x00')
            settings.used[index] = False
            settings.scanlist[index] = False
            return
        if not was_used:
            _mem.fill_raw(b'\x00')
            # The vendor software leaves these set on every channel
            _mem.unknown2 = 0b1001

        _mem.rxfreq = mem.freq
        _mem.txfreq = _tx_freq(mem)

        name_length = (LAST_NAME_LENGTH if mem.number == NUM_CHANNELS
                       else NAME_LENGTH)
        _mem.name = mem.name[:name_length].ljust(name_length)
        _mem.wide = mem.mode == 'FM'
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = len(POWER_LEVELS) - 1

        scan = mem.skip != 'S'
        _mem.scan = scan
        settings.scanlist[index] = scan
        settings.used[index] = True

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)
        _mem.txtone = encode_tone(txmode, txval, txpol)
        _mem.rxtone = encode_tone(rxmode, rxval, rxpol)

        data = bool(_mem.data) if was_used else False
        if mem.extra and 'data' in mem.extra:
            data = bool(mem.extra['data'].value)
        if is_data_freq(mem.freq) or is_data_freq(int(_mem.txfreq)):
            data = True
        _mem.data = data

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs

        txfreq_hz = _tx_freq(mem)

        if (mem.number == NUM_CHANNELS and
                len(mem.name.rstrip()) > LAST_NAME_LENGTH):
            msgs.append(chirp_common.ValidationWarning(
                'Channel 250 names are limited to %i characters' %
                LAST_NAME_LENGTH))

        if is_data_freq(mem.freq) != is_data_freq(txfreq_hz):
            msgs.append(chirp_common.ValidationError(
                'RX and TX must both be in 219-220 MHz or both in '
                '222-225 MHz'))
        elif is_data_freq(mem.freq):
            data = mem.extra and 'data' in mem.extra and \
                bool(mem.extra['data'].value)
            if mem.extra and 'data' in mem.extra and not data:
                msgs.append(chirp_common.ValidationWarning(
                    '219-220 MHz channels are always set to Data only'))
        return msgs

    def get_settings(self):
        _set = self._memobj.settings
        basic = RadioSettingGroup('basic', 'Basic Settings')
        scan = RadioSettingGroup('scan', 'Scan')
        top = RadioSettings(basic, scan)

        def add(group, name, label, value, doc):
            rs = MemSetting('settings.%s' % name, label, value)
            rs.set_doc(doc)
            group.append(rs)

        def choice(options, index):
            return RadioSettingValueList(
                options, current_index=min(int(index), len(options) - 1))

        def number(low, high, value):
            return RadioSettingValueInteger(low, high,
                                            min(max(int(value), low), high))

        add(basic, 'squelch', 'Squelch', number(1, 9, _set.squelch),
            'Squelch level, from 1 (loose) to 9 (tight)')
        add(basic, 'beeps', 'Beeps',
            RadioSettingValueBoolean(bool(_set.beeps)),
            'Key and confirmation beeps')
        add(basic, 'tot', 'TX time-out (seconds)',
            number(0, 600, _set.tot),
            'Longest single transmission allowed (stuck mic timer)')
        add(basic, 'apo', 'Auto power off', choice(APO_LIST, _set.apo),
            'How long the radio may sit idle before powering off')
        add(basic, 'cos_decode', 'COS output',
            choice(COS_LIST, _set.cos_decode),
            'When the accessory connector COS output becomes active: on '
            'any carrier, or only on a valid tone/code decode')
        add(basic, 'password', 'Programming password',
            RadioSettingValueString(0, 10,
                                    str(_set.password).rstrip('\x00 '),
                                    charset=PASSWORD_CHARSET,
                                    mem_pad_char='\x00'),
            'Password the vendor software asks for before reading the '
            'radio. Leave blank for none.')

        add(scan, 'scan_unmute_carrier', 'Scan unmute',
            choice(SCAN_UNMUTE_LIST, _set.scan_unmute_carrier),
            'Stop scanning on any carrier, or only on a valid tone/code '
            'decode')
        add(scan, 'scan_speed', 'Scan speed (ms per channel)',
            number(100, 5000, _set.scan_speed),
            'Time spent on each channel while scanning')
        add(scan, 'scan_hang', 'Scan hang time (ms)',
            number(400, 5000, _set.scan_hang),
            'Time to wait after a call ends before resuming the scan')
        add(scan, 'scan_wait', 'Scan wait for signal (ms)',
            number(0, 5000, _set.scan_wait),
            'Time to wait for a valid signal before resuming the scan')
        return top

    def set_settings(self, settings):
        settings.apply_to(self._memobj)
