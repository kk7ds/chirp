# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

import struct
import time
import os
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList

if os.getenv("CHIRP_DEBUG"):
    DEBUG = True
else:
    DEBUG = False

WOUXUN_MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 _3_unknown_1:4,
     bcl:1,
     _3_unknown_2:3;
  u8 splitdup:1,
     skip:1,
     power_high:1,
     iswide:1,
     _2_unknown_2:4;
  u8 unknown[2];
} memory[199];

#seekto 0x0E5C;
struct {
  u8 unknown_flag1:7,
     menu_available:1;
} v1settings;

#seekto 0x0F00;
struct {
  u8 unknown1[44];
  u8 unknown_flag1:6,
     voice:2;
  u8 unknown_flag2:7,
     beep:1;
  u8 unknown2[12];
  u8 unknown_flag3:6,
     ponmsg:2;
  u8 unknown3[3];
  u8 unknown_flag4:7,
     sos_ch:1;
  u8 unknown4[29];
  u8 unknown_flag5:7,
     menu_available:1;
} v6settings;

#seekto 0x1008;
struct {
  u8 unknown[8];
  u8 name[6];
  u8 pad[2];
} names[199];
"""

def _wouxun_identify(radio, string):
    """Do the original wouxun identification dance"""
    for _i in range(0, 5):
        radio.pipe.write(string)
        resp = radio.pipe.read(9)
        if len(resp) != 9:
            print "Got:\n%s" % util.hexprint(r)
            print "Retrying identification..."
            time.sleep(1)
            continue
        if resp[2:8] != radio._model:
            raise Exception("I can't talk to this model (%s)" % util.hexprint(resp))
        return
    if len(resp) == 0:
        raise Exception("Radio not responding")
    else:
        raise Exception("Unable to identify radio")

def wouxun_identify(radio):
    return _wouxun_identify(radio, "HiWOUXUN\x02")

def wouxun6_identify(radio):
    return _wouxun_identify(radio, "HiWXUVD1\x02")

def wouxun_start_transfer(radio):
    """Tell the radio to go into transfer mode"""
    radio.pipe.write("\x02\x06")
    time.sleep(0.05)
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise Exception("Radio refused transfer mode")    

def do_download(radio, start, end, blocksize):
    """Initiate a download of @radio between @start and @end"""
    image = ""
    for i in range(start, end, blocksize):
        cmd = struct.pack(">cHb", "R", i, blocksize)
        if DEBUG:
            print util.hexprint(cmd)
        radio.pipe.write(cmd)
        length = len(cmd) + blocksize
        resp = radio.pipe.read(length)
        if len(resp) != (len(cmd) + blocksize):
            print util.hexprint(resp)
            raise Exception("Failed to read full block (%i!=%i)" % \
                                (len(resp),
                                 len(cmd) + blocksize))
        
        radio.pipe.write("\x06")
        radio.pipe.read(1)
        image += resp[4:]

        if radio.status_fn:
            status = chirp_common.Status()           
            status.cur = i
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)
    
    return memmap.MemoryMap(image)

def do_upload(radio, start, end, blocksize):
    """Initiate an upload of @radio between @start and @end"""
    ptr = start
    for i in range(start, end, blocksize):
        cmd = struct.pack(">cHb", "W", i, blocksize)
        chunk = radio.get_mmap()[ptr:ptr+blocksize]
        ptr += blocksize
        radio.pipe.write(cmd + chunk)
        if DEBUG:
            print util.hexprint(cmd + chunk)

        ack = radio.pipe.read(1)
        if not ack == "\x06":
            raise Exception("Radio did not ack block %i" % ptr)
        #radio.pipe.write(ack)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)

def wouxun_download(radio):
    """Talk to an original wouxun and do a download"""
    try:
        wouxun_identify(radio)
        wouxun_start_transfer(radio)
        return do_download(radio, 0x0000, 0x2000, 0x0040)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def wouxun_upload(radio):
    """Talk to an original wouxun and do an upload"""
    try:
        wouxun_identify(radio)
        wouxun_start_transfer(radio)
        return do_upload(radio, 0x0000, 0x2000, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def wouxun6_download(radio):
    """Talk to an original wouxun and do a download"""
    try:
        wouxun6_identify(radio)
        wouxun_start_transfer(radio)
        return do_download(radio, 0x0000, 0x2000, 0x0040)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def wouxun6_upload(radio):
    """Talk to an original wouxun and do an upload"""
    try:
        wouxun6_identify(radio)
        wouxun_start_transfer(radio)
        return do_upload(radio, 0x0000, 0x2000, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

CHARSET = list("0123456789") + [chr(x + ord("A")) for x in range(0, 26)] + \
    list("?+ ")

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                chirp_common.PowerLevel("Low", watts=1.00)]

def wipe_memory(_mem, byte):
    _mem.set_raw(byte * (_mem.size() / 8))

@directory.register
class KGUVD1PRadio(chirp_common.CloneModeRadio):
    """Wouxun KG-UVD1P,UV2,UV3"""
    VENDOR = "Wouxun"
    MODEL = "KG-UVD1P"
    _model = "KG669V"

    def sync_in(self):
        self._mmap = wouxun_download(self)
        self.process_mmap()

    def sync_out(self):
        wouxun_upload(self)

    def process_mmap(self):
        if len(self._mmap.get_packed()) != 8192:
            print "NOTE: Fixing old-style Wouxun image"
            # Originally, CHIRP's wouxun image had eight bytes of
            # static data, followed by the first memory at offset
            # 0x0008.  Between 0.1.11 and 0.1.12, this was fixed to 16
            # bytes of (whatever) followed by the first memory at
            # offset 0x0010, like the radio actually stores it.  So,
            # if we find one of those old ones, convert it to the new
            # format, padding 16 bytes of 0xFF in front.
            self._mmap = memmap.MemoryMap(("\xFF" * 16) + \
                                              self._mmap.get_packed()[8:8184])
        self._memobj = bitwise.parse(WOUXUN_MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
                        "Tone->Tone",
                        "Tone->DTCS",
                        "DTCS->Tone",
                        "DTCS->",
                        "->Tone",
                        "->DTCS",
                        "DTCS->DTCS",
                    ]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(136000000, 174000000), (216000000, 520000000)]
        rf.valid_characters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        rf.valid_name_length = 6
        rf.valid_duplexes = ["", "+", "-", "split"]
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_settings = True
        rf.memory_bounds = (1, 128)
        rf.can_odd_split = True
        return rf

    def get_settings(self):
        group = RadioSettingGroup("top", "All Settings")

        rs = RadioSetting("menu_available", "Menu Available",
                          RadioSettingValueBoolean(self._memobj.v1settings.menu_available))
        group.append(rs)

        return group

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                setattr(self._memobj.v1settings, element.get_name(), element.value)
            except Exception, e:
                print element.get_name()
                raise



    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol
            
        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2800:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2800:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if mem.tmode == "DTCS":
            mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        if DEBUG:
            print "Got TX %s (%i) RX %s (%i)" % (txmode, _mem.tx_tone,
                                                 rxmode, _mem.rx_tone)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw() == ("\xff" * 16):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        if _mem.splitdup:
            mem.duplex = "split"
        elif int(_mem.rx_freq) < int(_mem.tx_freq):
            mem.duplex = "+"
        elif int(_mem.rx_freq) > int(_mem.tx_freq):
            mem.duplex = "-"

        if mem.duplex == "":
            mem.offset = 0
        elif mem.duplex == "split":
            mem.offset = int(_mem.tx_freq) * 10
        else:
            mem.offset = abs(int(_mem.tx_freq) - int(_mem.rx_freq)) * 10

        if not _mem.skip:
            mem.skip = "S"
        if not _mem.iswide:
            mem.mode = "NFM"

        self._get_tone(_mem, mem)

        mem.power = POWER_LEVELS[not _mem.power_high]

        for i in _nam.name:
            if i == 0xFF:
                break
            mem.name += CHARSET[i]

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            return val

        if mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
        elif mem.tmode == "Tone":
            tx_mode = mem.tmode
            rx_mode = None
        else:
            tx_mode = rx_mode = mem.tmode


        if tx_mode == "DTCS":
            _mem.tx_tone = mem.tmode != "DTCS" and \
                _set_dcs(mem.dtcs, mem.dtcs_polarity[0]) or _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[0])
        elif tx_mode:
            _mem.tx_tone = tx_mode == "Tone" and \
                int(mem.rtone * 10) or int(mem.ctone * 10)
        else:
            _mem.tx_tone = 0xFFFF

        if rx_mode == "DTCS":
            _mem.rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
        elif rx_mode:
            _mem.rx_tone = int(mem.ctone * 10)
        else:
            _mem.rx_tone = 0xFFFF

        if DEBUG:
            print "Set TX %s (%i) RX %s (%i)" % (tx_mode, _mem.tx_tone,
                                                 rx_mode, _mem.rx_tone)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            wipe_memory(_mem, "\xFF")
            return

        if _mem.get_raw() == ("\xFF" * 16):
            wipe_memory(_mem, "\x00")

        _mem.rx_freq = int(mem.freq / 10)
        if mem.duplex == "split":
            _mem.tx_freq = int(mem.offset / 10)
        elif mem.duplex == "+":
            _mem.tx_freq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.tx_freq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.tx_freq = int(mem.freq / 10)
        _mem.splitdup = mem.duplex == "split"
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"

        self._set_tone(mem, _mem)

        if mem.power:
            _mem.power_high = not POWER_LEVELS.index(mem.power)
        else:
            _mem.power_high = True

        # Default to disabling the busy channel lockout
        _mem.bcl = 0

        _nam.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _nam.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")

    @classmethod
    def match_model(cls, filedata, filename):
        # New-style image (CHIRP 0.1.12)
        if len(filedata) == 8192 and \
                filedata[0x60:0x64] != "2009" and \
                filedata[0xf00:0xf05] != "KGUV6":
                    # TODO Must find an == test to avoid
                    # collision with future supported radios
            return True
        # Old-style image (CHIRP 0.1.11)
        if len(filedata) == 8200 and \
                filedata[0:4] == "\x01\x00\x00\x00":
            return True
        return False

@directory.register
class KGUV6DRadio(KGUVD1PRadio):
    MODEL = "KG-UV6D"

    def get_features(self):
        rf = KGUVD1PRadio.get_features(self)
        rf.valid_bands = [(136000000, 175000000), (350000000, 471000000)]
        rf.memory_bounds = (1, 199)
        return rf

    def get_settings(self):
        group = RadioSettingGroup("top", "All Settings")

        rs = RadioSetting("menu_available", "Menu Available",
                          RadioSettingValueBoolean(self._memobj.v6settings.menu_available))
        group.append(rs)
        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(self._memobj.v6settings.beep))
        group.append(rs)
        options = ["Off", "Welcome", "V bat"]
        rs = RadioSetting("ponmsg", "PONMSG",
                          RadioSettingValueList(options,
                                            options[self._memobj.v6settings.ponmsg]))
        group.append(rs)
        options = ["Off", "Chinese", "English"]
        rs = RadioSetting("voice", "Voice",
                          RadioSettingValueList(options,
                                            options[self._memobj.v6settings.voice]))
        group.append(rs)
        options = ["CH A", "CH B"]
        rs = RadioSetting("sos_ch", "SOS CH",
                          RadioSettingValueList(options,
                                            options[self._memobj.v6settings.sos_ch]))
        group.append(rs)


        return group

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                setattr(self._memobj.v6settings, element.get_name(), element.value)
            except Exception, e:
                print element.get_name()
                raise

    def sync_in(self):
        self._mmap = wouxun6_download(self)
        self.process_mmap()

    def sync_out(self):
        wouxun6_upload(self)

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) == 8192 and \
                filedata[0xf00:0xf06] == "KGUV6D":
            return True
        return False

@directory.register
class KGUV6XRadio(KGUV6DRadio):
    MODEL = "KG-UV6X"

    def get_features(self):
        rf = KGUV6DRadio.get_features(self)
        rf.valid_bands = [(136000000, 175000000), (375000000, 512000000)]
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) == 8192 and \
                filedata[0xf00:0xf06] == "KGUV6X":
            return True
        return False


def _puxing_prep(radio):
    radio.pipe.write("\x02PROGRA")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise Exception("Radio did not ACK first command")

    radio.pipe.write("M\x02")
    ident = radio.pipe.read(8)
    if len(ident) != 8:
        print util.hexprint(ident)
        raise Exception("Radio did not send identification")

    radio.pipe.write("\x06")
    if radio.pipe.read(1) != "\x06":
        raise Exception("Radio did not ACK ident")

def puxing_prep(radio):
    """Do the Puxing PX-777 identification dance"""
    for _i in range(0, 10):
        try:
            return _puxing_prep(radio)
        except Exception, e:
            time.sleep(1)

    raise e

def puxing_download(radio):
    """Talk to a Puxing PX-777 and do a download"""
    try:
        puxing_prep(radio)
        return do_download(radio, 0x0000, 0x0C60, 0x0008)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def puxing_upload(radio):
    """Talk to a Puxing PX-777 and do an upload"""
    try:
        puxing_prep(radio)
        return do_upload(radio, 0x0000, 0x0C40, 0x0008)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

PUXING_CHARSET = list("0123456789") + \
    [chr(x + ord("A")) for x in range(0, 26)] + \
    list("-                       ")

PUXING_MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 _3_unknown_1;
  u8 _2_unknown_1:2,
     power_high:1,
     iswide:1,
     skip:1,
     bclo:2,
     _2_unknown_2:1;
  u8 _4_unknown1:7,
     pttid:1;
  u8 unknown;
} memory[128];

#seekto 0x080A;
struct {
  u8 limits;
  u8 model;
} model[1];

#seekto 0x0850;
struct {
  u8 name[6];
  u8 pad[2];
} names[128];
"""

