# Copyright 2011 Dan Smith <dsmith@danplanet.com>
#
# FT-2900-specific modifications by Richard Cochran, <ag6qr@sonic.net>
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

import time
import os
import logging

from chirp import util, memmap, chirp_common, bitwise, directory, errors
from chirp.drivers.yaesu_clone import YaesuCloneModeRadio

from textwrap import dedent

LOG = logging.getLogger(__name__)


def _send(s, data):
    s.write(data)
    echo = s.read(len(data))
    if data != echo:
        raise Exception("Failed to read echo")
    LOG.debug("got echo\n%s\n" % util.hexprint(echo))

IDBLOCK = "\x56\x43\x32\x33\x00\x02\x46\x01\x01\x01"
ACK = "\x06"
INITIAL_CHECKSUM = 73


def _download(radio):

    blankChunk = ""
    for _i in range(0, 32):
        blankChunk += "\xff"

    LOG.debug("in _download\n")

    data = ""
    for _i in range(0, 20):
        data = radio.pipe.read(20)
        LOG.debug("Header:\n%s" % util.hexprint(data))
        LOG.debug("len(header) = %s\n" % len(data))

        if data == IDBLOCK:
            break

    if data != IDBLOCK:
        raise Exception("Failed to read header")

    _send(radio.pipe, ACK)

    # initialize data, the big var that holds all memory
    data = ""

    _blockNum = 0

    while len(data) < radio._block_sizes[1]:
        _blockNum += 1
        time.sleep(0.03)
        chunk = radio.pipe.read(32)
        LOG.debug("Block %i " % (_blockNum))
        if chunk == blankChunk:
            LOG.debug("blank chunk\n")
        else:
            LOG.debug("Got: %i:\n%s" % (len(chunk), util.hexprint(chunk)))
        if len(chunk) != 32:
            LOG.debug("len chunk is %i\n" % (len(chunk)))
            raise Exception("Failed to get full data block")
            break
        else:
            data += chunk

        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._block_sizes[1]
            status.cur = len(data)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    LOG.debug("Total: %i" % len(data))

    # radio should send us one final termination byte, containing
    # checksum
    chunk = radio.pipe.read(32)
    if len(chunk) != 1:
        LOG.debug("len(chunk) is %i\n" % len(chunk))
        raise Exception("radio sent extra unknown data")
    LOG.debug("Got: %i:\n%s" % (len(chunk), util.hexprint(chunk)))

    # compute checksum
    cs = INITIAL_CHECKSUM
    for byte in data:
        cs += ord(byte)
    LOG.debug("calculated checksum is %x\n" % (cs & 0xff))

    if (cs & 0xff) != ord(chunk[0]):
        raise Exception("Failed checksum on read.")

    # for debugging purposes, dump the channels, in hex.
    for _i in range(0, 200):
        _startData = 1892 + 20 * _i
        chunk = data[_startData:_startData + 20]
        LOG.debug("channel %i:\n%s" % (_i, util.hexprint(chunk)))

    return memmap.MemoryMap(data)


def _upload(radio):
    for _i in range(0, 10):
        data = radio.pipe.read(256)
        if not data:
            break
        LOG.debug("What is this garbage?\n%s" % util.hexprint(data))
        raise Exception("Radio sent unrecognized data")

    _send(radio.pipe, IDBLOCK)
    time.sleep(.2)
    ack = radio.pipe.read(300)
    LOG.debug("Ack was (%i):\n%s" % (len(ack), util.hexprint(ack)))
    if ack != ACK:
        raise Exception("Radio did not ack ID")

    block = 0
    cs = INITIAL_CHECKSUM

    while block < (radio.get_memsize() / 32):
        data = radio.get_mmap()[block*32:(block+1)*32]

        LOG.debug("Writing block %i:\n%s" % (block, util.hexprint(data)))

        _send(radio.pipe, data)
        time.sleep(0.03)

        for byte in data:
            cs += ord(byte)

        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._block_sizes[1]
            status.cur = block * 32
            status.msg = "Cloning to radio"
            radio.status_fn(status)
        block += 1

    _send(radio.pipe, chr(cs & 0xFF))

