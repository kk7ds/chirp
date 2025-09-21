# Copyright 2025 Jim Unroe <rock.unroe@gmail.com>
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
    u32 rxfreq;      // 0-3
    ul16 rxtone;     // 4-5
    u32 txfreq;      // 6-9
    ul16 txtone;     // A-B
    u8 unknown0:3,   // C
       scan:1,       //
       is_wide:1,    //
       unknown1:1,   //
       highpower:1,  //
       unknown2:1;   //
    u8 unknown3[3];  // D-F
} ;

struct memory lochannels[14];
struct memory chnl15;
struct memory rptr15;
struct memory chnl16;
struct memory rptr16;
struct memory chnl17;
struct memory rptr17;
struct memory chnl18;
struct memory rptr18;
struct memory chnl19;
struct memory rptr19;
struct memory chnl20;
struct memory rptr20;
struct memory chnl21;
struct memory rptr21;
struct memory chnl22;
struct memory rptr22;
struct memory hichannels[77];

#seekto 0x0E00;
struct {
    u8 unknown00:4,   vox:4;         // 0E00 VOX
    u8 unknown01:7,   keytone:1;     // 0E01 Key Tone
    u8 unknown02:7,   roger:1;       // 0E02 Roger Beep
    u8 unknown03:5,   calltone:3;    // 0E03 Call Tone
    u8 unknown04:6,   brightness:2;  // 0E04 Screen Brightness
    u8 unknown05:5,   backlight:3;   // 0E05 Backlight Duration
    u8 unknown06:4,   squelch:4;     // 0E06 Squelch Level
    u8 unknown07;                    // 0E07 (Reserved/Unknown)
    u8 unknown08:7,   repeat:1;      // 0E08 Repeater
    u8 unknown09:5,   sleeptime:3;   // 0E09 Sleep Timer
    u8 unknown10:6,   speakersw:2;   // 0E0A Speaker Switch
    u8 unknown11:6,   micgain:2;     // 0E0B Mic Gain
    u8 unknown12:4,   tot:4;         // 0E0C Timeout Timer (TOT)
    u8 unknown13;                    // 0E0D (Reserved)
    u8 unknown14;                    // 0E0E (Reserved)
    u8 unknown15;                    // 0E0F (Reserved)
} settings;
"""

CMD_ACK = b"\x06"

LIST_OFF1TO9 = ["Off"] + ["%s" % x for x in range(1, 10)]
LIST_SLEEPTIME = ["OFF", "5s", "10s", "20s", "30s", "60s"]
LIST_SPEAKERSW = ["Base", "Mic", "Dual"]
LIST_TOT = ["Off"] + ["%s" % x for x in range(15, 195, 15)]

SPECIALS = {
        "RPTR15": -8,
        "RPTR16": -7,
        "RPTR17": -6,
        "RPTR18": -5,
        "RPTR19": -4,
        "RPTR20": -3,
        "RPTR21": -2,
        "RPTR22": -1
        }


def _enter_programming_mode(radio):
    serial = radio.pipe

    _magic = b"\x02" + radio._magic

    try:
        serial.write(_magic)
        serial.read(len(_magic))  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x02")
        serial.read(1)  # Chew the echo
        ident = serial.read(8)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    for fp in radio._fingerprint:
        if ident.startswith(fp):
            break
    else:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        serial.read(1)  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(radio.CMD_EXIT)
        serial.read(1)  # Chew the echo
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"R" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        serial.read(4)  # Chew the echo
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        serial.read(4 + len(data))  # Chew the echo
        serial.read(1)  # Chew the echo
        ack = serial.read(1)
        if ack != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


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


@directory.register
class RA86Radio(chirp_common.CloneModeRadio):
    """RETEVIS RA86"""
    VENDOR = "Retevis"
    MODEL = "RA86"
    BAUD_RATE = 115200
    BLOCK_SIZE = 0x10
    CMD_EXIT = b"b"

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=20.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    VALID_BANDS = [(400000000, 470000000)]

    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

    _magic = b"PROGRAM"
    _fingerprint = [b"SMP558"]
    _upper = 99

    _gmrs = False

    _ranges = [
        (0x0000, 0x06B0),
        (0x0E00, 0x0E10),
    ]
    _memsize = 0x0E10

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_special_chans = list(SPECIALS.keys())
        rf.has_settings = True
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.can_odd_split = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_name = False
        rf.memory_bounds = (1, self._upper)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = chirp_common.TUNING_STEPS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def decode_tone(self, val):
        mode = ""
        pol = "N"
        if val in [0, 0xFFFF]:
            xval = 0
        elif val <= 0x32:
            mode = "Tone"
            index = val - 1
            xval = chirp_common.TONES[index]
        elif val >= 0x0033:
            mode = "DTCS"
            if val > 0x69 + 0x32:
                index = val - 0x69 - 0x32 - 1
                pol = "R"
            else:
                index = val - 0x32 - 1
            xval = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: tone is %04x" % val)
        return mode, xval, pol

    def encode_tone(self, memtone, mode, tone, pol):
        if mode == "Tone":
            memtone.set_value(chirp_common.TONES.index(tone) + 1)
        elif mode == "TSQL":
            memtone.set_value(chirp_common.TONES.index(tone) + 1)
        elif mode == "DTCS":
            if pol == 'R':
                memtone.set_value(self.DTCS_CODES.index(tone) + 0x33 + 0x69)
            else:
                memtone.set_value(self.DTCS_CODES.index(tone) + 0x33)
        else:
            memtone.set_value(0)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()))
        elif number < 0:
            for k, v in SPECIALS.items():
                if number == v:
                    return (getattr(self._memobj, k.lower()))
        else:
            if number < 15:
                return self._memobj.lochannels[number - 1]
            elif 15 <= number <= 22:
                return getattr(self._memobj, f"chnl{number}")
            else:  # number > 22
                return self._memobj.hichannels[number - 23]

    def get_memory(self, number):
        _mem = self._get_memobjs(number)

        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = SPECIALS[number]
            mem.extd_number = number
        else:
            mem.number = number

        mem.freq = int(_mem.rxfreq)

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
        mem.freq = int(_mem.rxfreq)
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq)) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq)):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq)
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        mem.mode = _mem.is_wide and "FM" or "NFM"

        if not _mem.scan:
            mem.skip = "S"

        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = self.POWER_LEVELS[1 - _mem.highpower]

        return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._get_memobjs(mem.number)

        if mem.empty:
            _mem.fill_raw(b"\xFF")

            return

        _mem.fill_raw(b"\x00")

        _mem.rxfreq = mem.freq

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset)
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset)
        else:
            _mem.txfreq = mem.freq

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.highpower = mem.power == self.POWER_LEVELS[0]

        _mem.is_wide = mem.mode == "FM"
        _mem.scan = mem.skip != "S"

        _mem.unknown0 = 0
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = b"\x92\x1B\xC4"

    def get_settings(self):
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        if _mem.settings.vox >= len(LIST_OFF1TO9):
            val = 0x00
        else:
            val = _mem.settings.vox
        rs = RadioSetting("settings.vox", "VOX",
                          RadioSettingValueList(
                              LIST_OFF1TO9,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.keytone", "Key Tone",
                          RadioSettingValueBoolean(_mem.settings.keytone))
        basic.append(rs)

        rs = RadioSetting("settings.roger", "Roger Beep",
                          RadioSettingValueBoolean(_mem.settings.roger))
        basic.append(rs)

        if _mem.settings.calltone > 4:
            val = 1
        else:
            val = _mem.settings.calltone + 1
        rs = RadioSetting("settings.calltone", "Call Tone",
                          RadioSettingValueInteger(1, 5, val))
        basic.append(rs)

        if _mem.settings.brightness > 2:
            val = 1
        else:
            val = _mem.settings.brightness + 1
        rs = RadioSetting("settings.brightness", "Brightness",
                          RadioSettingValueInteger(1, 3, val))
        basic.append(rs)

        if _mem.settings.backlight > 4:
            val = 2
        else:
            val = _mem.settings.backlight
        rs = RadioSetting("settings.backlight", "Back Light",
                          RadioSettingValueInteger(0, 4, val))
        basic.append(rs)

        if _mem.settings.squelch >= len(LIST_OFF1TO9):
            val = 0x05
        else:
            val = _mem.settings.squelch
        rs = RadioSetting("settings.squelch", "Squelch",
                          RadioSettingValueList(
                              LIST_OFF1TO9,
                              current_index=val))
        basic.append(rs)

        if _mem.settings.tot >= len(LIST_TOT):
            val = 0x0C
        else:
            val = _mem.settings.tot
        rs = RadioSetting("settings.tot", "TOT",
                          RadioSettingValueList(
                              LIST_TOT,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.repeat", "Repeater",
                          RadioSettingValueBoolean(_mem.settings.repeat))
        basic.append(rs)

        if _mem.settings.sleeptime >= len(LIST_SLEEPTIME):
            val = 0x02
        else:
            val = _mem.settings.sleeptime
        rs = RadioSetting("settings.sleeptime", "Sleep Time",
                          RadioSettingValueList(
                              LIST_SLEEPTIME,
                              current_index=val))
        basic.append(rs)

        if _mem.settings.speakersw >= len(LIST_SPEAKERSW):
            val = 0x02
        else:
            val = _mem.settings.speakersw
        rs = RadioSetting("settings.speakersw", "Speaker Select",
                          RadioSettingValueList(
                              LIST_SPEAKERSW,
                              current_index=val))
        basic.append(rs)

        if _mem.settings.micgain > 2:
            val = 1
        else:
            val = _mem.settings.micgain + 1
        rs = RadioSetting("settings.micgain", "Mic Gain",
                          RadioSettingValueInteger(1, 5, val))
        basic.append(rs)

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
                    elif setting == "brightness":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "calltone":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "micgain":
                        setattr(obj, setting, int(element.value) - 1)
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise
