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
block, then 250 channels of 40 bytes each.

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
from chirp.settings import (RadioSetting, RadioSettingGroup,
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
     vfo_wide:1,
     cos_decode:1,            // 1: DECODE, 0: CARRIER
     unknown2:3;
  char password[10];
  u8 model;                   // 0: BCM-220, 1: BCM-144, 2: BCM-440
  u8 squelch;                 // 1-9
  u8 vfo_offset;              // 0: -1.6 MHz, 1: 0, 2: +1.6 MHz
  u8 vfo_step;
  u8 vfo_rxtone;
  u8 vfo_txtone;
  ul16 tot;                   // seconds
  ul16 vfo_power;
  ul16 scan_speed;            // ms
  ul16 scan_hang;             // ms
  ul16 scan_wait;             // ms
  u8 used[32];                // bitmap, MSB first
  u8 scanlist[32];            // bitmap, MSB first
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
} memory[250];
"""

BLOCK_SIZE = 0x100
NUM_BLOCKS = 40
CLONE_SIZE = BLOCK_SIZE * NUM_BLOCKS
# 0x100 + 250 * 40 runs 16 bytes past the end of what the radio clones, so
# the last 4 name characters of channel 250 are never transferred.  Like the
# vendor software, keep a 0x2810 byte image and pad the tail.
MEM_SIZE = 0x2810
LAST_NAME_LENGTH = 12

CMD_READ = 0x37
CMD_WRITE = 0x36
CMD_ADDR = 0xBB
CMD_RESET = 0xEE
ACK_MODE = b'\x55'
ACK = b'\xAA'

# Tone codes: 0 is none, then CTCSS, then DCS normal and DCS inverted
CTCSS_TONES = [67.0, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
               97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
               131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8,
               179.9, 186.2, 192.8, 203.5, 210.7, 218.1, 225.7, 233.6, 241.8,
               250.3]
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

STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0]
STEP_LIST = ["%i Hz" % (s * 1000) for s in STEPS]
OFFSET_LIST = ["-1.6 MHz", "0 MHz", "+1.6 MHz"]
UNMUTE_LIST = ["CARRIER", "DECODE"]
APO_LIST = ["%i Hours" % h for h in range(1, 13)]
SQUELCH_LIST = ["%i" % i for i in range(1, 10)]
TONE_LIST = (["NONE"] + ["%.1f" % t for t in CTCSS_TONES] +
             ["%03i" % c for c in DCS_CODES] +
             ["%03ii" % c for c in DCS_CODES])
NAME_CHARSET = (chirp_common.CHARSET_UPPER_NUMERIC +
                "abcdefghijklmnopqrstuvwxyz-/")
PASSWORD_CHARSET = chirp_common.CHARSET_ALPHANUMERIC


def is_data_freq(freq):
    return DATA_BAND[0] <= freq <= DATA_BAND[1]


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


def _bit(bitmap, index):
    return bool(bitmap[index // 8] & (0x80 >> (index % 8)))


def _set_bit(bitmap, index, value):
    mask = 0x80 >> (index % 8)
    if value:
        bitmap[index // 8] |= mask
    else:
        bitmap[index // 8] &= ~mask


def _send(radio, data):
    radio.pipe.write(bytes(data))


def _recv(radio, length):
    data = b''
    deadline = time.time() + 3
    while len(data) < length and time.time() < deadline:
        data += radio.pipe.read(length - len(data))
    return data


def _expect(radio, ack, what):
    resp = _recv(radio, len(ack))
    if resp != ack:
        LOG.debug('Expected %r for %s, got %r', ack, what, resp)
        raise errors.RadioError('Radio did not acknowledge %s' % what)


def _enter_mode(radio, cmd):
    radio.pipe.timeout = 0.25
    try:
        radio.pipe.dtr = False
        radio.pipe.rts = False
    except Exception:
        pass
    # The vendor software sends two wake-up bytes a second apart, and the
    # radio ignores the mode command without them.
    for i in range(2):
        _send(radio, [ACK[0]])
        time.sleep(1)
        radio.pipe.read(256)
    _send(radio, [cmd, ACK[0]])
    resp = _recv(radio, 1)
    if resp != ACK_MODE:
        LOG.debug('Mode response %r', resp)
        raise errors.RadioError('Radio did not respond. Check the cable '
                                'and that the radio is powered on.')


def _send_address(radio, block):
    _send(radio, [CMD_ADDR, block & 0xFF, block >> 8])
    _expect(radio, ACK, 'block %i address' % block)


def _exit(radio):
    _send(radio, [CMD_RESET])
    time.sleep(0.5)
    radio.pipe.read(16)


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
            chunk = _recv(radio, BLOCK_SIZE + 1)
            if len(chunk) != BLOCK_SIZE + 1:
                raise errors.RadioError('Short read of block %i' % block)
            if sum(chunk[:BLOCK_SIZE]) & 0xFF != chunk[BLOCK_SIZE]:
                raise errors.RadioError('Bad checksum in block %i' % block)
            data += chunk[:BLOCK_SIZE]
            status.cur = block + 1
            radio.status_fn(status)
    finally:
        _exit(radio)
    return memmap.MemoryMapBytes(data + b'\x00' * (MEM_SIZE - CLONE_SIZE))


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
        rf.valid_tuning_steps = STEPS
        rf.memory_bounds = (1, 250)
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

    @classmethod
    def match_model(cls, filedata, filename):
        # Only match images with CHIRP metadata
        return False

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _is_used(self, index):
        return _bit(self._memobj.settings.used, index)

    def get_memory(self, number):
        index = number - 1
        _mem = self._memobj.memory[index]
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
        mem.skip = '' if _bit(self._memobj.settings.scanlist, index) else 'S'

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
        _mem = self._memobj.memory[index]
        settings = self._memobj.settings

        was_used = self._is_used(index) and int(_mem.rxfreq) != 0

        if mem.empty:
            # Leave never-used slots alone; the radio keeps stray bytes in
            # some of them.
            if was_used:
                _mem.fill_raw(b'\x00')
            _set_bit(settings.used, index, False)
            _set_bit(settings.scanlist, index, False)
            return
        if not was_used:
            _mem.fill_raw(b'\x00')
            # The vendor software leaves these set on every channel
            _mem.unknown2 = 0b1001

        _mem.rxfreq = mem.freq
        if mem.duplex == 'split':
            _mem.txfreq = mem.offset
        elif mem.duplex == '+':
            _mem.txfreq = mem.freq + mem.offset
        elif mem.duplex == '-':
            _mem.txfreq = mem.freq - mem.offset
        else:
            _mem.txfreq = mem.freq

        if mem.number == 250:
            _mem.name = mem.name[:LAST_NAME_LENGTH].ljust(16)
        else:
            _mem.name = mem.name[:16].ljust(16)
        _mem.wide = mem.mode == 'FM'
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = len(POWER_LEVELS) - 1

        scan = mem.skip != 'S'
        _mem.scan = scan
        _set_bit(settings.scanlist, index, scan)
        _set_bit(settings.used, index, True)

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

        if mem.duplex == 'split':
            txfreq = mem.offset
        elif mem.duplex == '+':
            txfreq = mem.freq + mem.offset
        elif mem.duplex == '-':
            txfreq = mem.freq - mem.offset
        else:
            txfreq = mem.freq

        if mem.number == 250 and len(mem.name.rstrip()) > LAST_NAME_LENGTH:
            msgs.append(chirp_common.ValidationWarning(
                'Channel 250 names are limited to %i characters' %
                LAST_NAME_LENGTH))

        if is_data_freq(mem.freq) != is_data_freq(txfreq):
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
        vfo = RadioSettingGroup('vfo', 'VFO')
        top = RadioSettings(basic, scan, vfo)

        def add(group, name, label, value, doc):
            rs = RadioSetting(name, label, value)
            rs.set_doc(doc)
            group.append(rs)

        def choice(options, index):
            return RadioSettingValueList(
                options, current_index=min(int(index), len(options) - 1))

        def number(low, high, value):
            return RadioSettingValueInteger(low, high,
                                            min(max(int(value), low), high))

        add(basic, 'squelch', 'Squelch',
            choice(SQUELCH_LIST, max(int(_set.squelch), 1) - 1),
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
            choice(UNMUTE_LIST, _set.cos_decode),
            'When the accessory connector COS output becomes active: on '
            'any carrier, or only on a valid tone/code decode')
        add(basic, 'password', 'Programming password',
            RadioSettingValueString(0, 10,
                                    str(_set.password).rstrip('\x00 '),
                                    autopad=False,
                                    charset=PASSWORD_CHARSET),
            'Password the vendor software asks for before reading the '
            'radio. Leave blank for none.')

        add(scan, 'scan_unmute_carrier', 'Scan unmute',
            choice(UNMUTE_LIST, 0 if _set.scan_unmute_carrier else 1),
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

        add(vfo, 'vfo_power', 'TX power',
            choice([str(p) for p in POWER_LEVELS], _set.vfo_power),
            'Transmit power in VFO mode')
        add(vfo, 'vfo_step', 'Frequency step', choice(STEP_LIST,
                                                      _set.vfo_step),
            'Tuning step in VFO mode')
        add(vfo, 'vfo_wide', 'Channel spacing',
            choice(['NARROW', 'WIDE'], _set.vfo_wide),
            'Channel spacing in VFO mode: narrow (12.5 kHz) or wide '
            '(25 kHz)')
        add(vfo, 'vfo_offset', 'Duplex offset',
            choice(OFFSET_LIST, _set.vfo_offset),
            'Repeater offset in VFO mode')
        add(vfo, 'vfo_rxtone', 'RX signal',
            choice(TONE_LIST, _set.vfo_rxtone),
            'CTCSS tone or DCS code required to unmute in VFO mode '
            '("i" means inverted DCS)')
        add(vfo, 'vfo_txtone', 'TX signal',
            choice(TONE_LIST, _set.vfo_txtone),
            'CTCSS tone or DCS code sent in VFO mode ("i" means inverted '
            'DCS)')
        return top

    def set_settings(self, settings):
        _set = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            name = element.get_name()
            value = element.value
            if name == 'squelch':
                _set.squelch = int(value) + 1
            elif name == 'scan_unmute_carrier':
                _set.scan_unmute_carrier = int(value) == 0
            elif name == 'password':
                _set.password = str(value).ljust(10, '\x00')
            elif isinstance(value, RadioSettingValueList):
                setattr(_set, name, int(value))
            else:
                setattr(_set, name, int(value))
