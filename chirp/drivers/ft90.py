# Copyright 2011 Dan Smith <dsmith@danplanet.com>
# Copyright 2013 Jens Jensen AF5MI <kd4tjx@yahoo.com>
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

from chirp.drivers import yaesu_clone
from chirp import chirp_common, bitwise, memmap, directory, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

import time
import os
import traceback
import string
import re
import logging

from textwrap import dedent

LOG = logging.getLogger(__name__)

CMD_ACK = chr(0x06)

FT90_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
FT90_MODES = ["AM", "FM", "Auto"]
# idx 3 (Bell) not supported yet
FT90_TMODES = ["", "Tone", "TSQL", "", "DTCS"]
FT90_TONES = list(chirp_common.TONES)
for tone in [165.5, 171.3, 177.3]:
    FT90_TONES.remove(tone)
FT90_POWER_LEVELS_VHF = [chirp_common.PowerLevel("Hi", watts=50),
                         chirp_common.PowerLevel("Mid1", watts=20),
                         chirp_common.PowerLevel("Mid2", watts=10),
                         chirp_common.PowerLevel("Low", watts=5)]

FT90_POWER_LEVELS_UHF = [chirp_common.PowerLevel("Hi", watts=35),
                         chirp_common.PowerLevel("Mid1", watts=20),
                         chirp_common.PowerLevel("Mid2", watts=10),
                         chirp_common.PowerLevel("Low", watts=5)]

FT90_DUPLEX = ["", "-", "+", "split"]
FT90_CWID_CHARS = list(string.digits) + list(string.ascii_uppercase) + list(" ")
FT90_DTMF_CHARS = list("0123456789ABCD*#")
FT90_SPECIAL = ["vfo_vhf", "home_vhf", "vfo_uhf", "home_uhf",
                "pms_1L", "pms_1U", "pms_2L", "pms_2U"]


@directory.register
class FT90Radio(yaesu_clone.YaesuCloneModeRadio):
    VENDOR = "Yaesu"
    MODEL = "FT-90"
    ID = "\x8E\xF6"

    _memsize = 4063
    # block 03 (200 Bytes long) repeats 18 times; channel memories
    _block_lengths = [2, 232, 24] + ([200] * 18) + [205]

    mem_format = """
u16 id;
#seekto 0x22;
struct {
    u8 dtmf_active;
    u8 dtmf1_len;
    u8 dtmf2_len;
    u8 dtmf3_len;
    u8 dtmf4_len;
    u8 dtmf5_len;
    u8 dtmf6_len;
    u8 dtmf7_len;
    u8 dtmf8_len;
    u8 dtmf1[8];
    u8 dtmf2[8];
    u8 dtmf3[8];
    u8 dtmf4[8];
    u8 dtmf5[8];
    u8 dtmf6[8];
    u8 dtmf7[8];
    u8 dtmf8[8];
    char cwid[7];
    u8 unk1;
    u8 scan1:2,
       beep:1,
       unk3:3,
       rfsqlvl:2;
    u8 unk4:2,
       scan2:1,
       cwid_en:1,
       txnarrow:1,
       dtmfspeed:1,
       pttlock:2;
    u8 dtmftxdelay:3,
       fancontrol:2,
       unk5:3;
    u8 dimmer:3,
       unk6:1,
       lcdcontrast:4;
    u8 dcsmode:2,
       unk16:2,
       tot:4;
    u8 unk14;
    u8 unk8:1,
       ars:1,
       lock:1,
       txpwrsave:1,
       apo:4;
    u8 unk15;
    u8 unk9:4,
       key_lt:4;
    u8 unk10:4,
       key_rt:4;
    u8 unk11:4,
       key_p1:4;
    u8 unk12:4,
       key_p2:4;
    u8 unk13:4,
       key_acc:4;
} settings;

struct mem_struct {
    u8 mode:2,
       isUhf1:1,
       unknown1:2,
       step:3;
    u8 artsmode:2,
       unknown2:1,
       isUhf2:1
       power:2,
       shift:2;
    u8 skip:1,
       showname:1,
       unknown3:1,
       isUhfHi:1,
       unknown4:1,
       tmode:3;
    u32 rxfreq;
    u32 txfreqoffset;
    u8 UseDefaultName:1,
       ars:1,
       tone:6;
    u8 packetmode:1,
       unknown5:1,
       dcstone:6;
    char name[7];
};

#seekto 0x86;
struct mem_struct vfo_vhf;
struct mem_struct home_vhf;
struct mem_struct vfo_uhf;
struct mem_struct home_uhf;

#seekto 0xEB;
u8 chan_enable[23];

#seekto 0x101;
struct {
    u8 pms_2U_enable:1,
       pms_2L_enable:1,
       pms_1U_enable:1,
       pms_1L_enable:1,
       unknown6:4;
} special_enables;

#seekto 0x102;
struct mem_struct memory[180];

#seekto 0xf12;
struct mem_struct pms_1L;
struct mem_struct pms_1U;
struct mem_struct pms_2L;
struct mem_struct pms_2U;

#seekto 0x0F7B;
struct  {
    char demomsg1[50];
    char demomsg2[50];
} demomsg;
"""

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
1. Turn radio off.
2. Connect mic and hold [ACC] on mic while powering on.
    ("CLONE" will appear on the display)
