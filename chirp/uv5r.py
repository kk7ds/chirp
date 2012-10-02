# Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import struct

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueList, RadioSettingValueBoolean, \
    RadioSettingValueString

MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown1[2];
  u8 unknown2:7,
     lowpower:1;
  u8 unknown3:1,
     wide:1,
     unknown4:3,
     scan:1,
     unknown5:2;
} memory[128];

#seekto 0x0CB2;
struct {
  u8 code[5];
} ani;

#seekto 0x0E28;
struct {
  u8 squelch;
  u8 step;
  u8 unknown1;
  u8 save;
  u8 vox;
  u8 unknown2;
  u8 abr;
  u8 tdr;
  u8 beep;
  u8 timeout;
  u8 unknown3[4];
  u8 voice;
  u8 unknown4;
  u8 dtmfst;
  u8 unknown5;
  u8 screv;
  u8 pttid;
  u8 pttlt;
  u8 mdfa;
  u8 mdfb;
  u8 bcl;
  u8 autolk;
  u8 sftd;
  u8 unknown6[3];
  u8 wtled;
  u8 rxled;
  u8 txled;
  u8 almod;
  u8 tdrab;
  u8 ste;
  u8 rpste;
  u8 rptrl;
  u8 ponmsg;
  u8 roger;
} settings[2];

#seekto 0x1000;
struct {
  u8 unknown1[8];
  char name[7];
  u8 unknown2;
} names[128];

#seekto 0x1828;
struct {
  char line1[7];
  char line2[7];
} poweron_msg;

#seekto 0x1910;
struct limit {
  u8 unknown1[3];
  bbcd lower[2];
  bbcd upper[2];
  u8 unknown2;
  u8 unknown3[8];
};

struct limit vhf_limit;
struct limit uhf_limit;

