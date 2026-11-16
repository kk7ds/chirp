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

"""Kenwood TH-K20 clone-mode driver.

Clone protocol (as used by Kenwood MCP-5A):

* PC sends "$AMAPRG" at 9600 baud and the radio answers '&'. Both sides
  then switch to 19200 baud and the radio sends SYN (0x16).
* PC sends 0x12 and the radio answers with a 44-byte ident block that
  includes the model name ("TH-K20A", etc).
* PC sends a key byte and SYN, and the radio answers SYN. From then on,
  every byte in both directions is XORed with a session key of
  ((sum(ident[28:40]) ^ keybyte) + 0x41) & 0xFF, except that the radio
  uses 0x41 instead of 0. MCP-5A sends the current minutes + seconds as
  the key byte (the radio has no clock); we instead always pick the byte
  that makes the key 0x41 (the closest we can get to no XOR at all), so
  that serial traces are the same every time.
* Read:  'c' addr_hi addr_lo len -> 'h' + len bytes; PC sends SYN and
  the radio answers SYN.
* Write: 'h' addr_hi addr_lo len + len bytes -> radio answers SYN.
* Exit:  'U' -> radio answers SYN.
"""

import logging
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import MemSetting, RadioSettingGroup
from chirp.settings import RadioSettingValueBoolean

LOG = logging.getLogger(__name__)

SYN = 0x16
IDENT_LEN = 44

# Regions of radio memory read by MCP-5A. Only the first (channels and
# settings) is ever written back; the others hold factory/model data.
READ_RANGES = [(0x0000, 0x15C0), (0x1DC0, 0x1E10), (0x1E50, 0x1E60)]
WRITE_RANGES = [(0x0000, 0x15C0)]
MEMSIZE = 0x1E60
READ_BLOCK = 0x40
WRITE_BLOCK = 0x10

# MCP-5A save file (.mc5): a 0x100-byte header followed by the read
# ranges above, concatenated in order.
MC5_MAGIC = b'MCP-5A'
MC5_HEADER = 0x100
MC5_SIZE = MC5_HEADER + sum(e - s for s, e in READ_RANGES)

MEM_FORMAT = """
struct chan {
  ul32 freq;
  u8 rxstep;
  u8 unknown1:6,
     narrow:1,
     beatshift:1;
  u8 tmode:4,
     reverse:1,
     split:1,
     shift:2;
  u8 rtone;
  u8 ctone;
  u8 dtcs;
  u8 cross;
  ul32 offset;
  u8 txstep;
};

#seekto 0x0180;
struct chan memory[200];

#seekto 0x0F10;
struct chan call;

#seekto 0x0F40;
struct {
  char name[6];
} names[200];

#seekto 0x1480;
struct {
  u8 lockout:1,
     unknown2:7;
} flags[200];

#seekto 0x1E50;
char model[16];
"""

TONES = (67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
         94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0,
         127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9,
         173.8, 179.9, 186.2, 192.8, 203.5, 206.5, 210.7, 218.1, 225.7,
         229.1, 233.6, 241.8, 250.3, 254.1)
DTCS_CODES = tuple(chirp_common.DTCS_CODES)
STEPS = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]

# Values of the tmode field
TMODE_OFF = 0
TMODE_CROSS = 1
TMODE_DTCS = 2
TMODE_TSQL = 4
TMODE_TONE = 8
TMODES = {TMODE_OFF: '', TMODE_TONE: 'Tone', TMODE_TSQL: 'TSQL',
          TMODE_DTCS: 'DTCS', TMODE_CROSS: 'Cross'}

# Values of the cross field, used when tmode is TMODE_CROSS
CROSS_MODES = ['DTCS->', 'Tone->DTCS', 'DTCS->Tone', 'Tone->Tone']

DUPLEXES = ['', '+', '-']
CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + '-/'
NAME_LENGTH = 6
NUM_MEMS = 200
SPECIALS = ['Call']

# New channels start from what MCP-5A uses for an unprogrammed one
EMPTY_CHANNEL = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0xFC, 0x00, 0x08,
                       0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def _status(radio, cur, total, msg):
    status = chirp_common.Status()
    status.cur = cur
    status.max = total
    status.msg = msg
    radio.status_fn(status)


# The radio refuses a zero key and substitutes this one
SESSION_KEY = 0x41


def _key_byte(ident):
    # Chosen so that (sum ^ keybyte) + 0x41 wraps to zero, which the radio
    # then replaces with SESSION_KEY
    return (sum(ident[28:40]) & 0xFF) ^ (0x100 - SESSION_KEY)