3. Replace mic with PC programming cable.
4. <b>After clicking OK</b>, press the [SET] key to send image."""))
        rp.pre_upload = _(dedent("""\
1. Turn radio off.
2. Connect mic and hold [ACC] on mic while powering on.
    ("CLONE" will appear on the display)
3. Replace mic with PC programming cable.
4. Press the [DISP/SS] key
    ("R" will appear on the lower left of LCD)."""))
        rp.display_pre_upload_prompt_before_opening_port = False
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = False
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.has_dtcs = True
        rf.valid_modes = FT90_MODES
        rf.valid_tmodes = FT90_TMODES
        rf.valid_duplexes = FT90_DUPLEX
        rf.valid_tuning_steps = FT90_STEPS
        rf.valid_power_levels = FT90_POWER_LEVELS_VHF
        rf.valid_name_length = 7
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_skips = ["", "S"]
        rf.valid_special_chans = FT90_SPECIAL
        rf.memory_bounds = (1, 180)
        rf.valid_bands = [(100000000, 230000000),
                          (300000000, 530000000),
                          (810000000, 999975000)]

        return rf

    def _read(self, blocksize, blocknum):
        data = self.pipe.read(blocksize+2)

        # chew echo'd ack
        self.pipe.write(CMD_ACK)
        time.sleep(0.02)
        self.pipe.read(1)  # chew echoed ACK from 1-wire serial

        if len(data) == blocksize + 2 and data[0] == chr(blocknum):
            checksum = yaesu_clone.YaesuChecksum(1, blocksize)
            if checksum.get_existing(data) != checksum.get_calculated(data):
                raise Exception("Checksum Failed [%02X<>%02X] block %02X, "
                                "data len: %i" %
                                (checksum.get_existing(data),
                                 checksum.get_calculated(data),
                                 blocknum, len(data)))
            data = data[1:blocksize + 1]  # Chew blocknum and checksum

        else:
            raise Exception("Unable to read blocknum %02X "
                            "expected blocksize %i got %i." %
                            (blocknum, blocksize+2, len(data)))

        return data

    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.timeout = 4
        start = time.time()

        data = ""
        blocknum = 0
        status = chirp_common.Status()
        status.msg = "Cloning..."
        self.status_fn(status)
        status.max = len(self._block_lengths)
        for blocksize in self._block_lengths:
            data += self._read(blocksize, blocknum)
            blocknum += 1
            status.cur = blocknum
            self.status_fn(status)

        LOG.info("Clone completed in %i seconds, blocks read: %i" %
                 (time.time() - start, blocknum))

        return memmap.MemoryMap(data)

    def _clone_out(self):
        looppredelay = 0.4
        looppostdelay = 1.9
        start = time.time()

        blocknum = 0
        pos = 0
        status = chirp_common.Status()
        status.msg = "Cloning to radio..."
        self.status_fn(status)
        status.max = len(self._block_lengths)

        for blocksize in self._block_lengths:
            checksum = yaesu_clone.YaesuChecksum(pos, pos+blocksize-1)
            blocknumbyte = chr(blocknum)
            payloadbytes = self.get_mmap()[pos:pos+blocksize]
            checksumbyte = chr(checksum.get_calculated(self.get_mmap()))
            LOG.debug("Block %i - will send from %i to %i byte " %
                      (blocknum, pos, pos + blocksize))
            LOG.debug(util.hexprint(blocknumbyte))
            LOG.debug(util.hexprint(payloadbytes))
            LOG.debug(util.hexprint(checksumbyte))
            # send wrapped bytes
            time.sleep(looppredelay)
            self.pipe.write(blocknumbyte)
            self.pipe.write(payloadbytes)
            self.pipe.write(checksumbyte)
            tmp = self.pipe.read(blocksize + 2)  # chew echo
            LOG.debug("bytes echoed: ")
            LOG.debug(util.hexprint(tmp))
            # radio is slow to write/ack:
            time.sleep(looppostdelay)
            buf = self.pipe.read(1)
            LOG.debug("ack recd:")
            LOG.debug(util.hexprint(buf))
            if buf != CMD_ACK:
                raise Exception("Radio did not ack block %i" % blocknum)
            pos += blocksize
            blocknum += 1
            status.cur = blocknum
            self.status_fn(status)

        LOG.info("Clone completed in %i seconds" % (time.time() - start))

    def sync_in(self):
        try:
            self._mmap = self._clone_in()
        except errors.RadioError:
            raise
        except Exception as e:
            trace = traceback.format_exc()
            raise errors.RadioError(
                    "Failed to communicate with radio: %s" % trace)
        self.process_mmap()

    def sync_out(self):
        try:
            self._clone_out()
        except errors.RadioError:
            raise
        except Exception as e:
            trace = traceback.format_exc()
            raise errors.RadioError(
                    "Failed to communicate with radio: %s" % trace)

    def process_mmap(self):
        self._memobj = bitwise.parse(self.mem_format, self._mmap)

    def _get_chan_enable(self, number):
        number = number - 1
        bytepos = number // 8
        bitpos = number % 8
        chan_enable = self._memobj.chan_enable[bytepos]
        if chan_enable & (1 << bitpos):
            return True
        else:
            return False

    def _set_chan_enable(self, number, enable):
        number = number - 1
        bytepos = number // 8
        bitpos = number % 8
        chan_enable = self._memobj.chan_enable[bytepos]
        if enable:
            chan_enable = chan_enable | (1 << bitpos)  # enable
        else:
            chan_enable = chan_enable & ~(1 << bitpos)  # disable
        self._memobj.chan_enable[bytepos] = chan_enable

    def get_memory(self, number):
        mem = chirp_common.Memory()
        if isinstance(number, str):
            # special channel
            _mem = getattr(self._memobj, number)
            mem.number = - len(FT90_SPECIAL) + FT90_SPECIAL.index(number)
            mem.extd_number = number
            if re.match('^pms', mem.extd_number):
                # enable pms_XY channel flag
                _special_enables = self._memobj.special_enables
                mem.empty = not getattr(_special_enables,
                                        mem.extd_number + "_enable")
        else:
            # regular memory
            _mem = self._memobj.memory[number-1]
            mem.number = number
            mem.empty = not self._get_chan_enable(number)
        if mem.empty:
            return mem  # bail out, do not parse junk
        mem.freq = _mem.rxfreq * 10
        mem.offset = _mem.txfreqoffset * 10
        if not _mem.tmode < len(FT90_TMODES):
            _mem.tmode = 0
        mem.tmode = FT90_TMODES[_mem.tmode]
        mem.rtone = FT90_TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcstone]
        mem.mode = FT90_MODES[_mem.mode]
        mem.duplex = FT90_DUPLEX[_mem.shift]
        if mem.freq / 1000000 > 300:
            mem.power = FT90_POWER_LEVELS_UHF[_mem.power]
        else:
            mem.power = FT90_POWER_LEVELS_VHF[_mem.power]

        # radio has a known bug with 5khz step and squelch
        if _mem.step == 0 or _mem.step > len(FT90_STEPS)-1:
            _mem.step = 2
        mem.tuning_step = FT90_STEPS[_mem.step]
        mem.skip = _mem.skip and "S" or ""
        if not all(char in chirp_common.CHARSET_ASCII
                   for char in str(_mem.name)):
            # dont display blank/junk name
            mem.name = ""
        else:
            mem.name = str(_mem.name)
        return mem

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def set_memory(self, mem):
        if mem.number < 0:      # special channels
            _mem = getattr(self._memobj, mem.extd_number)
            if re.match('^pms', mem.extd_number):
                # enable pms_XY channel flag
                _special_enables = self._memobj.special_enables
                setattr(_special_enables, mem.extd_number + "_enable", True)
        else:
            _mem = self._memobj.memory[mem.number - 1]
            self._set_chan_enable(mem.number, not mem.empty)
        _mem.skip = mem.skip == "S"
        # radio has a known bug with 5khz step and dead squelch
        if not mem.tuning_step or mem.tuning_step == FT90_STEPS[0]:
            _mem.step = 2
        else:
            _mem.step = FT90_STEPS.index(mem.tuning_step)
        _mem.rxfreq = mem.freq / 10
        # vfo will unlock if not in right band?
        if mem.freq > 300000000:
            # uhf
            _mem.isUhf1 = 1
            _mem.isUhf2 = 1
            if mem.freq > 810000000:
                # uhf hiband
                _mem.isUhfHi = 1
            else:
                _mem.isUhfHi = 0
        else:
            # vhf
            _mem.isUhf1 = 0
            _mem.isUhf2 = 0
            _mem.isUhfHi = 0
        _mem.txfreqoffset = mem.offset / 10
        _mem.tone = FT90_TONES.index(mem.rtone)
        _mem.tmode = FT90_TMODES.index(mem.tmode)
        _mem.mode = FT90_MODES.index(mem.mode)
        _mem.shift = FT90_DUPLEX.index(mem.duplex)
        _mem.dcstone = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.step = FT90_STEPS.index(mem.tuning_step)
        _mem.shift = FT90_DUPLEX.index(mem.duplex)
        if mem.power:
            _mem.power = FT90_POWER_LEVELS_VHF.index(mem.power)
        else:
            _mem.power = 3  # default to low power
        if (len(mem.name) == 0):
            _mem.name = bytearray.fromhex("80ffffffffffff")
            _mem.showname = 0
        else:
            _mem.name = str(mem.name).ljust(7)
            _mem.showname = 1
            _mem.UseDefaultName = 0

    def _decode_cwid(self, cwidarr):
        cwid = ""
        LOG.debug("@ +_decode_cwid:")
        for byte in cwidarr.get_value():
            char = int(byte)
            LOG.debug(char)
            # bitwise wraps in quotes! get rid of those
            if char < len(FT90_CWID_CHARS):
                cwid += FT90_CWID_CHARS[char]
        return cwid

    def _encode_cwid(self, cwidarr):
        cwid = ""
        LOG.debug("@ _encode_cwid:")
        for char in cwidarr.get_value():
            cwid += chr(FT90_CWID_CHARS.index(char))
        LOG.debug(cwid)
        return cwid

    def _bbcd2dtmf(self, bcdarr, strlen=16):
        # doing bbcd, but with support for ABCD*#
        LOG.debug(bcdarr.get_value())
        string = ''.join("%02X" % b for b in bcdarr)
        LOG.debug("@_bbcd2dtmf, received: %s" % string)
        string = string.replace('E', '*').replace('F', '#')
        if strlen <= 16:
            string = string[:strlen]
        return string

    def _dtmf2bbcd(self, dtmf):
        dtmfstr = dtmf.get_value()
        dtmfstr = dtmfstr.replace('*', 'E').replace('#', 'F')
        dtmfstr = str.ljust(dtmfstr.strip(), 16, "0")
        bcdarr = list(bytearray.fromhex(dtmfstr))
        LOG.debug("@_dtmf2bbcd, sending: %s" % bcdarr)
        return bcdarr

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        autodial = RadioSettingGroup("autodial", "AutoDial")
        keymaps = RadioSettingGroup("keymaps", "KeyMaps")

        top = RadioSettings(basic, keymaps, autodial)

        rs = RadioSetting(
                "beep", "Beep",
                RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)
        rs = RadioSetting(
                "lock", "Lock",
                RadioSettingValueBoolean(_settings.lock))
        basic.append(rs)
        rs = RadioSetting(
                "ars", "Auto Repeater Shift",
                RadioSettingValueBoolean(_settings.ars))
        basic.append(rs)
        rs = RadioSetting(
                "txpwrsave", "TX Power Save",
                RadioSettingValueBoolean(_settings.txpwrsave))
        basic.append(rs)
        rs = RadioSetting(
                "txnarrow", "TX Narrow",
                RadioSettingValueBoolean(_settings.txnarrow))
        basic.append(rs)
        options = ["Off", "S-3", "S-5", "S-Full"]
        rs = RadioSetting(
                "rfsqlvl", "RF Squelch Level",
                RadioSettingValueList(options, options[_settings.rfsqlvl]))
        basic.append(rs)
        options = ["Off", "Band A", "Band B", "Both"]
        rs = RadioSetting(
                "pttlock", "PTT Lock",
                RadioSettingValueList(options, options[_settings.pttlock]))
        basic.append(rs)

        rs = RadioSetting(
                "cwid_en", "CWID Enable",
                RadioSettingValueBoolean(_settings.cwid_en))
        basic.append(rs)

        cwid = RadioSettingValueString(0, 7, self._decode_cwid(_settings.cwid))
        cwid.set_charset(FT90_CWID_CHARS)
        rs = RadioSetting("cwid", "CWID", cwid)
        basic.append(rs)

        options = ["OFF"] + map(str, range(1, 12+1))
        rs = RadioSetting(
                "apo", "APO time (hrs)",
                RadioSettingValueList(options, options[_settings.apo]))
        basic.append(rs)

        options = ["Off"] + map(str, range(1, 60+1))
        rs = RadioSetting(
                "tot", "Time Out Timer (mins)",
                RadioSettingValueList(options, options[_settings.tot]))
        basic.append(rs)

        options = ["off", "Auto/TX", "Auto", "TX"]
        rs = RadioSetting(
                "fancontrol", "Fan Control",
                RadioSettingValueList(options, options[_settings.fancontrol]))
        basic.append(rs)

        keyopts = ["Scan Up", "Scan Down", "Repeater", "Reverse", "Tone Burst",
                   "Tx Power", "Home Ch", "VFO/MR", "Tone", "Priority"]
        rs = RadioSetting(
                "key_lt", "Left Key",
                RadioSettingValueList(keyopts, keyopts[_settings.key_lt]))
        keymaps.append(rs)
        rs = RadioSetting(
                "key_rt", "Right Key",
                RadioSettingValueList(keyopts, keyopts[_settings.key_rt]))
        keymaps.append(rs)
        rs = RadioSetting(
                "key_p1", "P1 Key",
                RadioSettingValueList(keyopts, keyopts[_settings.key_p1]))
        keymaps.append(rs)
        rs = RadioSetting(
                "key_p2", "P2 Key",
                RadioSettingValueList(keyopts, keyopts[_settings.key_p2]))
        keymaps.append(rs)
        rs = RadioSetting(
                "key_acc", "ACC Key",
                RadioSettingValueList(keyopts, keyopts[_settings.key_acc]))
        keymaps.append(rs)

        options = map(str, range(0, 12+1))
        rs = RadioSetting(
                "lcdcontrast", "LCD Contrast",
                RadioSettingValueList(options, options[_settings.lcdcontrast]))
        basic.append(rs)

        options = ["off", "d4", "d3", "d2", "d1"]
        rs = RadioSetting(
                "dimmer", "Dimmer",
                RadioSettingValueList(options, options[_settings.dimmer]))
        basic.append(rs)

        options = ["TRX Normal", "RX Reverse", "TX Reverse", "TRX Reverse"]
        rs = RadioSetting(
                "dcsmode", "DCS Mode",
                RadioSettingValueList(options, options[_settings.dcsmode]))
        basic.append(rs)

        options = ["50 ms", "100 ms"]
        rs = RadioSetting(
                "dtmfspeed", "DTMF Speed",
                RadioSettingValueList(options, options[_settings.dtmfspeed]))
        autodial.append(rs)

        options = ["50 ms", "250 ms", "450 ms", "750 ms", "1 sec"]
        rs = RadioSetting(
                "dtmftxdelay", "DTMF TX Delay",
                RadioSettingValueList(options, options[_settings.dtmftxdelay]))
        autodial.append(rs)

        options = map(str, range(1, 8 + 1))
        rs = RadioSetting(
                "dtmf_active", "DTMF Active",
                RadioSettingValueList(options, options[_settings.dtmf_active]))
        autodial.append(rs)

        # setup 8 dtmf autodial entries
        for i in map(str, range(1, 9)):
            objname = "dtmf" + i
            dtmfsetting = getattr(_settings, objname)
            dtmflen = getattr(_settings, objname + "_len")
            dtmfstr = self._bbcd2dtmf(dtmfsetting, dtmflen)
            dtmf = RadioSettingValueString(0, 16, dtmfstr)
            dtmf.set_charset(FT90_DTMF_CHARS + list(" "))
            rs = RadioSetting(objname, objname.upper(), dtmf)
            autodial.append(rs)

        return top

    def set_settings(self, uisettings):
        _settings = self._memobj.settings
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                setting = element.get_name()
                oldval = getattr(_settings, setting)
                newval = element.value
                if setting == "cwid":
                    newval = self._encode_cwid(newval)
                if re.match('dtmf\d', setting):
                    # set dtmf length field and then get bcd dtmf
                    dtmfstrlen = len(str(newval).strip())
                    setattr(_settings, setting + "_len", dtmfstrlen)
                    newval = self._dtmf2bbcd(newval)
                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                setattr(_settings, setting, newval)
            except Exception as e:
                LOG.debug(element.get_name())
                raise
