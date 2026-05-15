# Copyright 2024 CHIRP contributors
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

# Driver for the Vertex Standard VX-150 VHF handheld radio.
#
# The radio communicates at 9600 baud using the ft7800-style protocol:
# ACK after every 32-byte chunk (not after each logical block).  Image is
# 5353 bytes: 8-byte header + 167×32-byte body blocks + 1 checksum byte.
#
# Model bytes (offset 0x0000): 0x0A 0x01 0x04 0x00 0x01 0x24

import logging
import time

from chirp.drivers import yaesu_clone
from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings, \
    RadioSettingValueBoolean, RadioSettingValueList, RadioSettingValueString

LOG = logging.getLogger(__name__)

ACK = b'\x06'


def _send(ser, data):
    for i in data:
        ser.write(bytes([i]))
        time.sleep(0.002)
    echo = ser.read(len(data))
    if echo != data:
        raise errors.RadioError("Error reading echo (Bad cable?)")


def _download(radio):
    data = b""

    chunk = b""
    for _ in range(0, 30):
        chunk += radio.pipe.read(radio._block_lengths[0])
        if chunk:
            break

    if len(chunk) != radio._block_lengths[0]:
        raise errors.RadioError("Failed to read header (%i)" % len(chunk))
    data += chunk
    _send(radio.pipe, ACK)

    for i in range(0, radio._block_lengths[1], radio._block_size):
        chunk = radio.pipe.read(radio._block_size)
        data += chunk
        if len(chunk) != radio._block_size:
            break
        time.sleep(0.01)
        _send(radio.pipe, ACK)
        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio.get_memsize()
            status.cur = i + len(chunk)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    data += radio.pipe.read(1)
    _send(radio.pipe, ACK)

    return memmap.MemoryMapBytes(data)


# Channel memory layout — 16 bytes per channel, starting at 0x07D8.
#
# Full 16-byte pattern of an unprogrammed channel
_EMPTY_CHANNEL = (b'\x00\x01\x00\x44\x00\x00\x60\x00'
                  b'\x0c\x00\x00\x00\xaa\x00\x02\x00')

# Byte 0 — flags:
#   bit 7    : active (0=masked or empty, 1=active)
#   bit 6    : skip (0=no skip, 1=skip)
#   bits 5-4 : unknown
#   bits 3-2 : duplex  (0=simplex, 2=neg offset, 3=pos offset)
#   bits 1-0 : tmode   (0=none, 1=Tone, 2=TSQL, 3=DTCS)
#
# Bytes 1-3 — frequency (custom BCD):
#   byte 1 bit 7,6 : 2.5 kHz increments.
#   byte 1 bits 6-0 : band indicator (always 0x01 for 2 m)
#   byte 2 : BCD, 10-kHz digits  (e.g. 0x52 → 52 → 520 kHz)
#   byte 3 : BCD, MHz digits above 100 (e.g. 0x46 → 46 → 146 MHz)
#
# Byte 8 : CTCSS tone index (chirp_common.TONES)
# Byte 9 : DCS code index  (chirp_common.DTCS_CODES)
#
# Bytes 4-7, 10-15 : not yet decoded.

MEM_FORMAT = """
#seekto 0x0013;
u8 step;

#seekto 0x0026;
struct {
    u8 mem_only:1,
       unknown1:5,
       power:2;
} settings3;

#seekto 0x0049;
struct {
    u8 unknown1:2,
       tx_led:1,
       unknown2:1,
       scan_lamp:1,
       ars:1,
       scan_resume:2;
    u8 bclo:1,
       edge_beep:1,
       key_beep:1,
       arts_interval:1,
       tx_save:1,
       rx_save:3;
    u8 unknown4a:1,
       dtmf_speed:1,
       smt_mod:1,
       ani_on:1,
       unknown5:1,
       apo:3;
    u8 unknown5b:6,
       arts_bp:2;
    u8 unknown6:3,
       rev_hm:1,
       moni_tcall:1,
       bell:3;
    u8 unknown7:5,
       lamp:3;
    u8 unknown8:5,
       tot:3;
    u8 lock_mode;
    u8 unknown9[3];
    u8 dtmf_delay;
} settings2;

#seekto 0x0056;
struct {
    u8 p1_key;
    u8 p2_key;
} p_keys;

struct channel {
    u8 active:1,
       skip:1,
       unknown1:2,
       duplex:2,
       tmode:2;
    u8 sub_khz:2,
       unknown_flags:5,
       band:1;
    bbcd freq_khz;
    bbcd freq_mhz;
    u8 unknown2:2,
       narrow:1,
       clock_shift:1,
       unknown3:4;
    u8 unknown4;
    bbcd offset_low;
    bbcd offset_high;
    u8 tone;
    u8 dtcs;
    u8 unknown5[6];
};

struct channel home;

u8 cwid[16];
u8 ani[16];
struct {
    u8 digits[16];
} dtmf[9];

#seekto 0x0150;
struct {
    u8 name[7];
    u8 show_name;
} names[199];

struct {
    u8 name[7];
    u8 show_name;
} limit_names[10];

struct channel memory[199];

struct channel limits[10];
"""