# Limits
#   67- 72: 0xEE
#  136-174: 0xEF
#  240-260: 0xF0
#  350-390: 0xF1
#  400-430: 0xF2
#  430-450: 0xF3
#  450-470: 0xF4
#  470-490: 0xF5
#  400-470: 0xF6
#  460-520: 0xF7

PUXING_MODELS = {
    328 : 0x38,
    338 : 0x39,
    777 : 0x3A,
}

PUXING_777_BANDS = [
    ( 67000000,  72000000),
    (136000000, 174000000),
    (240000000, 260000000),
    (350000000, 390000000),
    (400000000, 430000000),
    (430000000, 450000000),
    (450000000, 470000000),
    (470000000, 490000000),
    (400000000, 470000000),
    (460000000, 520000000),
]

@directory.register
class Puxing777Radio(KGUVD1PRadio):
    """Puxing PX-777"""
    VENDOR = "Puxing"
    MODEL = "PX-777"

    def sync_in(self):
        self._mmap = puxing_download(self)
        self.process_mmap()

    def sync_out(self):
        puxing_upload(self)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        rf.valid_name_length = 6
        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.memory_bounds = (1, 128)

        if not hasattr(self, "_memobj") or self._memobj is None:
            limit_idx = 1
        else:
            limit_idx = self._memobj.model.limits - 0xEE
        try:
            rf.valid_bands = [PUXING_777_BANDS[limit_idx]]
        except IndexError:
            print "Invalid band index %i (0x%02x)" % \
                (limit_idx, self._memobj.model.limits)
            rf.valid_bands = [PUXING_777_BANDS[1]]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(PUXING_MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1]) + "\r\n" + \
            repr(self._memobj.names[number - 1])

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) > 0x080B and \
                ord(filedata[0x080B]) != PUXING_MODELS[777]:
            return False
        return len(filedata) == 3168

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        def _is_empty():
            for i in range(0, 4):
                if _mem.rx_freq[i].get_raw() != "\xFF":
                    return False
            return True

        def _is_no_tone(field):
            return field[0].get_raw() == "\xFF"

        def _get_dtcs(value):
            # Upper nibble 0x80 -> DCS, 0xC0 -> Inv. DCS
            if value > 12000:
                return "R", value - 12000
            elif value > 8000:
                return "N", value - 8000
            else:
                raise Exception("Unable to convert DCS value")

        def _do_dtcs(mem, txfield, rxfield):
            if int(txfield) < 8000 or int(rxfield) < 8000:
                raise Exception("Split tone not supported")

            if txfield[0].get_raw() == "\xFF":
                tp, tx = "N", None
            else:
                tp, tx = _get_dtcs(int(txfield))
            
            if rxfield[0].get_raw() == "\xFF":
                rp, rx = "N", None
            else:
                rp, rx = _get_dtcs(int(rxfield))

            if not rx:
                rx = tx
            if not tx:
                tx = rx

            if tx != rx:
                raise Exception("Different RX and TX DCS codes not supported")

            mem.dtcs = tx
            mem.dtcs_polarity = "%s%s" % (tp, rp)

        mem = chirp_common.Memory()
        mem.number = number

        if _is_empty():
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        mem.offset = (int(_mem.tx_freq) * 10) - mem.freq
        if mem.offset < 0:
            mem.duplex = "-"
        elif mem.offset:
            mem.duplex = "+"
        mem.offset = abs(mem.offset)
        if not _mem.skip:
            mem.skip = "S"
        if not _mem.iswide:
            mem.mode = "NFM"

        if _is_no_tone(_mem.tx_tone):
            pass # No tone
        elif int(_mem.tx_tone) > 8000 or \
                (not _is_no_tone(_mem.rx_tone) and int(_mem.rx_tone) > 8000):
            mem.tmode = "DTCS"
            _do_dtcs(mem, _mem.tx_tone, _mem.rx_tone)
        else:
            mem.rtone = int(_mem.tx_tone) / 10.0
            mem.tmode = _is_no_tone(_mem.rx_tone) and "Tone" or "TSQL"

        mem.power = POWER_LEVELS[not _mem.power_high]

        for i in _nam.name:
            if i == 0xFF:
                break
            mem.name += PUXING_CHARSET[i]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            wipe_memory(_mem, "\xFF")
            return

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq / 10) + (mem.offset / 10)
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq / 10) - (mem.offset / 10)
        else:
            _mem.tx_freq = (mem.freq / 10)
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"


        _mem.rx_tone[0].set_raw("\xFF")
        _mem.rx_tone[1].set_raw("\xFF")
        _mem.tx_tone[0].set_raw("\xFF")
        _mem.tx_tone[1].set_raw("\xFF")


        if mem.tmode == "DTCS":
            _mem.tx_tone = int("%x" % int("%i" % (mem.dtcs), 16))
            _mem.rx_tone = int("%x" % int("%i" % (mem.dtcs), 16))

            # Argh.  Set the high order two bits to signal DCS or Inv. DCS
            txm = mem.dtcs_polarity[0] == "N" and 0x80 or 0xC0
            rxm = mem.dtcs_polarity[1] == "N" and 0x80 or 0xC0
            _mem.tx_tone[1].set_raw(chr(ord(_mem.tx_tone[1].get_raw()) | txm))
            _mem.rx_tone[1].set_raw(chr(ord(_mem.rx_tone[1].get_raw()) | rxm))

        elif mem.tmode:
            _mem.tx_tone = int(mem.rtone * 10)
            if mem.tmode == "TSQL":
                _mem.rx_tone = int(_mem.tx_tone)

        if mem.power:
            _mem.power_high = not POWER_LEVELS.index(mem.power)
        else:
            _mem.power_high = True

        # Default to disabling the busy channel lockout
        # 00 == Close
        # 01 == Carrier
        # 10 == QT/DQT
        _mem.bclo = 0

        _nam.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _nam.name[i] = PUXING_CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")

def puxing_2r_prep(radio):
    """Do the Puxing 2R identification dance"""
    radio.pipe.setTimeout(0.2)
    radio.pipe.write("PROGRAM\x02")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise Exception("Radio is not responding")

    radio.pipe.write(ack)
    ident = radio.pipe.read(16)
    print "Radio ident: %s (%i)" % (repr(ident), len(ident))

def puxing_2r_download(radio):
    """Talk to a Puxing 2R and do a download"""
    try:
        puxing_2r_prep(radio)
        return do_download(radio, 0x0000, 0x0FE0, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def puxing_2r_upload(radio):
    """Talk to a Puxing 2R and do an upload"""
    try:
        puxing_2r_prep(radio)
        return do_upload(radio, 0x0000, 0x0FE0, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

PUXING_2R_MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd freq[4];
  lbcd offset[4];
  u8 rx_tone;
  u8 tx_tone;
  u8 duplex:2,
     txdtcsinv:1,
     rxdtcsinv:1,
     simplex:1,
     unknown2:1,
     iswide:1,
     ishigh:1;
  u8 name[5];
} memory[128];
"""

PX2R_DUPLEX = ["", "+", "-", ""]
PX2R_POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.0),
                     chirp_common.PowerLevel("High", watts=2.0)]
PX2R_CHARSET = "0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZ +"

@directory.register
class Puxing2RRadio(KGUVD1PRadio):
    """Puxing PX-2R"""
    VENDOR = "Puxing"
    MODEL = "PX-2R"
    _memsize = 0x0FE0

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = PX2R_POWER_LEVELS
        rf.valid_bands = [(400000000, 500000000)]
        rf.valid_characters = PX2R_CHARSET
        rf.valid_name_length = 5
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_skips = []
        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.memory_bounds = (1, 128)
        rf.can_odd_split = False
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return (len(filedata) == cls._memsize) and \
            filedata[-16:] != "IcomCloneFormat3"

    def sync_in(self):
        self._mmap = puxing_2r_download(self)
        self.process_mmap()

    def sync_out(self):
        puxing_2r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(PUXING_2R_MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        if _mem.get_raw()[0:4] == "\xff\xff\xff\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10
        mem.mode = _mem.iswide and "FM" or "NFM"
        mem.duplex = PX2R_DUPLEX[_mem.duplex]
        mem.power = PX2R_POWER_LEVELS[_mem.ishigh]

        if _mem.tx_tone >= 0x33:
            mem.dtcs = chirp_common.DTCS_CODES[_mem.tx_tone - 0x33]
            mem.tmode = "DTCS"
            mem.dtcs_polarity = \
                (_mem.txdtcsinv and "R" or "N") + \
                (_mem.rxdtcsinv and "R" or "N")
        elif _mem.tx_tone:
            mem.rtone = chirp_common.TONES[_mem.tx_tone - 1]
            mem.tmode = _mem.rx_tone and "TSQL" or "Tone"

        count = 0
        for i in _mem.name:
            if i == 0xFF:
                break
            try:
                mem.name += PX2R_CHARSET[i]
            except Exception:
                print "Unknown name char %i: 0x%02x (mem %i)" % (count,
                                                                 i, number)
                mem.name += " "
            count += 1
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            return

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10
        _mem.iswide = mem.mode == "FM"
        _mem.duplex = PX2R_DUPLEX.index(mem.duplex)
        _mem.ishigh = mem.power == PX2R_POWER_LEVELS[1]

        if mem.tmode == "DTCS":
            _mem.tx_tone = chirp_common.DTCS_CODES.index(mem.dtcs) + 0x33
            _mem.rx_tone = chirp_common.DTCS_CODES.index(mem.dtcs) + 0x33
            _mem.txdtcsinv = mem.dtcs_polarity[0] == "R" 
            _mem.rxdtcsinv = mem.dtcs_polarity[1] == "R"
        elif mem.tmode in ["Tone", "TSQL"]:
            _mem.tx_tone = chirp_common.TONES.index(mem.rtone) + 1
            _mem.rx_tone = mem.tmode == "TSQL" and int(_mem.tx_tone) or 0
        else:
            _mem.tx_tone = 0
            _mem.rx_tone = 0

        for i in range(0, 5):
            try:
                _mem.name[i] = PX2R_CHARSET.index(mem.name[i])
            except IndexError:
                _mem.name[i] = 0xFF

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

def _uv3r_prep(radio):
    radio.pipe.write("\x05PROGRAM")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not ACK first command")

    radio.pipe.write("\x02")
    ident = radio.pipe.read(8)
    if len(ident) != 8:
        print util.hexprint(ident)
        raise errors.RadioError("Radio did not send identification")

    radio.pipe.write("\x06")
    if radio.pipe.read(1) != "\x06":
        raise errors.RadioError("Radio did not ACK ident")

def uv3r_prep(radio):
    """Do the UV3R identification dance"""
    for _i in range(0, 10):
        try:
            return _uv3r_prep(radio)
        except errors.RadioError, e:
            time.sleep(1)

    raise e

def uv3r_download(radio):
    """Talk to a UV3R and do a download"""
    try:
        uv3r_prep(radio)
        return do_download(radio, 0x0000, 0x0E40, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def uv3r_upload(radio):
    """Talk to a UV3R and do an upload"""
    try:
        uv3r_prep(radio)
        return do_upload(radio, 0x0000, 0x0E40, 0x0010)
    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

UV3R_MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rx_freq[4];
  u8 rxtone;
  lbcd offset[4];
  u8 txtone;
  u8 ishighpower:1,
     iswide:1,
     dtcsinvt:1,
     unknown1:1,
     dtcsinvr:1,
     unknown2:1,
     duplex:2;
  u8 unknown;
  lbcd tx_freq[4];
} tx_memory[99];
#seekto 0x0810;
struct {
  lbcd rx_freq[4];
  u8 rxtone;
  lbcd offset[4];
  u8 txtone;
  u8 ishighpower:1,
     iswide:1,
     dtcsinvt:1,
     unknown1:1,
     dtcsinvr:1,
     unknown2:1,
     duplex:2;
  u8 unknown;
  lbcd tx_freq[4];
} rx_memory[99];

#seekto 0x1008;
struct {
  u8 unknown[8];
  u8 name[6];
  u8 pad[2];
} names[128];
"""

UV3R_DUPLEX = ["", "-", "+", ""]
UV3R_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                     chirp_common.PowerLevel("Low", watts=0.50)]
UV3R_DTCS_POL = ["NN", "NR", "RN", "RR"]

