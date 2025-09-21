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
    RadioSettingValueBoolean, RadioSettingValueFloat, \
    RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  u8 range174_180;  // 174-180 MHz
  u8 range180_190;  // 180-190 MHz
  u8 range190_200;  // 190-200 MHz
  u8 range200_210;  // 200-210 MHz
  u8 range210_220;  // 210-220 MHz
  u8 range220_230;  // 220-230 MHz
  u8 range230_240;  // 230-240 MHz
  u8 range240_250;  // 240-250 MHz
  u8 range250_260;  // 240-250 MHz
  u8 range260_270;  // 260-270 MHz
  u8 range270_280;  // 270-280 MHz
  u8 range280_290;  // 280-290 MHz
  u8 range290_300;  // 290-300 MHz
  u8 range300_310;  // 300-310 MHz
  u8 range310_320;  // 310-320 MHz
  u8 range320_330;  // 320-330 MHz
  u8 range330_340;  // 330-340 MHz
  u8 range340_350;  // 340-350 MHz
  u8 range350_360;  // 350-360 MHz
  u8 range360_370;  // 360-370 MHz
  u8 range370_380;  // 370-380 MHz
  u8 range380_390;  // 380-390 MHz
  u8 range390_400;  // 290-400 MHz
  u8 range520_530;  // 520-530 MHz
  u8 range530_540;  // 530-540 MHz
  u8 range540_550;  // 540-550 MHz
  u8 range550_560;  // 550-560 MHz
  u8 range560_570;  // 560-570 MHz
  u8 range570_580;  // 570-580 MHz
  u8 range580_590;  // 580-590 MHz
  u8 range590_600;  // 590-600 MHz
  u8 range600_610;  // 600-610 MHz
  u8 range610_620;  // 610-620 MHz
  u8 range620_630;  // 620-630 MHz
  u8 range630_640;  // 630-640 MHz
  u8 range640_650;  // 640-650 MHz
  u8 range650_660;  // 650-660 MHz
} txallow;

#seekto 0x0039;
struct {
  u8 display_timer;         // 0x0039        Display Timer
  u8 led_timer;             // 0x003A        LED Timer
  u8 auto_lock;             // 0x003B        Auto Lock
  u8 pfkey1short;           // 0x003C        FS1 Short
  u8 pfkey1long;            // 0x003D        FS1 Long
  u8 pfkey2short;           // 0x003E        FS2 Short
  u8 pfkey2long;            // 0x003F        FS2 Long
  u8 unknown_0;             // 0x0040
  u8 voice:2,               // 0x0041        Voice Prompt
     beep:1,                //               Beep Switch
     roger:2,               //               Roger Tone
     save:3;                //               Power Save
  u8 dispmode:1,            // 0x0042        Display Mode
     dstandby:1,            //               Dual Standby
     unknown_1:1,
     standby:1,             //               Radio Standby
     squelch:4;             //               Squelch Level
  u8 vox_level:4,           // 0x0043        VOX Level
     vox_delay:4;           //               VOX Delay
  u8 brightness:2,          // 0x0044        Screen Light
     unknown_2:1,
     alarm:1,               //               Alarm
     scramble:4;            //               Scramble
  u8 screen:1,              // 0x0045        Screen On-off
     led:1,                 //               LED On-off
     key_lock:1,            //               Key Lock
     radio:1,               //               Radio On-off
     compander:1,           //               Compander
     rp:1,                  //               Offset
     freq_lock:1,           //               Freq Lock
     vox:1;                 //               VOX On-off
  u8 unknown_4:4,           // 0x0046
     txpri:1,               //               TX PRI
     unknown_5:1,
     tail_tone:2;           //               Tail Tone
  ul16 fmcur;               // 0x0047        Radio Freq
  u8 unknown_49;            // 0x0049
  u8 unknown_4A;            // 0x004A
  u8 unknown_4B;            // 0x004B
  u8 unknown_4C;            // 0x004C
  u8 dsrangea;              // 0x004D        Dual Standby Range A
  u8 dsrangeb;              // 0x004E        Dual Standby Range B
  u8 tot;                   // 0x004F
} settings;

struct memory {
  ul32 rxfreq;                               // 00-03
  ul16 rx_tone;   // PL/DPL Decode           // 04-05
  ul32 txfreq;                               // 06-09
  ul16 tx_tone;   // PL/DPL Encode           // 0a-0b
  u8 lowpower:1,  // Power Level             // 0c
     isnarrow:1,  // Bandwidth
     unknown1:1,
     unknown2:3,
     bcl:1,       // Busy Channel Lockout
     scan:1;      // Scan Add
  u8 unknown3[3];                            // 0d-0f
};

