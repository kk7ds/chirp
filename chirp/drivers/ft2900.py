# Copyright 2011 Dan Smith <dsmith@danplanet.com>
#
# FT-2900-specific modifications by Richard Cochran, <ag6qr@sonic.net>
# Initial work on settings by Chris Fosnight, <chris.fosnight@gmail.com>
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
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueString, RadioSettings

from textwrap import dedent

LOG = logging.getLogger(__name__)


def _send(s, data):
    s.write(data)
    echo = s.read(len(data))
    if data != echo:
        raise Exception("Failed to read echo")
    LOG.debug("got echo\n%s\n" % util.hexprint(echo))

ACK = "\x06"
INITIAL_CHECKSUM = 0


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

        if data == radio.IDBLOCK:
            break

    if data != radio.IDBLOCK:
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
    for byte in radio.IDBLOCK:
        cs += ord(byte)
    for byte in data:
        cs += ord(byte)
    LOG.debug("calculated checksum is %x\n" % (cs & 0xff))
    LOG.debug("Radio sent checksum is %x\n" % ord(chunk[0]))

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

    _send(radio.pipe, radio.IDBLOCK)
    time.sleep(.2)
    ack = radio.pipe.read(300)
    LOG.debug("Ack was (%i):\n%s" % (len(ack), util.hexprint(ack)))
    if ack != ACK:
        raise Exception("Radio did not ack ID. Check cable, verify"
                        " radio is not locked.\n"
                        " (press & Hold red \"*L\" button to unlock"
                        " radio if needed)")

    block = 0
    cs = INITIAL_CHECKSUM
    for byte in radio.IDBLOCK:
        cs += ord(byte)

    while block < (radio.get_memsize() / 32):
        data = radio.get_mmap()[block * 32:(block + 1) * 32]

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
#seekto 0x0080;
struct {
    u8  apo;
    u8  arts_beep;
    u8  bell;
    u8  dimmer;
    u8  cw_id_string[16];
    u8  cw_trng;
    u8  x95;
    u8  x96;
    u8  x97;
    u8  int_cd;
    u8  int_set;
    u8  x9A;
    u8  x9B;
    u8  lock;
    u8  x9D;
    u8  mic_gain;
    u8  open_msg;
    u8  openMsg_Text[6];
    u8  rf_sql;
    u8  unk:6,
        pag_abk:1,
        unk:1;
    u8  pag_cdr_1;
    u8  pag_cdr_2;
    u8  pag_cdt_1;
    u8  pag_cdt_2;
    u8  prog_p1;
    u8  xAD;
    u8  prog_p2;
    u8  xAF;
    u8  prog_p3;
    u8  xB1;
    u8  prog_p4;
    u8  xB3;
    u8  resume;
    u8  tot;
    u8  unk:1,
        cw_id:1,
        unk:1,
        ts_speed:1,
        ars:1,
        unk:2,
        dtmf_mode:1;
    u8  unk:1,
        ts_mut:1
        wires_auto:1,
        busy_lockout:1,
        edge_beep:1,
        unk:3;
    u8  unk:2,
        s_search:1,
        unk:2,
        cw_trng_units:1,
        unk:2;
    u8  dtmf_speed:1,
        unk:2,
        arts_interval:1,
        unk:1,
        inverted_dcs:1,
        unk:1,
        mw_mode:1;
    u8  unk:2,
        wires_mode:1,
        wx_alert:1,
        unk:1,
        wx_vol_max:1,
        revert:1,
        unk:1;
    u8  vfo_scan;
    u8  scan_mode;
    u8  dtmf_delay;
    u8  beep;
    u8  xBF;
} settings;

#seekto 0x00d0;
    u8  passwd[4];
    u8  mbs;

#seekto 0x00c0;
struct {
  u16 in_use;
} bank_used[8];

#seekto 0x00ef;
  u8 currentTone;

#seekto 0x00f0;
  u8 curChannelMem[20];

#seekto 0x1e0;
struct {
  u8 dtmf_string[16];
} dtmf_strings[10];

#seekto 0x0127;
  u8 curChannelNum;

#seekto 0x012a;
  u8 banksoff1;

#seekto 0x15f;
  u8 checksum1;