# Character set: index → character.  0x00-0x09 = '0'-'9', 0x0A-0x23 = 'A'-'Z'
# 0xFF = empty/pad.
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ()+-=*/ΔγΣ|"

DTMF_CHARSET = "0123456789ABCDEF"
SPECIALS = ["Home", "L1", "L2", "L3", "L4", "L5", "U1", "U2", "U3", "U4", "U5"]

P_KEY_LIST = [
    "1: ALPHA",
    "2: ARS",
    "3: RPT",
    "4: SHIFT",
    "5: V-SPLIT",
    "6: STEP",
    "7: RESUME",
    "8: SCN LMP",
    "9: RX SAVE",
    "10: TX SAVE",
    "11: APO",
    "12: TRX LED",
    "13: ARTS",
    "14: ARTS BP",
    "15: AR ITVL",
    "16: KEY BP",
    "17: EDGE BP",
    "18: BELL",
    "19: MON/TCL",
    "20: REV/HM",
    "21: LMP MOD",
    "22: TOT",
    "23: BCLO",
    "24: CLK SFT",
    "25: SQL TYP",
    "26: TN SET",
    "27: DCS SET",
    "28: DTMF",
    "29: CW ID",
    "30: S SRCH",
    "31: SMT MOD",
    "32: LK MODE",
    "33: NAR/WID",
    "34: DTMF SP",
    "35: DT DLY",
    "36: ANI",
    "37: BATT",
    "38: SKIP",
]

STEP_LIST = ["5.0", "10.0", "12.5", "15.0", "20.0", "25.0", "50.0"]
POWER_LIST = ["Low", "Mid", "High"]
SCAN_RESUME_LIST = ["5 Seconds", "Busy", "Hold"]
SCAN_LAMP_LIST = ["Off", "On"]
RX_SAVE_LIST = ["Off", "0.2 sec", "0.3 sec", "0.5 sec", "1 sec", "2 sec"]
APO_LIST = ["Off", "30 Min", "1 Hour", "3 Hour", "5 Hour", "8 Hour"]
ARTS_BP_LIST = ["Off", "In Range", "Always"]
ARTS_INTERVAL_LIST = ["25 Sec", "15 Sec"]
BELL_LIST = ["Off", "1", "3", "5", "8", "Repeat"]
MONI_TCALL_LIST = ["Monitor", "T.Call"]
REV_HM_LIST = ["REV", "Home"]
LAMP_LIST = ["Key", "5 Sec", "Toggle"]
TOT_LIST = ["Off", "1 Min", "2.5 Min", "5 Min", "10 Min"]

# duplex field value → CHIRP duplex string
DUPLEX_MAP = {0: "", 2: "-", 3: "+"}
DUPLEX_REV = {"": 0, "-": 2, "+": 3}

# tmode field value → CHIRP tmode string
TMODE_MAP = {0: "", 1: "Tone", 2: "TSQL", 3: "DTCS"}
TMODE_REV = {"": 0, "Tone": 1, "TSQL": 2, "DTCS": 3}


def _decode_str(raw_bytes, charset):
    """Decode a FF-terminated byte array using charset."""
    s = ""
    for b in raw_bytes:
        b = int(b)
        if b == 0xFF:
            break
        if b < len(charset):
            s += charset[b]
    return s