class THK20Session:
    """A single programming-mode session with the radio"""

    def __init__(self, pipe):
        self.pipe = pipe
        self.key = 0

    def _xor(self, data):
        return bytes(b ^ self.key for b in data)

    def _send(self, data):
        self.pipe.write(self._xor(data))

    def _recv(self, count):
        data = self.pipe.read(count)
        if len(data) != count:
            LOG.error('Short read: expected %i bytes, got %i',
                      count, len(data))
            raise errors.RadioError('Radio stopped responding')
        return self._xor(data)

    def _expect_syn(self, what):
        resp = self._recv(1)
        if resp[0] != SYN:
            LOG.error('Expected SYN after %s, got %02x', what, resp[0])
            raise errors.RadioError('Radio refused %s' % what)

    def enter(self):
        pipe = self.pipe
        pipe.baudrate = 9600
        pipe.timeout = 3
        pipe.write(b'$AMAPRG')
        resp = pipe.read(1)
        if not resp:
            raise errors.RadioNoResponse()
        if resp != b'&':
            LOG.error('Unexpected handshake response %r', resp)
            raise errors.RadioError('Radio refused programming mode')

        pipe.baudrate = 19200
        self._expect_syn('program mode')

        pipe.write(b'\x12')
        ident = self._recv(IDENT_LEN)
        LOG.debug('Radio ident: %r', ident)
        if b'TH-K20' not in ident:
            raise errors.RadioError('Radio is not a TH-K20')

        pipe.write(bytes([_key_byte(ident), SYN]))
        self._expect_syn('session key')
        self.key = SESSION_KEY
        pipe.log('All further data is XORed with 0x%02X' % SESSION_KEY)
        return ident

    def read_block(self, addr, length):
        self._send(struct.pack('>BHB', ord('c'), addr, length))
        resp = self._recv(1 + length)
        if resp[0] != ord('h'):
            LOG.error('Bad read response at %04x: %02x', addr, resp[0])
            raise errors.RadioError('Invalid response from radio')
        self._send(bytes([SYN]))
        self._expect_syn('read at %04x' % addr)
        return resp[1:]

    def write_block(self, addr, data):
        self._send(struct.pack('>BHB', ord('h'), addr, len(data)) + data)
        self._expect_syn('write at %04x' % addr)

    def exit(self):
        self._send(b'U')
        self.pipe.read(1)


def do_download(radio):
    session = THK20Session(radio.pipe)
    data = bytearray(b'\xFF' * MEMSIZE)
    total = sum(e - s for s, e in READ_RANGES)
    done = 0
    session.enter()
    try:
        for start, end in READ_RANGES:
            for addr in range(start, end, READ_BLOCK):
                length = min(READ_BLOCK, end - addr)
                data[addr:addr + length] = session.read_block(addr, length)
                done += length
                _status(radio, done, total, 'Cloning from radio')
    finally:
        session.exit()
    return memmap.MemoryMapBytes(bytes(data))


def do_upload(radio):
    session = THK20Session(radio.pipe)
    data = radio.get_mmap().get_packed()
    total = sum(e - s for s, e in WRITE_RANGES)
    done = 0
    ident = session.enter()
    try:
        # The image model string is e.g. "PTH-K20" and the ident block
        # contains "TH-K20A"; make sure we are not writing an image from
        # some other model.
        model = data[0x1E51:0x1E60].rstrip(b'\xFF')
        if model and model not in ident:
            raise errors.RadioError('Image is for a different model')
        for start, end in WRITE_RANGES:
            for addr in range(start, end, WRITE_BLOCK):
                length = min(WRITE_BLOCK, end - addr)
                session.write_block(addr, data[addr:addr + length])
                done += length
                _status(radio, done, total, 'Cloning to radio')
    finally:
        session.exit()