#seekto 0x16f;
  u8 curentTone2;

#seekto 0x1aa;
  u16 banksoff2;

#seekto 0x1df;
  u8 checksum2;

#seekto 0x0360;
struct{
  u8 name[6];
} bank_names[8];


#seekto 0x03c4;
struct{
  u16 channels[50];
} banks[8];

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
        return [0xff] * 6

    name = [None] * 6
    for i in range(0, 6):
        try:
            name[i] = CHARSET.index(mem[i])
        except IndexError:
            name[i] = CHARSET.index(" ")

    name[0] = name[0] | 0x80
    return name


def _wipe_memory(mem):
    mem.set_raw("\xff" * (mem.size() / 8))


class FT2900Bank(chirp_common.NamedBank):

    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xff:
                break
            name += CHARSET[i & 0x7f]

        return name.rstrip()

    def set_name(self, name):
        name = name.upper().ljust(6)[:6]
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(6)[:6]]


class FT2900BankModel(chirp_common.BankModel):

    def get_num_mappings(self):
        return 8

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = FT2900Bank(self, "%i" % index, "b%i" % (index + 1))
            bank.index = index
            bank_mappings.append(bank)

        return bank_mappings

    def _get_channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xffff:
            return set()

        _members = self._radio._memobj.banks[bank.index]
        return set([int(ch) for ch in _members.channels if ch != 0xffff])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.banks[bank.index]
        if len(channels_in_bank) > len(_members.channels):
            raise Exception("More than %i entries in bank %d" %
                            (len(_members.channels), bank.index))

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channels[index] = channel_number
            empty = index + 1
        for index in range(empty, len(_members.channels)):
            _members.channels[index] = 0xffff

        _bank_used = self._radio._memobj.bank_used[bank.index]
        if empty == 0:
            _bank_used.in_use = 0xffff
        else:
            _bank_used.in_use = empty - 1

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        # tells radio that banks are active
        self._radio._memobj.banksoff1 = bank.index
        self._radio._memobj.banksoff2 = bank.index

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._get_channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._get_channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