def _encode_str(s, charset, length):
    """Encode a string to a fixed-length byte list using charset, FF-padded."""
    result = []
    for c in s[:length]:
        if c in charset:
            result.append(charset.index(c))
        else:
            result.append(0xFF)
    result += [0xFF] * (length - len(result))
    return result


def _upload(radio):
    """Upload image to VX-150.

    Mirror of ft7800._download: the radio ACKs each 32-byte body block but
    does NOT ACK the 8-byte header (asymmetric vs. download direction).
    """
    mmap = radio.get_mmap().get_byte_compatible()

    # Header (8 bytes) — send, then wait for the radio to ACK it
    _send(radio.pipe, mmap[0:8])
    if radio.pipe.read(1) != ACK:
        raise errors.RadioError("Radio did not ack header")

    # Body (5344 bytes) in 32-byte blocks — radio ACKs each
    cur = 8
    body_end = 8 + radio._block_lengths[1]
    while cur < body_end:
        length = min(radio._block_size, body_end - cur)
        _send(radio.pipe, mmap[cur:cur + length])
        if radio.pipe.read(1) != ACK:
            raise errors.RadioError("Radio did not ack block at %i" % cur)
        cur += length
        time.sleep(0.05)
        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = cur
            status.max = radio.get_memsize()
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    # Checksum (1 byte) — send last
    _send(radio.pipe, mmap[cur:cur + 1])


