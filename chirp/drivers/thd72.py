# Copyright 2010 Vernon Mauery <vernon@mauery.org>
# Copyright 2016 Angus Ainslie <angus@akkea.ca>
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

from chirp import chirp_common, errors, util, directory
from chirp import bitwise, memmap
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString
from chirp.settings import RadioSettingValueList, RadioSettingValueBoolean
import time
import struct
import sys
import logging

LOG = logging.getLogger(__name__)

# TH-D72 memory map
# 0x0000..0x0200: startup password and other stuff
# 0x0200..0x0400: current channel and other settings
#   0x244,0x246: last menu numbers
#   0x249: last f menu number
# 0x0400..0x0c00: APRS settings and likely other settings
# 0x0c00..0x1500: memory channel flags
# 0x1500..0x5380: 0-999 channels
# 0x5380..0x54c0: 0-9 scan channels
# 0x54c0..0x5560: 0-9 wx channels
# 0x5560..0x5e00: ?
# 0x5e00..0x7d40: 0-999 channel names
# 0x7d40..0x7de0: ?
# 0x7de0..0x7e30: wx channel names
# 0x7e30..0x7ed0: ?
# 0x7ed0..0x7f20: group names
# 0x7f20..0x8b00: ?
# 0x8b00..0x9c00: last 20 APRS entries
# 0x9c00..0xe500: ?
# 0xe500..0xe7d0: startup bitmap
# 0xe7d0..0xe800: startup bitmap filename
# 0xe800..0xead0: gps-logger bitmap
# 0xe8d0..0xeb00: gps-logger bipmap filename
# 0xeb00..0xff00: ?
# 0xff00..0xffff: stuff?

# memory channel
# 0 1 2 3  4 5     6            7     8     9    a          b c d e   f
# [freq ]  ? mode  tmode/duplex rtone ctone dtcs cross_mode [offset]  ?

mem_format = """
#seekto 0x0000;
struct {
  ul16 version;
  u8   shouldbe32;
  u8   efs[11];
  u8   unknown0[3];
  u8   radio_custom_image;
  u8   gps_custom_image;
  u8   unknown1[7];
  u8   passwd[6];
} frontmatter;

#seekto 0x02c0;
struct {
  ul32 start_freq;
  ul32 end_freq;
} prog_vfo[6];

#seekto 0x0300;
struct {
  char power_on_msg[8];
  u8 unknown0[8];
  u8 unknown1[2];
  u8 lamp_timer;
  u8 contrast;
  u8 battery_saver;
  u8 APO;
  u8 unknown2;
  u8 key_beep;
  u8 unknown3[8];
  u8 unknown4;
  u8 balance;
  u8 unknown5[23];
  u8 lamp_control;
} settings;

#seekto 0x0c00;
struct {
  u8 disabled:4,
     prog_vfo:4;
  u8 skip;
} flag[1032];

#seekto 0x1500;
struct {
  ul32 freq;
  u8 unknown1;
  u8 mode;
  u8 tone_mode:4,
     duplex:4;
  u8 rtone;
  u8 ctone;
  u8 dtcs;
  u8 cross_mode;
  ul32 offset;
  u8 unknown2;
} memory[1032];

#seekto 0x5e00;
struct {
    char name[8];
} channel_name[1000];

#seekto 0x7de0;
struct {
    char name[8];
} wx_name[10];

#seekto 0x7ed0;
struct {
    char name[8];
} group_name[10];
"""

THD72_SPECIAL = {}

for i in range(0, 10):
    THD72_SPECIAL["L%i" % i] = 1000 + (i * 2)
    THD72_SPECIAL["U%i" % i] = 1000 + (i * 2) + 1
for i in range(0, 10):
    THD72_SPECIAL["WX%i" % (i + 1)] = 1020 + i
THD72_SPECIAL["C VHF"] = 1030
THD72_SPECIAL["C UHF"] = 1031

THD72_SPECIAL_REV = {}
for k, v in THD72_SPECIAL.items():
    THD72_SPECIAL_REV[v] = k

TMODES = {
    0x08: "Tone",
    0x04: "TSQL",
    0x02: "DTCS",
    0x01: "Cross",
    0x00: "",
}
TMODES_REV = {
    "": 0x00,
    "Cross": 0x01,
    "DTCS": 0x02,
    "TSQL": 0x04,
    "Tone": 0x08,
}

MODES = {
    0x00: "FM",
    0x01: "NFM",
    0x02: "AM",
}

