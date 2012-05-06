#
# Copyright 2012 Filippi Marco <iz3gme.marco@gmail.com>
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

from chirp import chirp_common, yaesu_clone, util, memmap, errors, directory
from chirp import bitwise
import time, os

CMD_ACK = 0x06

def ft817_read(pipe, block, blocknum):
    for i in range(0,60):
        data = pipe.read(block+2)
	if data:
            break
	time.sleep(0.5)
    if len(data) == block+2 and data[0] == chr(blocknum):
            checksum = yaesu_clone.YaesuChecksum(1, block)
            if checksum.get_existing(data) != \
                    checksum.get_calculated(data):
                raise Exception("Checksum Failed [%02X<>%02X] block %02X" % (checksum.get_existing(data), checksum.get_calculated(data), blocknum))
	    data = data[1:block+1] # Chew away the block number and the checksum
    else:
        raise Exception("Unable to read block %02X expected %i got %i" % (blocknum, block+2, len(data)))

    if os.getenv("CHIRP_DEBUG"):
        print "Read %i" % len(data)
    return data        

def clone_in(radio):
    pipe = radio.pipe

    # Be very patient with the radio
    pipe.setTimeout(2)

    start = time.time()

    data = ""
    blocks = 0
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.max = len(radio._block_lengths) + 39
    for block in radio._block_lengths:
        if blocks == 8:
            repeat = 40   # repeated read of 40 block same size (memory area btw)
        else:
            repeat = 1
        for i in range(0, repeat):	
	    data += ft817_read(pipe, block, blocks)
	    pipe.write(chr(CMD_ACK))
	    blocks += 1
	    status.cur = blocks
	    radio.status_fn(status)

    print "Clone completed in %i seconds" % (time.time() - start)

    return memmap.MemoryMap(data)

def clone_out(radio):
    delay = 0.5
    pipe = radio.pipe

    start = time.time()

    blocks = 0
    pos = 0
    status = chirp_common.Status()
    status.msg = "Cloning to radio"
    status.max = len(radio._block_lengths) + 39
    for block in radio._block_lengths:
        if blocks == 8:
            repeat = 40   # repeated read of 40 block same size (memory area btw)
        else:
            repeat = 1
	for i in range(0, repeat):
            time.sleep(0.01)
            checksum = yaesu_clone.YaesuChecksum(pos, pos+block-1)
            if os.getenv("CHIRP_DEBUG"):
                print "Block %i - will send from %i to %i byte " % (blocks, pos, pos+block)
                print util.hexprint(chr(blocks))
                print util.hexprint(radio._mmap[pos:pos+block])
                print util.hexprint(chr(checksum.get_calculated(radio._mmap)))
            pipe.write(chr(blocks))
            pipe.write(radio._mmap[pos:pos+block])
            pipe.write(chr(checksum.get_calculated(radio._mmap)))
	    buf = pipe.read(1)
            if not buf or buf[0] != chr(CMD_ACK):
                time.sleep(delay)
                buf = pipe.read(1)
            if not buf or buf[0] != chr(CMD_ACK):
                if os.getenv("CHIRP_DEBUG"):
                    print util.hexprint(buf)
                raise Exception("Radio did not ack block %i" % blocks)
            pos += block
            blocks += 1
	    status.cur = blocks
	    radio.status_fn(status)

    print "Clone completed in %i seconds" % (time.time() - start)

mem_format = """
#seekto 0x3fd;
u8 visible[25];

#seekto 0x417;
u8 filled[25];

#seekto 0x431;
struct {
  u8   tag_on_off:1,
       tag_default:1,
       unknown1:3,
       mode:3;
  u8   duplex:2,
       is_duplex:1,
       is_cwdig_narrow:1,
       is_fm_narrow:1,
       freq_range:3;
  u8   skip:1,
       unknown2:1,
       ipo:1,
       att:1,
       unknown3:4;
  u8   ssb_step:2,
       am_step:3,
       fm_step:3;
  u8   unknown4:6,
       tmode:2;
  u8   unknown5:2,
       tx_mode:3,
       tx_freq_range:3;
  u8   unknown6:1,
       unknown_flag:1,
       tone:6;
  u8   unknown7:1,
       dcs:7;
  ul16 rit;
  u32 freq;
  u32 offset;
  u8   name[8];
} memory[200];

#seekto 0x1979;
struct {
  u8   tag_on_off:1,
       tag_default:1,
       unknown1:3,
       mode:3;
  u8   duplex:2,
       is_duplex:1,
       is_cwdig_narrow:1,
       is_fm_narrow:1,
       freq_range:3;
  u8   skip:1,
       unknown2:1,
       ipo:1,
       att:1,
       unknown3:4;
  u8   ssb_step:2,
       am_step:3,
       fm_step:3;
  u8   unknown4:6,
       tmode:2;
  u8   unknown5:2,
       tx_mode:3,
       tx_freq_range:3;
  u8   unknown6:1,
       unknown_flag:1,
       tone:6;
  u8   unknown7:1,
       dcs:7;
  ul16 rit;
  u32 freq;
  u32 offset;
  u8   name[8];
} sixtymeterchannels[5];
"""

@directory.register
class FT817Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 9600
    MODEL = "FT-817"

    DUPLEX = ["", "-", "+", "split"]
    MODES  = ["LSB", "USB", "CW", "CWR", "AM", "FM", "DIG", "PKT", "NCW", "NCWR", "NFM"]   # narrow modes has to be at end
    TMODES = ["", "Tone", "TSQL", "DTCS"]
    STEPSFM = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
    STEPSAM = [2.5, 5.0, 9.0, 10.0, 12.5, 25.0]
    STEPSSSB = [1.0, 2.5, 5.0]
    VALID_BANDS = [(100000,33000000), (33000000,56000000), (76000000,108000000), (108000000,137000000), (137000000,154000000), (420000000,470000000)] # warning ranges has to be in this exact order


    CHARSET = [chr(x) for x in range(0, 256)]

    POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),       # not used in memory
                    chirp_common.PowerLevel("L3", watts=2.50),
                    chirp_common.PowerLevel("L2", watts=1.00),
                    chirp_common.PowerLevel("L1", watts=0.5)]

    _model = ""
    _memsize = 6509
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [ 2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 118]


    def sync_in(self):
        self._mmap = clone_in(self)
        self.process_mmap()

    def sync_out(self):
        clone_out(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.has_nostep_tuning = True
        rf.valid_modes = list(set(self.MODES))
        rf.valid_tmodes = list(self.TMODES)
        rf.valid_duplexes = list(self.DUPLEX)
        rf.valid_tuning_steps = list(self.STEPSFM)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 8
        rf.memory_bounds = (1, 200)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_duplex(self, mem, _mem):
        if _mem.is_duplex == 1:
            mem.duplex = self.DUPLEX[_mem.duplex]
        else:
            mem.duplex = ""

    def get_tmode(self, mem, _mem):
        mem.tmode = self.TMODES[_mem.tmode]

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        used = (self._memobj.visible[(number-1)/8] >> (number-1)%8) & 0x01

        mem = chirp_common.Memory()
        mem.number = number
        if not used:
            mem.empty = True
            return mem

        return self._get_memory(mem, _mem)

    def _get_memory(self, mem, _mem):
        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10
        self.get_duplex(mem, _mem)
        mem.mode = self.MODES[_mem.mode]
        if mem.mode == "FM":
            if _mem.is_fm_narrow == 1:
                mem.mode = "NFM"
            mem.tuning_step = self.STEPSFM[_mem.fm_step]
        elif mem.mode == "AM":
            mem.tuning_step = self.STEPSAM[_mem.am_step]
        elif mem.mode == "CW" or mem.mode == "CWR":
            if _mem.is_cwdig_narrow == 1:
                mem.mode = "N" + mem.mode
            mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
        else:   # TODO more investigation needed on steps for other modes 
            mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
        mem.skip = _mem.skip and "S" or ""
        self.get_tmode(mem, _mem)
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]

	if _mem.tag_on_off == 1:
            for i in _mem.name:
                if i == "\xFF":
                    break
                mem.name += self.CHARSET[i]
            mem.name = mem.name.rstrip()
        else:
            mem.name = ""

        return mem

    def set_duplex(self, mem, _mem):
        _mem.duplex = self.DUPLEX.index(mem.duplex)
        _mem.is_duplex = mem.duplex != ""

    def set_tmode(self, mem, _mem):
        _mem.tmode = self.TMODES.index(mem.tmode)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        if mem.empty:
            if mem.number == 1:
                # as Dan says "yaesus are not good about that :("
		# if you ulpoad an empty image you can brick your radio
                raise Exception("Sorry, can't delete first memory") 
            self._memobj.visible[(mem.number-1)/8] &= ~ (1 << (mem.number-1)%8)
            self._memobj.filled[(mem.number-1)/8] = self._memobj.visible[(mem.number-1)/8]
            return
        
        self._set_memory(mem, _mem)

    def _set_memory(self, mem, _mem):
        self._memobj.visible[(mem.number-1)/8] |= 1 << (mem.number-1)%8
        self._memobj.filled[(mem.number-1)/8] = self._memobj.visible[(mem.number-1)/8]

        if len(mem.name) > 0:     # not supported in chirp
                                  # so I make label visible if have one
            _mem.tag_on_off = 1
        else:
            _mem.tag_on_off = 0
        _mem.tag_default = 0       # never use default label "CH-nnn"
        self.set_duplex(mem, _mem)
        if mem.mode[0] == "N": # is it narrow?
            _mem.mode = self.MODES.index(mem.mode[1:])
            _mem.is_fm_narrow = _mem.is_cwdig_narrow = 1       # here I suppose it's safe to set both
        else:
            _mem.mode = self.MODES.index(mem.mode)
            _mem.is_fm_narrow = _mem.is_cwdig_narrow = 0       # here I suppose it's safe to set both
        i = 0                                   # This search can probably be written better but
        for lo, hi in self.VALID_BANDS:              # I just don't know python enought
            if mem.freq > lo and mem.freq < hi:
                break 
            i+=1
        _mem.freq_range = i
        if mem.duplex == "split":	# all this should be safe also when not in split but ... 
            _mem.tx_mode = _mem.mode
            i = 0                                   # This search can probably be written better but
            for lo, hi in self.VALID_BANDS:              # I just don't know python enought
                if mem.offset >= lo and mem.offset < hi:
                    break 
                i+=1
            _mem.tx_freq_range = i
        _mem.skip = mem.skip == "S"
        _mem.ipo = 0	# not supported in chirp
        _mem.att = 0    # not supported in chirp
        self.set_tmode(mem, _mem)
        try:
            _mem.ssb_step = self.STEPSSSB.index(mem.tuning_step)
        except ValueError:
            pass
        try:
            _mem.am_step = self.STEPSAM.index(mem.tuning_step)
        except ValueError:
            pass
        try:
            _mem.fm_step = self.STEPSFM.index(mem.tuning_step)
        except ValueError:
            pass
        _mem.unknown_flag = 0	# have to put this bit to 0 otherwise we get strange display in tone
                                # frequency (menu 83) see bug #88 and #163
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.rit = 0	# not supported in chirp
        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10
        for i in range(0, 8):
            _mem.name[i] = self.CHARSET.index(mem.name.ljust(8)[i])
        
    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)

	lo, hi = self.VALID_BANDS[3]    # this is fm broadcasting
	if mem.freq >= lo and mem.freq <= hi:
            if mem.mode != "FM":
                msgs.append(chirp_common.ValidationError("Only FM is supported in this band"))
        # TODO check that step is valid in current mode
        return msgs

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize

@directory.register
class FT817NDRadio(FT817Radio):
    MODEL = "FT-817ND (Intl versions)"

    _model = ""
    _memsize = 6521
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [ 2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 130]

SPECIAL_60M = {
    "M-601" : -1,
    "M-602" : -2,
    "M-603" : -3,
    "M-604" : -4,
    "M-605" : -5,
    }

@directory.register
class FT817ND_US_Radio(FT817Radio):
    # seems that radios configured for 5MHz operations send one paket more than others
    # so we have to distinguish sub models
    MODEL = "FT-817ND (US Version)"

    _model = ""
    _memsize = 6651
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [ 2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 130, 130]

    def get_special_locations(self):
        return SPECIAL_60M.keys()

    def _get_special(self, number):
        mem = chirp_common.Memory()
        mem.number = SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[abs(mem.number)-1]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "skip", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

    def _set_special(self, mem):
        cur_mem = self._get_special(mem.extd_number)

        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on M-60x channels")

        if mem.mode not in ["USB", "LSB", "CW", "CWR", "NCW", "NCWR", "DIG"]:
            raise errors.RadioError(_("Mode {mode} is not valid "
                                      "in 60m channels").format(mode=mem.mode))
        _mem = self._memobj.sixtymeterchannels[abs(mem.number)-1]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        else:
            return FT817Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.number < 0:
            return self._set_special(memory)
        else:
            return FT817Radio.set_memory(self, memory)
