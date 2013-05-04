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
import time

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    InvalidValueError

MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:4,
     scode:4;
  u8 unknown1[1];
  u8 unknown2:7,
     lowpower:1;
  u8 unknown3:1,
     wide:1,
     unknown4:2,
     bcl:1,
     scan:1,
     pttid:2;
} memory[128];

#seekto 0x0B08;
struct {
  u8 code[5];
  u8 unused[11];
} pttid[15];

#seekto 0x0C88;
struct {
  u8 code222[3];
  u8 unused222[2];
  u8 code333[3];
  u8 unused333[2];
  u8 alarmcode[3];
  u8 unused119[2];
  u8 unknown1;
  u8 code555[3];
  u8 unused555[2];
  u8 code666[3];
  u8 unused666[2];
  u8 code777[3];
  u8 unused777[2];
  u8 unknown2;
  u8 code60606[5];
  u8 code70707[5];
  u8 code[5];
  u8 unused1:6,
     aniid:2;
  u8 unknown[2];
  u8 dtmfon;
  u8 dtmfoff;
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
  u8 band;
  u8 tdrab;
  u8 ste;
  u8 rpste;
  u8 rptrl;
  u8 ponmsg;
  u8 roger;
} settings[2];

#seekto 0x0E52;
struct {
  u8 displayab:1,
     unknown1:2,
     fmradio:1,
     alarm:1,
     unknown2:1,
     reset:1,
     menu:1;
  u8 unknown3;
  u8 workmode;
  u8 keylock;
} extra;

#seekto 0x0E7E;
struct {
  u8 unused1:1,
     mrcha:7;
  u8 unused2:1,
     mrchb:7;
} wmchannel;

#seekto 0x0F10;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:6;
} vfoa;

#seekto 0x0F30;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:6;
} vfob;

#seekto 0x1000;
struct {
  u8 unknown1[8];
  char name[7];
  u8 unknown2;
} names[128];

#seekto 0x1818;
struct {
  char line1[7];
  char line2[7];
} sixpoweron_msg;

#seekto 0x1828;
struct {
  char line1[7];
  char line2[7];
} poweron_msg;

#seekto 0x1838;
struct {
  char line1[7];
  char line2[7];
} firmware_msg;

struct limit {
  u8 enable;
  bbcd lower[2];
  bbcd upper[2];
};

#seekto 0x1908;
struct {
  struct limit vhf;
  struct limit uhf;
} limits_new;

#seekto 0x1910;
struct {
  u8 unknown1[2];
  struct limit vhf;
  u8 unknown2;
  u8 unknown3[8];
  u8 unknown4[2];
  struct limit uhf;
} limits_old;