MODES_REV = {
    "FM": 0x00,
    "NFM": 0x01,
    "AM": 0x2,
}

DUPLEX = {
    0x00: "",
    0x01: "+",
    0x02: "-",
    0x04: "split",
}
DUPLEX_REV = {
    "": 0x00,
    "+": 0x01,
    "-": 0x02,
    "split": 0x04,
}


EXCH_R = "R\x00\x00\x00\x00"
EXCH_W = "W\x00\x00\x00\x00"

DEFAULT_PROG_VFO = (
    (136000000, 174000000),
    (410000000, 470000000),
    (118000000, 136000000),
    (136000000, 174000000),
    (320000000, 400000000),
    (400000000, 524000000),
)
# index of PROG_VFO used for setting memory.unknown1 and memory.unknown2
# see http://chirp.danplanet.com/issues/1611#note-9
UNKNOWN_LOOKUP = (0, 7, 4, 0, 4, 7)


def get_prog_vfo(frequency):
    for i, (start, end) in enumerate(DEFAULT_PROG_VFO):
        if start <= frequency < end:
            return i
    raise ValueError("Frequency is out of range.")


@directory.register
class THD72Radio(chirp_common.CloneModeRadio):

    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = "TH-D72 (clone mode)"
    HARDWARE_FLOW = sys.platform == "darwin"  # only OS X driver needs hw flow

    mem_upper_limit = 1022
    _memsize = 65536
    _model = ""  # FIXME: REMOVE
    _dirty_blocks = []

    _LCD_CONTRAST = ["Level %d" % x for x in range(1, 16)]
    _LAMP_CONTROL = ["Manual", "Auto"]
    _LAMP_TIMER = ["Seconds %d" % x for x in range(2, 11)]
    _BATTERY_SAVER = ["OFF", "0.03 Seconds", "0.2 Seconds", "0.4 Seconds",
                      "0.6 Seconds", "0.8 Seconds", "1 Seconds", "2 Seconds",
                      "3 Seconds", "4 Seconds", "5 Seconds"]
    _APO = ["OFF", "15 Minutes", "30 Minutes", "60 Minutes"]
    _AUDIO_BALANCE = ["Center", "A +50%", "A +100%", "B +50%", "B +100%"]
    _KEY_BEEP = ["OFF", "Radio & GPS", "Radio Only", "GPS Only"]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 1031)
        rf.valid_bands = [(118000000, 174000000),
                          (320000000, 524000000)]
        rf.has_cross = True
        rf.can_odd_split = True
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_settings = True
        rf.valid_tuning_steps = []
        rf.valid_modes = MODES_REV.keys()
        rf.valid_tmodes = TMODES_REV.keys()
        rf.valid_duplexes = DUPLEX_REV.keys()
        rf.valid_skips = ["", "S"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 8
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)
        self._dirty_blocks = []

    def _detect_baud(self):
        for baud in [9600, 19200, 38400, 57600]:
            self.pipe.baudrate = baud
            try:
                self.pipe.write("\r\r")
            except:
                break
            self.pipe.read(32)
            try:
                id = self.get_id()
                LOG.info("Radio %s at %i baud" % (id, baud))
                return True
            except errors.RadioError:
                pass

        raise errors.RadioError("No response from radio")

    def get_special_locations(self):
        return sorted(THD72_SPECIAL.keys())

    def add_dirty_block(self, memobj):
        block = memobj._offset / 256
        if block not in self._dirty_blocks:
            self._dirty_blocks.append(block)
        self._dirty_blocks.sort()
        print("dirty blocks: ", self._dirty_blocks)

    def get_channel_name(self, number):
        if number < 999:
            name = str(self._memobj.channel_name[number].name) + '\xff'
        elif number >= 1020 and number < 1030:
            number -= 1020
            name = str(self._memobj.wx_name[number].name) + '\xff'
        else:
            return ''
        return name[:name.index('\xff')].rstrip()

    def set_channel_name(self, number, name):
        name = name[:8] + '\xff' * 8
        if number < 999:
            self._memobj.channel_name[number].name = name[:8]
            self.add_dirty_block(self._memobj.channel_name[number])
        elif number >= 1020 and number < 1030:
            number -= 1020
            self._memobj.wx_name[number].name = name[:8]
            self.add_dirty_block(self._memobj.wx_name[number])

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
            repr(self._memobj.flag[number])

    def get_memory(self, number):
        if isinstance(number, str):
            try:
                number = THD72_SPECIAL[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" %
                                                   number)

        if number < 0 or number > (max(THD72_SPECIAL.values()) + 1):
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and 999")

        _mem = self._memobj.memory[number]
        flag = self._memobj.flag[number]

        mem = chirp_common.Memory()
        mem.number = number

        if number > 999:
            mem.extd_number = THD72_SPECIAL_REV[number]
        if flag.disabled == 0xf:
            mem.empty = True
            return mem

        mem.name = self.get_channel_name(number)
        mem.freq = int(_mem.freq)
        mem.tmode = TMODES[int(_mem.tone_mode)]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.duplex = DUPLEX[int(_mem.duplex)]
        mem.offset = int(_mem.offset)
        mem.mode = MODES[int(_mem.mode)]

        if number < 999:
            mem.skip = chirp_common.SKIP_VALUES[int(flag.skip)]
            mem.cross_mode = chirp_common.CROSS_MODES[_mem.cross_mode]
        if number > 999:
            mem.cross_mode = chirp_common.CROSS_MODES[0]
            mem.immutable = ["number", "bank", "extd_number", "cross_mode"]
            if number >= 1020 and number < 1030:
                mem.immutable += ["freq", "offset", "tone", "mode",
                                  "tmode", "ctone", "skip"]  # FIXME: ALL
            else:
                mem.immutable += ["name"]

        return mem

    def set_memory(self, mem):
        LOG.debug("set_memory(%d)" % mem.number)
        if mem.number < 0 or mem.number > (max(THD72_SPECIAL.values()) + 1):
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and 999")

        # weather channels can only change name, nothing else
        if mem.number >= 1020 and mem.number < 1030:
            self.set_channel_name(mem.number, mem.name)
            return

        flag = self._memobj.flag[mem.number]
        self.add_dirty_block(self._memobj.flag[mem.number])

        # only delete non-WX channels
        was_empty = flag.disabled == 0xf
        if mem.empty:
            flag.disabled = 0xf
            return
        flag.disabled = 0

        _mem = self._memobj.memory[mem.number]
        self.add_dirty_block(_mem)
        if was_empty:
            self.initialize(_mem)

        _mem.freq = mem.freq

        if mem.number < 999:
            self.set_channel_name(mem.number, mem.name)

        _mem.tone_mode = TMODES_REV[mem.tmode]
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.cross_mode = chirp_common.CROSS_MODES.index(mem.cross_mode)
        _mem.duplex = DUPLEX_REV[mem.duplex]
        _mem.offset = mem.offset
        _mem.mode = MODES_REV[mem.mode]

        prog_vfo = get_prog_vfo(mem.freq)
        flag.prog_vfo = prog_vfo
        _mem.unknown1 = _mem.unknown2 = UNKNOWN_LOOKUP[prog_vfo]

        if mem.number < 999:
            flag.skip = chirp_common.SKIP_VALUES.index(mem.skip)

    def sync_in(self):
        self._detect_baud()
        self._mmap = self.download()
        self.process_mmap()

    def sync_out(self):
        self._detect_baud()
        if len(self._dirty_blocks):
            self.upload(self._dirty_blocks)
        else:
            self.upload()

    def read_block(self, block, count=256):
        self.pipe.write(struct.pack("<cBHB", "R", 0, block, 0))
        r = self.pipe.read(5)
        if len(r) != 5:
            raise Exception("Did not receive block response")

        cmd, _zero, _block, zero = struct.unpack("<cBHB", r)
        if cmd != "W" or _block != block:
            raise Exception("Invalid response: %s %i" % (cmd, _block))

        data = ""
        while len(data) < count:
            data += self.pipe.read(count - len(data))

        self.pipe.write(chr(0x06))
        if self.pipe.read(1) != chr(0x06):
            raise Exception("Did not receive post-block ACK!")

        return data

    def write_block(self, block, map):
        self.pipe.write(struct.pack("<cBHB", "W", 0, block, 0))
        base = block * 256
        self.pipe.write(map[base:base + 256])

        ack = self.pipe.read(1)

        return ack == chr(0x06)

    def download(self, raw=False, blocks=None):
        if blocks is None:
            blocks = range(self._memsize / 256)
        else:
            blocks = [b for b in blocks if b < self._memsize / 256]

        if self.command("0M PROGRAM") != "0M":
            raise errors.RadioError("No response from self")

        allblocks = range(self._memsize / 256)
        self.pipe.baudrate = 57600
        try:
            self.pipe.setRTS()
        except AttributeError:
            self.pipe.rts = True
        self.pipe.read(1)
        data = ""
        LOG.debug("reading blocks %d..%d" % (blocks[0], blocks[-1]))
        total = len(blocks)
        count = 0
        for i in allblocks:
            if i not in blocks:
                data += 256 * '\xff'
                continue
            data += self.read_block(i)
            count += 1
            if self.status_fn:
                s = chirp_common.Status()
                s.msg = "Cloning from radio"
                s.max = total
                s.cur = count
                self.status_fn(s)

        self.pipe.write("E")

        if raw:
            return data
        return memmap.MemoryMap(data)

    def upload(self, blocks=None):
        if blocks is None:
            blocks = range((self._memsize / 256) - 2)
        else:
            blocks = [b for b in blocks if b < self._memsize / 256]

        if self.command("0M PROGRAM") != "0M":
            raise errors.RadioError("No response from self")

        self.pipe.baudrate = 57600
        try:
            self.pipe.setRTS()
        except AttributeError:
            self.pipe.rts = True
        self.pipe.read(1)
        LOG.debug("writing blocks %d..%d" % (blocks[0], blocks[-1]))
        total = len(blocks)
        count = 0
        for i in blocks:
            r = self.write_block(i, self._mmap)
            count += 1
            if not r:
                raise errors.RadioError("self NAK'd block %i" % i)
            if self.status_fn:
                s = chirp_common.Status()
                s.msg = "Cloning to radio"
                s.max = total
                s.cur = count
                self.status_fn(s)

        self.pipe.write("E")
        # clear out blocks we uploaded from the dirty blocks list
        self._dirty_blocks = [b for b in self._dirty_blocks if b not in blocks]

    def command(self, cmd, timeout=0.5):
        start = time.time()

        data = ""
        LOG.debug("PC->D72: %s" % cmd)
        self.pipe.write(cmd + "\r")
        while not data.endswith("\r") and (time.time() - start) < timeout:
            data += self.pipe.read(1)
        LOG.debug("D72->PC: %s" % data.strip())
        return data.strip()

    def get_id(self):
        r = self.command("ID")
        if r.startswith("ID "):
            return r.split(" ")[1]
        else:
            raise errors.RadioError("No response to ID command")

    def initialize(self, mmap):
        mmap.set_raw("\x00\xc8\xb3\x08\x00\x01\x00\x08"
                     "\x08\x00\xc0\x27\x09\x00\x00\x00")

    def _get_settings(self):
        top = RadioSettings(self._get_display_settings(),
                            self._get_audio_settings(),
                            self._get_battery_settings())
        return top

    def set_settings(self, settings):
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    try:
                        element.run_apply_callback()
                    except NotImplementedError as e:
                        LOG.error("thd72: %s", e)
                    continue

                # Find the object containing setting.
                obj = _mem
                bits = element.get_name().split(".")
                setting = bits[-1]
                for name in bits[:-1]:
                    if name.endswith("]"):
                        name, index = name.split("[")
                        index = int(index[:-1])
                        obj = getattr(obj, name)[index]
                    else:
                        obj = getattr(obj, name)

                try:
                    old_val = getattr(obj, setting)
                    LOG.debug("Setting %s(%r) <= %s" % (
                        element.get_name(), old_val, element.value))
                    setattr(obj, setting, element.value)
                except AttributeError as e:
                    LOG.error("Setting %s is not in the memory map: %s" %
                              (element.get_name(), e))
            except Exception, e:
                LOG.debug(element.get_name())
                raise

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    @classmethod
    def apply_power_on_msg(cls, setting, obj):
        message = setting.value.get_value()
        setattr(obj, "power_on_msg", cls._add_ff_pad(message, 8))

    def apply_lcd_contrast(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._LCD_CONTRAST.index(rawval) + 1
        obj.contrast = val

    def apply_lamp_control(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._LAMP_CONTROL.index(rawval)
        obj.lamp_control = val

    def apply_lamp_timer(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._LAMP_TIMER.index(rawval) + 2
        obj.lamp_timer = val

    def _get_display_settings(self):
        menu = RadioSettingGroup("display", "Display")
        display_settings = self._memobj.settings

        val = RadioSettingValueString(
            0, 8, str(display_settings.power_on_msg).rstrip("\xFF"))
        rs = RadioSetting("display.power_on_msg", "Power on message", val)
        rs.set_apply_callback(self.apply_power_on_msg, display_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LCD_CONTRAST,
            self._LCD_CONTRAST[display_settings.contrast - 1])
        rs = RadioSetting("display.contrast", "LCD Contrast",
                          val)
        rs.set_apply_callback(self.apply_lcd_contrast, display_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LAMP_CONTROL,
            self._LAMP_CONTROL[display_settings.lamp_control])
        rs = RadioSetting("display.lamp_control", "Lamp Control",
                          val)
        rs.set_apply_callback(self.apply_lamp_control, display_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LAMP_TIMER,
            self._LAMP_TIMER[display_settings.lamp_timer - 2])
        rs = RadioSetting("display.lamp_timer", "Lamp Timer",
                          val)
        rs.set_apply_callback(self.apply_lamp_timer, display_settings)
        menu.append(rs)

        return menu

    def apply_battery_saver(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._BATTERY_SAVER.index(rawval)
        obj.battery_saver = val

    def apply_APO(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._APO.index(rawval)
        obj.APO = val

    def _get_battery_settings(self):
        menu = RadioSettingGroup("battery", "Battery")
        battery_settings = self._memobj.settings

        val = RadioSettingValueList(
            self._BATTERY_SAVER,
            self._BATTERY_SAVER[battery_settings.battery_saver])
        rs = RadioSetting("battery.battery_saver", "Battery Saver",
                          val)
        rs.set_apply_callback(self.apply_battery_saver, battery_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._APO,
            self._APO[battery_settings.APO])
        rs = RadioSetting("battery.APO", "Auto Power Off",
                          val)
        rs.set_apply_callback(self.apply_APO, battery_settings)
        menu.append(rs)

        return menu

    def apply_balance(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._AUDIO_BALANCE.index(rawval)
        obj.balance = val

    def apply_key_beep(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._KEY_BEEP.index(rawval)
        obj.key_beep = val

    def _get_audio_settings(self):
        menu = RadioSettingGroup("audio", "Audio")
        audio_settings = self._memobj.settings

        val = RadioSettingValueList(
            self._AUDIO_BALANCE,
            self._AUDIO_BALANCE[audio_settings.balance])
        rs = RadioSetting("audio.balance", "Balance",
                          val)
        rs.set_apply_callback(self.apply_balance, audio_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._KEY_BEEP,
            self._KEY_BEEP[audio_settings.key_beep])
        rs = RadioSetting("audio.key_beep", "Key Beep",
                          val)
        rs.set_apply_callback(self.apply_key_beep, audio_settings)
        menu.append(rs)

        return menu

    @staticmethod
    def _add_ff_pad(val, length):
        return val.ljust(length, "\xFF")[:length]

    @classmethod
    def _strip_ff_pads(cls, messages):
        result = []
        for msg_text in messages:
            result.append(str(msg_text).rstrip("\xFF"))
        return result

if __name__ == "__main__":
    import sys
    import serial
    import detect
    import getopt

    def fixopts(opts):
        r = {}
        for opt in opts:
            k, v = opt
            r[k] = v
        return r

    def usage():
        print "Usage: %s <-i input.img>|<-o output.img> -p port " \
            "[[-f first-addr] [-l last-addr] | [-b list,of,blocks]]" % \
            sys.argv[0]
        sys.exit(1)

    opts, args = getopt.getopt(sys.argv[1:], "i:o:p:f:l:b:")
    opts = fixopts(opts)
    first = last = 0
    blocks = None
    if '-i' in opts:
        fname = opts['-i']
        download = False
    elif '-o' in opts:
        fname = opts['-o']
        download = True
    else:
        usage()
    if '-p' in opts:
        port = opts['-p']
    else:
        usage()

    if '-f' in opts:
        first = int(opts['-f'], 0)
    if '-l' in opts:
        last = int(opts['-l'], 0)
    if '-b' in opts:
        blocks = [int(b, 0) for b in opts['-b'].split(',')]
        blocks.sort()

    ser = serial.Serial(port=port, baudrate=9600, timeout=0.25)
    r = THD72Radio(ser)
    memmax = r._memsize
    if not download:
        memmax -= 512

    if blocks is None:
        if first < 0 or first > (r._memsize - 1):
            raise errors.RadioError("first address out of range")
        if (last > 0 and last < first) or last > memmax:
            raise errors.RadioError("last address out of range")
        elif last == 0:
            last = memmax
        first /= 256
        if last % 256 != 0:
            last += 256
        last /= 256
        blocks = range(first, last)

    if download:
        data = r.download(True, blocks)
        file(fname, "wb").write(data)
    else:
        r._mmap = file(fname, "rb").read(r._memsize)
        r.upload(blocks)
    print "\nDone"
