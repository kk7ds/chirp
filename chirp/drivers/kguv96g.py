# Copyright 2026 Rich Dunajewski <rich@mygmrs.com>
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

"""Wouxun KG-UV96G radio management module.

The protocol and memory layout were worked out by observing the serial
traffic between the radio and the OEM "KG-R96 Commander" software (v1.0.1),
using the KG-935G driver as the starting point, and confirmed on a radio
running firmware VB1.02.

The transport is the KG-935G one (0x7C frames, 0x57 chained XOR). This radio
does not answer the KG-935G identify command; instead the model string "T3"
is read from the factory block at 0x0340.
"""

import logging
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.drivers import kg935g
from chirp.settings import (
    MemSetting, RadioSetting, RadioSettingGroup, RadioSettings,
    RadioSettingSubGroup, RadioSettingValueBoolean, RadioSettingValueFloat,
    RadioSettingValueInteger, RadioSettingValueMap, RadioSettingValueString)

LOG = logging.getLogger(__name__)

BLOCK_SIZE = 64
MEM_SIZE = 0x3800
MEM_VALID = 0x9E
MODEL_ID = b"T3"

FACTORY_BLOCK = (0x0340, 224)
# The whole memory is downloaded, but uploads only write the regions the
# OEM software writes, in the same order. The factory block is never written.
WRITE_REGIONS = [
    (0x0420, 192),   # settings
    (0x0540, 32),    # VFO A/B
    (0x05E0, 6416),  # channels 0-400 (0 unused)
    (0x1F00, 4812),  # channel names
    (0x3200, 401),   # channel in-use flags
    (0x3700, 40),    # FM broadcast presets
    (0x3400, 126),   # call codes
    (0x3500, 252),   # call names
]

MEM_FORMAT = """
#seekto 0x0340;
struct {
  char brand[12];
  char area[12];
  char city[12];
  char factory_no[8];
  char date[10];
  char model[16];
  char firmware[16];
  u8 voice_lang[3];
  u8 step_2k5;
  u8 band_set[2];
  ul32 rx_limits[4];
} factory;

#seekto 0x0420;
struct {
  u8 menu_avail;
  u8 battery_save;
  u8 roger;
  u8 tot;
  u8 toa;
  u8 vox;
  u8 vox_delay;
  u8 language;
  u8 voice;
  u8 beep;
  u8 scan_mode;
  u8 backlight;
  u8 brightness;
  u8 brightness_stby;
  u8 led_stby;
  u8 ponmsg;
  u8 ptt_id;
  u8 ptt_id_delay;
  u8 sidetone;
  u8 dtmf_tx_time;
  u8 dtmf_interval;
  u8 ring_time;
  u8 alert;
  u8 auto_lock;
  u8 lock_mode;
  ul16 pri_ch;
  u8 pri_scan;
  u8 scan_det;
  u8 sc_qt;
  u8 rpt_tone;
  u8 theme;
  u8 second;
  u8 wx_mode;
  u8 wx_alert;
  u8 wx_alert_type;
  ul16 theme_colors[16];
  u8 mode_switch_code[6];
  u8 init_code[6];
  u8 work_mode[2];
  ul16 work_ch[2];
  ul16 wx_ch;
  u8 work_mode_a_temp;
  u8 step[2];
  u8 squelch[2];
  u8 ptt2;
  u8 pf1_short;
  u8 pf1_long;
  u8 pf2_short;
  u8 pf2_long;
  u8 pf3_short;
  u8 pf3_long;
  u8 ani[6];
  u8 scc[6];
  u8 call_code[6];
  ul16 fm_freq;
  u8 tdr;
  u8 band_local;
  u8 kbd_lock;
  char startup_msg[20];
  char area_msg[20];
  u8 bluetooth;
} settings;

#seekto 0x0540;
struct {
  ul32 freq;
  ul32 offset;
  ul16 rxtone;
  ul16 txtone;
  u8 scramble:4,
     am:2,
     power:2;
  u8 unknown7:1,
     shift:2,
     bcl:1,
     compander:1,
     mute_mode:2,
     wide:1;
  u8 call_group;
  u8 unknown15;
} vfo[2];

#seekto 0x05E0;
struct {
  ul32 rxfreq;
  ul32 txfreq;
  ul16 rxtone;
  ul16 txtone;
  u8 scramble:4,
     am:2,
     power:2;
  u8 unknown7:1,
     unknown6:1,
     scan_add:1,
     bcl:1,
     compander:1,
     mute_mode:2,
     wide:1;
  u8 call_group;
  u8 unknown15;
} memory[401];

#seekto 0x1F00;
struct {
  char name[12];
} names[401];

#seekto 0x3200;
u8 valid[401];

#seekto 0x3400;
struct {
  u8 digits[6];
} call_codes[21];

#seekto 0x3500;
struct {
  char name[8];
} call_names[21];

#seekto 0x3700;
ul16 fm_presets[20];
"""

DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
TUNING_STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
STEP_LIST = ["2.5K", "5K", "6.25K", "8.33K", "10K", "12.5K", "25K", "50K",
             "100K", "1000K"]
OFF_ON = ["Off", "On"]
BOT_EOT = ["Off", "BOT", "EOT", "Both"]
MUTE_MODES = ["QT", "QT+DTMF", "QT*DTMF"]
SCRAMBLE = ["Off"] + ["%d" % i for i in range(1, 9)]
CALL_GROUPS = ["%d" % i for i in range(1, 21)]
WORK_MODES = ["VFO", "Channel number", "Channel frequency", "Channel name"]
KEY_FUNCS = ["Off", "Monitor", "Scan", "Reverse", "Band", "Work mode",
             "Backlight", "TX power", "VOX", "Flashlight", "FM radio",
             "Talkaround", "Second", "Call"]
WX_FREQS = ["162.400", "162.425", "162.450", "162.475", "162.500",
            "162.525", "162.550"]


def _map(options, raw, offset=0):
    """A list value whose memory value is index + offset.

    Out-of-range values in memory show as the first option.
    """
    entries = [(opt, i + offset) for i, opt in enumerate(options)]
    if not offset <= raw < offset + len(options):
        LOG.debug("Out-of-range value %d for %s", raw, options)
        raw = offset
    return RadioSettingValueMap(entries, mem_val=raw)


def _encode(text, length):
    """NUL-padded ASCII bytes for a char[length] field."""
    raw = text.rstrip().encode("ascii", errors="replace")[:length]
    return raw.ljust(length, b"\x00")


def _cstr(value):
    """Turn a bitwise char array into a clean Python string."""
    return str(value).split("\x00")[0].rstrip("\xff").rstrip()


