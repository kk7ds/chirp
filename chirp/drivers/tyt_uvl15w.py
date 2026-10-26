# Copyright 2026
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

"""TYT UVL-15W

Based on TYT's "UVL-15W communications protocol V3.0" and "UVL-15W data
storage instructions V1.0" documents.

The radio talks over USB CDC (or Bluetooth) using framed binary packets:

  request:  FE.. FE EE EF <cmd> <escaped data> <escaped lrc> FD
  response: FE.. FE EF EE <cmd> <escaped data> <escaped lrc> FD

Data and LRC bytes are sent as (byte + 0x80); results above 0xF9 are sent
as FF followed by the low nibble, so FA..FF never appear inside a frame.
The LRC is the two's complement of the 8-bit sum of the raw data.

The clone image is the radio's whole read/write window of its SPI flash,
0x8000-0x21000. Offsets in MEM_FORMAT are relative to 0x8000.
"""

import logging
import struct

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import MemSetting, RadioSetting, RadioSettingGroup
from chirp.settings import RadioSettings, RadioSettingValueBoolean
from chirp.settings import RadioSettingValueInteger, RadioSettingValueList
from chirp.settings import RadioSettingValueString

LOG = logging.getLogger(__name__)

MODEL_ID = b"UVL-15W"
FLASH_START = 0x8000
FLASH_END = 0x21000
MEM_SIZE = FLASH_END - FLASH_START
READ_BLOCK = 0x800
WRITE_BLOCK = 0x200
RETRIES = 3

CMD_INFO = 0xE0
CMD_INFO_RESP = 0xE1
CMD_READ_START = 0xE2
CMD_WRITE_START = 0xE3
CMD_WRITE = 0xE4
CMD_FINISH = 0xE5
CMD_READ = 0xE6
CMD_ERROR = 0xEE

NUM_CHANNELS = 1000
GROUP_SLOTS = 128
VFOS = ["VFO A", "VFO B"]
WX_CHANNELS = ["WX%i" % i for i in range(1, 11)]
SPECIALS = VFOS + WX_CHANNELS

MEM_FORMAT = """
struct channel {
  u32 rxfreq;
  u32 txfreq;
  char name[24];
  u32 offset;
  u8 step:4,
     reverse:2,
     duplex:2;
  u8 bcl:2,
     rxonly:1,
     power:2,
     mode:3;
  u8 txtone_type:3,
     sql_type:3,
     unknown26:2;
  u8 unknown27:1,
     compander:2,
     dcs_pol:2,
     rxtone_type:3;
  u8 txtone;
  u8 rxtone;
  u8 sig_type;
  u8 sig_index;
  u8 scramble;
  u8 pttid;
  u8 aprs_rx;
  u8 reserved;
};

#seekto 0x0000;
struct channel memory[1000];

#seekto 0xBB80;
struct channel vfo[2];

#seekto 0xBC40;
struct channel temp[2];

#seekto 0xBCA0;
struct channel wx[10];

#seekto 0xD000;
lbit valid[1024];

#seekto 0xD080;
u8 scanflags[256];

#seekto 0xD300;
struct {
  u8 unknown0[7];
  u8 a_mode;
  u8 b_mode;
  u8 unknown09;
  u16 a_channel;
  u16 b_channel;
} status;

#seekto 0xD400;
struct {
  u8 language;
  u8 unknown01[4];
  u8 unknown05:5,
     show_zone:1,
     show_name:1,
     show_freq:1;
  u8 menu_exit;
  u8 backlight;
  u8 auto_dim;
  u8 auto_dim_delay;
  u8 rx_wake;
  u8 tx_wake;
  u8 ai_denoise;
  u8 vox;
  u8 vox_level;
  u8 vox_delay;
  u8 unknown10[10];
  u8 key_beep;
  u8 low_bat_beep;
  u8 unknown1c;
  u8 unknown1d:6,
     roger_end:1,
     roger_start:1;
  u8 mic_gain;
  u8 power_on_beep;
  u8 unknown20[5];
  u8 theme;
  u8 unknown26[4];
  u8 tot_beep;
  u8 bat_display;
  u8 rx_led;
  u8 rssi;
  u8 standby_led;
  u8 unknown2f;
  u8 dual_mode;
  u8 cross_mode;
  u8 squelch;
  u8 tot;
  u8 tx_channel;
  u8 hang_time;
  u8 tail_ctcss;
  u8 tail_dcs;
  u8 tail_carrier;
  u8 tail_time;
  u8 tbst_time;
  u8 tbst_freq;
  u8 tbst_sidetone;
  u8 scan_mode;
  u8 mr_scan_type;
  u8 cross_monitor;
  u8 unknown40[32];
  u8 boot_logo;
  u8 boot_fw;
  u8 boot_msg_on;
  u8 boot_voltage;
  char boot_msg[50];
  u8 unknown96[26];
  u8 save_mode;
  u8 save_delay;
} settings;
"""

