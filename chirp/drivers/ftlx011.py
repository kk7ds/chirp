# Copyright 2019 Pavel Milanes, CO7WT <pavelmc@gmail.com>
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

import logging
import time

from chirp import chirp_common, directory, memmap, errors, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettings

LOG = logging.getLogger(__name__)

# SAMPLE MEM DUMP as sent from the radios

# FTL-1011
# 0x000000  52 f0 16 90 04 08 38 c0  00 00 00 01 00 00 00 ff  |R.....8.........|
# 0x000010  20 f1 00 20 00 00 00 20  04 47 25 04 47 25 00 00  | .. ... .G%.G%..|

# FTL-2011
# 0x000000: 50 90 21 40 04 80 fc 40  00 00 00 01 00 00 00 ff  |P.!@...@........|
# 0x000010: 20 f1 00 0b 00 00 00 0b  14 51 70 14 45 70 00 00  |.........Qp.Ep..|


MEM_FORMAT = """
u8 rid;                 // Radio Identification

struct {
u8 scan_time:4,         // Scan timer per channel: 0-15 (5-80msec in 5msec steps)
   unknownA:4;
bbcd if[2];             // Radio internal IF, depending on model (16.90, 21.40, 45.10, 47.90)
u8 chcount;             // how many channels are programmed
u8 scan_resume:1,           // Scan sesume: 0 = 0.5 seconds, 1 = Carrier
   priority_during_scan:1,  // Priority during scan: 0 = enabled, 1 = disabled
   priority_speed:1,        // Priority speed: 0 = slow, 1 = fast
   monitor:1,               // Monitor: 0 = enabled, 1 = disabled
   off_hook:1,              // Off hook: 0 = enabled, 1 = disabled
   home_channel:1,          // Home Channel: 0 = Scan Start ch, 1 = Priority 1ch
   talk_back:1,             // Talk Back: 0 = enabled, 1 = disabled
   tx_carrier_delay:1;      // TX carrier delay: 1 = enabled, 0 = disabled
u8 tot:4,                   // Time out timer: 16 values (0.0-7.5 in 0.5s step)
   tot_resume:2,            // Time out timer resume: 3, 2, 1, 0 => 0s, 6s, 20s, 60s
   unknownB:2;
u8 a_key:2,                 // A key function: resume: 0-3: Talkaround, High/Low, Call, Accessory
   unknownC:6;
u8 pch1;                    // Priority channel 1
u8 pch2;                    // Priority channel 1
} settings;

#seekto 0x010;
struct {
  u8 notx:1,            // 0 = Tx possible,  1 = Tx disabled
     empty:1,           // 0 = channel enabled, 1 = channed empty
     tot:1,             // 0 = tot disabled, 1 = tot enabled
     power:1,           // 0 = high, 1 = low
     bclo_cw:1,         // 0 = disabled, 1 = Busy Channel Lock out by carrier
     bclo_tone:1,       // 0 = disabled, 1 = Busy Channel Lock out by tone (set rx tone)
     skip:1,            // 0 = scan enabled, 1 = skip on scanning
     unknownA0:1;
  u8 chname;
  u8 rx_tone[2];      // empty value is \x00\x0B / disabled is \x00\x00
  u8 unknown4;
  u8 unknown5;
  u8 tx_tone[2];      // empty value is \x00\x0B / disabled is \x00\x00
  bbcd rx_freq[3];      // RX freq
  bbcd tx_freq[3];      // TX freq
  u8 unknownA[2];
} memory[24];

//#seekto 0x0190;
char filename[11];

#seekto 0x19C;
u8 checksum;
"""

MEM_SIZE = 0x019C
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=50),
                chirp_common.PowerLevel("Low", watts=5)]
DTCS_CODES = chirp_common.DTCS_CODES
SKIP_VALUES = ["", "S"]
LIST_BCL = ["OFF", "Carrier", "Tone"]
LIST_SCAN_RESUME = ["0.5 seconds", "Carrier drop"]
LIST_SCAN_TIME = ["%s ms" % x for x in range(5, 85, 5)]
LIST_SCAN_P_SPEED = ["Slow", "Fast"]
LIST_HOME_CHANNEL = ["Scan Start ch", "Priority 1ch"]
LIST_TOT = ["Off"] + ["%.1f s" % (x/10.0) for x in range(5, 80, 5)]
# 3, 2, 1, 0 => 0 s, 6 s, 20 s, 60 s
LIST_TOT_RESUME = ["60 s", "20 s", "6 s", "0 s"]
LIST_A_KEY = ["Talkaround", "High/Low", "Call", "Accessory"]
LIST_PCH = []  # dynamic, as depends on channel list.
# make a copy of the tones, is not funny to work with this directly
TONES = list(chirp_common.TONES)
# this old radios has not the full tone ranges in CST
invalid_tones = (
    69.3,
    159.8,
    165.5,
    171.3,
    177.3,
    183.5,
    189.9,
    196.6,
    199.5,
    206.5,
    229.1,
    245.1)