MEM_FORMAT = """
#seekto 0x00ef;
  u8 currentTone;

#seekto 0x00f0;
  u8 curChannelMem[20];

#seekto 0x0127;
  u8 curChannelNum;

#seekto 0x15f;
  u8 checksum1;

#seekto 0x16f;
  u8 curentTone2;

#seekto 0x1a7;
  u8 curChannelMem2[20];

#seekto 0x1df;
  u8 checksum2;

#seekto 0x06e4;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[225];

#seekto 0x0764;
struct {
  u8 unknown0:2,
     isnarrow:1,
     unknown1:5;
  u8 unknown2:2,
     duplex:2,
     unknown3:1,
     step:3;
  bbcd freq[3];
  u8 power:2,
     unknown4:3,
     tmode:3;
  u8 name[6];
  bbcd offset[3];
  u8 ctonesplitflag:1,
     ctone:7;
  u8 rx_dtcssplitflag:1,
     rx_dtcs:7;
  u8 unknown5;
  u8 rtonesplitflag:1,
     rtone:7;
  u8 dtcssplitflag:1,
     dtcs:7;
} memory[200];

"""

MODES = ["FM", "NFM"]
TMODES = ["", "Tone", "TSQL", "DTCS", "TSQL-R", "Cross"]
CROSS_MODES = ["DTCS->", "Tone->DTCS", "DTCS->Tone",
               "Tone->Tone", "DTCS->DTCS"]
DUPLEX = ["", "-", "+", "split"]
POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=75),
                chirp_common.PowerLevel("Low3", watts=30),
                chirp_common.PowerLevel("Low2", watts=10),
                chirp_common.PowerLevel("Low1", watts=5),
                ]

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ +-/?C[] _"
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]


def _decode_tone(radiotone):
    try:
        chirptone = chirp_common.TONES[radiotone]
    except IndexError:
        chirptone = 100
        LOG.debug("found invalid radio tone: %i\n" % radiotone)
    return chirptone


def _decode_dtcs(radiodtcs):
    try:
        chirpdtcs = chirp_common.DTCS_CODES[radiodtcs]
    except IndexError:
        chirpdtcs = 23
        LOG.debug("found invalid radio dtcs code: %i\n" % radiodtcs)
    return chirpdtcs


def _decode_name(mem):
    name = ""
    for i in mem:
        if (i & 0x7F) == 0x7F:
            break
        try:
            name += CHARSET[i & 0x7F]
        except IndexError:
            LOG.debug("Unknown char index: %x " % (i))
    name = name.strip()
    return name


def _encode_name(mem):
    if(mem.strip() == ""):
        return [0xff]*6

    name = [None]*6
    for i in range(0, 6):
        try:
            name[i] = CHARSET.index(mem[i])
        except IndexError:
            name[i] = CHARSET.index(" ")

    name[0] = name[0] | 0x80
    return name


def _wipe_memory(mem):
    mem.set_raw("\xff" * (mem.size() / 8))


