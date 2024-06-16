import itertools
import logging
import struct
import sys
import time

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap

LOG = logging.getLogger(__name__)

CALL_CHANS = ['VHF Call (A)',
              'VHF Call (D)',
              '220M Call (A)',
              '220M Call (D)',
              'UHF Call (A)',
              'UHF Call (D)']

# This is the order of special channels in memory directly after
# regular memory #999
EXTD_NUMBERS = list(itertools.chain(
    ['%s%02i' % (i % 2 and 'Upper' or 'Lower', i // 2) for i in range(100)],
    ['Priority'],
    ['WX%i' % (i + 1) for i in range(10)],
    [None for i in range(20)],  # 20-channel buffer?
    [CALL_CHANS[i] for i in range(len(CALL_CHANS))]))

D74_FILE_HEADER = (
    b'MCP-D74\xFFV1.03\xFF\xFF\xFF' +
    b'TH-D74' + (b'\xFF' * 10) +
    b'\x00' + (b'\xFF' * 15) +
    b'\xFF' * (5 * 16) +
    b'K2' + (b'\xFF' * 14) +
    b'\xFF' * (7 * 16))
GROUP_NAME_OFFSET = 1152

MEM_FORMAT = """
#seekto 0x2000;
struct {
  u8 used;
  u8 unknown1:7,
     lockout:1;
  u8 group;
  u8 unknownFF;
} flags[1200];

#seekto 0x4000;
struct memory {
    ul32 freq;
    ul32 offset;
    u8 tuning_step:4,
       split_tuning_step:3,
       unknown2:1;
    u8 unknown3_0:1,
       mode:3,
       narrow:1,
       fine_mode:1,
       fine_step:2;
    u8 tone_mode:1,
       ctcss_mode:1,
       dtcs_mode:1,
       cross_mode:1,
       unknown4_0:1,
       split:1,
       duplex:2;
    u8 rtone;
    u8 unknownctone:2,
       ctone:6;
    u8 unknowndtcs:1,
       dtcs_code:7;
    u8 unknown5_1:2,
       cross_mode_mode:2,
       unknown5_2:2,
       dig_squelch:2;
    char dv_urcall[8];
    char dv_rpt1call[8];
    char dv_rpt2call[8];
    u8 unknown9:1,
       dv_code:7;
};

struct {
  struct memory memories[6];
  u8 pad[16];
} memgroups[192];

//#seekto 0x10000;
struct {
  char name[16];
} names[1200];
"""


def decode_call(call):
    return ''.join(str(c) for c in call if ord(str(c)) > 0)


def encode_call(call):
    return call[:8].ljust(8, '\x00')


DUPLEX = ['', '+', '-']
TUNE_STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0,
              100.0]
CROSS_MODES = ['DTCS->', 'Tone->DTCS', 'DTCS->Tone', 'Tone->Tone']
MODES = ['FM', 'DV', 'AM', 'LSB', 'USB', 'CW', 'NFM',
         'DV',  # Actually DR in the radio
         ]
DSQL_MODES = ['', 'Code', 'Callsign']
FINE_STEPS = [20, 100, 500, 1000]


class KenwoodGroup(chirp_common.NamedBank):
    def __init__(self, model, index):
        # Default name until we are initialized, then we will report
        # the value from memory
        super().__init__(model, index, 'GRP-%i' % index)

    def get_name(self):
        name = self._model._radio._memobj.names[
            GROUP_NAME_OFFSET + self._index].name
        return str(name).rstrip()

    def set_name(self, name):
        names = self._model._radio._memobj.names
        names[GROUP_NAME_OFFSET + self._index].name = str(name)[:16].ljust(16)
        super().set_name(name.strip())


class KenwoodTHD74Bankmodel(chirp_common.BankModel):
    channelAlwaysHasBank = True

    def get_num_mappings(self):
        return 30

    def get_mappings(self):
        groups = []
        for i in range(self.get_num_mappings()):
            groups.append(KenwoodGroup(self, i))
        return groups

    def add_memory_to_mapping(self, memory, bank):
        self._radio._memobj.flags[memory.number].group = bank.get_index()

    def remove_memory_from_mapping(self, memory, bank):
        self._radio._memobj.flags[memory.number].group = 0

    def get_mapping_memories(self, bank):
        features = self._radio.get_features()
        memories = []
        for i in range(0, features.memory_bounds[1]):
            if self._radio._memobj.flags[i].group == bank.get_index():
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        index = self._radio._memobj.flags[memory.number].group
        return [self.get_mappings()[index]]


def get_used_flag(mem):
    if mem.empty:
        return 0xFF
    if mem.duplex == 'split':
        freq = mem.offset
    else:
        freq = mem.freq

    if freq < chirp_common.to_MHz(150):
        return 0x00
    elif freq < chirp_common.to_MHz(400):
        return 0x01
    else:
        return 0x02


@directory.register
class THD74Radio(chirp_common.CloneModeRadio,
                 chirp_common.IcomDstarSupport):
    VENDOR = "Kenwood"
    MODEL = "TH-D74 (clone mode)"
    BAUD_RATE = 9600
    HARDWARE_FLOW = sys.platform == "darwin"  # only OS X driver needs hw flow
    FORMATS = [directory.register_format('Kenwood MCP-D74', '*.d74')]

    _memsize = 0x7A300

    def read_block(self, block, count=256):
        hdr = struct.pack(">cHH", b"R", block, 0)
        self.pipe.write(hdr)
        r = self.pipe.read(5)
        if len(r) != 5:
            raise errors.RadioError("Did not receive block response")

        cmd, _block, zero = struct.unpack(">cHH", r)
        if cmd != b"W" or _block != block:
            raise errors.RadioError("Invalid response: %s %i" % (cmd, _block))

        data = b""
        while len(data) < count:
            data += self.pipe.read(count - len(data))

        self.pipe.write(b'\x06')
        if self.pipe.read(1) != b'\x06':
            raise errors.RadioError("Did not receive post-block ACK!")

        return data

    def write_block(self, block, map, size=256):
        hdr = struct.pack(">cHH", b"W", block, size < 256 and size or 0)
        base = block * size
        data = map[base:base + size]
        self.pipe.write(hdr + data)
        self.pipe.flush()

        for i in range(10):
            ack = self.pipe.read(1)
            if ack != b'\x06':
                LOG.error('Ack for block %i was: %r' % (block, ack))
            else:
                break
        return ack == b'\x06'

    def download(self, raw=False, blocks=None):
        if blocks is None:
            blocks = range(self._memsize // 256)
        else:
            blocks = [b for b in blocks if b < self._memsize // 256]

        if self.command("0M PROGRAM") != "0M":
            raise errors.RadioError("No response from self")

        allblocks = range(self._memsize // 256)
        self.pipe.baudrate = 57600
        self.pipe.read(1)
        data = b""
        LOG.debug("reading blocks %d..%d" % (blocks[0], blocks[-1]))
        total = len(blocks)
        count = 0
        for i in allblocks:
            if i not in blocks:
                data += 256 * b'\xff'
                continue
            data += self.read_block(i)
            count += 1
            if self.status_fn:
                s = chirp_common.Status()
                s.msg = "Cloning from radio"
                s.max = total
                s.cur = count
                self.status_fn(s)

        self.pipe.write(b"E")

        if raw:
            return data
        return memmap.MemoryMapBytes(data)

    def upload(self, blocks=None):
        if blocks is None:
            blocks = range((self._memsize // 256) - 2)
        else:
            blocks = [b for b in blocks if b < self._memsize // 256]

        if self.command("0M PROGRAM") != "0M":
            raise errors.RadioError("No response from self")

        self.pipe.baudrate = 57600
        self.pipe.read(1)

        try:
            LOG.debug("writing blocks %d..%d" % (blocks[0], blocks[-1]))
            total = len(blocks)
            count = 0
            for i in blocks:
                r = self.write_block(i, self._mmap)
                count += 1
                if not r:
                    raise errors.RadioError("self NAK'd block %i" % i)
                if self.status_fn:
                    s = chirp_common.Status()
                    s.msg = "Cloning to radio"
                    s.max = total
                    s.cur = count
                    self.status_fn(s)
        finally:
            self.pipe.write(b"E")

    def command(self, cmd, timeout=1):
        start = time.time()

        data = b""
        LOG.debug("PC->D74: %s" % cmd)
        self.pipe.write((cmd + "\r").encode())
        while not data.endswith(b"\r") and (time.time() - start) < timeout:
            data += self.pipe.read(1)
        LOG.debug("D74->PC: %s" % data.strip())
        return data.decode().strip()

    def get_id(self):
        r = self.command("ID")
        if r.startswith("ID "):
            return r.split(" ")[1]
        else:
            raise errors.RadioError("No response to ID command")

    def _detect_baud(self):
        id = None
        for baud in [9600, 19200, 38400, 57600]:
            self.pipe.baudrate = baud
            try:
                self.pipe.write(b"\r\r")
            except Exception:
                break
            self.pipe.read(32)
            try:
                id = self.get_id()
                LOG.info("Radio %s at %i baud" % (id, baud))
                break
            except errors.RadioError:
                pass

        if id and not self.MODEL.startswith(id):
            raise errors.RadioError(_('Unsupported model %r' % id))
        elif id:
            return id
        else:
            raise errors.RadioError("No response from radio")

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        self._detect_baud()
        self._mmap = self.download()
        self.process_mmap()

    def sync_out(self):
        self._detect_baud()
        self.upload()

    def load_mmap(self, filename):
        if filename.lower().endswith('.d74'):
            with open(filename, 'rb') as f:
                f.seek(0x100)
                self._mmap = memmap.MemoryMapBytes(f.read())
                LOG.info('Loaded MCP d74 file at offset 0x100')
            self.process_mmap()
        else:
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.d74'):
            with open(filename, 'wb') as f:
                f.write(D74_FILE_HEADER)
                f.write(self._mmap.get_packed())
                LOG.info('Wrote MCP d74 file')
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tuning_steps = list(TUNE_STEPS)
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = list(CROSS_MODES)
        rf.valid_duplexes = DUPLEX + ['split']
        rf.valid_skips = ['', 'S']
        rf.valid_modes = list(MODES)
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 16
        rf.valid_bands = [(100000, 470000000)]
        rf.valid_special_chans = [x for x in EXTD_NUMBERS if x]
        rf.has_cross = True
        rf.has_dtcs_polarity = False
        rf.has_bank = True
        rf.has_bank_names = True
        rf.can_odd_split = True
        rf.requires_call_lists = False
        rf.memory_bounds = (0, 999)
        return rf

    def _get_raw_memory(self, number):
        # Why Kenwood ... WHY?
        return self._memobj.memgroups[number // 6].memories[number % 6]

    def get_memory(self, number):
        if isinstance(number, str):
            extd_number = number
            number = 1000 + EXTD_NUMBERS.index(number)
        else:
            extd_number = None

        _mem = self._get_raw_memory(number)
        _flg = self._memobj.flags[number]

        if MODES[_mem.mode] == 'DV':
            mem = chirp_common.DVMemory()
        else:
            mem = chirp_common.Memory()

        mem.number = number
        if extd_number:
            mem.extd_number = extd_number

        if _flg.used == 0xFF:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq)
        if 'Call' in mem.extd_number:
            name_index_adj = 5
        else:
            name_index_adj = 0
        _nam = self._memobj.names[number + name_index_adj]
        mem.name = str(_nam.name).rstrip().strip('\x00')
        mem.offset = int(_mem.offset)
        if _mem.split:
            mem.duplex = 'split'
        else:
            mem.duplex = DUPLEX[_mem.duplex]
        mem.tuning_step = TUNE_STEPS[_mem.tuning_step]
        mem.mode = MODES[_mem.mode]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs_code]

        if _mem.tone_mode:
            mem.tmode = 'Tone'
        elif _mem.ctcss_mode:
            mem.tmode = 'TSQL'
        elif _mem.dtcs_mode:
            mem.tmode = 'DTCS'
        elif _mem.cross_mode:
            mem.tmode = 'Cross'
            mem.cross_mode = CROSS_MODES[_mem.cross_mode_mode]
        else:
            mem.tmode = ''

        mem.skip = _flg.lockout and 'S' or ''

        if mem.mode == 'DV':
            mem.dv_urcall = decode_call(_mem.dv_urcall)
            mem.dv_rpt1call = decode_call(_mem.dv_rpt1call)
            mem.dv_rpt2call = decode_call(_mem.dv_rpt2call)
            mem.dv_code = int(_mem.dv_code)

        if mem.extd_number:
            mem.immutable.append('empty')

        if 'WX' in mem.extd_number:
            mem.tmode = ''
            mem.immutable.extend(['rtone', 'ctone', 'dtcs', 'rx_dtcs',
                                  'tmode', 'cross_mode', 'dtcs_polarity',
                                  'skip', 'power', 'offset', 'mode',
                                  'tuning_step'])
        if 'Call' in mem.extd_number and mem.mode == 'DV':
            mem.immutable.append('mode')

        return mem

    def set_memory(self, mem):

        if mem.number > 999 and 'Call' in EXTD_NUMBERS[mem.number - 1000]:
            name_index_adj = 5
        else:
            name_index_adj = 0

        _mem = self._get_raw_memory(mem.number)
        _flg = self._memobj.flags[mem.number]
        _nam = self._memobj.names[mem.number + name_index_adj]

        _flg.used = get_used_flag(mem)

        if mem.empty:
            _flg.lockout = 0
            _flg.group = 0
            _nam.name = ('\x00' * 16)
            _mem.set_raw(b'\xFF' * 40)
            return

        _mem.set_raw(b'\x00' * 40)

        _flg.group = 0  # FIXME

        _mem.freq = mem.freq
        _nam.name = mem.name.ljust(16)
        _mem.offset = int(mem.offset)
        if mem.duplex == 'split':
            _mem.split = True
            _mem.duplex = 0
            _mem.split_tuning_step = TUNE_STEPS.index(
                chirp_common.required_step(mem.offset))
        else:
            _mem.split = False
            _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tuning_step = TUNE_STEPS.index(mem.tuning_step)
        _mem.mode = MODES.index(mem.mode)
        _mem.narrow = mem.mode == 'NFM'
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs_code = chirp_common.DTCS_CODES.index(mem.dtcs)

        _mem.tone_mode = mem.tmode == 'Tone'
        _mem.ctcss_mode = mem.tmode == 'TSQL'
        _mem.dtcs_mode = mem.tmode == 'DTCS'
        _mem.cross_mode = mem.tmode == 'Cross'

        if mem.tmode == 'Cross':
            _mem.cross_mode_mode = CROSS_MODES.index(mem.cross_mode)

        _flg.lockout = mem.skip == 'S'
        if isinstance(mem, chirp_common.DVMemory):
            _mem.dv_urcall = encode_call(mem.dv_urcall)
            _mem.dv_rpt1call = encode_call(mem.dv_rpt1call)
            _mem.dv_rpt2call = encode_call(mem.dv_rpt2call)
            _mem.dv_code = mem.dv_code

    def get_raw_memory(self, number):
        return (repr(self._get_raw_memory(number)) +
                repr(self._memobj.flags[number]))

    def get_bank_model(self):
        return KenwoodTHD74Bankmodel(self)

    @classmethod
    def match_model(cls, filedata, filename):
        if filename.endswith('.d74'):
            return True
        else:
            return chirp_common.CloneModeRadio.match_model(filedata, filename)


@directory.register
class THD75Radio(THD74Radio):
    MODEL = 'TH-D75'