# Zone and scan list areas. Each zone or scan list has an ordered list of
# up to 128 channels (0-based, FFFF for unused), and each channel has an
# inverted bitmap of the zones and scan lists it belongs to.
# On layout 2 the channel lists are big-endian and the bitmaps
# little-endian (seen on a radio). TYT's document says the layout 1 lists
# are little-endian.
# Layout 1 (firmware 3.03.x) is from TYT's storage document; layout 2
# (firmware 3.09.x) was found by setting zones in TYT's V3.09.21 software.
GROUP_FORMATS = {
    1: """
#seekto 0x10000;
struct {
  ul16 slot[128];
} zone_members[16];

#seekto 0x11000;
struct {
  ul16 slot[128];
} scan_members[16];

#seekto 0x12000;
ul16 ch_zones[1000];

#seekto 0x12800;
ul16 ch_scans[1000];

#seekto 0x13000;
struct {
  u8 name[24];
} zone_names[16];

#seekto 0x13400;
struct {
  u8 name[24];
} scan_names[16];
""",
    2: """
#seekto 0x10000;
struct {
  u16 slot[128];
} zone_members[32];

#seekto 0x12000;
struct {
  u16 slot[128];
} scan_members[32];

#seekto 0x14000;
ul32 ch_zones[1000];

#seekto 0x15000;
ul32 ch_scans[1000];

#seekto 0x16000;
struct {
  u8 name[24];
} zone_names[32];

#seekto 0x16500;
struct {
  u8 name[24];
} scan_names[32];
""",
}
GROUP_COUNTS = {1: 16, 2: 32}


POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                chirp_common.PowerLevel("Mid", watts=5.00),
                chirp_common.PowerLevel("High", watts=15.00)]
MODES = ["FM", "NFM", "AM", "NAM"]
STEPS = [2.5, 3.125, 5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0,
         100.0]
DUPLEXES = ["", "-", "+", "split"]
TONES = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
         94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
         131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9,
         171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
         203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1]
DTCS_CODES = [
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74,
    114, 115, 116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162,
    165, 172, 174, 205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325, 331, 332, 343,
    346, 351, 356, 364, 365, 371, 411, 412, 413, 423, 431, 432, 445, 446,
    452, 454, 455, 462, 464, 465, 466, 503, 506, 516, 523, 526, 532, 546,
    565, 606, 612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723, 731,
    732, 734, 743, 754]
# dcs_pol field: 0=TX N/RX N, 1=TX N/RX R, 2=TX R/RX N, 3=TX R/RX R
DCS_POLARITY = ["NN", "NR", "RN", "RR"]
# rxtone_type field: 0=off 1=CTCSS 2=DCS 3=CTCSS (reverse) 4=DCS (reverse)
SQL_CARRIER = 0
SQL_TONE = 1
# Squelch types that use the tone decoder: tone, tone and signal, tone or
# signal. Type 2 (optional signalling only) ignores the decode tone.
SQL_WITH_TONE = (1, 3, 4)
BCL = ["Off", "Repeater", "Carrier"]
SCRAMBLE = ["Off", "2700", "2800", "2900", "3000", "3100", "3200", "3300",
            "3400"]
COMPANDER = ["Off", "TX", "RX", "TX/RX"]
PTTID = ["Off"] + ["%i" % i for i in range(8)]
APRS_RX = ["Off", "On", "On (mute)"]
REVERSE = ["Off", "Talkaround", "Reverse"]
SKIP_VALUES = ["", "S", "P"]

LANGUAGES = ["Simplified Chinese", "Traditional Chinese", "English",
             "Turkish"]
LEVELS9 = ["%i" % i for i in range(1, 10)]
OFF_ON = ["Off", "On"]
TOT = ["Off"] + ["%i min" % i for i in range(1, 11)] + [
    "15 min", "20 min", "25 min", "30 min"]
MENU_EXIT = ["Off"] + ["%i s" % i for i in range(5, 16)] + [
    "%i s" % i for i in range(20, 60, 5)] + [
    "%i min" % i for i in range(1, 11)]
AUTO_DIM = ["Off", "Auto off"] + ["Dim level %i" % i for i in range(1, 9)]
DUAL_MODES = ["Single", "Dual watch, single TX", "Dual RX, single TX",
              "Cross-band repeat"]
WORK_MODES = ["Memory", "Frequency", "Call", "Weather"]
SCAN_MODES = ["Carrier", "Time", "Search"]
TBST_FREQS = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
THEMES = ["White", "Black"]
BAT_DISPLAY = ["Icon", "Voltage", "Icon and voltage"]
RSSI = ["Off", "dBm", "S-meter/dBm"]
MIC_GAIN = ["Low", "Medium", "High"] + ["%i" % i for i in range(32)]
SAVE_DELAY = ["%i s" % i for i in range(3, 11)] + [
    "%i s" % i for i in range(12, 21, 2)] + [
    "%i s" % i for i in range(25, 61, 5)] + [
    "%i s" % i for i in range(70, 121, 10)] + [
    "%i s" % i for i in range(150, 301, 30)]