"""

# 0x1EC0 - 0x2000

STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
STEP_LIST = [str(x) for x in STEPS]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
STEP291_LIST = [str(x) for x in STEPS]
TIMEOUT_LIST = ["%s sec" % x for x in range(15, 615, 15)]
VOICE_LIST = ["Off", "English", "Chinese"]
DTMFST_LIST = ["OFF", "DT-ST", "ANI-ST", "DT+ANI"]
RESUME_LIST = ["TO", "CO", "SE"]
MODE_LIST = ["Channel", "Name", "Frequency"]
COLOR_LIST = ["Off", "Blue", "Orange", "Purple"]
ALMOD_LIST = ["Site", "Tone", "Code"]
TDRAB_LIST = ["Off", "A", "B"]
PONMSG_LIST = ["Full", "Message"]
RPSTE_LIST = ["%s" % x for x in range(1, 11, 1)]
RPSTE_LIST.insert(0, "OFF")
STEDELAY_LIST = ["%s ms" % x for x in range(100, 1100, 100)]
STEDELAY_LIST.insert(0, "OFF")
SCODE_LIST = ["%s" % x for x in range(1, 16)]
DTMFSPEED_LIST = ["%s ms" % x for x in range(50, 2010, 10)]

SETTING_LISTS = {
    "step" : STEP_LIST,
    "step291" : STEP291_LIST,
    "timeout" : TIMEOUT_LIST,
    "voice" : VOICE_LIST,
    "dtmfst" : DTMFST_LIST,
    "screv" : RESUME_LIST,
    "mdfa" : MODE_LIST,
    "mdfb" : MODE_LIST,
    "wtled" : COLOR_LIST,
    "rxled" : COLOR_LIST,
    "txled" : COLOR_LIST,
    "almod" : ALMOD_LIST,
    "tdrab" : TDRAB_LIST,
    "ponmsg" : PONMSG_LIST,
    "rpste" : RPSTE_LIST,
    "stedelay" : STEDELAY_LIST,
    "scode" : SCODE_LIST,
    "dtmfspeed" : DTMFSPEED_LIST,
}

def _do_status(radio, block):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = block
    status.max = radio.get_memsize()
    radio.status_fn(status)

def validate_orig(ident):
    try:
        ver = int(ident[4:7])
        if ver >= 291:
            raise errors.RadioError("Radio version %i not supported" % ver)
    except ValueError:
        raise errors.RadioError("Radio reported invalid version string")

def validate_291(ident):
    if ident[4:7] != "\x30\x04\x50":
        raise errors.RadioError("Radio version not supported")

UV5R_MODEL_ORIG = "\x50\xBB\xFF\x01\x25\x98\x4D"
UV5R_MODEL_291 = "\x50\xBB\xFF\x20\x12\x07\x25"
UV5R_MODEL_F11 = "\x50\xBB\xFF\x13\xA1\x11\xDD"

def _firmware_version_from_data(data):
    return data[0x1838:0x1848]

def _firmware_version_from_image(radio):
    return _firmware_version_from_data(radio.get_mmap())

def _do_ident(radio, magic):
    serial = radio.pipe
    serial.setTimeout(1)

    print "Sending Magic: %s" % util.hexprint(magic)
    serial.write(magic)
    ack = serial.read(1)
    
    if ack != "\x06":
        if ack:
            print repr(ack)
        raise errors.RadioError("Radio did not respond")

    serial.write("\x02")
    ident = serial.read(8)

    print "Ident:\n%s" % util.hexprint(ident)

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

def _get_radio_firmware_version(radio):
    block1 = _read_block(radio, 0x1EC0, 0x40)
    block2 = _read_block(radio, 0x1F00, 0x40)
    block = block1 + block2
    return block[48:64]

def _ident_radio(radio):
    for magic in radio._idents:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError, e:
            print e
            error = e
            time.sleep(2)
    if error:
        raise error
    raise errors.RadioError("Radio did not respond")

def _do_download(radio):
    data = _ident_radio(radio)

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
    _ident_radio(radio)

    image_version = _firmware_version_from_image(radio)
    radio_version = _get_radio_firmware_version(radio)
    print "Image is %s" % repr(image_version)
    print "Radio is %s" % repr(radio_version)

    if "BFB" not in radio_version and "USA" not in radio_version:
        raise errors.RadioError("Unsupported firmware version: `%s'" %
                                radio_version)

    # Main block
    for i in range(0x08, 0x1808, 0x10):
        _send_block(radio, i - 0x08, radio.get_mmap()[i:i+0x10])
        _do_status(radio, i)

    if len(radio.get_mmap().get_packed()) == 0x1808:
        print "Old image, not writing aux block"
        return # Old image, no aux block

    if image_version != radio_version:
        raise errors.RadioError("Upload finished, but the 'Other Settings' "
                                "could not be sent because the firmware "
                                "version of the image does not match that "
                                "of the radio")

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
    _basetype = "BFB"
    _idents = [UV5R_MODEL_ORIG,
               UV5R_MODEL_291,
               ]

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
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_name_length = 7
        rf.valid_characters = UV5R_CHARSET
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = UV5R_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_bands = [(136000000, 174000000), (400000000, 520000000)]
        rf.memory_bounds = (0, 127)
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return (len(filedata) in [0x1808, 0x1948] and
                cls._basetype in _firmware_version_from_data(filedata))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

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
            mem.rx_dtcs = UV5R_DTCS[index]
        else:
            print "Bug: rxtone is %04x" % _mem.rxtone

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = UV5R_POWER_LEVELS[_mem.lowpower]
        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        options = ["Off", "BOT", "EOT", "Both"]
        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(options,
                                                options[_mem.pttid]))
        mem.extra.append(rs)

        options = ["%s" % x for x in range(1, 16)]
        rs = RadioSetting("scode", "PTT ID Code",
                          RadioSettingValueList(options,
                                                options[_mem.scode]))
        mem.extra.append(rs)

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
                _mem.rxtone = UV5R_DTCS.index(mem.rx_dtcs) + 1
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

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _is_orig(self):
        version_tag = _firmware_version_from_image(self)
        try:
            if 'BFB' in version_tag:
                idx = version_tag.index("BFB") + 3
                version = int(version_tag[idx:idx+3])
                return version < 291
            if 'USA' in version_tag:
                return False
        except:
            pass
        raise errors.RadioError("Unable to parse version string %s" %
                                version_tag)

    def _my_version(self):
        version_tag = _firmware_version_from_image(self)
        if 'BFB' in version_tag:
            idx = version_tag.index("BFB") + 3
            return int(version_tag[idx:idx+3])
        elif 'USA' in version_tag:
            idx = version_tag.index("USA") + 3
            return int(version_tag[idx:idx+3])
        raise Exception("Unrecognized firmware version string")

    def _get_settings(self):
        _settings = self._memobj.settings[0]
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group = RadioSettingGroup("top", "All Settings", basic, advanced)

        rs = RadioSetting("squelch", "Carrier Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueInteger(0, 4, _settings.save))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Sensitivity",
                          RadioSettingValueInteger(0, 10, _settings.vox))
        advanced.append(rs)

        rs = RadioSetting("abr", "Backlight Timeout",
                          RadioSettingValueInteger(0, 24, _settings.abr))
        basic.append(rs)

        rs = RadioSetting("tdr", "Dual Watch",
                          RadioSettingValueBoolean(_settings.tdr))
        advanced.append(rs)

        rs = RadioSetting("tdrab", "Dual Watch Priority",
                          RadioSettingValueList(TDRAB_LIST,
                                                TDRAB_LIST[_settings.tdrab]))
        advanced.append(rs)

        rs = RadioSetting("almod", "Alarm Mode",
                          RadioSettingValueList(ALMOD_LIST,
                                                ALMOD_LIST[_settings.almod]))
        advanced.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("timeout", "Timeout Timer",
                          RadioSettingValueList(TIMEOUT_LIST,
                                                TIMEOUT_LIST[_settings.timeout]))
        basic.append(rs)

        if self._my_version() >= 251:
            rs = RadioSetting("voice", "Voice",
                              RadioSettingValueList(VOICE_LIST,
                                                    VOICE_LIST[_settings.voice]))
            advanced.append(rs)
        else:
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

        rs = RadioSetting("extra.fmradio", "Broadcast FM Radio",
                          RadioSettingValueBoolean(self._memobj.extra.fmradio))
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

        rs = RadioSetting("roger", "Roger Beep",
                          RadioSettingValueBoolean(_settings.roger))
        basic.append(rs)

        rs = RadioSetting("ste", "Squelch Tail Eliminate (HT to HT)",
                          RadioSettingValueBoolean(_settings.ste))
        advanced.append(rs)

        rs = RadioSetting("rpste", "Squelch Tail Eliminate (repeater)",
                          RadioSettingValueList(RPSTE_LIST,
                                                RPSTE_LIST[_settings.rpste]))
        advanced.append(rs)

        rs = RadioSetting("rptrl", "STE Repeater Delay",
                          RadioSettingValueList(STEDELAY_LIST,
                                                STEDELAY_LIST[_settings.rptrl]))
        advanced.append(rs)

        rs = RadioSetting("extra.reset", "RESET Menu",
                          RadioSettingValueBoolean(self._memobj.extra.reset))
        advanced.append(rs)

        rs = RadioSetting("extra.menu", "All Menus",
                          RadioSettingValueBoolean(self._memobj.extra.menu))
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

        _msg = self._memobj.firmware_msg
        val = RadioSettingValueString(0, 7, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line1", "Firmware Message 1", val)
        other.append(rs)

        val = RadioSettingValueString(0, 7, _filter(_msg.line2))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line2", "Firmware Message 2", val)
        other.append(rs)

        _msg = self._memobj.sixpoweron_msg
        rs = RadioSetting("sixpoweron_msg.line1", "6+Power-On Message 1",
                          RadioSettingValueString(0, 7, _filter(_msg.line1)))
        other.append(rs)
        rs = RadioSetting("sixpoweron_msg.line2", "6+Power-On Message 2",
                          RadioSettingValueString(0, 7, _filter(_msg.line2)))
        other.append(rs)

        _msg = self._memobj.poweron_msg
        rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                          RadioSettingValueString(0, 7, _filter(_msg.line1)))
        other.append(rs)
        rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                          RadioSettingValueString(0, 7, _filter(_msg.line2)))
        other.append(rs)

        rs = RadioSetting("ponmsg", "Power-On Message",
                          RadioSettingValueList(PONMSG_LIST,
                                                PONMSG_LIST[_settings.ponmsg]))
        other.append(rs)

        if self._is_orig():
            limit = "limits_old"
        else:
            limit = "limits_new"

        vhf_limit = getattr(self._memobj, limit).vhf
        rs = RadioSetting("%s.vhf.lower" % limit, "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   vhf_limit.lower))
        other.append(rs)

        rs = RadioSetting("%s.vhf.upper" % limit, "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   vhf_limit.upper))
        other.append(rs)

        rs = RadioSetting("%s.vhf.enable" % limit, "VHF TX Enabled",
                          RadioSettingValueBoolean(vhf_limit.enable))
        other.append(rs)

        uhf_limit = getattr(self._memobj, limit).uhf
        rs = RadioSetting("%s.uhf.lower" % limit, "UHF Lower Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   uhf_limit.lower))
        other.append(rs)
        rs = RadioSetting("%s.uhf.upper" % limit, "UHF Upper Limit (MHz)",
                          RadioSettingValueInteger(1, 1000,
                                                   uhf_limit.upper))
        other.append(rs)
        rs = RadioSetting("%s.uhf.enable" % limit, "UHF TX Enabled",
                          RadioSettingValueBoolean(uhf_limit.enable))
        other.append(rs)

        workmode = RadioSettingGroup("workmode", "Work Mode Settings")
        group.append(workmode)

        options = ["A", "B"]
        rs = RadioSetting("extra.displayab", "Display",
                          RadioSettingValueList(options,
                                                options[self._memobj.extra.displayab]))
        workmode.append(rs)

        options = ["Frequency", "Channel"]
        rs = RadioSetting("extra.workmode", "VFO/MR Mode",
                          RadioSettingValueList(options,
                                                options[self._memobj.extra.workmode]))
        workmode.append(rs)

        rs = RadioSetting("extra.keylock", "Keypad Lock",
                          RadioSettingValueBoolean(self._memobj.extra.keylock))
        workmode.append(rs)

        _mrcna = self._memobj.wmchannel.mrcha
        rs = RadioSetting("wmchannel.mrcha", "MR A Channel",
                          RadioSettingValueInteger(0, 127, _mrcna))
        workmode.append(rs)

        _mrcnb = self._memobj.wmchannel.mrchb
        rs = RadioSetting("wmchannel.mrchb", "MR B Channel",
                          RadioSettingValueInteger(0, 127, _mrcnb))
        workmode.append(rs)

        def convert_bytes_to_freq(bytes):
           real_freq = 0
           for byte in bytes:
               real_freq = (real_freq * 10) + byte
           return chirp_common.format_freq(real_freq * 10)

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            if 17400000 <= value and value < 40000000:
                raise InvalidValueError("Can't be between 174.00000-400.00000")
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            obj.band = value >= 40000000
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10,
            convert_bytes_to_freq(self._memobj.vfoa.freq))
        val1a.set_validate_callback(my_validate)
        rs = RadioSetting("vfoa.freq", "VFO A Frequency", val1a)
        rs.set_apply_callback(apply_freq, self._memobj.vfoa)
        workmode.append(rs)

        val1b = RadioSettingValueString(0, 10,
            convert_bytes_to_freq(self._memobj.vfob.freq))
        val1b.set_validate_callback(my_validate)
        rs = RadioSetting("vfob.freq", "VFO B Frequency", val1b)
        rs.set_apply_callback(apply_freq, self._memobj.vfob)
        workmode.append(rs)

        options = ["Off", "+", "-"]
        rs = RadioSetting("vfoa.sftd", "VFO A Shift",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfoa.sftd]))
        workmode.append(rs)

        rs = RadioSetting("vfob.sftd", "VFO B Shift",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfob.sftd]))
        workmode.append(rs)

        def convert_bytes_to_offset(bytes):
           real_offset = 0
           for byte in bytes:
               real_offset = (real_offset * 10) + byte
           return chirp_common.format_freq(real_offset * 10000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10000
            for i in range(3, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10,
            convert_bytes_to_offset(self._memobj.vfoa.offset))
        rs = RadioSetting("vfoa.offset", "VFO A Offset (0.00-69.95)", val1a)
        rs.set_apply_callback(apply_offset, self._memobj.vfoa)
        workmode.append(rs)

        val1b = RadioSettingValueString(0, 10,
            convert_bytes_to_offset(self._memobj.vfob.offset))
        rs = RadioSetting("vfob.offset", "VFO B Offset (0.00-69.95)", val1b)
        rs.set_apply_callback(apply_offset, self._memobj.vfob)
        workmode.append(rs)

        options = ["High", "Low"]
        rs = RadioSetting("vfoa.txpower", "VFO A Power",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfoa.txpower]))
        workmode.append(rs)

        rs = RadioSetting("vfob.txpower", "VFO B Power",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfob.txpower]))
        workmode.append(rs)

        options = ["Wide", "Narrow"]
        rs = RadioSetting("vfoa.widenarr", "VFO A Bandwidth",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfoa.widenarr]))
        workmode.append(rs)

        rs = RadioSetting("vfob.widenarr", "VFO B Bandwidth",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfob.widenarr]))
        workmode.append(rs)

        options = ["%s" % x for x in range(1, 16)]
        rs = RadioSetting("vfoa.scode", "VFO A PTT-ID",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfoa.scode]))
        workmode.append(rs)

        rs = RadioSetting("vfob.scode", "VFO B PTT-ID",
                          RadioSettingValueList(options,
                                                options[self._memobj.vfob.scode]))
        workmode.append(rs)

        if self._my_version() >= 291:
            rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                              RadioSettingValueList(STEP291_LIST,
                                                    STEP291_LIST[self._memobj.vfoa.step]))
            workmode.append(rs)
            rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                              RadioSettingValueList(STEP291_LIST,
                                                    STEP291_LIST[self._memobj.vfob.step]))
            workmode.append(rs)
        else:
            rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                              RadioSettingValueList(STEP_LIST,
                                                    STEP_LIST[self._memobj.vfoa.step]))
            workmode.append(rs)
            rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                              RadioSettingValueList(STEP_LIST,
                                                    STEP_LIST[self._memobj.vfob.step]))
            workmode.append(rs)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)
        dtmfchars = "0123456789 *#ABCD"

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(dtmfchars)
            rs = RadioSetting("pttid/%i.code" % i, "PTT ID Code %i" % (i + 1), val)
            def apply_code(setting, obj):
                code = []
                for j in range(0, 5):
                    try:
                        code.append(dtmfchars.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code
            rs.set_apply_callback(apply_code, self._memobj.pttid[i])
            dtmf.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.code", "ANI Code", val)
        def apply_code(setting, obj):
            code = []
            for j in range(0, 5):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, self._memobj.ani)
        dtmf.append(rs)

        options = ["Off", "BOT", "EOT", "Both"]
        rs = RadioSetting("ani.aniid", "ANI ID",
                          RadioSettingValueList(options,
                                                options[self._memobj.ani.aniid]))
        dtmf.append(rs)

        _codeobj = self._memobj.ani.alarmcode
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 3, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.alarmcode", "Alarm Code", val)
        def apply_code(setting, obj):
            alarmcode = []
            for j in range(0, 3):
                try:
                    alarmcode.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    alarmcode.append(0xFF)
            obj.alarmcode = alarmcode
        rs.set_apply_callback(apply_code, self._memobj.ani)
        dtmf.append(rs)

        rs = RadioSetting("dtmfst", "DTMF Sidetone",
                          RadioSettingValueList(DTMFST_LIST,
                                                DTMFST_LIST[_settings.dtmfst]))
        dtmf.append(rs)

        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                DTMFSPEED_LIST[self._memobj.ani.dtmfon]))
        dtmf.append(rs)

        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                DTMFSPEED_LIST[self._memobj.ani.dtmfoff]))
        dtmf.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            print "Failed to parse settings:"
            traceback.print_exc()
            return None

    def set_settings(self, settings):
        _settings = self._memobj.settings[0]
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                name = element.get_name()
                if "." in name:
                    bits = name.split(".")
                    obj = self._memobj
                    for bit in bits[:-1]:
                        if "/" in bit:
                            bit, index = bit.split("/", 1)
                            index = int(index)
                            obj = getattr(obj, bit)[index]
                        else:
                            obj = getattr(obj, bit)
                    setting = bits[-1]
                else:
                    obj = _settings
                    setting = element.get_name()

                if element.has_apply_callback():
                    print "Using apply callback"
                    element.run_apply_callback()
                else:
                    print "Setting %s = %s" % (setting, element.value)
                    setattr(obj, setting, element.value)
            except Exception, e:
                print element.get_name()
                raise

@directory.register
class BaofengF11Radio(BaofengUV5R):
    VENDOR = "Baofeng"
    MODEL = "F-11"
    _basetype = "USA"
    _idents = [UV5R_MODEL_F11]