@directory.register
class FT2900Radio(YaesuCloneModeRadio):

    """Yaesu FT-2900"""
    VENDOR = "Yaesu"
    MODEL = "FT-2900R/1900R"
    IDBLOCK = "\x56\x43\x32\x33\x00\x02\x46\x01\x01\x01"
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
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_settings = True

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
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Downloaded in %.2f sec" % (time.time() - start))
        self.process_mmap()

    def sync_out(self):
        self.pipe.timeout = 1
        start = time.time()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Uploaded in %.2f sec" % (time.time() - start))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[(number) / 2]

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
        _flag = self._memobj.flags[(mem.number) / 2]

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

        # clear all the split tone flags -- we'll set them as needed below
        _mem.ctonesplitflag = 0
        _mem.rx_dtcssplitflag = 0
        _mem.rtonesplitflag = 0
        _mem.dtcssplitflag = 0

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
                # TSQL, but with separate tones for
                # send and receive
                _mem.tmode = TMODES.index("TSQL")
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

    def get_settings(self):
        _settings = self._memobj.settings
        _dtmf_strings = self._memobj.dtmf_strings
        _passwd = self._memobj.passwd

        repeater = RadioSettingGroup("repeater", "Repeater Settings")
        ctcss = RadioSettingGroup("ctcss", "CTCSS/DCS/EPCS Settings")
        arts = RadioSettingGroup("arts", "ARTS Settings")
        mbls = RadioSettingGroup("banks", "Memory Settings")
        scan = RadioSettingGroup("scan", "Scan Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        wires = RadioSettingGroup("wires", "WiRES(tm) Settings")
        switch = RadioSettingGroup("switch", "Switch/Knob Settings")
        disp = RadioSettingGroup("disp", "Display Settings")
        misc = RadioSettingGroup("misc", "Miscellaneous Settings")

        setmode = RadioSettings(repeater, ctcss, arts, mbls, scan,
                                dtmf, wires, switch, disp, misc)

        # numbers and names of settings refer to the way they're
        # presented in the set menu, as well as the list starting on
        # page 74 of the manual

        # 1 APO
        opts = ["Off", "30 Min", "1 Hour", "3 Hour", "5 Hour", "8 Hour"]
        misc.append(
            RadioSetting(
                "apo", "Automatic Power Off",
                RadioSettingValueList(opts, opts[_settings.apo])))

        # 2 AR.BEP
        opts = ["Off", "In Range", "Always"]
        arts.append(
            RadioSetting(
                "arts_beep", "ARTS Beep",
                RadioSettingValueList(opts, opts[_settings.arts_beep])))

        # 3 AR.INT
        opts = ["15 Sec", "25 Sec"]
        arts.append(
            RadioSetting(
                "arts_interval", "ARTS Polling Interval",
                RadioSettingValueList(opts, opts[_settings.arts_interval])))

        # 4 ARS
        opts = ["Off", "On"]
        repeater.append(
            RadioSetting(
                "ars", "Automatic Repeater Shift",
                RadioSettingValueList(opts, opts[_settings.ars])))

        # 5 BCLO
        opts = ["Off", "On"]
        misc.append(RadioSetting(
            "busy_lockout", "Busy Channel Lock-Out",
            RadioSettingValueList(opts, opts[_settings.busy_lockout])))

        # 6 BEEP
        opts = ["Off", "Key+Scan", "Key"]
        switch.append(RadioSetting(
            "beep", "Enable the Beeper",
            RadioSettingValueList(opts, opts[_settings.beep])))

        # 7 BELL
        opts = ["Off", "1", "3", "5", "8", "Continuous"]
        ctcss.append(RadioSetting("bell", "Bell Repetitions",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.bell])))

        # 8 BNK.LNK
        for i in range(0, 8):
            opts = ["Off", "On"]
            mbs = (self._memobj.mbs >> i) & 1
            rs = RadioSetting("mbs%i" % i, "Bank %s Scan" % (i + 1),
                              RadioSettingValueList(opts, opts[mbs]))

            def apply_mbs(s, index):
                if int(s.value):
                    self._memobj.mbs |= (1 << index)
                else:
                    self._memobj.mbs &= ~(1 << index)
            rs.set_apply_callback(apply_mbs, i)
            mbls.append(rs)

        # 9 BNK.NM - A per-bank attribute, nothing to do here.

        # 10 CLK.SFT - A per-channel attribute, nothing to do here.

        # 11 CW.ID
        opts = ["Off", "On"]
        arts.append(RadioSetting("cw_id", "CW ID Enable",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.cw_id])))

        cw_id_text = ""
        for i in _settings.cw_id_string:
            try:
                cw_id_text += CHARSET[i & 0x7F]
            except IndexError:
                if i != 0xff:
                    LOG.debug("unknown char index in cw id: %x " % (i))

        val = RadioSettingValueString(0, 16, cw_id_text, True)
        val.set_charset(CHARSET + "abcdefghijklmnopqrstuvwxyz")
        rs = RadioSetting("cw_id_string", "CW Identifier Text", val)

        def apply_cw_id(s):
            str = s.value.get_value().upper().rstrip()
            mval = ""
            mval = [chr(CHARSET.index(x)) for x in str]
            for x in range(len(mval), 16):
                mval.append(chr(0xff))
            for x in range(0, 16):
                _settings.cw_id_string[x] = ord(mval[x])
        rs.set_apply_callback(apply_cw_id)
        arts.append(rs)

        # 12 CWTRNG
        opts = ["Off", "4WPM", "5WPM", "6WPM", "7WPM", "8WPM", "9WPM",
                "10WPM", "11WPM", "12WPM", "13WPM", "15WPM", "17WPM",
                "20WPM", "24WPM", "30WPM", "40WPM"]
        misc.append(RadioSetting("cw_trng", "CW Training",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.cw_trng])))

        # todo: make the setting of the units here affect the display
        # of the speed.  Not critical, but would be slick.
        opts = ["CPM", "WPM"]
        misc.append(RadioSetting("cw_trng_units", "CW Training Units",
                                 RadioSettingValueList(opts,
                                                       opts[_settings.
                                                            cw_trng_units])))

        # 13 DC VLT - a read-only status, so nothing to do here

        # 14 DCS CD - A per-channel attribute, nothing to do here

        # 15 DCS.RV
        opts = ["Disabled", "Enabled"]
        ctcss.append(RadioSetting(
                     "inverted_dcs",
                     "\"Inverted\" DCS Code Decoding",
                     RadioSettingValueList(opts,
                                           opts[_settings.inverted_dcs])))

        # 16 DIMMER
        opts = ["Off"] + ["Level %d" % (x) for x in range(1, 11)]
        disp.append(RadioSetting("dimmer", "Dimmer",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .dimmer])))

        # 17 DT.A/M
        opts = ["Manual", "Auto"]
        dtmf.append(RadioSetting("dtmf_mode", "DTMF Autodialer",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .dtmf_mode])))

        # 18 DT.DLY
        opts = ["50 ms", "250 ms", "450 ms", "750 ms", "1000 ms"]
        dtmf.append(RadioSetting("dtmf_delay", "DTMF Autodialer Delay Time",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .dtmf_delay])))

        # 19 DT.SET
        for memslot in range(0, 10):
            dtmf_memory = ""
            for i in _dtmf_strings[memslot].dtmf_string:
                if i != 0xFF:
                    try:
                        dtmf_memory += CHARSET[i]
                    except IndexError:
                        LOG.debug("unknown char index in dtmf: %x " % (i))

            val = RadioSettingValueString(0, 16, dtmf_memory, True)
            val.set_charset(CHARSET + "abcdef")
            rs = RadioSetting("dtmf_string_%d" % memslot,
                              "DTMF Memory %d" % memslot, val)

            def apply_dtmf(s, i):
                LOG.debug("applying dtmf for %x\n" % i)
                str = s.value.get_value().upper().rstrip()
                LOG.debug("str is %s\n" % str)
                mval = ""
                mval = [chr(CHARSET.index(x)) for x in str]
                for x in range(len(mval), 16):
                    mval.append(chr(0xff))
                for x in range(0, 16):
                    _dtmf_strings[i].dtmf_string[x] = ord(mval[x])
            rs.set_apply_callback(apply_dtmf, memslot)
            dtmf.append(rs)

        # 20 DT.SPD
        opts = ["50 ms", "100 ms"]
        dtmf.append(RadioSetting("dtmf_speed",
                                 "DTMF Autodialer Sending Speed",
                                 RadioSettingValueList(opts,
                                                       opts[_settings.
                                                            dtmf_speed])))

        # 21 EDG.BEP
        opts = ["Off", "On"]
        mbls.append(RadioSetting("edge_beep", "Band Edge Beeper",
                                 RadioSettingValueList(opts,
                                                       opts[_settings.
                                                            edge_beep])))

        # 22 INT.CD
        opts = ["DTMF %X" % (x) for x in range(0, 16)]
        wires.append(RadioSetting("int_cd", "Access Number for WiRES(TM)",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.int_cd])))

        # 23 ING MD
        opts = ["Sister Radio Group", "Friends Radio Group"]
        wires.append(RadioSetting("wires_mode",
                                  "Internet Link Connection Mode",
                                  RadioSettingValueList(opts,
                                                        opts[_settings.
                                                             wires_mode])))

        # 24 INT.A/M
        opts = ["Manual", "Auto"]
        wires.append(RadioSetting("wires_auto", "Internet Link Autodialer",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .wires_auto])))
        # 25 INT.SET
        opts = ["F%d" % (x) for x in range(0, 10)]

        wires.append(RadioSetting("int_set", "Memory Register for "
                                  "non-WiRES Internet",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .int_set])))

        # 26 LOCK
        opts = ["Key", "Dial", "Key + Dial", "PTT",
                "Key + PTT", "Dial + PTT", "All"]
        switch.append(RadioSetting("lock", "Control Locking",
                                   RadioSettingValueList(opts,
                                                         opts[_settings
                                                              .lock])))

        # 27 MCGAIN
        opts = ["Level %d" % (x) for x in range(1, 10)]
        misc.append(RadioSetting("mic_gain", "Microphone Gain",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .mic_gain])))

        # 28 MEM.SCN
        opts = ["Tag 1", "Tag 2", "All Channels"]
        rs = RadioSetting("scan_mode", "Memory Scan Mode",
                          RadioSettingValueList(opts,
                                                opts[_settings
                                                     .scan_mode - 1]))
        # this setting is unusual in that it starts at 1 instead of 0.
        # that is, index 1 corresponds to "Tag 1", and index 0 is invalid.
        # so we create a custom callback to handle this.

        def apply_scan_mode(s):
            myopts = ["Tag 1", "Tag 2", "All Channels"]
            _settings.scan_mode = myopts.index(s.value.get_value()) + 1
        rs.set_apply_callback(apply_scan_mode)
        mbls.append(rs)

        # 29 MW MD
        opts = ["Lower", "Next"]
        mbls.append(RadioSetting("mw_mode", "Memory Write Mode",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .mw_mode])))

        # 30 NM SET - This is per channel, so nothing to do here

        # 31 OPN.MSG
        opts = ["Off", "DC Supply Voltage", "Text Message"]
        disp.append(RadioSetting("open_msg", "Opening Message Type",
                                 RadioSettingValueList(opts,
                                                       opts[_settings.
                                                            open_msg])))

        openmsg = ""
        for i in _settings.openMsg_Text:
            try:
                openmsg += CHARSET[i & 0x7F]
            except IndexError:
                if i != 0xff:
                    LOG.debug("unknown char index in openmsg: %x " % (i))

        val = RadioSettingValueString(0, 6, openmsg, True)
        val.set_charset(CHARSET + "abcdefghijklmnopqrstuvwxyz")
        rs = RadioSetting("openMsg_Text", "Opening Message Text", val)

        def apply_openmsg(s):
            str = s.value.get_value().upper().rstrip()
            mval = ""
            mval = [chr(CHARSET.index(x)) for x in str]
            for x in range(len(mval), 6):
                mval.append(chr(0xff))
            for x in range(0, 6):
                _settings.openMsg_Text[x] = ord(mval[x])
        rs.set_apply_callback(apply_openmsg)
        disp.append(rs)

        # 32 PAGER - a per-channel attribute

        # 33 PAG.ABK
        opts = ["Off", "On"]
        ctcss.append(RadioSetting("pag_abk", "Paging Answer Back",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .pag_abk])))

        # 34 PAG.CDR
        opts = ["%2.2d" % (x) for x in range(1, 50)]
        ctcss.append(RadioSetting("pag_cdr_1", "Receive Page Code 1",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .pag_cdr_1])))

        ctcss.append(RadioSetting("pag_cdr_2", "Receive Page Code 2",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .pag_cdr_2])))

        # 35 PAG.CDT
        opts = ["%2.2d" % (x) for x in range(1, 50)]
        ctcss.append(RadioSetting("pag_cdt_1", "Transmit Page Code 1",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .pag_cdt_1])))

        ctcss.append(RadioSetting("pag_cdt_2", "Transmit Page Code 2",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .pag_cdt_2])))

        # Common Button Options
        button_opts = ["Squelch Off", "Weather", "Smart Search",
                       "Tone Scan", "Scan", "T Call", "ARTS"]

        # 36 PRG P1
        opts = button_opts + ["DC Volts"]
        switch.append(RadioSetting(
            "prog_p1", "P1 Button",
            RadioSettingValueList(opts, opts[_settings.prog_p1])))

        # 37 PRG P2
        opts = button_opts + ["Dimmer"]
        switch.append(RadioSetting(
            "prog_p2", "P2 Button",
            RadioSettingValueList(opts, opts[_settings.prog_p2])))

        # 38 PRG P3
        opts = button_opts + ["Mic Gain"]
        switch.append(RadioSetting(
            "prog_p3", "P3 Button",
            RadioSettingValueList(opts, opts[_settings.prog_p3])))

        # 39 PRG P4
        opts = button_opts + ["Skip"]
        switch.append(RadioSetting(
            "prog_p4", "P4 Button",
            RadioSettingValueList(opts, opts[_settings.prog_p4])))

        # 40 PSWD
        password = ""
        for i in _passwd:
            if i != 0xFF:
                try:
                    password += CHARSET[i]
                except IndexError:
                    LOG.debug("unknown char index in password: %x " % (i))

        val = RadioSettingValueString(0, 4, password, True)
        val.set_charset(CHARSET[0:15] + "abcdef ")
        rs = RadioSetting("passwd", "Password", val)

        def apply_password(s):
            str = s.value.get_value().upper().rstrip()
            mval = ""
            mval = [chr(CHARSET.index(x)) for x in str]
            for x in range(len(mval), 4):
                mval.append(chr(0xff))
            for x in range(0, 4):
                _passwd[x] = ord(mval[x])
        rs.set_apply_callback(apply_password)
        misc.append(rs)

        # 41 RESUME
        opts = ["3 Sec", "5 Sec", "10 Sec", "Busy", "Hold"]
        scan.append(RadioSetting("resume", "Scan Resume Mode",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.resume])))

        # 42 RF.SQL
        opts = ["Off"] + ["S-%d" % (x) for x in range(1, 10)]
        misc.append(RadioSetting("rf_sql", "RF Squelch Threshold",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.rf_sql])))

        # 43 RPT - per channel attribute, nothing to do here

        # 44 RVRT
        opts = ["Off", "On"]
        misc.append(RadioSetting("revert", "Priority Revert",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.revert])))

        # 45 S.SRCH
        opts = ["Single", "Continuous"]
        misc.append(RadioSetting("s_search", "Smart Search Sweep Mode",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.s_search])))

        # 46 SHIFT - per channel setting, nothing to do here

        # 47 SKIP = per channel setting, nothing to do here

        # 48 SPLIT - per channel attribute, nothing to do here

        # 49 SQL.TYP - per channel attribute, nothing to do here

        # 50 STEP - per channel attribute, nothing to do here

        # 51 TEMP - read-only status, nothing to do here

        # 52 TN FRQ - per channel attribute, nothing to do here

        # 53 TOT
        opts = ["Off", "1 Min", "3 Min", "5 Min", "10 Min"]
        misc.append(RadioSetting("tot", "Timeout Timer",
                                 RadioSettingValueList(opts,
                                                       opts[_settings.tot])))

        # 54 TS MUT
        opts = ["Off", "On"]
        ctcss.append(RadioSetting("ts_mut", "Tone Search Mute",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .ts_mut])))

        # 55 TS SPEED
        opts = ["Fast", "Slow"]
        ctcss.append(RadioSetting("ts_speed", "Tone Search Scanner Speed",
                                  RadioSettingValueList(opts,
                                                        opts[_settings
                                                             .ts_speed])))

        # 56 VFO.SCN
        opts = ["+/- 1MHz", "+/- 2MHz", "+/-5MHz", "All"]
        scan.append(RadioSetting("vfo_scan", "VFO Scanner Width",
                                 RadioSettingValueList(opts,
                                                       opts[_settings
                                                            .vfo_scan])))

        # 57 WX.ALT
        opts = ["Off", "On"]
        misc.append(RadioSetting("wx_alert", "Weather Alert Scan",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.wx_alert])))

        # 58 WX.VOL
        opts = ["Normal", "Maximum"]
        misc.append(RadioSetting("wx_vol_max", "Weather Alert Volume",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.wx_vol_max])))

        # 59 W/N DV - this is a per-channel attribute, nothing to do here

        return setmode

    def set_settings(self, uisettings):
        _settings = self._memobj.settings
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue

            try:
                name = element.get_name()
                value = element.value

                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    obj = getattr(_settings, name)
                    setattr(_settings, name, value)

                LOG.debug("Setting %s: %s" % (name, value))
            except Exception as e:
                LOG.debug(element.get_name())
                raise

    def get_bank_model(self):
        return FT2900BankModel(self)

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
            5. Make sure display says "-WAIT-" (see note below if not)
            6. Click OK to dismiss this dialog and start transfer.

            Note: if you don't see "-WAIT-" at step 5, try cycling
                  power and pressing and holding red "*L" button to unlock
                  radio, then start back at step 1."""))
        return rp


# the FT2900E is the European version of the radio, almost identical
# to the R (USA) version, except for the model number and ID Block.  We
# create and register a class for it, with only the needed overrides
# NOTE: Disabled until detection is fixed
# @directory.register
class FT2900ERadio(FT2900Radio):

    """Yaesu FT-2900E"""
    MODEL = "FT-2900E/1900E"
    VARIANT = "E"
    IDBLOCK = "\x56\x43\x32\x33\x00\x02\x41\x02\x01\x01"