def _escape(data):
    out = bytearray()
    for byte in data:
        temp = (byte + 0x80) & 0xFF
        if temp > 0xF9:
            out += bytes([0xFF, temp & 0x0F])
        else:
            out.append(temp)
    return bytes(out)


def _unescape(data):
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0xFF:
            if i + 1 >= len(data):
                raise errors.RadioError("Truncated escape in response")
            out.append((0xF0 + data[i + 1] + 0x80) & 0xFF)
            i += 2
        else:
            out.append((data[i] + 0x80) & 0xFF)
            i += 1
    return bytes(out)


def _lrc(data):
    return (0x100 - (sum(data) & 0xFF)) & 0xFF


def _make_frame(cmd, data=b""):
    return (b"\xFE\xFE\xEE\xEF" + bytes([cmd]) +
            _escape(data + bytes([_lrc(data)])) + b"\xFD")


def _parse_frame(frame):
    """Return (cmd, data) from a response frame ending in FD"""
    frame = frame.lstrip(b"\xFE")
    if len(frame) < 5 or frame[:2] != b"\xEF\xEE" or frame[-1] != 0xFD:
        raise errors.RadioError("Malformed response from radio")
    cmd = frame[2]
    payload = _unescape(frame[3:-1])
    if not payload or sum(payload) & 0xFF:
        raise errors.RadioError("Bad checksum in response from radio")
    return cmd, payload[:-1]


def _recv_frame(radio):
    pipe = radio.pipe
    frame = b""
    # Worst case is a read block with every byte escaped, plus framing
    for _i in range(2 * (READ_BLOCK + 8) + 64):
        byte = pipe.read(1)
        if not byte:
            if not frame:
                raise errors.RadioNoResponse()
            raise errors.RadioError("Timeout waiting for radio response")
        if not frame and byte != b"\xFE":
            # Discard noise before the preamble
            continue
        frame += byte
        if byte == b"\xFD":
            return _parse_frame(frame)
    raise errors.RadioError("Radio sent an overlong or garbled response")


def _command(radio, cmd, data=b"", expect=None):
    for attempt in range(RETRIES):
        radio.pipe.write(_make_frame(cmd, data))
        try:
            rcmd, rdata = _recv_frame(radio)
        except errors.RadioNoResponse:
            raise
        except errors.RadioError as e:
            LOG.warning("Command %02X attempt %i failed: %s",
                        cmd, attempt + 1, e)
            continue
        if rcmd == CMD_ERROR:
            msg = rdata.decode("ascii", "replace")
            LOG.warning("Radio error for command %02X: %s", cmd, msg)
            if "Lrc" in msg or "Frame" in msg:
                continue
            raise errors.RadioError("Radio reported error: %s" % msg)
        if expect is not None and rcmd != expect:
            raise errors.RadioError(
                "Unexpected response %02X to command %02X" % (rcmd, cmd))
        return rdata
    raise errors.RadioError("Radio did not accept command %02X" % cmd)


def _identify(radio):
    radio.pipe.timeout = 2
    info = _command(radio, CMD_INFO, MODEL_ID, expect=CMD_INFO_RESP)
    LOG.debug("Radio info: %r", info)
    if not info.startswith(MODEL_ID):
        raise errors.RadioError("Radio is not a UVL-15W: %r" % info[:16])
    return info


def _check_password(info, offset, op):
    if len(info) > offset and info[offset]:
        raise errors.RadioError(
            "The radio has a %s password set. Remove it from the radio "
            "before using CHIRP." % op)


def _range_data():
    # The end address is inclusive. TYT's older software sent 0x21000 here,
    # which can make the radio erase the flash sector after the data area,
    # where the menu icons live; their V3.09.21 software sends 0x20FFF.
    return struct.pack(">II", FLASH_START, FLASH_END - 1)


def _expect_text(data, text):
    if text not in data:
        raise errors.RadioError("Radio refused: %r" % data)


def _finish(radio, text):
    try:
        _command(radio, CMD_FINISH, text)
    except errors.RadioError as e:
        # The radio reboots after this; a missed reply does no harm
        LOG.warning("No reply to finish command: %s", e)