@directory.register
class THK20Radio(chirp_common.CloneModeRadio):
    """Kenwood TH-K20"""
    VENDOR = 'Kenwood'
    MODEL = 'TH-K20'
    BAUD_RATE = 9600
    FORMATS = [directory.register_format('Kenwood MCP-5A', '*.mc5')]
    _memsize = MEMSIZE

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver was developed without documentation from the '
            'manufacturer. Please keep a backup of your radio image '
            'before uploading.')
        rp.pre_download = (
            'Connect the programming cable to the radio and turn the radio '
            'on. The radio will show "MCP" on the display while cloning.')
        rp.pre_upload = rp.pre_download
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        # Only used to recognize MCP-5A save files
        return (len(filedata) == MC5_SIZE and
                filedata.startswith(MC5_MAGIC) and
                b'TH-K20' in filedata[:MC5_HEADER])

    def load_mmap(self, filename):
        with open(filename, 'rb') as f:
            filedata = f.read()
        if not self.match_model(filedata, filename):
            return super().load_mmap(filename)

        data = bytearray(b'\xFF' * MEMSIZE)
        pos = MC5_HEADER
        for start, end in READ_RANGES:
            data[start:end] = filedata[pos:pos + end - start]
            pos += end - start
        self._mmap = memmap.MemoryMapBytes(bytes(data))
        self.process_mmap()

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed to download from radio')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed to upload to radio')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, NUM_MEMS - 1)
        rf.valid_special_chans = list(SPECIALS)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = True
        rf.can_odd_split = True
        rf.valid_bands = [(136000000, 174000000)]
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = list(CROSS_MODES)
        rf.valid_duplexes = DUPLEXES + ['split']
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_characters = CHARSET
        rf.valid_name_length = NAME_LENGTH
        rf.valid_skips = ['', 'S']
        return rf

    def _get_objects(self, number):
        if isinstance(number, str):
            return (self._memobj.call, None, None,
                    NUM_MEMS + SPECIALS.index(number), number)
        if number >= NUM_MEMS:
            name = SPECIALS[number - NUM_MEMS]
            return self._memobj.call, None, None, number, name
        return (self._memobj.memory[number], self._memobj.names[number],
                self._memobj.flags[number], number, None)

    def get_raw_memory(self, number):
        _mem, _name, _flag, _num, _ext = self._get_objects(number)
        return '\n'.join(repr(x) for x in (_mem, _name, _flag)
                         if x is not None)

    @staticmethod
    def _is_empty(_mem, _flag):
        if _flag is not None and _flag.get_raw() == b'\xFF':
            return True
        return _mem.get_raw()[:4] == b'\xFF\xFF\xFF\xFF'

    def get_memory(self, number):
        _mem, _name, _flag, num, ext = self._get_objects(number)
        mem = chirp_common.Memory()
        mem.number = num
        if ext:
            mem.extd_number = ext
            mem.immutable = ['empty', 'name', 'skip']

        if self._is_empty(_mem, _flag):
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq)
        mem.offset = int(_mem.offset)
        if _mem.split:
            mem.duplex = 'split'
        elif _mem.shift < len(DUPLEXES):
            mem.duplex = DUPLEXES[_mem.shift]

        mem.mode = 'NFM' if _mem.narrow else 'FM'
        if _mem.rxstep < len(STEPS):
            mem.tuning_step = STEPS[_mem.rxstep]

        if _mem.rtone < len(TONES):
            mem.rtone = TONES[_mem.rtone]
        if _mem.ctone < len(TONES):
            mem.ctone = TONES[_mem.ctone]
        if _mem.dtcs < len(DTCS_CODES):
            mem.dtcs = DTCS_CODES[_mem.dtcs]

        mem.tmode = TMODES.get(int(_mem.tmode), '')
        if mem.tmode == 'Cross':
            if _mem.cross < len(CROSS_MODES):
                mem.cross_mode = CROSS_MODES[_mem.cross]
            else:
                mem.tmode = ''

        if _name is not None:
            mem.name = str(_name.name).replace('\xFF', ' ').rstrip()
        if _flag is not None:
            mem.skip = 'S' if _flag.lockout else ''

        mem.extra = RadioSettingGroup('extra', 'Extra')
        mem.extra.append(MemSetting(
            'reverse', 'Reverse',
            RadioSettingValueBoolean(_mem.reverse)))
        mem.extra.append(MemSetting(
            'beatshift', 'Beat Shift',
            RadioSettingValueBoolean(_mem.beatshift)))

        return mem

    def set_memory(self, mem):
        _mem, _name, _flag, _num, _ext = self._get_objects(mem.number)

        if mem.empty:
            _mem.set_raw(b'\xFF' * 16)
            if _name is not None:
                _name.set_raw(b'\xFF' * NAME_LENGTH)
            if _flag is not None:
                _flag.set_raw(b'\xFF')
            return

        if self._is_empty(_mem, _flag):
            _mem.set_raw(EMPTY_CHANNEL)

        _mem.freq = mem.freq
        _mem.split = mem.duplex == 'split'
        if mem.duplex == 'split':
            _mem.shift = 0
            _mem.offset = mem.offset
        elif mem.duplex in DUPLEXES[1:]:
            _mem.shift = DUPLEXES.index(mem.duplex)
            _mem.offset = mem.offset
        else:
            _mem.shift = 0
            _mem.offset = 0

        _mem.narrow = mem.mode == 'NFM'
        step = STEPS.index(mem.tuning_step) if mem.tuning_step in STEPS else 0
        _mem.rxstep = _mem.txstep = step

        _mem.rtone = TONES.index(mem.rtone)
        _mem.ctone = TONES.index(mem.ctone)
        _mem.dtcs = DTCS_CODES.index(mem.dtcs)
        tmodes = {v: k for k, v in TMODES.items()}
        _mem.tmode = tmodes[mem.tmode]
        if mem.tmode == 'Cross':
            _mem.cross = CROSS_MODES.index(mem.cross_mode)
        else:
            _mem.cross = 0

        if _name is not None:
            _name.name = mem.name.rstrip().ljust(NAME_LENGTH, '\xFF')
        if _flag is not None:
            _flag.set_raw(b'\x00')
            _flag.lockout = mem.skip == 'S'

        if mem.extra:
            for setting in mem.extra:
                setting.apply_to_memobj(_mem)
        else:
            _mem.reverse = 0
            _mem.beatshift = 0