@directory.register
class VX150Radio(yaesu_clone.YaesuCloneModeRadio):
    """Vertex Standard VX-150"""
    VENDOR = "Yaesu"
    MODEL = "VX-150"
    BAUD_RATE = 9600

    # Confirmed from a real radio dump.  Binary header, not ASCII like most
    # Yaesu/Vertex models.  Bytes: 0x0A 0x01 0x04 0x00 0x01 0x24
    _model = b"\x0a\x01\x04\x00\x01\x24"

    # 8-byte header + 167×32-byte body + 1 checksum byte
    _memsize = 5353
    _block_lengths = [8, 5344, 1]
    _block_size = 32

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect clone cable to the MIC/SP jack.\n"
            "3. Press and hold [PTT] and [Lamp] while turning the radio on.\n"
            "4. Rotate the dial to select \"CLONE\", then press [F].\n"
            "     (\"CLONE\" will appear on the display)\n"
            "5. <b>After clicking OK</b>, hold [PTT] briefly to transmit.\n"
            "     (\"SENDING\" will appear on the display)\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect clone cable to the MIC/SP jack.\n"
            "3. Press and hold [PTT] and [Lamp] while turning the radio on.\n"
            "4. Rotate the dial to select \"CLONE\", then press [F].\n"
            "     (\"CLONE\" will appear on the display)\n"
            "5. Press [MONI] to receive.\n"
            "     (\"SAVING\" will appear on the display)\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 199)
        rf.valid_bands = [(136000000, 174000000)]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = 7
        rf.valid_characters = CHARSET
        rf.valid_special_chans = SPECIALS
        rf.valid_tones = chirp_common.OLD_TONES
        rf.valid_tuning_steps = list(chirp_common.COMMON_TUNING_STEPS) + [12.5]
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_settings = True
        rf.has_tuning_step = False
        return rf

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        if len(self._mmap) != self._memsize:
            raise errors.RadioError(
                "Expected %i bytes but got %i" % (
                    self._memsize, len(self._mmap)))
        self.process_mmap()

    def _checksums(self):
        # Sum of all bytes 0x0000–0x14E7, stored at 0x14E8
        return [yaesu_clone.YaesuChecksum(0x0000, self._memsize - 2)]

    def sync_out(self):
        self.update_checksums()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        if number == "Home":
            return repr(self._memobj.home)
        if isinstance(number, str):
            return repr(self._memobj.limits[SPECIALS.index(number) - 1])
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        if number == "Home":
            raw = self._memobj.home
            raw_name = None
            mem = chirp_common.Memory()
            mem.extd_number = "Home"
        elif isinstance(number, str):
            idx = SPECIALS.index(number) - 1
            raw = self._memobj.limits[idx]
            raw_name = self._memobj.limit_names[idx]
            mem = chirp_common.Memory()
            mem.extd_number = number
        else:
            raw = self._memobj.memory[number - 1]
            raw_name = self._memobj.names[number - 1]
            mem = chirp_common.Memory(number)

        if number == "Home":
            offset = 0x0058
        elif isinstance(number, str):
            offset = 0x1448 + (SPECIALS.index(number) - 1) * 16
        else:
            offset = 0x07d8 + (number - 1) * 16
        raw16 = bytes(self._mmap.get_byte_compatible()[offset:offset + 16])
        if raw16 == _EMPTY_CHANNEL:
            mem.empty = True
            return mem

        mem.freq = ((100 + int(raw.freq_mhz)) * 1_000_000
                    + int(raw.freq_khz) * 10_000
                    + int(raw.sub_khz) * 2_500)
        mem.skip = "S" if raw.skip else ""
        mem.mode = "NFM" if raw.narrow else "FM"
        mem.duplex = DUPLEX_MAP.get(int(raw.duplex), "")
        mem.offset = (int(raw.offset_high) * 1_000_000 +
                      int(raw.offset_low) * 10_000)
        mem.tmode = TMODE_MAP.get(int(raw.tmode), "")

        tone_idx = int(raw.tone)
        if tone_idx < len(chirp_common.OLD_TONES):
            mem.rtone = chirp_common.OLD_TONES[tone_idx]
            mem.ctone = mem.rtone

        dtcs_idx = int(raw.dtcs)
        if dtcs_idx < len(chirp_common.DTCS_CODES):
            mem.dtcs = chirp_common.DTCS_CODES[dtcs_idx]

        if raw_name is not None:
            name = ""
            for byte in raw_name.name:
                b = int(byte)
                if b == 0xFF:
                    break
                if b < len(CHARSET):
                    name += CHARSET[b]
            mem.name = name.rstrip()

        mem.extra = RadioSettingGroup("extra", "Extra")
        mem.extra.append(RadioSetting(
            "masked", "Masked",
            RadioSettingValueBoolean(not bool(raw.active))))
        mem.extra.append(RadioSetting(
            "clock_shift", "Clock Shift",
            RadioSettingValueBoolean(bool(raw.clock_shift))))

        return mem

    def get_settings(self):
        _settings2 = self._memobj.settings2
        _settings3 = self._memobj.settings3

        basic = RadioSettingGroup("basic", "Basic")
        top = RadioSettings(basic)

        basic.append(RadioSetting(
            "mem_only", "Memory Only Mode",
            RadioSettingValueBoolean(bool(_settings3.mem_only))))

        basic.append(RadioSetting(
            "power", "Power Level",
            RadioSettingValueList(
                POWER_LIST, current_index=int(_settings3.power))))

        basic.append(RadioSetting(
            "ars", "2: Auto Repeater Shift",
            RadioSettingValueBoolean(bool(_settings2.ars))))

        basic.append(RadioSetting(
            "step", "6: Tuning Step (kHz)",
            RadioSettingValueList(
                STEP_LIST, current_index=int(self._memobj.step))))

        basic.append(RadioSetting(
            "scan_resume", "7: Scan Resume",
            RadioSettingValueList(
                SCAN_RESUME_LIST, current_index=int(_settings2.scan_resume))))

        basic.append(RadioSetting(
            "scan_lamp", "8: Scan Lamp",
            RadioSettingValueList(
                SCAN_LAMP_LIST, current_index=int(_settings2.scan_lamp))))

        basic.append(RadioSetting(
            "rx_save", "9: RX Save",
            RadioSettingValueList(
                RX_SAVE_LIST, current_index=int(_settings2.rx_save))))

        basic.append(RadioSetting(
            "tx_save", "10: TX Save",
            RadioSettingValueBoolean(bool(_settings2.tx_save))))

        basic.append(RadioSetting(
            "apo", "11: Auto Power Off",
            RadioSettingValueList(
                APO_LIST, current_index=int(_settings2.apo))))

        basic.append(RadioSetting(
            "tx_led", "12: TX LED",
            RadioSettingValueBoolean(not bool(_settings2.tx_led))))

        basic.append(RadioSetting(
            "arts_bp", "14: ARTS Beep",
            RadioSettingValueList(
                ARTS_BP_LIST, current_index=int(_settings2.arts_bp))))

        basic.append(RadioSetting(
            "arts_interval", "15: ARTS Interval",
            RadioSettingValueList(
                ARTS_INTERVAL_LIST,
                current_index=int(_settings2.arts_interval))))

        basic.append(RadioSetting(
            "key_beep", "16: Key Beep",
            RadioSettingValueBoolean(bool(_settings2.key_beep))))

        basic.append(RadioSetting(
            "edge_beep", "17: Edge Beep",
            RadioSettingValueBoolean(bool(_settings2.edge_beep))))

        basic.append(RadioSetting(
            "bell", "18: Bell (CTCSS)",
            RadioSettingValueList(
                BELL_LIST, current_index=int(_settings2.bell))))

        basic.append(RadioSetting(
            "moni_tcall", "19: MONI Button",
            RadioSettingValueList(
                MONI_TCALL_LIST, current_index=int(_settings2.moni_tcall))))

        basic.append(RadioSetting(
            "rev_hm", "20: REV(HM) Key",
            RadioSettingValueList(
                REV_HM_LIST, current_index=int(_settings2.rev_hm))))

        basic.append(RadioSetting(
            "lamp", "21: Lamp Mode",
            RadioSettingValueList(
                LAMP_LIST, current_index=int(_settings2.lamp))))

        basic.append(RadioSetting(
            "tot", "22: Time-Out Timer",
            RadioSettingValueList(
                TOT_LIST, current_index=int(_settings2.tot))))

        basic.append(RadioSetting(
            "bclo", "23: Busy Channel Lockout",
            RadioSettingValueBoolean(bool(_settings2.bclo))))

        basic.append(RadioSetting(
            "smt_mod", "31: Smart Search Mode",
            RadioSettingValueList(
                ["Single", "Continue"],
                current_index=int(_settings2.smt_mod))))

        basic.append(RadioSetting(
            "lock_mode", "32: Lock Mode",
            RadioSettingValueList(
                ["Key", "Dial", "K+D", "PTT", "K+P", "D+P", "All"],
                current_index=int(_settings2.lock_mode) - 1)))

        basic.append(RadioSetting(
            "dtmf_speed", "34: DTMF Speed",
            RadioSettingValueList(
                ["50ms", "100ms"], current_index=int(_settings2.dtmf_speed))))

        DTMF_DELAY_LIST = ["450ms", "750ms"]
        DTMF_DELAY_MAP = [0xD3, 0xB5]
        basic.append(RadioSetting(
            "dtmf_delay", "35: DTMF Delay",
            RadioSettingValueList(
                DTMF_DELAY_LIST,
                current_index=DTMF_DELAY_MAP.index(
                    int(_settings2.dtmf_delay)))))

        basic.append(RadioSetting(
            "ani_on", "36: ANI",
            RadioSettingValueBoolean(bool(_settings2.ani_on))))

        _p_keys = self._memobj.p_keys
        basic.append(RadioSetting(
            "p1_key", "P1 Key",
            RadioSettingValueList(
                P_KEY_LIST, current_index=int(_p_keys.p1_key) - 1)))

        basic.append(RadioSetting(
            "p2_key", "P2 Key",
            RadioSettingValueList(
                P_KEY_LIST, current_index=int(_p_keys.p2_key) - 1)))

        ani = RadioSettingGroup("ani", "ANI")
        top.append(ani)
        ani_str = _decode_str(self._memobj.ani, DTMF_CHARSET)
        ani.append(RadioSetting(
            "ani", "ANI Code",
            RadioSettingValueString(0, 16, ani_str, False, DTMF_CHARSET)))

        cwid = RadioSettingGroup("cwid", "CW ID")
        top.append(cwid)
        cwid_str = _decode_str(self._memobj.cwid, CHARSET)
        cwid.append(RadioSetting(
            "cwid", "CW ID",
            RadioSettingValueString(0, 16, cwid_str, False, CHARSET)))

        dtmf = RadioSettingGroup("dtmf", "DTMF")
        top.append(dtmf)
        for i in range(9):
            dtmf_str = _decode_str(self._memobj.dtmf[i].digits, DTMF_CHARSET)
            dtmf.append(RadioSetting(
                "dtmf_%d" % (i + 1), "D%d" % (i + 1),
                RadioSettingValueString(0, 16, dtmf_str, False, DTMF_CHARSET)))

        return top

    def set_settings(self, uisettings):
        _settings2 = self._memobj.settings2
        _settings3 = self._memobj.settings3

        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            name = element.get_name()
            if name in ("mem_only", "power"):
                setattr(_settings3, name, element.value)
            elif name == "step":
                self._memobj.step = element.value
            elif name == "tx_led":
                _settings2.tx_led = not bool(element.value)
            elif name in ("scan_resume", "scan_lamp", "ars", "rx_save",
                          "tx_save", "apo", "ani_on", "dtmf_speed", "bclo",
                          "edge_beep", "key_beep", "arts_interval", "arts_bp",
                          "bell", "moni_tcall", "rev_hm", "lamp", "tot",
                          "smt_mod"):
                setattr(_settings2, name, element.value)
            elif name == "ani":
                self._memobj.ani = _encode_str(
                    str(element.value), DTMF_CHARSET, 16)
            elif name == "cwid":
                self._memobj.cwid = _encode_str(
                    str(element.value), CHARSET, 16)
            elif name == "lock_mode":
                _settings2.lock_mode = int(element.value) + 1
            elif name == "dtmf_delay":
                _settings2.dtmf_delay = [0xD3, 0xB5][int(element.value)]
            elif name in ("p1_key", "p2_key"):
                setattr(self._memobj.p_keys, name, int(element.value) + 1)
            elif name.startswith("dtmf_"):
                i = int(name.split("_")[1]) - 1
                self._memobj.dtmf[i].digits = _encode_str(
                    str(element.value), DTMF_CHARSET, 16)

    def set_memory(self, mem):
        number = mem.extd_number or mem.number
        if number == "Home":
            raw = self._memobj.home
            raw_name = None
        elif isinstance(number, str):
            idx = SPECIALS.index(number) - 1
            raw = self._memobj.limits[idx]
            raw_name = self._memobj.limit_names[idx]
        else:
            raw = self._memobj.memory[number - 1]
            raw_name = self._memobj.names[number - 1]

        if mem.empty:
            raw.set_raw(bytes(_EMPTY_CHANNEL))
            if raw_name is not None:
                for i in range(7):
                    raw_name.name[i] = 0xFF
                raw_name.show_name = 0xFF
            return

        # Frequency
        freq_hz = mem.freq
        mhz = freq_hz // 1_000_000
        remainder = freq_hz % 1_000_000
        khz_10 = remainder // 10_000
        sub_khz = (remainder % 10_000) // 2_500
        raw.freq_mhz = mhz - 100
        raw.freq_khz = khz_10
        raw.sub_khz = sub_khz
        raw.band = 1

        # Byte 0 flags
        raw.skip = 1 if mem.skip == "S" else 0
        raw.duplex = DUPLEX_REV.get(mem.duplex, 0)
        raw.tmode = TMODE_REV.get(mem.tmode, 0)

        # Byte 4: mode and clock shift
        raw.narrow = 1 if mem.mode == "NFM" else 0
        clock_shift = 0
        masked = False
        if mem.extra:
            for setting in mem.extra:
                sname = setting.get_name()
                if sname == "clock_shift":
                    clock_shift = int(bool(setting.value))
                elif sname == "masked":
                    masked = bool(setting.value)
        raw.clock_shift = clock_shift
        raw.active = 0 if masked else 1

        # Byte 5: always 0x10 in programmed channels
        raw.unknown4 = 0x10

        # Offset
        offset_hz = mem.offset
        raw.offset_high = offset_hz // 1_000_000
        raw.offset_low = (offset_hz % 1_000_000) // 10_000

        # Tone / DCS
        raw.tone = (chirp_common.OLD_TONES.index(mem.rtone)
                    if mem.rtone in chirp_common.OLD_TONES else 0)
        raw.dtcs = (chirp_common.DTCS_CODES.index(mem.dtcs)
                    if mem.dtcs in chirp_common.DTCS_CODES else 0)

        # Bytes 10-15: constant across all programmed channels
        for i, b in enumerate([0x00, 0x00, 0xaa, 0x00, 0x02, 0x00]):
            raw.unknown5[i] = b

        # Name
        if raw_name is not None:
            name = mem.name.rstrip()
            encoded = _encode_str(name, CHARSET, 7)
            for i in range(7):
                raw_name.name[i] = encoded[i]
            raw_name.show_name = 0x00 if name else 0xFF

    @classmethod
    def match_model(cls, filedata, filename):
        # New driver — images are identified by the metadata sidecar
        return False
