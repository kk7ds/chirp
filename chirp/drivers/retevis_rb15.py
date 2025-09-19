# Copyright 2022 Jim Unroe <rock.unroe@gmail.com>
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
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct memory {
  u32 rxfreq;                                // 00-03
  u16 decQT;                                 // 04-05
  u32 txfreq;                                // 06-09
  u16 encQT;                                 // 0a-0b
  u8 lowpower:1,  // Power Level             // 0c
     unknown1:1,
     isnarrow:1,  // Bandwidth
     bcl:2,       // Busy Channel Lockout
     scan:1,      // Scan Add
     encode:1,    // Encode
     isunused:1;  // Is Unused
  u8 unknown3[3];                            // 0d-0f
};

#seekto 0x0170;
struct memory channels[99];

#seekto 0x0162;
struct {
  u8 unknown_1:1,           // 0x0162
     voice:2,               //               Voice Prompt
     beep:1,                //               Beep Switch
     unknown_2:1,
     vox:1,                 //               VOX
     autolock:1,            //               Auto Lock
     vibrate:1;             //               Vibrate Switch
  u8 squelch:4,             // 0x0163        SQ Level
     unknown_3:1,
     volume:3;              //               Volume Level
  u8 voxl:4,                // 0x0164        VOX Level
     voxd:4;                //               VOX Delay
  u8 unknown_5:1,           // 0x0165
     save:3,                //               Power Save
     calltone:4;            //               Call Tone
  u8 unknown_6:4,           // 0x0166
     roger:2,               //               Roger Tone
     backlight:2;           //               Backlight Set
  u16 tot;                  // 0x0167-0x0168 Time-out Timer
  u8 unknown_7[3];          // 0x0169-0x016B
  u8 skeyul;                // 0x016C        Side Key Up Long
  u8 skeyus;                // 0x016D        Side Key Up Short
  u8 skeydl;                // 0x016E        Side Key Down Long
  u8 skeyds;                // 0x016F        Side Key Down Short
} settings;
"""

CMD_ACK = b"\x06"

RB15_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

LIST_BACKLIGHT = ["Off", "On", "Auto"]
LIST_BCL = ["None", "Carrier", "QT/DQT Match"]
LIST_ROGER = ["Off", "Start", "End", "Start and End"]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4", "1:5"]
_STEP_LIST = [2.5, 5., 6.25, 10., 12.5, 20., 25., 50.]
LIST_VOICE = ["Off", "Chinese", "English"]
LIST_VOXD = ["0.0", "0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "3.5", "4.0",
             "4.5", "5.0S"]

SKEY_CHOICES = ["None", "Scan", "Monitor", "VOX On/Off",
                "Local Alarm", "Remote Alarm", "Backlight On/Off", "Call Tone"]
SKEY_VALUES = [0x00, 0x01, 0x03, 0x04, 0x09, 0x0A, 0x13, 0x14]

TOT_CHOICES = ["Off", "15", "30", "45", "60", "75", "90", "105", "120",
               "135", "150", "165", "180", "195", "210", "225", "240",
               "255", "270", "285", "300", "315", "330", "345", "360",
               "375", "390", "405", "420", "435", "450", "465", "480",
               "495", "510", "525", "540", "555", "570", "585", "600"
               ]
TOT_VALUES = [0x00, 0x0F, 0x1E, 0x2D, 0x3C, 0x4B, 0x5A, 0x69, 0x78,
              0x87, 0x96, 0xA5, 0xB4, 0xC3, 0xD2, 0xE1, 0xF0,
              0xFF, 0x10E, 0x11D, 0x12C, 0x13B, 0x14A, 0x159, 0x168,
              0x177, 0x186, 0x195, 0x1A4, 0x1B3, 0x1C2, 0x1D1, 0x1E0,
              0x1EF, 0x1FE, 0x20D, 0x21C, 0x22B, 0x23A, 0x249, 0x258
              ]


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def tone2short(t):
    """Convert a string tone or DCS to an encoded u16
    """
    tone = str(t)
    if tone == "----":
        u16tone = 0x0000
    elif tone[0] == 'D':  # This is a DCS code
        c = tone[1: -1]
        code = int(c, 8)
        if tone[-1] == 'I':
            code |= 0x4000
        u16tone = code | 0x8000
    else:  # This is an analog CTCSS
        u16tone = int(tone[0:-2]+tone[-1]) & 0xffff  # strip the '.'
    return u16tone


def short2tone(tone):
    """ Map a binary CTCSS/DCS to a string name for the tone
    """
    if tone == 0xC000 or tone == 0xffff:
        ret = "----"
    else:
        code = tone & 0x3fff
        if tone & 0x4000:      # This is a DCS
            ret = "D%0.3oN" % code
        elif tone & 0x8000:  # This is an inverse code
            ret = "D%0.3oI" % code
        else:   # Just plain old analog CTCSS
            ret = "%4.1f" % (code / 10.0)
    return ret


def _rb15_enter_programming_mode(radio):
    serial = radio.pipe

    # lengthen the timeout here as these radios are resetting due to timeout
    radio.pipe.timeout = 0.75

    exito = False
    for i in range(0, 5):
        serial.write(radio.magic)
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # return timeout to default value
    radio.pipe.timeout = 0.25

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)


def _rb15_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"21" + b"\x05\xEE" + b"V")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rb15_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">BH", ord(b'R'), block_addr)

    ccs = bytes([_checksum(cmd)])

    expectedresponse = b"R" + cmd[1:]

    cmd = cmd + ccs

    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(3 + block_size + 1)

        cs = bytes([_checksum(response[:-1])])

        if response[:3] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        chunk = response[3:]

        if chunk[-1:] != cs:
            raise Exception("Block failed checksum!")

        block_data = chunk[:-1]
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _rb15_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">BH", ord(b'W'), block_addr)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    cs = bytes([_checksum(cmd + data)])
    data += cs

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _rb15_enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0x0000, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _rb15_read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _rb15_exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rb15_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            _rb15_write_block(radio, addr, radio.BLOCK_SIZE)

    _rb15_exit_programming_mode(radio)


class RB15RadioBase(chirp_common.CloneModeRadio):
    """RETEVIS RB15 BASE"""
    VENDOR = "Retevis"
    BAUD_RATE = 9600

    BLOCK_SIZE = 0x10
    magic = b"21" + b"\x05\x10" + b"x"

    VALID_BANDS = [(400000000, 480000000)]

    _ranges = [
               (0x0150, 0x07A0),
              ]
    _memsize = 0x07A0

    _frs = _pmr = False

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_dtcs_codes = RB15_DTCS
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = _STEP_LIST
        rf.valid_bands = self.VALID_BANDS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        """Decode both the encode and decode CTSS/DCS codes from
        the memory channel and stuff them into the UI
        memory channel row.
        """
        txtone = short2tone(_mem.encQT)
        rxtone = short2tone(_mem.decQT)
        pt = "N"
        pr = "N"

        if txtone == "----":
            txmode = ""
        elif txtone[0] == "D":
            mem.dtcs = int(txtone[1:4])
            if txtone[4] == "I":
                pt = "R"
            txmode = "DTCS"
        else:
            mem.rtone = float(txtone)
            txmode = "Tone"

        if rxtone == "----":
            rxmode = ""
        elif rxtone[0] == "D":
            mem.rx_dtcs = int(rxtone[1:4])
            if rxtone[4] == "I":
                pr = "R"
            rxmode = "DTCS"
        else:
            mem.ctone = float(rxtone)
            rxmode = "Tone"

        if txmode == "Tone" and len(rxmode) == 0:
            mem.tmode = "Tone"
        elif (txmode == rxmode and txmode == "Tone" and
              mem.rtone == mem.ctone):
            mem.tmode = "TSQL"
        elif (txmode == rxmode and txmode == "DTCS" and
              mem.dtcs == mem.rx_dtcs):
            mem.tmode = "DTCS"
        elif (len(rxmode) + len(txmode)) > 0:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = pt + pr

        LOG.debug("_get_tone: Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.encQT, rxmode, _mem.decQT))

    def _set_tone(self, mem, _mem):
        """Update the memory channel block CTCC/DCS tones
        from the UI fields
        """
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) | 0x4000
            if pol == "R":
                val = int("%i" % code, 8) | 0x8000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0xC000

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            txtone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10)

        _mem.decQT = rxtone
        _mem.encQT = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.encQT, rx_mode, _mem.decQT))

    def get_memory(self, number):
        mem = chirp_common.Memory()
        _mem = self._memobj.channels[number - 1]
        mem.number = number

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.get_raw() == (b"\xFF" * 16):
            LOG.debug("Initializing empty memory")
            _mem.set_raw(b"\x00" * 16)

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        mem.mode = _mem.isnarrow and "NFM" or "FM"

        self._get_tone(_mem, mem)

        mem.power = self.POWER_LEVELS[_mem.lowpower]

        if not _mem.scan:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        if _mem.bcl > 0x02:
            val = 0
        else:
            val = _mem.bcl
        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueList(
                              LIST_BCL, current_index=val))
        mem.extra.append(rs)

        rs = RadioSetting("encode", "Encode",
                          RadioSettingValueBoolean(_mem.encode))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
        _mem = self._memobj.channels[mem.number - 1]

        # if empty memory
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        _mem.isunused = False
        _mem.unknown1 = False

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.scan = mem.skip != "S"
        _mem.isnarrow = mem.mode == "NFM"

        self._set_tone(mem, _mem)

        _mem.lowpower = mem.power == self.POWER_LEVELS[1]

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        sidekey = RadioSettingGroup("sidekey", "Side Key Settings")
        voxset = RadioSettingGroup("vox", "VOX Settings")
        top = RadioSettings(basic, sidekey, voxset)

        voice = RadioSetting("voice", "Language", RadioSettingValueList(
                             LIST_VOICE, current_index=_settings.voice))
        basic.append(voice)

        beep = RadioSetting("beep", "Key Beep",
                            RadioSettingValueBoolean(_settings.beep))
        basic.append(beep)

        volume = RadioSetting("volume", "Volume Level",
                              RadioSettingValueInteger(
                                  0, 7, _settings.volume))
        basic.append(volume)

        save = RadioSetting("save", "Battery Save",
                            RadioSettingValueList(
                                LIST_SAVE, current_index=_settings.save))
        basic.append(save)

        backlight = RadioSetting("backlight", "Backlight",
                                 RadioSettingValueList(
                                     LIST_BACKLIGHT,
                                     current_index=_settings.backlight))
        basic.append(backlight)

        vibrate = RadioSetting("vibrate", "Vibrate",
                               RadioSettingValueBoolean(_settings.vibrate))
        basic.append(vibrate)

        autolock = RadioSetting("autolock", "Auto Lock",
                                RadioSettingValueBoolean(_settings.autolock))
        basic.append(autolock)

        calltone = RadioSetting("calltone", "Call Tone",
                                RadioSettingValueInteger(
                                    1, 10, _settings.calltone))
        basic.append(calltone)

        roger = RadioSetting("roger", "Roger Tone",
                             RadioSettingValueList(
                                 LIST_ROGER, current_index=_settings.roger))
        basic.append(roger)

        squelch = RadioSetting("squelch", "Squelch Level",
                               RadioSettingValueInteger(
                                   0, 10, _settings.squelch))
        basic.append(squelch)

        def apply_tot_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(
                      setting.value) + " from list")
            val = str(setting.value)
            index = TOT_CHOICES.index(val)
            val = TOT_VALUES[index]
            obj.set_value(val)

        if _settings.tot in TOT_VALUES:
            idx = TOT_VALUES.index(_settings.tot)
        else:
            idx = TOT_VALUES.index(0x78)
        rs = RadioSettingValueList(TOT_CHOICES, current_index=idx)
        rset = RadioSetting("tot", "Time-out Timer", rs)
        rset.set_apply_callback(apply_tot_listvalue, _settings.tot)
        basic.append(rset)

        # Side Key Settings
        def apply_skey_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(
                      setting.value) + " from list")
            val = str(setting.value)
            index = SKEY_CHOICES.index(val)
            val = SKEY_VALUES[index]
            obj.set_value(val)

        # Side Key (Upper) - Short Press
        if _settings.skeyus in SKEY_VALUES:
            idx = SKEY_VALUES.index(_settings.skeyus)
        else:
            idx = SKEY_VALUES.index(0x01)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skeyus", "Side Key(upper) - Short Press", rs)
        rset.set_apply_callback(apply_skey_listvalue, _settings.skeyus)
        sidekey.append(rset)

        # Side Key (Upper) - Long Press
        if _settings.skeyul in SKEY_VALUES:
            idx = SKEY_VALUES.index(_settings.skeyul)
        else:
            idx = SKEY_VALUES.index(0x04)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skeyul", "Side Key(upper) - Long Press", rs)
        rset.set_apply_callback(apply_skey_listvalue, _settings.skeyul)
        sidekey.append(rset)

        # Side Key (Lower) - Short Press
        if _settings.skeyds in SKEY_VALUES:
            idx = SKEY_VALUES.index(_settings.skeyds)
        else:
            idx = SKEY_VALUES.index(0x03)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skeyds", "Side Key(lower) - Short Press", rs)
        rset.set_apply_callback(apply_skey_listvalue, _settings.skeyds)
        sidekey.append(rset)

        # Side Key (Lower) - Long Press
        if _settings.skeyul in SKEY_VALUES:
            idx = SKEY_VALUES.index(_settings.skeydl)
        else:
            idx = SKEY_VALUES.index(0x14)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skeydl", "Side Key(lower) - Long Press", rs)
        rset.set_apply_callback(apply_skey_listvalue, _settings.skeydl)
        sidekey.append(rset)

        # VOX Settings
        vox = RadioSetting("vox", "VOX",
                           RadioSettingValueBoolean(_settings.vox))
        voxset.append(vox)

        voxl = RadioSetting("voxl", "VOX Level",
                            RadioSettingValueInteger(
                                0, 10, _settings.voxl))
        voxset.append(voxl)

        voxd = RadioSetting("voxd", "VOX Delay (seconde)",
                            RadioSettingValueList(
                                LIST_VOXD, current_index=_settings.voxd))
        voxset.append(voxd)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB15Radio(RB15RadioBase):
    """RETEVIS RB15"""
    VENDOR = "Retevis"
    MODEL = "RB15"

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _ranges = [
               (0x0150, 0x07A0),
              ]
    _memsize = 0x07A0

    _upper = 99
    _frs = False  # sold as FRS radio but supports full band TX/RX


@directory.register
class RB615RadioBase(RB15RadioBase):
    """RETEVIS RB615"""
    VENDOR = "Retevis"
    MODEL = "RB615"

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _ranges = [
               (0x0150, 0x07A0),
              ]
    _memsize = 0x07A0

    _upper = 99
    _pmr = False  # sold as PMR radio but supports full band TX/RX