// #seekto 0x0050;
struct memory channels[128];

"""

CMD_ACK = b"\x06"

RB15_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

_STEP_LIST = [0.25, 1.25, 2.5, 5., 6.25, 10., 12.5, 25., 50., 100.]

LIST_ALARM = ["Local", "Remote"]
LIST_BRIGHT = ["Low", "Middle", "High"]
LIST_DISPM = ["Frequency", "Channel Number"]
LIST_ROGER = ["Off", "Start", "End", "Start and End"]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4", "1:5"]
LIST_SCRAMBLE = ["Off"] + ["%s" % x for x in range(1, 9)]
LIST_SKEY = ["None", "Monitor", "Local Alarm", "Remote Alarm",
             "Screen On/Off", "Frequency Lock"]
LIST_TIMER = ["Off"] + ["%s seconds" % x for x in range(15, 615, 15)]
LIST_TXPRI = ["Edit", "Busy"]
LIST_VOICE = ["Off", "Chinese", "English"]

TXALLOW_CHOICES = ["RX Only", "TX/RX"]
TXALLOW_VALUES = [0xFF, 0x00]


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _enter_programming_mode(radio):
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


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"93" + b"\x05\xEE\x5F")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">BH", ord(b'R'), block_addr + 0x0340)

    ccs = bytes([_checksum(cmd)])

    expectedresponse = b"R" + cmd[1:]

    cmd = cmd + ccs

    LOG.debug("Reading block %04x..." % (block_addr + 0x0340))

    try:
        serial.write(cmd)
        response = serial.read(3 + block_size + 1)

        cs = _checksum(response[:-1])

        if response[:3] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr +
                            0x0340))

        chunk = response[3:]

        if chunk[-1] != cs:
            raise Exception("Block failed checksum!")

        block_data = chunk[:-1]
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr +
                                0x0340)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    data = radio.get_mmap()[block_addr:block_addr + block_size]

    cmd = struct.pack(">BH", ord(b'W'), block_addr + 0x0340)

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
                                "to radio at %04x" % (block_addr + 0x0340))


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE)

    _exit_programming_mode(radio)


class IradioUV5118(chirp_common.CloneModeRadio):
    """IRADIO UV5118"""
    VENDOR = "Iradio"
    MODEL = "UV-5118"
    BAUD_RATE = 9600

    BLOCK_SIZE = 0x10
    magic = b"93" + b"\x05\x10\x81"

    VALID_BANDS = [(20000000, 64000000),  # RX only
                   (108000000, 136000000),  # RX only (Air Band)
                   (136000000, 174000000),  # TX/RX (VHF)
                   (174000000, 400000000),  # TX/RX
                   (400000000, 520000000),  # TX/RX (UHF)
                   (520000000, 660000000)]  # TX/RX

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    # Radio's memory starts at 0x0340
    # Radio's memory ends at 0x0B90

    _ranges = [
               (0x0000, 0x0850),
              ]
    _memsize = 0x0850

    _upper = 128

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
        rf.valid_duplexes = ["", "-", "+", "split"]
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

    @staticmethod
    def _decode_tone(toneval):
        # DCS examples:
        # D023N - 1013 - 0001 0000 0001 0011
        #                   ^-DCS
        # D023I - 2013 - 0010 0000 0001 0100
        #                  ^--DCS inverted
        # D754I - 21EC - 0010 0001 1110 1100
        #    code in octal-------^^^^^^^^^^^

        if toneval == 0x3000:
            return '', None, None
        elif toneval & 0x1000:
            # DTCS N
            code = int('%o' % (toneval & 0x1FF))
            return 'DTCS', code, 'N'
        elif toneval & 0x2000:
            # DTCS R
            code = int('%o' % (toneval & 0x1FF))
            return 'DTCS', code, 'R'
        else:
            return 'Tone', toneval / 10.0, None

    @staticmethod
    def _encode_tone(mode, val, pol):
        if not mode:
            return 0x3000
        elif mode == 'Tone':
            return int(val * 10)
        elif mode == 'DTCS':
            code = int('%i' % val, 8)
            if pol == 'N':
                code |= 0x1800
            if pol == 'R':
                code |= 0x2800
            return code
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)

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
            _mem.set_raw("\xFF" * 4 + "\x00\x30" + "\xFF" * 4 + "\x00\x30" +
                         "\x00" * 4)

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
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

        chirp_common.split_tone_decode(mem,
                                       self._decode_tone(_mem.tx_tone),
                                       self._decode_tone(_mem.rx_tone))

        mem.power = self.POWER_LEVELS[_mem.lowpower]

        if not _mem.scan:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
        _mem = self._memobj.channels[mem.number - 1]

        # if empty memory
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        _mem.set_raw("\xFF" * 4 + "\x00\x30" + "\xFF" * 4 + "\x00\x30" +
                     "\x00" * 4)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.scan = mem.skip != "S"
        _mem.isnarrow = mem.mode == "NFM"

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.tx_tone = self._encode_tone(*txtone)
        _mem.rx_tone = self._encode_tone(*rxtone)

        _mem.lowpower = mem.power == self.POWER_LEVELS[1]

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _txallow = self._memobj.txallow
        basic = RadioSettingGroup("basic", "Basic Settings")
        sidekey = RadioSettingGroup("sidekey", "Side Key Settings")
        dwatch = RadioSettingGroup("dwatch", "Dual Watch Settings")
        txallow = RadioSettingGroup("txallow", "TX Allow")
        top = RadioSettings(basic, sidekey, dwatch, txallow)

        voice = RadioSetting("voice", "Language", RadioSettingValueList(
                             LIST_VOICE, current_index=_settings.voice))
        basic.append(voice)

        beep = RadioSetting("beep", "Key Beep",
                            RadioSettingValueBoolean(_settings.beep))
        basic.append(beep)

        roger = RadioSetting("roger", "Roger Tone",
                             RadioSettingValueList(
                                 LIST_ROGER, current_index=_settings.roger))
        basic.append(roger)

        save = RadioSetting("save", "Battery Save",
                            RadioSettingValueList(
                                LIST_SAVE, current_index=_settings.save))
        basic.append(save)

        dispmode = RadioSetting("dispmode", "Display Mode",
                                RadioSettingValueList(
                                    LIST_DISPM,
                                    current_index=_settings.dispmode))
        basic.append(dispmode)

        brightness = RadioSetting("brightness", "Screen Light",
                                  RadioSettingValueList(
                                      LIST_BRIGHT,
                                      current_index=_settings.brightness))
        basic.append(brightness)

        screen = RadioSetting("screen", "Screen",
                              RadioSettingValueBoolean(_settings.screen))
        basic.append(screen)

        display_timer = RadioSetting(
            "display_timer", "Display Timer",
            RadioSettingValueList(
                LIST_TIMER, current_index=_settings.display_timer))
        basic.append(display_timer)

        led = RadioSetting("led", "LED",
                           RadioSettingValueBoolean(_settings.led))
        basic.append(led)

        led_timer = RadioSetting("led_timer", "LED Timer",
                                 RadioSettingValueList(
                                     LIST_TIMER,
                                     current_index=_settings.led_timer))
        basic.append(led_timer)

        squelch = RadioSetting("squelch", "Squelch Level",
                               RadioSettingValueInteger(
                                   0, 9, _settings.squelch))
        basic.append(squelch)

        vox = RadioSetting("vox", "VOX",
                           RadioSettingValueBoolean(_settings.vox))
        basic.append(vox)

        vox_level = RadioSetting("vox_level", "VOX Level",
                                 RadioSettingValueInteger(
                                     0, 9, _settings.vox_level))
        basic.append(vox_level)

        vox_delay = RadioSetting("vox_delay", "VOX Delay",
                                 RadioSettingValueInteger(
                                     0, 9, _settings.vox_delay))
        basic.append(vox_delay)

        compander = RadioSetting("compander", "Compander",
                                 RadioSettingValueBoolean(_settings.compander))
        basic.append(compander)

        scramble = RadioSetting("scramble", "Scramble",
                                RadioSettingValueList(
                                    LIST_SCRAMBLE,
                                    current_index=_settings.scramble))
        basic.append(scramble)

        rp = RadioSetting("rp", "Offset",
                          RadioSettingValueBoolean(_settings.rp))
        basic.append(rp)

        txpri = RadioSetting("txpri", "TX Priority",
                             RadioSettingValueList(
                                 LIST_TXPRI,
                                 current_index=_settings.txpri))
        basic.append(txpri)

        tot = RadioSetting("tot", "Time-out Timer",
                           RadioSettingValueList(
                               LIST_TIMER,
                               current_index=_settings.tot))
        basic.append(tot)

        tail_tone = RadioSetting("tail_tone", "Tail Tone",
                                 RadioSettingValueInteger(
                                     0, 3, _settings.tail_tone))
        basic.append(tail_tone)

        alarm = RadioSetting("alarm", "Alarm",
                             RadioSettingValueList(
                                 LIST_ALARM,
                                 current_index=_settings.alarm))
        basic.append(alarm)

        freq_lock = RadioSetting("freq_lock", "Frequency Lock",
                                 RadioSettingValueBoolean(_settings.freq_lock))
        basic.append(freq_lock)

        key_lock = RadioSetting("key_lock", "Key Lock",
                                RadioSettingValueBoolean(_settings.key_lock))
        basic.append(key_lock)

        auto_lock = RadioSetting("auto_lock", "Auto Lock Timer",
                                 RadioSettingValueList(
                                     LIST_TIMER,
                                     current_index=_settings.auto_lock))
        basic.append(auto_lock)

        radio = RadioSetting("radio", "Broadcast FM Radio",
                             RadioSettingValueBoolean(_settings.radio))
        basic.append(radio)

        standby = RadioSetting("standby", "Radio Standby",
                               RadioSettingValueBoolean(_settings.standby))
        basic.append(standby)

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        # FM Broadcast Settings
        val = _settings.fmcur
        val = val / 10.0
        if val < 87.5 or val > 108.0:
            val = 90.4
        rx = RadioSettingValueFloat(87.5, 108.0, val, 0.1, 1)
        rset = RadioSetting("fmcur", "Broadcast FM Freq (MHz)", rx)
        rset.set_apply_callback(myset_freq, _settings, "fmcur", 10)
        basic.append(rset)

        # Side Key Settings
        pfkey1short = RadioSetting("pfkey1short", "Side Key 1 - Short Press",
                                   RadioSettingValueList(
                                       LIST_SKEY,
                                       current_index=_settings.pfkey1short))
        sidekey.append(pfkey1short)

        pfkey1long = RadioSetting("pfkey1long", "Side Key 1 - Long Press",
                                  RadioSettingValueList(
                                      LIST_SKEY,
                                      current_index=_settings.pfkey1long))
        sidekey.append(pfkey1long)

        pfkey2short = RadioSetting("pfkey2short", "Side Key 2 - Short Press",
                                   RadioSettingValueList(
                                       LIST_SKEY,
                                       current_index=_settings.pfkey2short))
        sidekey.append(pfkey2short)

        pfkey2long = RadioSetting("pfkey2long", "Side Key 2 - Long Press",
                                  RadioSettingValueList(
                                      LIST_SKEY,
                                      current_index=_settings.pfkey2long))
        sidekey.append(pfkey2long)

        dstandby = RadioSetting("dstandby", "Dual Standby",
                                RadioSettingValueBoolean(_settings.dstandby))
        dwatch.append(dstandby)

        dsrangea = RadioSetting("dsrangea", "Dual Standby Range A",
                                RadioSettingValueInteger(
                                    1, 128, _settings.dsrangea + 1))
        dwatch.append(dsrangea)

        dsrangeb = RadioSetting("dsrangeb", "Dual Standby Range B",
                                RadioSettingValueInteger(
                                    1, 128, _settings.dsrangeb + 1))
        dwatch.append(dsrangeb)

        def apply_txallow_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(
                      setting.value) + " from list")
            val = str(setting.value)
            index = TXALLOW_CHOICES.index(val)
            val = TXALLOW_VALUES[index]
            obj.set_value(val)

        if _txallow.range174_180 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range174_180)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range174_180", "174-180 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range174_180)
        txallow.append(rset)

        if _txallow.range180_190 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range180_190)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range180_190", "180-190 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range180_190)
        txallow.append(rset)

        if _txallow.range190_200 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range190_200)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range190_200", "190-200 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range190_200)
        txallow.append(rset)

        if _txallow.range200_210 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range200_210)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range200_210", "200-210 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range200_210)
        txallow.append(rset)

        if _txallow.range210_220 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range210_220)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range210_220", "210-220 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range210_220)
        txallow.append(rset)

        if _txallow.range220_230 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range220_230)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range220_230", "220-230 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range220_230)
        txallow.append(rset)

        if _txallow.range230_240 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range230_240)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range230_240", "230-240 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range230_240)
        txallow.append(rset)

        if _txallow.range240_250 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range240_250)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range240_250", "240-250 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range240_250)
        txallow.append(rset)

        if _txallow.range250_260 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range250_260)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range250_260", "250-260 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range250_260)
        txallow.append(rset)

        if _txallow.range260_270 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range260_270)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range260_270", "260-270 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range260_270)
        txallow.append(rset)

        if _txallow.range270_280 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range270_280)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range270_280", "270-280 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range270_280)
        txallow.append(rset)

        if _txallow.range280_290 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range280_290)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range280_290", "280-290 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range280_290)
        txallow.append(rset)

        if _txallow.range290_300 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range290_300)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range290_300", "290-300 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range290_300)
        txallow.append(rset)

        if _txallow.range300_310 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range300_310)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range300_310", "300-310 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range300_310)
        txallow.append(rset)

        if _txallow.range310_320 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range310_320)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range310_320", "310-320 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range310_320)
        txallow.append(rset)

        if _txallow.range320_330 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range320_330)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range320_330", "320-330 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range320_330)
        txallow.append(rset)

        if _txallow.range330_340 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range330_340)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range330_340", "330-340 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range330_340)
        txallow.append(rset)

        if _txallow.range340_350 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range340_350)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range340_350", "340-350 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range340_350)
        txallow.append(rset)

        if _txallow.range350_360 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range350_360)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range350_360", "350-360 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range350_360)
        txallow.append(rset)

        if _txallow.range360_370 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range360_370)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range360_370", "360-370 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range360_370)
        txallow.append(rset)

        if _txallow.range370_380 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range370_380)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range370_380", "370-380 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range370_380)
        txallow.append(rset)

        if _txallow.range380_390 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range380_390)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range380_390", "380-390 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range380_390)
        txallow.append(rset)

        if _txallow.range390_400 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range390_400)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range390_400", "390-400 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range390_400)
        txallow.append(rset)

        if _txallow.range520_530 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range520_530)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range520_530", "520-530 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range520_530)
        txallow.append(rset)

        if _txallow.range530_540 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range530_540)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range530_540", "530-540 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range530_540)
        txallow.append(rset)

        if _txallow.range540_550 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range540_550)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range540_550", "540-550 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range540_550)
        txallow.append(rset)

        if _txallow.range550_560 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range550_560)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range550_560", "550-560 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range550_560)
        txallow.append(rset)

        if _txallow.range560_570 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range560_570)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range560_570", "560-570 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range560_570)
        txallow.append(rset)

        if _txallow.range570_580 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range570_580)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range570_580", "570-580 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range570_580)
        txallow.append(rset)

        if _txallow.range580_590 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range580_590)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range580_590", "580-590 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range580_590)
        txallow.append(rset)

        if _txallow.range590_600 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range590_600)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range590_600", "590-600 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range590_600)
        txallow.append(rset)

        if _txallow.range600_610 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range600_610)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range600_610", "600-610 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range600_610)
        txallow.append(rset)

        if _txallow.range610_620 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range610_620)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range610_620", "610-620 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range610_620)
        txallow.append(rset)

        if _txallow.range620_630 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range620_630)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range620_630", "620-630 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range620_630)
        txallow.append(rset)

        if _txallow.range630_640 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range630_640)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range630_640", "630-640 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range630_640)
        txallow.append(rset)

        if _txallow.range640_650 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range640_650)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range640_650", "640-650 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range640_650)
        txallow.append(rset)

        if _txallow.range650_660 in TXALLOW_VALUES:
            idx = TXALLOW_VALUES.index(_txallow.range650_660)
        else:
            idx = TXALLOW_VALUES.index(0xFF)
        rs = RadioSettingValueList(TXALLOW_CHOICES, current_index=idx)
        rset = RadioSetting("txallow.range650_660", "650-660 MHz", rs)
        rset.set_apply_callback(apply_txallow_listvalue, _txallow.range650_660)
        txallow.append(rset)

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
                    elif setting == "dsrangea":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "dsrangeb":
                        setattr(obj, setting, int(element.value) - 1)
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
class AbbreeAR518Radio(IradioUV5118):
    """ABBREE AR518"""
    VENDOR = "Abbree"
    MODEL = "AR-518"