@directory.register
class UV3RRadio(KGUVD1PRadio):
    """Baofeng UV-3R"""
    VENDOR = "Baofeng"
    MODEL = "UV-3R"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = UV3R_POWER_LEVELS
        rf.valid_bands = [(136000000, 174000000), (400000000, 470000000)]
        rf.valid_skips = []
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS"]
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_name = False
        rf.can_odd_split = True
        rf.memory_bounds = (1, 99)
        return rf

    def sync_in(self):
        self._mmap = uv3r_download(self)
        self.process_mmap()

    def sync_out(self):
        uv3r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(UV3R_MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        _mem = self._memobj.rx_memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        mem.offset = int(_mem.offset) * 10
        mem.duplex = UV3R_DUPLEX[_mem.duplex]
        if mem.offset > 60000000:
            if mem.duplex == "+":
                mem.offset = mem.freq + mem.offset
            elif mem.duplex == "-":
                mem.offset = mem.freq - mem.offset
            mem.duplex = "split"
        mem.power = UV3R_POWER_LEVELS[1 - _mem.ishighpower]
        if not _mem.iswide:
            mem.mode = "NFM"

        dtcspol = (int(_mem.dtcsinvt) << 1) + _mem.dtcsinvr
        mem.dtcs_polarity = UV3R_DTCS_POL[dtcspol]

        if _mem.txtone in [0, 0xFF]:
            txmode = ""
        elif _mem.txtone < 0x33:
            mem.rtone = chirp_common.TONES[_mem.txtone - 1]
            txmode = "Tone"
        elif _mem.txtone >= 0x33:
            tcode = chirp_common.DTCS_CODES[_mem.txtone - 0x33]
            mem.dtcs = tcode
            txmode = "DTCS"
        else:
            print "Bug: tx_mode is %02x" % _mem.txtone

        if _mem.rxtone in [0, 0xFF]:
            rxmode = ""
        elif _mem.rxtone < 0x33:
            mem.ctone = chirp_common.TONES[_mem.rxtone - 1]
            rxmode = "Tone"
        elif _mem.rxtone >= 0x33:
            rcode = chirp_common.DTCS_CODES[_mem.rxtone - 0x33]
            mem.dtcs = rcode
            rxmode = "DTCS"
        else:
            print "Bug: rx_mode is %02x" % _mem.rxtone

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS":
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        return mem

    def _set_tone(self, _mem, which, value, mode):
        if mode == "Tone":
            val = chirp_common.TONES.index(value) + 1
        elif mode == "DTCS":
            val = chirp_common.DTCS_CODES.index(value) + 0x33
        elif mode == "":
            val = 0
        else:
            raise errors.RadioError("Internal error: tmode %s" % mode)

        setattr(_mem, which, val)

    def _set_memory(self, mem, _mem):
        if mem.empty:
            _mem.set_raw("\xff" * 16)
            return

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "split":
            diff = mem.freq - mem.offset
            _mem.offset = abs(diff) / 10
            _mem.duplex = UV3R_DUPLEX.index(diff < 0 and "+" or "-")
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        else:
            _mem.offset = mem.offset / 10
            _mem.duplex = UV3R_DUPLEX.index(mem.duplex)
            _mem.tx_freq = (mem.freq + mem.offset) / 10

        _mem.ishighpower = mem.power == UV3R_POWER_LEVELS[0]
        _mem.iswide = mem.mode == "FM"

        _mem.dtcsinvt = mem.dtcs_polarity[0] == "R"
        _mem.dtcsinvr = mem.dtcs_polarity[1] == "R"

        rxtone = txtone = 0
        rxmode = txmode = ""

        if mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            rxtone = txtone = mem.dtcs
        elif mem.tmode and mem.tmode != "Cross":
            rxtone = txtone = mem.tmode == "Tone" and mem.rtone or mem.ctone
            txmode = "Tone"
            rxmode = mem.tmode == "TSQL" and "Tone" or ""
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

            if txmode == "DTCS":
                txtone = mem.dtcs
            elif txmode == "Tone":
                txtone = mem.rtone

            if rxmode == "DTCS":
                rxtone = mem.dtcs
            elif rxmode == "Tone":
                rxtone = mem.ctone

        self._set_tone(_mem, "txtone", txtone, txmode)
        self._set_tone(_mem, "rxtone", rxtone, rxmode)

    def set_memory(self, mem):
        _tmem = self._memobj.tx_memory[mem.number - 1]
        _rmem = self._memobj.rx_memory[mem.number - 1]

        self._set_memory(mem, _tmem)
        self._set_memory(mem, _rmem)

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == 3648

    def get_raw_memory(self, number):
        _rmem = self._memobj.tx_memory[number - 1]
        _tmem = self._memobj.rx_memory[number - 1]
        return repr(_rmem) + repr(_tmem)

def tyt_uv3r_prep(radio):
    try:
        radio.pipe.write("PROGRAMa")
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio did not ACK first command")
    except:
        raise errors.RadioError("Unable to communicate with the radio")

def tyt_uv3r_download(radio):
    tyt_uv3r_prep(radio)
    return do_download(radio, 0x0000, 0x0910, 0x0010)

def tyt_uv3r_upload(radio):
    tyt_uv3r_prep(radio)
    return do_upload(radio, 0x0000, 0x0910, 0x0010)

mem_format = """
struct memory {
  ul24 duplex:2,
       bit:1,
       iswide:1,
       bits:2,
       is625:1,
       freq:17;
  ul16 offset;
  ul16 rx_tone;
  ul16 tx_tone;
  u8 unknown;
  u8 name[6];
};

#seekto 0x0010;
struct memory memory[128];

#seekto 0x0870;
u8 emptyflags[16];
u8 skipflags[16];
"""

THUV3R_DUPLEX = ["", "+", "-"]
THUV3R_CHARSET = "".join([chr(ord("0") + x) for x in range(0, 10)] +
                         [" -*+"] +
                         [chr(ord("A") + x) for x in range(0, 26)] +
                         ["_/"])
@directory.register
class TYTUV3RRadio(KGUVD1PRadio):
    VENDOR = "TYT"
    MODEL = "TH-UV3R"
    BAUD_RATE = 2400
    _memsize = 2320

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_cross = True
        rf.memory_bounds = (1, 128)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone",
                                "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS"]
        rf.valid_skips = []
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_name_length = 6
        rf.valid_characters = THUV3R_CHARSET
        rf.valid_bands = [(136000000, 470000000)]
        rf.valid_tuning_steps = [5.0, 6.25, 10.0, 12.5, 25.0, 37.50,
                                 50.0, 100.0]
        rf.valid_skips = ["", "S"]
        return rf

    def sync_in(self):
        self.pipe.setTimeout(2)
        self._mmap = tyt_uv3r_download(self)
        self.process_mmap()

    def sync_out(self):
        tyt_uv3r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _decode_tone_value(self, value):
        if value == 0xFFFF:
            return "", "N", 0
        elif value & 0x8000:
            # FIXME: rev pol
            pol = value & 0x4000 and "R" or "N"
            return "DTCS", pol, int("%x" % (value & 0x0FFF))
        else:
            return "Tone", "N", int("%x" % value) / 10.0

    def _decode_tone(self, mem, _mem):
        tx_mode, tpol, tx_tone = self._decode_tone_value(_mem.tx_tone)
        rx_mode, rpol, rx_tone = self._decode_tone_value(_mem.rx_tone)

        if rx_mode == tx_mode == "":
            return

        mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        if rx_mode == tx_mode == "DTCS":
            # Break this for now until we can support this in chirp
            tx_tone = rx_tone

        if rx_mode in ["", tx_mode] and rx_tone in [0, tx_tone]:
            mem.tmode = rx_mode == "Tone" and "TSQL" or tx_mode
            if mem.tmode == "DTCS":
                mem.dtcs = tx_tone
            elif mem.tmode == "TSQL":
                mem.ctone = tx_tone
            else:
                mem.rtone = tx_tone
            return

        mem.cross_mode = "%s->%s" % (tx_mode, rx_mode)
        mem.tmode = "Cross"
        if tx_mode == "Tone":
            mem.rtone = tx_tone
        elif tx_mode == "DTCS":
            mem.dtcs = tx_tone
        if rx_mode == "Tone":
            mem.ctone = rx_tone
        elif rx_mode == "DTCS":
            mem.dtcs = rx_tone # No support for different codes yet

    def _encode_tone(self, mem, _mem):
        if mem.tmode == "":
            _mem.tx_tone = _mem.rx_tone = 0xFFFF
            return

        def _tone(val):
            return int("%i" % (val * 10), 16)
        def _dcs(val, pol):
            polmask = pol == "R" and 0xC000 or 0x8000
            return int("%i" % (val), 16) | polmask

        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            rx_mode = ""
            tx_mode = "Tone"
            tx_tone = _tone(mem.rtone)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = _tone(mem.ctone)
        elif mem.tmode == "DTCS":
            rx_tone = tx_tone = "DTCS"
            tx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->", 1)
            if tx_mode == "DTCS":
                tx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = _tone(mem.rtone)
            if rx_mode == "DTCS":
                rx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = _tone(mem.ctone)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone            

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        bit = 1 << ((number - 1) % 8)
        byte = (number - 1) / 8

        if self._memobj.emptyflags[byte] & bit:
            mem.empty = True
            return mem

        mult = _mem.is625 and 6250 or 5000
        mem.freq = _mem.freq * mult
        mem.offset = _mem.offset * 5000;
        mem.duplex = THUV3R_DUPLEX[_mem.duplex]
        mem.mode = _mem.iswide and "FM" or "NFM"
        self._decode_tone(mem, _mem)
        mem.skip = (self._memobj.skipflags[byte] & bit) and "S" or ""

        for char in _mem.name:
            try:
                c = THUV3R_CHARSET[char]
            except:
                c = ""
            mem.name += c
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        bit = 1 << ((mem.number - 1) % 8)
        byte = (mem.number - 1) / 8

        if mem.empty:
            self._memobj.emptyflags[byte] |= bit
            _mem.set_raw("\xFF" * 16)
            return

        self._memobj.emptyflags[byte] &= ~bit

        if chirp_common.is_fractional_step(mem.freq):
            mult = 6250
            _mem.is625 = True
        else:
            mult = 5000
            _mem.is625 = False
        _mem.freq = mem.freq / mult
        _mem.offset = mem.offset / 5000
        _mem.duplex = THUV3R_DUPLEX.index(mem.duplex)
        _mem.iswide = mem.mode == "FM"
        self._encode_tone(mem, _mem)

        if mem.skip:
            self._memobj.skipflags[byte] |= bit
        else:
            self._memobj.skipflags[byte] &= ~bit

        name = []
        for char in mem.name.ljust(6):
            try:
                c = THUV3R_CHARSET.index(char)
            except:
                c = THUV3R_CHARSET.index(" ")
            name.append(c)
        _mem.name = name
        print repr(_mem)

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == 2320