# remove invalid tones
for tone in invalid_tones:
    try:
        TONES.remove(tone)
    except:
        pass


def _set_serial(radio):
    """Set the serial protocol settings"""
    radio.pipe.timeout = 10
    radio.pipe.parity = "N"
    radio.pipe.baudrate = 9600


def _checksum(data):
    """the radio block checksum algorithm"""
    cs = 0
    for byte in data:
        cs += ord(byte)

    return cs % 256


def _update_cs(radio):
    """Update the checksum on the mmap"""
    payload = str(radio.get_mmap())[:-1]
    cs = _checksum(payload)
    radio._mmap[MEM_SIZE - 1] = cs


def _do_download(radio):
    """ The download function """
    # Get the whole 413 bytes (0x019D) bytes one at a time with plenty of time
    # to get to the user's pace

    # set serial discipline
    _set_serial(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = " Press A to clone. "
    radio.status_fn(status)

    data = ""
    for i in range(0, MEM_SIZE):
        a = radio.pipe.read(1)
        if len(a) == 0:
            # error, no received data
            if len(data) != 0:
                # received some data, not the complete stream
                msg = "Just %02i bytes of the %02i received, try again." % \
                    (len(data), MEM_SIZE)
            else:
                # timeout, please retry
                msg = "No data received, try again."

            raise errors.RadioError(msg)

        data += a
        # UI Update
        status.cur = len(data)
        radio.status_fn(status)

    if len(data) != MEM_SIZE:
        msg = "Incomplete data, we need %02i but got %02i bytes." % \
            (MEM_SIZE, len(data))
        raise errors.RadioError(msg)

    if ord(data[-1]) != _checksum(data[:-1]):
        msg = "Bad checksum, please try again."
        raise errors.RadioError(msg)

    return data


def _do_upload(radio):
    """The upload function"""
    # set serial discipline
    _set_serial(radio)

    # UI progress
    status = chirp_common.Status()

    # 10 seconds timeout
    status.cur = 0
    status.max = 100
    status.msg = " Quick, press MON on the radio to start. "
    radio.status_fn(status)

    for byte in range(0, 100):
        status.cur = byte
        radio.status_fn(status)
        time.sleep(0.1)

    # real upload if user don't cancel the timeout
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = " Cloning to radio... "
    radio.status_fn(status)

    # send data
    data = str(radio.get_mmap())

    # this radio has a trick, the EEPROM is an ancient SPI one, so it needs
    # some time to write, so we send every byte and then allow
    # a 0.01 seg to complete the write from the MCU to the SPI EEPROM
    c = 0
    for byte in data:
        radio.pipe.write(byte)
        time.sleep(0.01)

        # UI Update
        status.cur = c
        radio.status_fn(status)

        # counter
        c = c + 1


def _model_match(cls, data):
    """Use a experimental guess to determine if the radio you just
    downloaded or the img you opened is for this model"""

    # It's hard to tell when this radio is really this radio.
    # I use the first byte, that appears to be the ID and the IF settings

    radiod = [data[0], data[2:4]]
    return cls.finger == radiod


def bcd_to_int(data):
    """Convert an array of bcdDataElement like \x12
    into an int like 12"""
    value = 0
    a = (data & 0xF0) >> 4
    b = data & 0x0F
    value = (a * 10) + b
    return value


def int_to_bcd(data):
    """Convert a int like 94 to 0x94"""
    data, lsb = divmod(data, 10)
    data, msb = divmod(data, 10)
    res = (msb << 4) + lsb
    return res


class ftlx011(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """Vertex FTL1011/2011/7011 4/8/12/24 channels"""
    VENDOR = "Vertex Standard"
    NEEDS_COMPAT_SERIAL = True
    _memsize = MEM_SIZE
    _upper = 0
    _range = []
    finger = []  # two elements rid & IF

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This is a experimental driver, use it on your own risk.\n'
             '\n'
             'This driver is just for the 4/12/24 channels variants of '
             'these radios, 99 channel variants are not supported yet.\n'
             '\n'
             'The 99 channel versions appears to use another mem layout.\n'
             )
        rp.pre_download = _(
            "Please follow this steps carefully:\n"
            "1 - Turn on your radio\n"
            "2 - Connect the interface cable to your radio.\n"
            "3 - Click the button on this window to start download\n"
            "    (Radio will beep and led will flash)\n"
            "4 - Then press the \"A\" button in your radio to start"
            " cloning.\n"
            "    (At the end radio will beep)\n")
        rp.pre_upload = _(
            "Please follow this steps carefully:\n"
            "1 - Turn on your radio\n"
            "2 - Connect the interface cable to your radio\n"
            "3 - Click the button on this window to start download\n"
            "    (you may see another dialog, click ok)\n"
            "4 - Radio will beep and led will flash\n"
            "5 - You will get a 10 seconds timeout to press \"MON\" before\n"
            "    data upload start\n"
            "6 - If all goes right radio will beep at end.\n"
            "After cloning remove the cable and power cycle your radio to\n"
            "get into normal mode.\n")
        return rp

    def get_features(self):
        """Return information about this radio's features"""
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->DTCS",
            "DTCS->",
            "->DTCS"]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_skips = SKIP_VALUES
        rf.valid_modes = ["FM"]
        rf.valid_power_levels = POWER_LEVELS
        # rf.valid_tuning_steps = [5.0]
        rf.valid_bands = [self._range]
        rf.memory_bounds = (1, self._upper)
        return rf

    def sync_in(self):
        """Do a download of the radio eeprom"""
        try:
            data = _do_download(self)
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio:\n %s" % e)

        # match model
        if _model_match(self, data) is False:
            raise errors.RadioError("Incorrect radio model")

        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

        # set the channel count from the radio eeprom
        self._upper = int(ord(data[4]))

    def sync_out(self):
        """Do an upload to the radio eeprom"""
        # update checksum
        _update_cs(self)

        # sanity check, match model
        data = str(self.get_mmap())
        if len(data) != MEM_SIZE:
            raise errors.RadioError("Wrong radio image? Size miss match.")

        if _model_match(self, data) is False:
            raise errors.RadioError("Wrong image? Fingerprint miss match")

        try:
            _do_upload(self)
        except Exception as e:
            msg = "Failed to communicate with radio:\n%s" % e
            raise errors.RadioError(msg)

    def process_mmap(self):
        """Process the memory object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        """Return a raw representation of the memory object"""
        return repr(self._memobj.memory[number])

    def _decode_tone(self, mem, rx=True):
        """Parse the tone data to decode from mem tones are encoded like this
        CTCS: mapped [0x80...0xa5] = [67.0...250.3]
        DTCS: mixed  [0x88, 0x23] last is BCD and first is the 100 power - 88

        It return: ((''|DTCS|Tone), Value (None|###), None)"""
        mode = ""
        tone = None

        # get the tone depending of rx or tx
        if rx:
            t = mem.rx_tone
        else:
            t = mem.tx_tone

        tMSB = t[0]
        tLSB = t[1]

        # no tone at all
        if (tMSB == 0 and tLSB < 128):
            return ('', None, None)

        # extract the tone info
        if tMSB == 0x00:
            # CTCS
            mode = "Tone"
            try:
                tone = TONES[tLSB - 128]
            except IndexError:
                LOG.debug("Error decoding a CTCS tone")
                pass
        else:
            # DTCS
            mode = "DTCS"
            try:
                tone = ((tMSB - 0x88) * 100) + bcd_to_int(tLSB)
            except IndexError:
                LOG.debug("Error decoding a DTCS tone")
                pass

        return (mode, tone, None)

    def _encode_tone(self, mem, mode, value, pol, rx=True):
        """Parse the tone data to encode from UI to mem
        CTCS: mapped [0x80...0xa5] = [67.0...250.3]
        DTCS: mixed  [0x88, 0x23] last is BCD and first is the 100 power - 88
        """

        # array to pass
        tone = [0x00, 0x00]

        # which mod
        if mode == "DTCS":
            tone[0] = int(value / 100) + 0x88
            tone[1] = int_to_bcd(value % 100)

        if mode == "Tone":
            # CTCS
            tone[1] = TONES.index(value) + 128

        # set it
        if rx:
            mem.rx_tone = tone
        else:
            mem.tx_tone = tone

    def get_memory(self, number):
        """Extract a memory object from the memory map"""
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[number - 1]
        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()
        # number
        mem.number = number

        # empty
        if bool(_mem.empty) is True:
            mem.empty = True
            return mem

        # rx freq
        mem.freq = int(_mem.rx_freq) * 1000

        # power
        mem.power = POWER_LEVELS[int(_mem.power)]

        # checking if tx freq is disabled
        if bool(_mem.notx) is True:
            mem.duplex = "off"
            mem.offset = 0
        else:
            tx = int(_mem.tx_freq) * 1000
            if tx == mem.freq:
                mem.offset = 0
                mem.duplex = ""
            else:
                mem.duplex = mem.freq > tx and "-" or "+"
                mem.offset = abs(tx - mem.freq)

        # skip
        mem.skip = SKIP_VALUES[_mem.skip]

        # tone data
        rxtone = txtone = None
        rxtone = self._decode_tone(_mem)
        txtone = self._decode_tone(_mem, False)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # this radio has a primitive mode to show the channel number on a 7-segment
        # two digit LCD, we will use channel number
        # we will use a trick to show the numbers < 10 with a space not a zero in front
        chname = int_to_bcd(mem.number)
        if mem.number < 10:
            # convert to F# as BCD
            chname = mem.number + 240

        _mem.chname = chname

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        # bcl preparations: ["OFF", "Carrier", "Tone"]
        bcls = 0
        if _mem.bclo_cw:
            bcls = 1
        if _mem.bclo_tone:
            bcls = 2

        bcl = RadioSetting("bclo", "Busy channel lockout",
                           RadioSettingValueList(LIST_BCL,
                                                 current_index=bcls))
        mem.extra.append(bcl)

        # return mem
        return mem

    def set_memory(self, mem):
        """Store details about a high-level memory to the memory map
        This is called when a user edits a memory in the UI"""
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        # Empty memory
        _mem.empty = mem.empty
        if mem.empty:
            _mem.rx_freq = _mem.tx_freq = 0
            return

        # freq rx
        _mem.rx_freq = mem.freq / 1000

        # power, # default power level is high
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        # freq tx
        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 1000
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 1000
        elif mem.duplex == "off":
            _mem.notx = 1
            _mem.tx_freq = _mem.rx_freq
        else:
            _mem.tx_freq = mem.freq / 1000

        # scan add property
        _mem.skip = SKIP_VALUES.index(mem.skip)

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)

        # validate tone data from here
        if rxmode == "Tone" and rxtone in invalid_tones:
            msg = "The tone %s Hz is not valid for this radio" % rxtone
            raise errors.UnsupportedToneError(msg)

        if txmode == "Tone" and txtone in invalid_tones:
            msg = "The tone %s Hz is not valid for this radio" % txtone
            raise errors.UnsupportedToneError(msg)

        if rxmode == "DTCS" and rxtone not in DTCS_CODES:
            msg = "The digital tone %s is not valid for this radio" % rxtone
            raise errors.UnsupportedToneError(msg)

        if txmode == "DTCS" and txtone not in DTCS_CODES:
            msg = "The digital tone %s is not valid for this radio" % txtone
            raise errors.UnsupportedToneError(msg)

        self._encode_tone(_mem, rxmode, rxtone, rxpol)
        self._encode_tone(_mem, txmode, txtone, txpol, False)

        # this radio has a primitive mode to show the channel number on a 7-segment
        # two digit LCD, we will use channel number
        # we will use a trick to show the numbers < 10 with a space not a zero in front
        chname = int_to_bcd(mem.number)
        if mem.number < 10:
            # convert to F# as BCD
            chname = mem.number + 240

        def _zero_settings():
            _mem.bclo_cw = 0
            _mem.bclo_tone = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            LOG.debug("Extra-Setting supplied. Setting them.")
            # Zero them all first so any not provided by model don't
            # stay set
            _zero_settings()
            for setting in mem.extra:
                if setting.get_name() == "bclo":
                    sw = LIST_BCL.index(str(setting.value))
                    if sw == 0:
                        # empty
                        _zero_settings()
                    if sw == 1:
                        # carrier
                        _mem.bclo_cw = 1
                    if sw == 2:
                        # tone
                        _mem.bclo_tone = 1
                        # activate the tone
                        _mem.rx_tone = [0x00, 0x80]
        else:
            # reset extra settings
            _zero_settings()

        _mem.chname = chname

        return mem

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # ## Basic Settings
        scanr = RadioSetting("scan_resume", "Scan resume by",
                             RadioSettingValueList(
                              LIST_SCAN_RESUME, current_index=_settings.scan_resume))
        basic.append(scanr)

        scant = RadioSetting("scan_time", "Scan time per channel",
                             RadioSettingValueList(
                              LIST_SCAN_TIME, current_index=_settings.scan_time))
        basic.append(scant)

        LIST_PCH = ["%s" % x for x in range(1, _settings.chcount + 1)]
        pch1 = RadioSetting("pch1", "Priority channel 1",
                            RadioSettingValueList(
                                 LIST_PCH, current_index=_settings.pch1))
        basic.append(pch1)

        pch2 = RadioSetting("pch2", "Priority channel 2",
                            RadioSettingValueList(
                                LIST_PCH, current_index=_settings.pch2))
        basic.append(pch2)

        scanp = RadioSetting("priority_during_scan", "Disable priority during scan",
                             RadioSettingValueBoolean(_settings.priority_during_scan))
        basic.append(scanp)

        scanps = RadioSetting("priority_speed", "Priority scan speed",
                              RadioSettingValueList(
                                LIST_SCAN_P_SPEED, current_index=_settings.priority_speed))
        basic.append(scanps)

        oh = RadioSetting("off_hook", "Off Hook",  # inverted
                          RadioSettingValueBoolean(not _settings.off_hook))
        basic.append(oh)

        tb = RadioSetting("talk_back", "Talk Back",  # inverted
                          RadioSettingValueBoolean(not _settings.talk_back))
        basic.append(tb)

        tot = RadioSetting("tot", "Time out timer",
                           RadioSettingValueList(
                                 LIST_TOT, current_index=_settings.tot))
        basic.append(tot)

        totr = RadioSetting("tot_resume", "Time out timer resume guard",
                            RadioSettingValueList(
                               LIST_TOT_RESUME, current_index=_settings.tot_resume))
        basic.append(totr)

        ak = RadioSetting("a_key", "A Key function",
                          RadioSettingValueList(
                                LIST_A_KEY, current_index=_settings.a_key))
        basic.append(ak)

        monitor = RadioSetting("monitor", "Monitor",  # inverted
                               RadioSettingValueBoolean(not _settings.monitor))
        basic.append(monitor)

        homec = RadioSetting("home_channel", "Home Channel is",
                             RadioSettingValueList(
                                 LIST_HOME_CHANNEL, current_index=_settings.home_channel))
        basic.append(homec)

        txd = RadioSetting("tx_carrier_delay", "Talk Back",
                           RadioSettingValueBoolean(_settings.tx_carrier_delay))
        basic.append(txd)

        return group

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

                obj = getattr(_settings, name)
                if name in ["off_hook", "talk_back", "monitor"]:
                    setattr(_settings, name, not value)
                else:
                    setattr(_settings, name, value)

                LOG.debug("Setting %s: %s" % (name, value))
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == cls._memsize:
            match_size = True

        # testing the firmware fingerprint, this experimental
        try:
            match_model = _model_match(cls, filedata)
        except Exception:
            match_model = False

        return match_size and match_model


@directory.register
class ftl1011(ftlx011):
    """Vertex FTL-1011"""
    MODEL = "FTL-1011"
    _memsize = MEM_SIZE
    _upper = 4
    _range = [44000000, 56000000]
    finger = ["\x52", "\x16\x90"]


@directory.register
class ftl2011(ftlx011):
    """Vertex FTL-2011"""
    MODEL = "FTL-2011"
    _memsize = MEM_SIZE
    _upper = 24
    _range = [134000000, 174000000]
    finger = ["\x50", "\x21\x40"]


@directory.register
class ftl7011(ftlx011):
    """Vertex FTL-7011"""
    MODEL = "FTL-7011"
    _memsize = MEM_SIZE
    _upper = 24
    _range = [400000000, 512000000]
    finger = ["\x54", "\x47\x90"]


@directory.register
class ftl8011(ftlx011):
    """Vertex FTL-8011"""
    MODEL = "FTL-8011"
    _memsize = MEM_SIZE
    _upper = 24
    _range = [400000000, 512000000]
    finger = ["\x5c", "\x45\x10"]