def do_download(radio):
    info = _identify(radio)
    _check_password(info, 10, "read")
    radio.metadata = {"uvl15w_version":
                      info[12:20].decode("ascii", "replace").strip("\x00")}
    _expect_text(_command(radio, CMD_READ_START, _range_data()),
                 b"READ START OK")

    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.max = MEM_SIZE
    data = b""
    radio.pipe.timeout = 5
    for addr in range(FLASH_START, FLASH_END, READ_BLOCK):
        size = min(READ_BLOCK, FLASH_END - addr)
        req = struct.pack(">IH", addr, size)
        resp = _command(radio, CMD_READ, req, expect=CMD_WRITE)
        if resp[:6] != req or len(resp) != 6 + size:
            raise errors.RadioError("Bad block from radio at %06x" % addr)
        data += resp[6:]
        status.cur = len(data)
        radio.status_fn(status)

    _finish(radio, b"Read Complete")
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    info = _identify(radio)
    _check_password(info, 11, "write")
    radio._prepare_upload()
    _expect_text(_command(radio, CMD_WRITE_START, _range_data()),
                 b"WRITE START OK")

    status = chirp_common.Status()
    status.msg = "Cloning to radio"
    status.max = MEM_SIZE
    mmap = radio.get_mmap().get_byte_compatible()
    radio.pipe.timeout = 5
    for offset in range(0, MEM_SIZE, WRITE_BLOCK):
        addr = FLASH_START + offset
        block = mmap[offset:offset + WRITE_BLOCK]
        hdr = struct.pack(">IH", addr, len(block))
        resp = _command(radio, CMD_WRITE, hdr + block)
        if not resp.startswith(b"WF OK") or resp[5:11] != hdr:
            raise errors.RadioError("Radio refused block at %06x" % addr)
        status.cur = offset + len(block)
        radio.status_fn(status)

    _finish(radio, b"Write Complete")


def _decode_name(raw):
    raw = bytes(raw).split(b"\x00")[0]
    if raw[:1] == b"\xFF":
        return ""
    return raw.decode("utf-8", "replace")


class UVL15WZone(chirp_common.NamedBank):
    def get_name(self):
        name = _decode_name(
            self._model._radio._memobj.zone_names[self.index].name)
        return name if name.isprintable() and name else "Zone %i" % (
            self.index)

    def set_name(self, name):
        raw = name.rstrip().encode("utf-8")[:24]
        self._model._radio._memobj.zone_names[self.index].name = \
            raw.ljust(24, b"\x00")


class UVL15WZoneModel(chirp_common.MTOBankModel):
    """Zones. Each channel has an inverted bitmap of the zones it belongs
    to, and each zone has an ordered list of its channels; both are kept
    in step here, as the factory software does."""

    def __init__(self, radio):
        super().__init__(radio, "Zones")

    def _zone(self, index):
        zone = UVL15WZone(self, "%i" % (index + 1), "Zone %i" % (index + 1))
        zone.index = index
        return zone

    def get_num_mappings(self):
        return GROUP_COUNTS[self._radio._layout()]

    def get_mappings(self):
        return [self._zone(i) for i in range(self.get_num_mappings())]

    def add_memory_to_mapping(self, memory, zone):
        self._radio._group_add("zone", self._ch(memory), zone.index)

    def remove_memory_from_mapping(self, memory, zone):
        ch = self._ch(memory)
        if zone.index not in self._radio._channel_groups("zone", ch):
            raise errors.RadioError("Memory %i is not in zone %s" % (
                memory.number, zone.get_name()))
        self._radio._group_remove("zone", ch, zone.index)

    def get_mapping_memories(self, zone):
        return [self._radio.get_memory(ch + self._radio.FIRST_CHANNEL)
                for ch in self._radio._group_list("zone", zone.index)]

    def get_memory_mappings(self, memory):
        return [self._zone(z) for z in
                self._radio._channel_groups("zone", self._ch(memory))]

    def _ch(self, memory):
        return memory.number - self._radio.FIRST_CHANNEL