@directory.register
class KGUV96GRadio(kg935g.KG935GRadio):
    """Wouxun KG-UV96G"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV96G"
    BAUD_RATE = 9600

    # Wattage is not printed in the OEM software. 5 W matches Wouxun's
    # marketing for this GMRS handheld; the low setting is an estimate.
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.0),
                    chirp_common.PowerLevel("High", watts=5.0)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver is experimental. Save a backup image from your "
            "radio with CHIRP (and the Wouxun software if you have it) "
            "before uploading any changes.")
        rp.pre_download = (
            "1. Turn the radio off.\n"
            "2. Connect the programming cable.\n"
            "3. Turn the radio on.\n"
            "4. Click OK to download the image from the radio.")
        rp.pre_upload = rp.pre_download.replace(
            "download the image from", "upload the image to")
        return rp

    # ------------------------------------------------------------------
    # Serial protocol (framing and scrambling come from KG935GRadio)

    def _transact(self, cmd, payload, addr, expect=None, tries=8):
        # Right after an upload the radio ignores or garbles requests for a
        # moment, so retry anything that isn't the exact reply we want.
        for attempt in range(tries):
            self._write_record(cmd, payload)
            try:
                cs_error, reply = self._read_record()
            except (errors.RadioError, IndexError) as e:
                LOG.debug("No/bad reply for %02X @%04X (try %d): %s",
                          cmd, addr, attempt + 1, e)
                self.pipe.reset_input_buffer()
                continue
            if (cs_error or len(reply) < 2 or
                    struct.unpack(">H", reply[:2])[0] != addr):
                LOG.debug("Bad reply for %02X @%04X (try %d)",
                          cmd, addr, attempt + 1)
                self.pipe.reset_input_buffer()
                continue
            if expect is not None and len(reply) - 2 != expect:
                LOG.debug("Short reply at %04X (%d of %d bytes)",
                          addr, len(reply) - 2, expect)
                continue
            return reply[2:]
        raise errors.RadioError("Radio did not respond at 0x%04X" % addr)

    def _read_block(self, addr, count):
        return self._transact(kg935g.CMD_RD, struct.pack(">HB", addr, count),
                              addr, expect=count)

    def _write_block(self, addr, data):
        self._transact(kg935g.CMD_WR, struct.pack(">H", addr) + data, addr)

    def _status(self, cur, total, msg):
        if self.status_fn:
            status = chirp_common.Status()
            status.cur = cur
            status.max = total
            status.msg = msg
            self.status_fn(status)

    def _identify(self):
        addr, length = FACTORY_BLOCK
        block = b""
        for off in range(0, length, BLOCK_SIZE):
            block += self._read_block(addr + off,
                                      min(BLOCK_SIZE, length - off))
        model = block[54:70].split(b"\x00")[0]
        if model != MODEL_ID:
            raise errors.RadioError(
                "Radio identified as %r, not a KG-UV96G" % model)
        return block

    def _finish(self):
        try:
            super()._finish()
        except Exception:
            LOG.exception("Failed to send end command")

    def sync_in(self):
        image = b""
        try:
            self._identify()
            for addr in range(0, MEM_SIZE, BLOCK_SIZE):
                image += self._read_block(addr, BLOCK_SIZE)
                self._status(addr + BLOCK_SIZE, MEM_SIZE,
                             "Cloning from radio")
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Download failed")
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            self._finish()
        self._mmap = memmap.MemoryMapBytes(image)
        self.process_mmap()

    def sync_out(self):
        total = sum(n for _, n in WRITE_REGIONS)
        done = 0
        data = self._mmap.get_packed()
        try:
            self._identify()
            for addr, length in WRITE_REGIONS:
                for off in range(0, length, BLOCK_SIZE):
                    n = min(BLOCK_SIZE, length - off)
                    self._write_block(addr + off,
                                      bytes(data[addr + off:addr + off + n]))
                    done += n
                    self._status(done, total, "Cloning to radio")
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Upload failed")
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            self._finish()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # ------------------------------------------------------------------
    # Memories

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "DTCS->", "->Tone", "->DTCS", "DTCS->DTCS"]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 12
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_tuning_steps = TUNING_STEPS
        # RX limits read from the factory block of a US radio.
        rf.valid_bands = [(108000000, 175000000),
                          (400000000, 480000000)]
        rf.memory_bounds = (1, 400)
        return rf

    def get_raw_memory(self, number):
        return (repr(self._memobj.memory[number]) +
                repr(self._memobj.names[number]) +
                "valid: %02X" % self._memobj.valid[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        mem = chirp_common.Memory(number)

        if self._memobj.valid[number] == 0:
            mem.empty = True
            return mem

        rx = int(_mem.rxfreq)
        tx = int(_mem.txfreq)
        if tx in (0, 0xFFFFFFFF):
            mem.freq = rx * 10
            mem.duplex = "off"
        else:
            chirp_common.split_to_offset(mem, rx * 10, tx * 10)

        mem.name = _cstr(self._memobj.names[number].name)
        self.tone_model.get_tone(_mem, mem)
        mem.skip = "" if _mem.scan_add else "S"
        mem.power = self.POWER_LEVELS[min(int(_mem.power), 1)]
        if _mem.am:
            mem.mode = "AM"
        else:
            mem.mode = "FM" if _mem.wide else "NFM"

        mem.extra = RadioSettingGroup("extra", "Extra")
        rs = RadioSetting("am_tx", "AM transmit",
                          RadioSettingValueBoolean(int(_mem.am) == 2))
        rs.set_doc("In AM mode, transmit in AM as well as receive. When off, "
                   "an AM channel receives in AM and transmits in FM.")
        mem.extra.append(rs)
        rs = MemSetting("bcl", "Busy lockout",
                        RadioSettingValueBoolean(bool(_mem.bcl)))
        rs.set_doc("Prevent transmitting while the channel is busy")
        mem.extra.append(rs)
        rs = MemSetting("compander", "Compander",
                        RadioSettingValueBoolean(bool(_mem.compander)))
        rs.set_doc("Audio compander")
        mem.extra.append(rs)
        rs = MemSetting("scramble", "Scramble",
                        _map(SCRAMBLE, int(_mem.scramble)))
        rs.set_doc("Voice scrambler (Off or level 1-8)")
        mem.extra.append(rs)
        rs = MemSetting("mute_mode", "Mute mode",
                        _map(MUTE_MODES, int(_mem.mute_mode)))
        rs.set_doc("What opens the squelch: tone only, tone and DTMF, "
                   "or tone or DTMF")
        mem.extra.append(rs)
        group = int(_mem.call_group)
        # Channels the OEM software never touched store 0, which the radio
        # treats as group 1, so this one is applied by hand in set_memory.
        rs = RadioSetting("call_group", "Call group",
                          _map(CALL_GROUPS, group, offset=1))
        rs.set_doc("Call code group (1-20) used by this channel")
        mem.extra.append(rs)
        return mem

    def set_memory(self, mem):
        number = mem.number
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        if mem.empty:
            _mem.fill_raw(b"\x00")
            _nam.fill_raw(b"\x00")
            self._memobj.valid[number] = 0
            return

        if self._memobj.valid[number] == 0:
            # New channel: start from the defaults the OEM software uses
            _mem.fill_raw(b"\x00")
            _nam.fill_raw(b"\x00")
            _mem.call_group = 1
        self._memobj.valid[number] = MEM_VALID

        rx = mem.freq // 10
        _mem.rxfreq = rx
        if mem.duplex == "off":
            _mem.txfreq = 0
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            _mem.txfreq = rx + mem.offset // 10
        elif mem.duplex == "-":
            _mem.txfreq = rx - mem.offset // 10
        else:
            _mem.txfreq = rx

        # Only rewrite the name if it changed, so factory padding survives
        if _cstr(_nam.name) != mem.name.rstrip():
            _nam.name = _encode(mem.name, 12)
        self.tone_model.set_tone(mem, _mem)
        _mem.scan_add = int(mem.skip != "S")
        if mem.power in self.POWER_LEVELS:
            _mem.power = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 1
        am_tx = False
        for setting in RadioSettings(*mem.extra).apply_to(_mem):
            name = setting.get_name()
            if name == "am_tx":
                am_tx = bool(setting.value)
            elif name == "call_group":
                # Keep 0 (untouched, acts as group 1) unless it changed
                if not (_mem.call_group == 0 and int(setting.value) == 1):
                    _mem.call_group = int(setting.value)

        # AM field: 0 off, 1 AM receive (FM transmit), 2 AM receive+transmit
        if mem.mode == "AM":
            _mem.am = 2 if am_tx else 1
        else:
            _mem.am = 0
            _mem.wide = int(mem.mode == "FM")

    # ------------------------------------------------------------------
    # Settings

    def _get(self, path):
        """Look up a memory object value by MemSetting-style path."""
        obj = self._memobj
        for element in path.split("."):
            if "[" in element:
                name, index = element.rstrip("]").split("[")
                obj = getattr(obj, name)[int(index)]
            else:
                obj = getattr(obj, element)
        return int(obj)

    def _list(self, group, path, label, options, doc, offset=0):
        """Add a list setting stored as index + offset."""
        rs = MemSetting(path, label, _map(options, self._get(path), offset))
        rs.set_doc(doc)
        group.append(rs)

    def _bool(self, group, path, label, doc):
        rs = MemSetting(path, label,
                        RadioSettingValueBoolean(bool(self._get(path))))
        rs.set_doc(doc)
        group.append(rs)

    def _int(self, group, path, label, lo, hi, doc):
        cur = self._get(path)
        rs = MemSetting(path, label,
                        RadioSettingValueInteger(
                            lo, hi, cur if lo <= cur <= hi else lo))
        rs.set_doc(doc)
        group.append(rs)

    def _string(self, group, obj, field, label, length, doc):
        # Not a MemSetting: only rewrite the field if the text changed, so
        # leftover bytes after the NUL stay as the radio wrote them.
        rs = RadioSetting(field, label,
                          RadioSettingValueString(
                              0, length, _cstr(getattr(obj, field)),
                              autopad=False,
                              charset=chirp_common.CHARSET_ASCII))
        rs.set_doc(doc)

        def apply(setting):
            new = str(setting.value).rstrip()
            if new != _cstr(getattr(obj, field)):
                setattr(obj, field, _encode(new, length))
        rs.set_apply_callback(apply)
        group.append(rs)

    def get_settings(self):
        _set = self._memobj.settings
        _fac = self._memobj.factory

        basic = RadioSettingGroup("basic", "Basic")
        self._bool(basic, "settings.menu_avail", "Menu in channel mode",
                   "Allow the menu to be used while in channel mode")
        self._bool(basic, "settings.battery_save", "Battery save",
                   "Battery saver")
        self._list(basic, "settings.tot", "Time-out timer",
                   ["Off"] + ["%ds" % (i * 15) for i in range(1, 61)],
                   "Maximum transmit time")
        self._list(basic, "settings.toa", "TOT pre-alert",
                   ["Off"] + ["%ds" % i for i in range(1, 11)],
                   "Warning before the time-out timer expires")
        self._list(basic, "settings.vox", "VOX",
                   ["Off"] + ["%d" % i for i in range(1, 11)],
                   "Voice-operated transmit sensitivity")
        self._list(basic, "settings.vox_delay", "VOX delay",
                   ["Off"] + ["%ds" % i for i in range(1, 6)],
                   "How long VOX keeps transmitting after you stop talking")
        self._list(basic, "settings.scan_mode", "Scan mode",
                   ["Time operated", "Carrier operated", "Search"],
                   "How scanning resumes after stopping on a signal")
        self._list(basic, "settings.pri_scan", "Priority scan",
                   ["Off", "RX off", "Always on"],
                   "Priority channel scanning")
        self._int(basic, "settings.pri_ch", "Priority channel", 1, 400,
                  "Channel checked during priority scan")
        self._bool(basic, "settings.scan_det", "Scan tone detect",
                   "Detect CTCSS/DCS while scanning (SCAN-DET)")
        self._list(basic, "settings.sc_qt", "Saved scan tone",
                   ["Decoder", "Encoder", "Both"],
                   "Where a tone found by tone scan is saved (SC-QT)")
        self._list(basic, "settings.auto_lock", "Auto lock",
                   ["Off"] + ["%ds" % (i * 10) for i in range(1, 7)],
                   "Lock the keypad after this much idle time")
        self._list(basic, "settings.lock_mode", "Lock mode",
                   ["Keys", "Keys+PTT", "Keys+knob", "All"],
                   "What the keypad lock disables")
        self._bool(basic, "settings.bluetooth", "Bluetooth",
                   "Bluetooth on or off")
        self._bool(basic, "settings.second", "Second",
                   "The setting labelled 'Second' in the Wouxun software")

        audio = RadioSettingGroup("audio", "Audio")
        self._bool(audio, "settings.voice", "Voice guide", "Spoken prompts")
        self._bool(audio, "settings.beep", "Beep", "Key beep")
        self._list(audio, "settings.roger", "Roger beep", BOT_EOT,
                   "Tone at the start and/or end of each transmission")
        self._list(audio, "settings.alert", "Alert tone",
                   ["1750Hz", "2100Hz", "1000Hz", "1450Hz"],
                   "Tone burst used for repeater access")
        self._bool(audio, "settings.rpt_tone", "Repeater tone",
                   "Repeater tail tone")
        self._list(audio, "settings.ring_time", "Ring time",
                   ["Off"] + ["%ds" % i for i in range(1, 11)],
                   "How long the radio rings on an incoming call")

        display = RadioSettingGroup("display", "Display")
        self._list(display, "settings.backlight", "Backlight timer",
                   ["Always on"] + ["%ds" % i for i in range(1, 21)] +
                   ["Always off"],
                   "How long the display stays lit")
        self._list(display, "settings.brightness", "Brightness (active)",
                   ["%d" % i for i in range(1, 11)],
                   "Display brightness while in use", offset=1)
        self._list(display, "settings.brightness_stby", "Brightness (standby)",
                   ["Off"] + ["%d" % i for i in range(1, 11)],
                   "Display brightness while idle")
        self._bool(display, "settings.led_stby", "LED in standby",
                   "Status LED while idle")
        self._list(display, "settings.ponmsg", "Startup display",
                   ["Message", "Battery voltage"],
                   "What the radio shows when switched on")
        self._list(display, "settings.theme", "Theme",
                   ["White 1", "White 2", "Black 1", "Black 2",
                    "Custom 1", "Custom 2", "Custom 3", "Custom 4"],
                   "Display colour theme")
        self._string(display, _set, "startup_msg", "Startup message", 20,
                     "Text shown at power-on")
        self._string(display, _set, "area_msg", "Area message", 20,
                     "Second line of text shown on the display")

        work = RadioSettingGroup("work", "Work mode")
        for i, ab in enumerate("AB"):
            side = RadioSettingSubGroup("work_%s" % ab.lower(), "Side %s" % ab)
            for field, label, options, doc in (
                    ("work_mode", "Work mode", WORK_MODES,
                     "Show VFO or channels, and how channels are shown"),
                    ("step", "Tuning step", STEP_LIST,
                     "VFO tuning step"),
                    ("squelch", "Squelch", ["%d" % n for n in range(10)],
                     "Squelch level")):
                self._list(side, "settings.%s[%d]" % (field, i), label,
                           options, "%s for side %s" % (doc, ab))
            self._int(side, "settings.work_ch[%d]" % i, "Channel", 1, 400,
                      "Current channel for side %s" % ab)
            work.append(side)

        keys = RadioSettingGroup("keys", "Keys")
        self._list(keys, "settings.ptt2", "PTT2",
                   ["Call", "Transmit on sub band"],
                   "Function of the second PTT key")
        for key in ("pf1", "pf2", "pf3"):
            for press in ("short", "long"):
                self._list(keys, "settings.%s_%s" % (key, press),
                           "%s %s press" % (key.upper(), press),
                           KEY_FUNCS,
                           "Function of a %s press of %s" % (
                               press, key.upper()))

        dtmf = RadioSettingGroup("dtmf", "DTMF")
        self._list(dtmf, "settings.ptt_id", "PTT-ID", BOT_EOT,
                   "When to send the ANI code")
        self._list(dtmf, "settings.ptt_id_delay", "PTT-ID delay",
                   ["%dms" % (i * 100) for i in range(1, 31)],
                   "Delay before the ANI code is sent", offset=1)
        self._list(dtmf, "settings.sidetone", "DTMF sidetone",
                   ["Off", "DTMF", "ANI", "DTMF+ANI"],
                   "Which DTMF tones are heard in the speaker")
        self._list(dtmf, "settings.dtmf_tx_time", "DTMF tone length",
                   ["%dms" % (i * 10) for i in range(5, 51)],
                   "Length of each DTMF digit", offset=5)
        self._list(dtmf, "settings.dtmf_interval", "DTMF gap",
                   ["%dms" % (i * 10) for i in range(5, 51)],
                   "Gap between DTMF digits", offset=5)

        wx = RadioSettingGroup("weather", "Weather")
        self._bool(wx, "settings.wx_mode", "Weather mode",
                   "NOAA weather radio mode")
        self._list(wx, "settings.wx_ch", "Weather channel", WX_FREQS,
                   "NOAA weather frequency (MHz)", offset=1)
        self._bool(wx, "settings.wx_alert", "Weather alert",
                   "Watch for NOAA alert tones")
        self._list(wx, "settings.wx_alert_type", "Weather alert notification",
                   ["Off", "Icon", "Tone", "Flash", "Tone+Flash"],
                   "How a weather alert is shown")

        fm = RadioSettingGroup("fm", "FM radio")

        def fm_setting(name, label, raw, doc, setter):
            mhz = raw / 10.0 if 760 <= raw <= 1080 else 76.0
            rs = RadioSetting(name, label,
                              RadioSettingValueFloat(76.0, 108.0, mhz,
                                                     0.1, 1))
            rs.set_doc(doc)
            rs.set_apply_callback(
                lambda s: setter(int(round(float(s.value) * 10))))
            fm.append(rs)

        fm_setting("fm_freq", "Current FM frequency", int(_set.fm_freq),
                   "Broadcast FM frequency (MHz)",
                   lambda v: setattr(_set, "fm_freq", v))
        for i in range(20):
            def setter(v, i=i):
                self._memobj.fm_presets[i] = v
            fm_setting("fm_preset%d" % i, "FM memory %d" % (i + 1),
                       int(self._memobj.fm_presets[i]),
                       "Broadcast FM memory %d (MHz)" % (i + 1), setter)

        info = RadioSettingGroup("info", "Radio info")
        limits = ["%.4f" % (int(x) / 100000.0)
                  if int(x) != 0xFFFFFFFF else "-"
                  for x in _fac.rx_limits]
        for name, label, value in (
                ("model", "Model code", _cstr(_fac.model)),
                ("firmware", "Firmware", _cstr(_fac.firmware)),
                ("date", "Manufacture date", _cstr(_fac.date)),
                ("rx1", "RX range 1 (MHz)", "%s - %s" % tuple(limits[0:2])),
                ("rx2", "RX range 2 (MHz)", "%s - %s" % tuple(limits[2:4]))):
            rs = RadioSetting("info_" + name, label,
                              RadioSettingValueString(0, 32, value,
                                                      autopad=False))
            rs.value.set_mutable(False)
            rs.set_doc("Read from the radio's factory block (read-only)")
            info.append(rs)

        return RadioSettings(basic, audio, display, work, keys, dtmf, wx,
                             fm, info)

    def set_settings(self, settings):
        # Most settings are MemSettings; the strings and FM frequencies
        # need conversion and carry their own apply callbacks.
        for element in settings.apply_to(self._memobj):
            if element.has_apply_callback():
                element.run_apply_callback()