"""

# 0x1EC0 - 0x2000

STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
STEP_LIST = [str(x) for x in STEPS]
TIMEOUT_LIST = ["%s sec" % x for x in range(15, 615, 15)]
RESUME_LIST = ["TO", "CO", "SE"]
MODE_LIST = ["Channel", "Name", "Frequency"]
COLOR_LIST = ["Off", "Blue", "Orange", "Purple"]

SETTING_LISTS = {
    "step" : STEP_LIST,
    "timeout" : TIMEOUT_LIST,
    "screv" : RESUME_LIST,
    "mdfa" : MODE_LIST,
    "mdfb" : MODE_LIST,
    "wtled" : COLOR_LIST,
    "rxled" : COLOR_LIST,
    "txled" : COLOR_LIST,
}

def _do_status(radio, block):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = block
    status.max = radio.get_memsize()
    radio.status_fn(status)

def _do_ident(radio):
    serial = radio.pipe
    serial.setTimeout(1)

    serial.write("\x50\xBB\xFF\x01\x25\x98\x4D")
    ack = serial.read(1)
    
    if ack != "\x06":
        print repr(ack)
        raise errors.RadioError("Radio did not respond")

    serial.write("\x02")
    ident = serial.read(8)

    print "Ident:\n%s" % util.hexprint(ident)
    if ident[1:4] != "BFB":
        raise errors.RadioError("Radio reported unknown vendor")
    try:
        ver = int(ident[4:7])
        if ver >= 291:
            raise errors.RadioError("Radio version %i not supported" % ver)
    except ValueError:
        raise errors.RadioError("Radio reported invalid version string")

    serial.write("\x06")
    ack = serial.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio refused clone")

    return ident

def _read_block(radio, start, size):
    msg = struct.pack(">BHB", ord("S"), start, size)
    radio.pipe.write(msg)

    answer = radio.pipe.read(4)
    if len(answer) != 4:
        raise errors.RadioError("Radio refused to send block 0x%04x" % start)

    cmd, addr, length = struct.unpack(">BHB", answer)
    if cmd != ord("X") or addr != start or length != size:
        print "Invalid answer for block 0x%04x:" % start
        print "CMD: %s  ADDR: %04x  SIZE: %02x" % (cmd, addr, length)
        raise errors.RadioError("Unknown response from radio")

    chunk = radio.pipe.read(0x40)
    if not chunk:
        raise errors.RadioError("Radio did not send block 0x%04x" % start)
    elif len(chunk) != size:
        print "Chunk length was 0x%04i" % len(chunk)
        raise errors.RadioError("Radio sent incomplete block 0x%04x" % start)
    
    radio.pipe.write("\x06")

    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio refused to send block 0x%04x" % start)
    
    return chunk

def _do_download(radio):
    data = _do_ident(radio)

    # Main block
    for i in range(0, 0x1800, 0x40):
        data += _read_block(radio, i, 0x40)
        _do_status(radio, i)

    # Auxiliary block starts at 0x1ECO (?)
    for i in range(0x1EC0, 0x2000, 0x40):
        data += _read_block(radio, i, 0x40)

    return memmap.MemoryMap(data)

def _send_block(radio, addr, data):
    msg = struct.pack(">BHB", ord("X"), addr, len(data))
    radio.pipe.write(msg + data)

    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio refused to accept block 0x%04x" % addr)
    
def _do_upload(radio):
    _do_ident(radio)

    # Main block
    for i in range(0x08, 0x1808, 0x10):
        _send_block(radio, i - 0x08, radio.get_mmap()[i:i+0x10])
        _do_status(radio, i)

    if len(radio.get_mmap().get_packed()) == 0x1808:
        print "Old image, not writing aux block"
        return # Old image, no aux block

    # Auxiliary block at radio address 0x1EC0, our offset 0x1808
    for i in range(0x1EC0, 0x2000, 0x10):
        addr = 0x1808 + (i - 0x1EC0)
        _send_block(radio, i, radio.get_mmap()[addr:addr+0x10])

UV5R_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=4.00),
                     chirp_common.PowerLevel("Low",  watts=1.00)]

UV5R_DTCS = sorted(chirp_common.DTCS_CODES + [645])

UV5R_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + \
    "!@#$%^&*()+-=[]:\";'<>?,./"

# Uncomment this to actually register this radio in CHIRP
@directory.register
class BaofengUV5R(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """Baofeng UV-5R"""
    VENDOR = "Baofeng"
    MODEL = "UV-5R"
    BAUD_RATE = 9600

    _memsize = 0x1808

    @classmethod
    def get_experimental_warning(cls):
        return ('Due to the fact that the manufacturer continues to '
                'release new versions of the firmware with obscure and '
                'hard-to-track changes, this driver may not work with '
                'your device. Thus far and to the best knowledge of the '
                'author, no UV-5R radios have been harmed by using CHIRP. '
                'However, proceed at your own risk!')

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_name_length = 7
        rf.valid_characters = UV5R_CHARSET
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->"]
        rf.valid_power_levels = UV5R_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_bands = [(136000000, 174000000), (400000000, 512000000)]
        rf.memory_bounds = (0, 127)
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) in [0x1808, 0x1948]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        print self.get_settings()

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " " # The UV-5R software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = UV5R_DTCS[index]
        else:
            print "Bug: txtone is %04x" % _mem.txtone

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.dtcs = UV5R_DTCS[index]
        else:
            print "Bug: rxtone is %04x" % _mem.rxtone

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS":
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = UV5R_POWER_LEVELS[_mem.lowpower]
        mem.mode = _mem.wide and "FM" or "NFM"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            return

        _mem.set_raw("\x00" * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        for i in range(0, 7):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = UV5R_DTCS.index(mem.dtcs) + 1
            _mem.rxtone = UV5R_DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = UV5R_DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = UV5R_DTCS.index(mem.dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"
        _mem.lowpower = mem.power == UV5R_POWER_LEVELS[1]

    def get_settings(self):
        _settings = self._memobj.settings[0]
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group = RadioSettingGroup("top", "All Settings", basic, advanced)

        rs = RadioSetting("squelch", "Carrier Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("step", "Tuning Step",
                          RadioSettingValueList(STEP_LIST,
                                                STEP_LIST[_settings.step]))
        advanced.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueInteger(0, 4, _settings.save))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Sensitivity",
                          RadioSettingValueInteger(0, 10, _settings.vox))
        advanced.append(rs)

        rs = RadioSetting("abr", "Backlight Timeout",
                          RadioSettingValueInteger(0, 5, _settings.abr))
        basic.append(rs)

        rs = RadioSetting("tdr", "Dual Watch",
                          RadioSettingValueBoolean(_settings.tdr))
        advanced.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("timeout", "Timeout Timer",
                          RadioSettingValueList(TIMEOUT_LIST,
                                                TIMEOUT_LIST[_settings.timeout]))
        basic.append(rs)

        rs = RadioSetting("voice", "Voice",
                          RadioSettingValueBoolean(_settings.voice))
        advanced.append(rs)
        
        rs = RadioSetting("screv", "Scan Resume",
                          RadioSettingValueList(RESUME_LIST,
                                                RESUME_LIST[_settings.screv]))
        advanced.append(rs)

        rs = RadioSetting("mdfa", "Display Mode (A)",
                          RadioSettingValueList(MODE_LIST,
                                                MODE_LIST[_settings.mdfa]))
        basic.append(rs)

        rs = RadioSetting("mdfb", "Display Mode (B)",
                          RadioSettingValueList(MODE_LIST,
                                                MODE_LIST[_settings.mdfb]))
        basic.append(rs)

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(_settings.bcl))
        advanced.append(rs)

        rs = RadioSetting("autolk", "Automatic Key Lock",
                          RadioSettingValueBoolean(_settings.autolk))
        advanced.append(rs)

        rs = RadioSetting("wtled", "Standby LED Color",
                          RadioSettingValueList(COLOR_LIST,
                                                COLOR_LIST[_settings.wtled]))
        basic.append(rs)

        rs = RadioSetting("rxled", "RX LED Color",
                          RadioSettingValueList(COLOR_LIST,
                                                COLOR_LIST[_settings.rxled]))
        basic.append(rs)

        rs = RadioSetting("txled", "TX LED Color",
                          RadioSettingValueList(COLOR_LIST,
                                                COLOR_LIST[_settings.txled]))
        basic.append(rs)

        _ani = self._memobj.ani.code
        rs = RadioSetting("ani.code", "ANI Code",
                          RadioSettingValueInteger(0, 9, _ani[0]),
                          RadioSettingValueInteger(0, 9, _ani[1]),
                          RadioSettingValueInteger(0, 9, _ani[2]),
                          RadioSettingValueInteger(0, 9, _ani[3]),
                          RadioSettingValueInteger(0, 9, _ani[4]))
        advanced.append(rs)

        if len(self._mmap.get_packed()) == 0x1808:
            # Old image, without aux block
            return group

        other = RadioSettingGroup("other", "Other Settings")
        group.append(other)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.poweron_msg
        rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                          RadioSettingValueString(0, 7, _filter(_msg.line1)))
        other.append(rs)
        rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                          RadioSettingValueString(0, 7, _filter(_msg.line2)))
        other.append(rs)

        vhf_limit = self._memobj.vhf_limit
        rs = RadioSetting("vhf_limit.lower", "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   vhf_limit.lower))
        other.append(rs)

        rs = RadioSetting("vhf_limit.upper", "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   vhf_limit.upper))

        uhf_limit = self._memobj.uhf_limit
        other.append(rs)
        rs = RadioSetting("uhf_limit.lower", "UHF Lower Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   uhf_limit.lower))
        other.append(rs)
        rs = RadioSetting("uhf_limit.upper", "UHF Upper Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   uhf_limit.upper))
        other.append(rs)

        return group

    def set_settings(self, settings):
        _settings = self._memobj.settings[0]
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                if "." in element.get_name():
                    objname, setting = element.get_name().split(".", 1)
                    obj = getattr(self._memobj, objname)
                else:
                    obj = _settings
                    setting = element.get_name()
                print "Setting %s = %s" % (setting, element.value)
                setattr(obj, setting, element.value)
            except Exception, e:
                print element.get_name()
                raise