@directory.register
class UVL15WRadio(chirp_common.CloneModeRadio):
    """TYT UVL-15W"""
    VENDOR = "TYT"
    MODEL = "UVL-15W"
    BAUD_RATE = 115200
    NEEDS_COMPAT_SERIAL = False

    # The radio and TYT's software number channels from 0
    FIRST_CHANNEL = 0

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            "This driver is built from TYT's published protocol and memory "
            "layout and has not yet been tested widely. Save a copy of a "
            "fresh download from your radio before uploading. The radio "
            "restarts at the end of every download and upload.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        # Zones and settings are only mapped for known layouts
        known = self._layout() in GROUP_COUNTS
        rf.has_settings = known
        rf.has_bank = known
        rf.has_bank_names = known
        rf.has_name = True
        rf.has_tuning_step = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_dtcs_polarity = True
        rf.can_odd_split = True
        rf.valid_name_length = 16
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS",
                                "Tone->DTCS", "DTCS->Tone", "->Tone",
                                "DTCS->DTCS"]
        rf.valid_tones = list(TONES)
        rf.valid_dtcs_codes = list(DTCS_CODES)
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = list(SKIP_VALUES)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(108000000, 174000000), (400000000, 520000000)]
        rf.memory_bounds = (self.FIRST_CHANNEL,
                            self.FIRST_CHANNEL + NUM_CHANNELS - 1)
        rf.valid_special_chans = list(SPECIALS)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Download failed")
            raise errors.RadioError("Failed to download: %s" % e)
        self.process_mmap()

    def sync_out(self):
        # The image holds the radio's whole data area, including parts we
        # do not understand, so only write back an image read from a radio
        if "uvl15w_version" not in self.metadata:
            raise errors.RadioError(
                "This image was not downloaded from a UVL-15W. Download "
                "from your radio first, then copy channels into that image "
                "and upload it.")
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Upload failed")
            raise errors.RadioError("Failed to upload: %s" % e)

    def _prepare_upload(self):
        # The factory software mirrors VFO A/B to Temp A/B on every upload
        self._memobj.temp[0].set_raw(self._memobj.vfo[0].get_raw())
        self._memobj.temp[1].set_raw(self._memobj.vfo[1].get_raw())

    def process_mmap(self):
        self._layout_version = self._detect_layout()
        if self._layout_version == 0:
            raise errors.RadioError(
                "This image's data layout is not one CHIRP knows")
        self._memobj = bitwise.parse(
            MEM_FORMAT + GROUP_FORMATS.get(self._layout_version, ""),
            self._mmap)

    def _layout(self):
        if self._mmap is None:
            return 1
        return self._layout_version

    def _detect_layout(self):
        """Return the data layout version, 0 if unknown.

        Firmware 3.03.x stores "EDG1" version 1 at 0x1BB00, matching TYT's
        storage document. Firmware 3.09.x moved the zone and scan list
        areas and stores "EDG1" version 2 at 0x1EB00."""
        data = self._mmap.get_byte_compatible()
        if data[0x13B00:0x13B05] == b"EDG1\x01":
            return 1
        if data[0x16B00:0x16B05] == b"EDG1\x02":
            return 2
        if data[0x13B00:0x13B05] == b"\xFF" * 5:
            # Never-written block, as on a factory-fresh image
            return 1
        return 0

    def _resolve(self, number):
        """Return (channel index or None for a special, record, number)"""
        if isinstance(number, str):
            special = SPECIALS.index(number)
        else:
            special = number - self.FIRST_CHANNEL - NUM_CHANNELS
        if special >= len(VFOS):
            return (None, self._memobj.wx[special - len(VFOS)],
                    self.FIRST_CHANNEL + NUM_CHANNELS + special)
        if special >= 0:
            return (None, self._memobj.vfo[special],
                    self.FIRST_CHANNEL + NUM_CHANNELS + special)
        ch = number - self.FIRST_CHANNEL
        return ch, self._memobj.memory[ch], number

    def get_raw_memory(self, number):
        return repr(self._resolve(number)[1])

    def get_bank_model(self):
        if self._layout() not in GROUP_COUNTS:
            return None
        return UVL15WZoneModel(self)

    # Zone and scan list membership helpers. kind is "zone" or "scan";
    # ch and group are 0-based.

    def _groups(self, kind):
        return (getattr(self._memobj, "%s_members" % kind),
                getattr(self._memobj, "ch_%ss" % kind))

    def _channel_groups(self, kind, ch):
        bits = ~int(self._groups(kind)[1][ch])
        return [g for g in range(GROUP_COUNTS[self._layout()])
                if bits & (1 << g)]

    def _group_list(self, kind, group):
        slots = self._groups(kind)[0][group].slot
        return [int(s) for s in slots if int(s) < NUM_CHANNELS]

    def _set_group_list(self, kind, group, channels):
        slots = self._groups(kind)[0][group].slot
        for i in range(GROUP_SLOTS):
            slots[i] = channels[i] if i < len(channels) else 0xFFFF

    def _group_add(self, kind, ch, group):
        members = self._group_list(kind, group)
        if ch not in members:
            if len(members) >= GROUP_SLOTS:
                raise errors.RadioError("%s %i is full" % (
                    kind.title(), group + 1))
            self._set_group_list(kind, group, members + [ch])
        bitmaps = self._groups(kind)[1]
        bitmaps[ch] = int(bitmaps[ch]) & ~(1 << group)

    def _group_remove(self, kind, ch, group):
        self._set_group_list(
            kind, group,
            [c for c in self._group_list(kind, group) if c != ch])
        bitmaps = self._groups(kind)[1]
        bitmaps[ch] = int(bitmaps[ch]) | (1 << group)

    def _clear_groups(self, ch):
        if self._layout() not in GROUP_COUNTS:
            return
        for kind in ("zone", "scan"):
            for group in self._channel_groups(kind, ch):
                self._group_remove(kind, ch, group)

    def _get_skip(self, ch):
        return (int(self._memobj.scanflags[ch // 4]) >> (2 * (ch % 4))) & 3

    def _set_skip(self, ch, value):
        shift = 2 * (ch % 4)
        flags = int(self._memobj.scanflags[ch // 4]) & ~(3 << shift)
        self._memobj.scanflags[ch // 4] = flags | (value << shift)

    def _get_tone(self, kind, index, pol):
        if kind in (1, 3) and index < len(TONES):
            return "Tone", TONES[index], None
        if kind in (2, 4) and index < len(DTCS_CODES):
            return "DTCS", DTCS_CODES[index], pol
        return "", None, None

    def get_memory(self, number):
        ch, _mem, number = self._resolve(number)
        mem = chirp_common.Memory()
        mem.number = number
        if ch is None:
            mem.extd_number = SPECIALS[number - self.FIRST_CHANNEL -
                                       NUM_CHANNELS]
            if mem.extd_number in WX_CHANNELS:
                # Receive-only weather channels with fixed names
                mem.name = _decode_name(_mem.name.get_raw()).rstrip()
            mem.immutable = ["name", "skip", "empty"]
        elif not self._memobj.valid[ch]:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq)
        if ch is not None:
            mem.name = _decode_name(_mem.name.get_raw()).rstrip()
        txfreq = int(_mem.txfreq)
        duplex = int(_mem.duplex)
        if _mem.rxonly:
            mem.duplex = "off"
        elif duplex in (1, 2):
            mem.duplex = DUPLEXES[duplex]
            mem.offset = int(_mem.offset)
        elif duplex == 3 or txfreq != mem.freq:
            chirp_common.split_to_offset(mem, mem.freq, txfreq)

        mem.mode = MODES[_mem.mode] if _mem.mode < len(MODES) else "FM"
        mem.power = POWER_LEVELS[min(int(_mem.power), 2)]
        if _mem.step < len(STEPS):
            mem.tuning_step = STEPS[_mem.step]

        pol = DCS_POLARITY[_mem.dcs_pol]
        txtone = self._get_tone(_mem.txtone_type, _mem.txtone, pol[0])
        rxtone = ("", None, None)
        if _mem.sql_type in SQL_WITH_TONE:
            rxtone = self._get_tone(_mem.rxtone_type, _mem.rxtone, pol[1])
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        if ch is not None:
            skip = self._get_skip(ch)
            mem.skip = SKIP_VALUES[skip] if skip < len(SKIP_VALUES) else ""

        mem.extra = RadioSettingGroup("extra", "Extra")
        mem.extra.append(MemSetting(
            "bcl", "Busy channel lockout",
            RadioSettingValueList(BCL, current_index=min(int(_mem.bcl), 2))))
        mem.extra.append(MemSetting(
            "reverse", "Talkaround/reverse",
            RadioSettingValueList(REVERSE,
                                  current_index=min(int(_mem.reverse), 2))))
        mem.extra.append(MemSetting(
            "compander", "Compander",
            RadioSettingValueList(COMPANDER,
                                  current_index=int(_mem.compander))))
        mem.extra.append(MemSetting(
            "scramble", "Scrambler",
            RadioSettingValueList(SCRAMBLE,
                                  current_index=min(int(_mem.scramble), 8))))
        pttid = int(_mem.pttid) & 0x0F
        mem.extra.append(RadioSetting(
            "pttid", "PTT ID",
            RadioSettingValueList(PTTID, current_index=min(pttid, 8))))
        aprs = int(_mem.aprs_rx) & 0x03
        mem.extra.append(RadioSetting(
            "aprs_rx", "APRS receive",
            RadioSettingValueList(APRS_RX, current_index=min(aprs, 2))))
        if ch is not None and self._layout() in GROUP_COUNTS:
            # One scan list per channel here; a channel the factory
            # software put in several lists shows the first of them.
            lists = self._channel_groups("scan", ch)
            mem.extra.append(RadioSetting(
                "scanlist", "Scan list",
                RadioSettingValueList(
                    self._scan_list_choices(),
                    current_index=lists[0] + 1 if lists else 0)))
        return mem

    def _scan_list_choices(self):
        choices = ["None"]
        for i in range(GROUP_COUNTS[self._layout()]):
            name = _decode_name(self._memobj.scan_names[i].name)
            if not name.isprintable():
                name = ""
            choices.append(("%i: %s" % (i, name)).rstrip(": "))
        return choices

    def _set_scan_list(self, ch, index):
        lists = self._channel_groups("scan", ch)
        current = lists[0] + 1 if lists else 0
        if index == current:
            return
        for group in lists:
            self._group_remove("scan", ch, group)
        if index:
            self._group_add("scan", ch, index - 1)

    def _set_tone(self, mode, value, pol):
        if mode == "Tone":
            return 1, TONES.index(value)
        if mode == "DTCS":
            return 2, DTCS_CODES.index(value)
        return 0, 0

    def set_memory(self, mem):
        ch, _mem, number = self._resolve(mem.extd_number or mem.number)
        if ch is None:
            pass
        elif mem.empty:
            self._memobj.valid[ch] = False
            _mem.fill_raw(b"\x00")
            # Unused channels have both scan bits set
            self._set_skip(ch, 3)
            self._clear_groups(ch)
            return

        elif not self._memobj.valid[ch]:
            _mem.fill_raw(b"\x00")
            self._clear_groups(ch)
            _mem.step = STEPS.index(12.5)
            _mem.power = 2
            # The radio keeps a default 600 kHz offset on simplex channels
            _mem.offset = 600000
        if ch is not None:
            self._memobj.valid[ch] = True
            _mem.name = mem.name.ljust(24, "\x00")[:24]

        _mem.rxfreq = mem.freq
        _mem.rxonly = mem.duplex == "off"
        if mem.duplex in ("+", "-"):
            _mem.duplex = DUPLEXES.index(mem.duplex)
            _mem.offset = mem.offset
            if mem.duplex == "+":
                _mem.txfreq = mem.freq + mem.offset
            else:
                _mem.txfreq = mem.freq - mem.offset
        elif mem.duplex == "split":
            _mem.duplex = 3
            _mem.txfreq = mem.offset
            _mem.offset = abs(mem.offset - mem.freq)
        else:
            _mem.duplex = 0
            _mem.txfreq = mem.freq

        _mem.mode = MODES.index(mem.mode)
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 2
        if mem.tuning_step in STEPS:
            _mem.step = STEPS.index(mem.tuning_step)

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)
        _mem.txtone_type, _mem.txtone = self._set_tone(txmode, txval, txpol)
        _mem.rxtone_type, _mem.rxtone = self._set_tone(rxmode, rxval, rxpol)
        _mem.dcs_pol = DCS_POLARITY.index(
            "%s%s" % (txpol or "N", rxpol or "N"))
        # The radio's per-channel SQL control has to be on Tone for it to
        # send the encode tone as well as to decode (seen on a radio)
        if (txmode or rxmode) and _mem.sql_type not in SQL_WITH_TONE:
            _mem.sql_type = SQL_TONE
        elif not (txmode or rxmode) and _mem.sql_type in SQL_WITH_TONE:
            _mem.sql_type = SQL_CARRIER

        if ch is not None:
            self._set_skip(ch, SKIP_VALUES.index(mem.skip or ""))

        for setting in mem.extra or []:
            if not self._own_extra(setting):
                # Copied from another radio's memory; not ours to apply
                continue
            if setting.get_name() == "pttid":
                _mem.pttid = (int(_mem.pttid) & 0xF0) | int(setting.value)
            elif setting.get_name() == "aprs_rx":
                _mem.aprs_rx = (int(_mem.aprs_rx) & 0xFC) | int(
                    setting.value)
            elif setting.get_name() == "scanlist":
                if ch is not None:
                    self._set_scan_list(ch, int(setting.value))
            else:
                setting.apply_to_memobj(_mem)

    @staticmethod
    def _own_extra(setting):
        options = {"bcl": BCL, "reverse": REVERSE, "compander": COMPANDER,
                   "scramble": SCRAMBLE, "pttid": PTTID, "aprs_rx": APRS_RX}
        name = setting.get_name()
        if not isinstance(setting.value, RadioSettingValueList):
            return False
        if name == "scanlist":
            return True
        return options.get(name) == setting.value.get_options()

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty or mem.duplex == "off":
            return msgs
        txfreq = mem.freq
        if mem.duplex == "+":
            txfreq += mem.offset
        elif mem.duplex == "-":
            txfreq -= mem.offset
        elif mem.duplex == "split":
            txfreq = mem.offset
        if not (136000000 <= txfreq < 174000000 or
                400000000 <= txfreq < 480000000):
            msgs.append(chirp_common.ValidationWarning(
                _("Transmit frequency is outside the radio's transmit "
                  "bands and may be refused by the radio")))
        return msgs

    def _add(self, group, setting):
        if setting is not None:
            group.append(setting)

    # A value outside the documented choices means this firmware uses the
    # byte differently, so leave it alone rather than offer to change it.

    def _list(self, path, name, choices, obj):
        current = int(obj)
        if current >= len(choices):
            LOG.debug("Skipping %s: unexpected value %i", path, current)
            return None
        return MemSetting(path, name,
                          RadioSettingValueList(choices,
                                                current_index=current))

    def _bool(self, path, name, obj):
        if int(obj) > 1:
            LOG.debug("Skipping %s: unexpected value %i", path, int(obj))
            return None
        return MemSetting(path, name, RadioSettingValueBoolean(int(obj)))

    def get_settings(self):
        _s = self._memobj.settings
        _st = self._memobj.status

        func = RadioSettingGroup("func", "Function")
        self._add(func, self._list(
            "settings.dual_mode", "Dual mode", DUAL_MODES, _s.dual_mode))
        self._add(func, self._list(
            "status.a_mode", "Side A mode", WORK_MODES, _st.a_mode))
        self._add(func, self._list(
            "status.b_mode", "Side B mode", WORK_MODES, _st.b_mode))
        for side in "ab":
            current = int(getattr(_st, "%s_channel" % side))
            if current < NUM_CHANNELS:
                func.append(RadioSetting(
                    "%s_channel" % side,
                    "Side %s memory channel" % side.upper(),
                    RadioSettingValueInteger(
                        self.FIRST_CHANNEL,
                        self.FIRST_CHANNEL + NUM_CHANNELS - 1,
                        current + self.FIRST_CHANNEL)))
        self._add(func, self._list(
            "settings.squelch", "Squelch level", LEVELS9, _s.squelch))
        self._add(func, self._list(
            "settings.tot", "Transmit timeout", TOT, _s.tot))
        self._add(func, self._list(
            "settings.scan_mode", "Scan resume", SCAN_MODES, _s.scan_mode))
        self._add(func, self._list(
            "settings.tbst_freq", "Tone burst frequency", TBST_FREQS,
            _s.tbst_freq))
        self._add(func, self._bool(
            "settings.save_mode", "Battery save", _s.save_mode))
        self._add(func, self._list(
            "settings.save_delay", "Battery save delay", SAVE_DELAY,
            _s.save_delay))

        disp = RadioSettingGroup("display", "Display")
        self._add(disp, self._list(
            "settings.language", "Language", LANGUAGES, _s.language))
        self._add(disp, self._list(
            "settings.theme", "Theme", THEMES, _s.theme))
        self._add(disp, self._list(
            "settings.backlight", "Backlight level", LEVELS9, _s.backlight))
        self._add(disp, self._list(
            "settings.auto_dim", "Auto dim", AUTO_DIM, _s.auto_dim))
        self._add(disp, self._list(
            "settings.menu_exit", "Menu auto exit", MENU_EXIT, _s.menu_exit))
        self._add(disp, self._bool(
            "settings.show_freq", "Show channel frequency", _s.show_freq))
        self._add(disp, self._bool(
            "settings.show_name", "Show channel name", _s.show_name))
        self._add(disp, self._bool(
            "settings.show_zone", "Show zone name", _s.show_zone))
        self._add(disp, self._list(
            "settings.bat_display", "Battery display", BAT_DISPLAY,
            _s.bat_display))
        self._add(disp, self._list(
            "settings.rssi", "Signal strength", RSSI, _s.rssi))
        self._add(disp, self._bool(
            "settings.boot_logo", "Show boot logo", _s.boot_logo))
        self._add(disp, self._bool(
            "settings.boot_msg_on", "Show boot message", _s.boot_msg_on))
        msg = _decode_name(_s.boot_msg.get_raw())
        if not msg.isprintable():
            msg = ""
        disp.append(RadioSetting(
            "boot_msg", "Boot message",
            RadioSettingValueString(0, 50, msg, autopad=False,
                                    charset=chirp_common.CHARSET_ASCII)))

        audio = RadioSettingGroup("audio", "Audio")
        self._add(audio, self._bool(
            "settings.key_beep", "Key beep", _s.key_beep))
        self._add(audio, self._bool(
            "settings.low_bat_beep", "Low battery beep", _s.low_bat_beep))
        self._add(audio, self._bool(
            "settings.power_on_beep", "Power on beep", _s.power_on_beep))
        self._add(audio, self._bool(
            "settings.tot_beep", "Timeout beep", _s.tot_beep))
        self._add(audio, self._bool(
            "settings.roger_start", "Talk start beep", _s.roger_start))
        self._add(audio, self._bool(
            "settings.roger_end", "Talk end beep", _s.roger_end))
        self._add(audio, self._list(
            "settings.mic_gain", "Mic gain", MIC_GAIN, _s.mic_gain))
        self._add(audio, self._bool(
            "settings.vox", "VOX", _s.vox))
        self._add(audio, self._bool(
            "settings.ai_denoise", "AI noise reduction", _s.ai_denoise))

        groups = [func, disp, audio]
        if self._layout() in GROUP_COUNTS:
            for kind, title in (("zone", "Zones"), ("scan", "Scan lists")):
                group = RadioSettingGroup(kind, title)
                names = getattr(self._memobj, "%s_names" % kind)
                for i in range(GROUP_COUNTS[self._layout()]):
                    name = _decode_name(names[i].name)
                    if not name.isprintable():
                        name = ""
                    group.append(RadioSetting(
                        "%s_name_%i" % (kind, i), "%s %i name" % (
                            "Zone" if kind == "zone" else "Scan list", i),
                        RadioSettingValueString(
                            0, 24, name, autopad=False,
                            charset=chirp_common.CHARSET_ASCII)))
                groups.append(group)
        return RadioSettings(*groups)

    def set_settings(self, settings):
        for element in settings.apply_to(self._memobj):
            if element.get_name() in ("a_channel", "b_channel"):
                setattr(self._memobj.status, element.get_name(),
                        int(element.value) - self.FIRST_CHANNEL)
            elif element.get_name() == "boot_msg":
                raw = str(element.value).encode("ascii")[:50]
                self._memobj.settings.boot_msg = raw.ljust(50, b"\x00")
            elif element.get_name()[4:10] == "_name_":
                kind, i = element.get_name().split("_name_")
                names = getattr(self._memobj, "%s_names" % kind)
                raw = str(element.value).rstrip().encode("ascii")[:24]
                names[int(i)].name = raw.ljust(24, b"\x00")