@directory.register
class FT2900Radio(YaesuCloneModeRadio):
    """Yaesu FT-2900"""
    VENDOR = "Yaesu"
    MODEL = "FT-2900R/1900R"
    BAUD_RATE = 19200

    _memsize = 8000
    _block_sizes = [8, 8000]

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)

        rf.can_odd_split = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False

        rf.valid_tuning_steps = STEPS
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_cross_modes = CROSS_MODES
        rf.valid_bands = [(136000000, 174000000)]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 6
        rf.valid_characters = CHARSET

        return rf

    def sync_in(self):
        start = time.time()
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Downloaded in %.2f sec" % (time.time() - start))
        self.process_mmap()

    def sync_out(self):
        self.pipe.setTimeout(1)
        start = time.time()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Uploaded in %.2f sec" % (time.time() - start))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[(number)/2]

        nibble = ((number) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()

        mem.number = number

        if _mem.get_raw()[0] == "\xFF" or not valid or not used:
            mem.empty = True
            return mem

        mem.tuning_step = STEPS[_mem.step]
        mem.freq = int(_mem.freq) * 1000

        # compensate for 12.5 kHz tuning steps, add 500 Hz if needed
        if(mem.tuning_step == 12.5):
            lastdigit = int(_mem.freq) % 10
            if (lastdigit == 2 or lastdigit == 7):
                mem.freq += 500

        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 1000)
        mem.duplex = DUPLEX[_mem.duplex]
        if _mem.tmode < TMODES.index("Cross"):
            mem.tmode = TMODES[_mem.tmode]
            mem.cross_mode = CROSS_MODES[0]
        else:
            mem.tmode = "Cross"
            mem.cross_mode = CROSS_MODES[_mem.tmode - TMODES.index("Cross")]

        mem.rtone = _decode_tone(_mem.rtone)
        mem.ctone = _decode_tone(_mem.ctone)

        # check for unequal ctone/rtone in TSQL mode.  map it as a
        # cross tone mode
        if mem.rtone != mem.ctone and (mem.tmode == "TSQL" or
                                       mem.tmode == "Tone"):
            mem.tmode = "Cross"
            mem.cross_mode = "Tone->Tone"

        mem.dtcs = _decode_dtcs(_mem.dtcs)
        mem.rx_dtcs = _decode_dtcs(_mem.rx_dtcs)

        # check for unequal dtcs/rx_dtcs in DTCS mode.  map it as a
        # cross tone mode
        if mem.dtcs != mem.rx_dtcs and mem.tmode == "DTCS":
            mem.tmode = "Cross"
            mem.cross_mode = "DTCS->DTCS"

        if (int(_mem.name[0]) & 0x80) != 0:
            mem.name = _decode_name(_mem.name)

        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.skip = pskip and "P" or skip and "S" or ""
        mem.power = POWER_LEVELS[3 - _mem.power]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[(mem.number)/2]

        nibble = ((mem.number) % 2) and "even" or "odd"

        valid = _flag["%s_valid" % nibble]
        used = _flag["%s_masked" % nibble]

        if not valid:
            _wipe_memory(_mem)

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return

        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _flag["%s_valid" % nibble] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.tmode != "Cross":
            _mem.tmode = TMODES.index(mem.tmode)
            # for the non-cross modes, use ONE tone for both send
            # and receive but figure out where to get it from.
            if mem.tmode == "TSQL" or mem.tmode == "TSQL-R":
                _mem.rtone = chirp_common.TONES.index(mem.ctone)
                _mem.ctone = chirp_common.TONES.index(mem.ctone)
            else:
                _mem.rtone = chirp_common.TONES.index(mem.rtone)
                _mem.ctone = chirp_common.TONES.index(mem.rtone)

            # and one tone for dtcs, but this is always the sending one
            _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
            _mem.rx_dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        else:
            _mem.rtone = chirp_common.TONES.index(mem.rtone)
            _mem.ctone = chirp_common.TONES.index(mem.ctone)
            _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
            _mem.rx_dtcs = chirp_common.DTCS_CODES.index(mem.rx_dtcs)
            if mem.cross_mode == "Tone->Tone":
                # tone->tone cross mode is treated as
                # Tone, but with separate tones for
                # send and receive
                _mem.tmode = TMODES.index("Tone")
                _mem.rtonesplitflag = 1
            elif mem.cross_mode == "DTCS->DTCS":
                # DTCS->DTCS cross mode is treated as
                # DTCS, but with separate codes for
                # send and receive
                _mem.tmode = TMODES.index("DTCS")
                _mem.dtcssplitflag = 1
            else:
                _mem.tmode = TMODES.index("Cross") + \
                    CROSS_MODES.index(mem.cross_mode)

        _mem.isnarrow = MODES.index(mem.mode)
        _mem.step = STEPS.index(mem.tuning_step)
        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 3

        _mem.name = _encode_name(mem.name)

        # set all unknown areas of the memory map to 0
        _mem.unknown0 = 0
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0
        _mem.unknown4 = 0
        _mem.unknown5 = 0

        LOG.debug("encoded mem\n%s\n" % (util.hexprint(_mem.get_raw()[0:20])))

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn Radio off.
            2. Connect data cable.
            3. While holding "A/N LOW" button, turn radio on.
            4. <b>After clicking OK</b>, press "SET MHz" to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn Radio off.
            2. Connect data cable.
            3. While holding "A/N LOW" button, turn radio on.
            4. Press "MW D/MR" to receive image.
            5. Click OK to dismiss this dialog and start transfer."""))
        return rp
