# Copyright 2024:
# * Pavel Moravec, OK2MOP <moravecp.cz@gmail.com>
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
from chirp import chirp_common, directory
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList
from chirp.drivers import baofeng_uv17Pro, baofeng_uv17

LOG = logging.getLogger(__name__)


@directory.register
class RT620(baofeng_uv17.UV17):
    """Radtel RT-620"""
    VENDOR = "Radtel"
    MODEL = "RT-620"
    _radio_memsize = 0x2efff
    _has_workmode_support = True
    _has_gps = True
    _vfoscan = True

    # Top key is referenced in CPS but does not exist in GPS model
    _has_top_key = False
    _has_pilot_tone = True

    STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

    # Blocks 16-19 - channels, 24-26 channel names, 4 settings,
    #        6 - secondary settings, identity codes,
    #        2 - calibration, 1 - empty radio param
    BLOCK_O_READ = baofeng_uv17.UV17.BLOCK_O_READ + [2]  # back up calibration

    _airband = (108000000, 135999999)
    _vhf_range = (136000000, 299999999)
    _uhf_range = (300000000, 559999999)
    VALID_BANDS = [_airband, _vhf_range, _uhf_range]
    _fingerprint = b"\x06" + b"PROGR6F"
    _magics2 = [(b"\x06", 1),
                (b"\xFF\xFF\xFF\xFF\x0CPROGR6F", 1),
                (b"\02", 8),
                (b"\x06", 1)]
    CHANNELS = 999
    MODES = ["NFM", "FM", "WFM"]
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("Mid",  watts=5.00),
                    chirp_common.PowerLevel("High",  watts=10.00)]
    LIST_MODE = ["VFO", "Channel Number",
                 "Frequency + Channel Number", "Name + Channel Number"]
    LIST_BEEP = ["Off", "On"]
    LIST_VOX_LEVEL = baofeng_uv17Pro.LIST_VOX_LEVEL
    LIST_ALARMMODE = baofeng_uv17Pro.LIST_ALARMMODE
    LIST_PILOT_TONE = baofeng_uv17Pro.LIST_PILOT_TONE
    LIST_VOX_DELAY_TIME = ["Off"] + ["%s ms" %
                                     x for x in range(500, 2100, 100)]
    LIST_NOAA = ["NOAA OFF", "NOAA Forecast",
                 "NOAA Alarm", "NOAA Both"]  # NOAA here
    LIST_100ms = ["%s ms" % x for x in range(100, 1100, 100)]
    LIST_AB = ["A", "B"]
    LIST_BRIGHTNESS = ["%i" % x for x in range(1, 6)]
    LIST_MENU_QUIT_TIME = ["Off"] + ["%s sec" % x for x in range(1, 31)]
    LIST_KEYS = ["None", "Monitor", "Sweep", "Scan", "Voltage",
                 "Emergency", "Scrambler", "FM Radio", "Compander"]
    MEM_DEFS = """
    struct channel {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      ul16 rxtone;
      ul16 txtone;
      u8 unknown12_7:1,
         bcl:1,
         pttid:2,
         wide:2,
         lowpower:2;
      u8 unknown13_5:3,
         compander:1,
         unknown_13_2:2,
         scrambler:2;
      u8 scode:4,
         unknown14_1:3,
         scan:1;
      u8 step;
    };
    struct channelname {
      char name[11];
    };
    struct settings {
      u8 powerondistype;
      u8 unknown0[15];
      char boottext1[10];
      u8 unknown1[6];
      char boottext2[10];
      u8 unknown2[22];
      u8 tot;
      u8 voxdlytime;
      u8 vox;
      u8 powersave: 4,
         unknown3:1,
         chedit:1,
         voice: 1,
         voicesw: 1;
      u8 backlight;
      u8 beep:1,
         autolock:1,
         unknown_5b5:1,
         noaa:2,
         tail:1,
         dtmfst:2;
      u8 fminterrupt:1,
         dualstandby:1,
         roger:1,
         alarmmode:2,
         alarmtone:1,
         fmenable:1,
         absel:1;
      u8 tailrevert;
      u8 taildelay;
      u8 tone;
      u8 backlightbr;
      u8 squelch;
      u8 chbsquelch;
      u8 chbdistype;
      u8 chadistype;
      u8 menuquittime;
      u8 sk1short;
      u8 sk1long;
      u8 sk2short;
      u8 sk2long;
      u8 topshort;
      u8 toplong;
      u8 scanmode; // Fake Scanmode to satisfy parent method
      u8 unknown8[5];
    };
    struct ani {
      u8 unknown[5];
      u8 code[5];
    };
    struct pttid {
      u8 code[5];
    };
    struct proglocks {
      u8 writelock; //0x00 - off, 0xA5 - on
      u8 readlock;
      char writepass[8];
      char readpass[8];
      u8 empty[13];
      char unknowncode[6]; //Kill code maybe
    };
    struct gps {
      u8 state;
      u8 tzadd12;
    };
    struct dtmfen {
        u8 delay;
        u8 digit;
        u8 interval;
    };
    """
    MEM_LAYOUT = """
    struct {
      ul16 channels;
      ul16 ch_a;
      ul16 ch_b;
    } chsel;
    #seekto 0x0030;
    struct {
      struct channel mem[252];
    } mem1;
    #seek 0x10;
    struct {
      struct channel mem[255];
    } mem2;
    #seek 0x10;
    struct {
      struct channel mem[255];
    } mem3;
    #seek 0x10;
    struct {
      struct channel mem[237];
    } mem4;
    #seekto 0x7000;
    struct settings settings;
    #seekto 0x0010;
    struct {
      struct channel a;
      struct channel b;
    } vfo;
    #seekto 0x4000;
    struct channelname names1[372];
    #seek 0x4;
    struct channelname names2[372];
    #seek 0x4;
    struct channelname names3[255];
    #seekto 0x7100;
    struct gps gps;
    #seekto 0x7069;
    struct proglocks locks;
    #seekto 0x8000;
    struct pttid pttid[15];
    struct ani ani;
    #seekto 0x8061;
    struct dtmfen dtmf;
    """
    MEM_FORMAT = MEM_DEFS + MEM_LAYOUT
    REMOVE_SETTINGS = ['settings.scanmode']

    def remove_extras(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                settings.remove(element)
                settings.append(self.remove_extra_items(element))
        settings.sort()

    def remove_extra_items(self, group):
        tmp = RadioSettingGroup(group.get_name(), group.get_shortname())
        for element in group:
            name = element.get_name()
            if not isinstance(element, RadioSetting):
                tmp.append(self.remove_extra_items(element))
            elif name not in self.REMOVE_SETTINGS:
                tmp.append(element)
        return tmp

    def get_settings(self):
        top = super().get_settings()
        _mem = self._memobj
        self.remove_extras(top)
        extra = RadioSettingGroup("extra", "Extra Settings")
        self.get_settings_extra(extra, _mem)
        top.append(extra)
        if self._has_gps:
            gps = RadioSettingGroup("gps", "GPS Settings")
            rs = RadioSetting("gps.state", "GPS Enable",
                              RadioSettingValueBoolean(_mem.gps.state))
            gps.append(rs)
            rs = RadioSetting("gps.tzadd12", "GPS Timezone",
                              RadioSettingValueList(
                                  baofeng_uv17Pro.LIST_GPS_TIMEZONE,
                                  current_index=_mem.gps.tzadd12))
            gps.append(rs)
            top.append(gps)
        return top

    def get_settings_extra(self, extra, _mem):
        rs = RadioSetting("settings.absel", "Selected Channel",
                          RadioSettingValueList(
                              self.LIST_AB, current_index=_mem.settings.absel))
        extra.append(rs)
        if _mem.settings.chbsquelch >= len(self.SQUELCH_LIST):
            val = 0x00
        else:
            val = _mem.settings.chbsquelch
        rs = RadioSetting("settings.chbsquelch", "Channel B Squelch",
                          RadioSettingValueList(
                              self.SQUELCH_LIST, current_index=val))
        extra.append(rs)
        # Settings menu 4
        rs = RadioSetting("settings.vox", "Vox Level",
                          RadioSettingValueList(
                              self.LIST_VOX_LEVEL,
                              current_index=_mem.settings.vox))
        extra.append(rs)
        # Settings menu 5
        rs = RadioSetting("settings.voxdlytime", "Vox Delay Time",
                          RadioSettingValueList(
                              self.LIST_VOX_DELAY_TIME,
                              current_index=_mem.settings.voxdlytime))
        extra.append(rs)
        # Settings menu 12
        rs = RadioSetting("settings.backlightbr", "Backlight Brightnes",
                          RadioSettingValueList(
                              self.LIST_BRIGHTNESS,
                              current_index=_mem.settings.backlightbr))
        extra.append(rs)
        rs = RadioSetting("settings.chedit", "Allow Channel Editing",
                          RadioSettingValueBoolean(_mem.settings.chedit))
        extra.append(rs)
        # Settings menu 22
        rs = RadioSetting("settings.tail", "CTCSS Tail Revert",
                          RadioSettingValueBoolean(_mem.settings.tail))
        extra.append(rs)
        rs = RadioSetting("settings.tailrevert", "Repeater Tail Revert Time",
                          RadioSettingValueList(
                              self.LIST_100ms,
                              current_index=_mem.settings.tailrevert))
        extra.append(rs)
        rs = RadioSetting("settings.taildelay", "Repeater Tail Delay Time",
                          RadioSettingValueList(
                              self.LIST_100ms,
                              current_index=_mem.settings.taildelay))
        extra.append(rs)
        rs = RadioSetting("settings.fminterrupt", "FM radio Interruption",
                          RadioSettingValueBoolean(_mem.settings.fminterrupt))
        extra.append(rs)
        # Settings menu 21
        rs = RadioSetting("settings.alarmmode", "Alarm Mode",
                          RadioSettingValueList(
                              self.LIST_ALARMMODE,
                              current_index=_mem.settings.alarmmode))
        extra.append(rs)
        rs = RadioSetting("settings.alarmtone", "Sound Alarm",
                          RadioSettingValueBoolean(_mem.settings.alarmtone))
        extra.append(rs)
        rs = RadioSetting("settings.menuquittime", "Menu Quit Timer",
                          RadioSettingValueList(
                              self.LIST_MENU_QUIT_TIME,
                              current_index=_mem.settings.menuquittime))
        extra.append(rs)
        if self._has_pilot_tone:
            rs = RadioSetting("settings.tone", "Pilot Tone",
                              RadioSettingValueList(
                                  self.LIST_PILOT_TONE,
                                  current_index=_mem.settings.tone))
            extra.append(rs)
        # Settings menu 27
        if _mem.settings.sk1short >= len(self.LIST_KEYS):
            val = 0x00
        else:
            val = _mem.settings.sk1short
        rs = RadioSetting("settings.sk1short", "Side Key 1 Short Press",
                          RadioSettingValueList(
                              self.LIST_KEYS, current_index=val))
        extra.append(rs)
        # Settings menu 28
        if _mem.settings.sk1long >= len(self.LIST_KEYS):
            val = 0x00
        else:
            val = _mem.settings.sk1long
        rs = RadioSetting("settings.sk1long", "Side Key 1 Long Press",
                          RadioSettingValueList(
                              self.LIST_KEYS, current_index=val))
        extra.append(rs)
        # Settings menu 29
        if _mem.settings.sk2short >= len(self.LIST_KEYS):
            val = 0x00
        else:
            val = _mem.settings.sk2short
        rs = RadioSetting("settings.sk2short", "Side Key 2 Short Press",
                          RadioSettingValueList(
                              self.LIST_KEYS, current_index=val))
        extra.append(rs)
        # Settings menu 30
        if _mem.settings.sk2long >= len(self.LIST_KEYS):
            val = 0x00
        else:
            val = _mem.settings.sk2long
        rs = RadioSetting("settings.sk2long", "Side Key 2 Long Press",
                          RadioSettingValueList(
                              self.LIST_KEYS, current_index=val))
        extra.append(rs)
        # Official CPS sets this, but radio does not have top key
        # Probably the non-GPS version or some other clone uses it so
        # I have included it here when/if it will be needed
        if self._has_top_key:
            if _mem.settings.topshort >= len(self.LIST_KEYS):
                val = 0x00
            else:
                val = _mem.settings.topshort
            rs = RadioSetting("settings.topshort", "Top Key Short Press",
                              RadioSettingValueList(
                                  self.LIST_KEYS, current_index=val))
            extra.append(rs)
            # Settings menu 30
            if _mem.settings.toplong >= len(self.LIST_KEYS):
                val = 0x00
            else:
                val = _mem.settings.toplong
            rs = RadioSetting("settings.toplong", "Top Key Long Press",
                              RadioSettingValueList(
                                  self.LIST_KEYS, current_index=val))
            extra.append(rs)
        # NOAA menu
        rs = RadioSetting("settings.noaa", "NOAA Weather mode",
                          RadioSettingValueList(
                              self.LIST_NOAA,
                              current_index=_mem.settings.noaa))
        extra.append(rs)

    def _get_raw_memory(self, number):
        if number == -1:
            return self._memobj.vfo.b
        elif number == -2:
            return self._memobj.vfo.a
        else:
            return super()._get_raw_memory(number)

    def get_memory(self, number):
        mem = super().get_memory(number)
        _mem = self._get_raw_memory(number)
        if hasattr(mem.extra, "keys") and \
                "compander" not in mem.extra.keys():
            rs = RadioSetting("compander", "Compander",
                              RadioSettingValueBoolean(_mem.compander))
            mem.extra.append(rs)
        mem.tuning_step = self.STEPS[_mem.step] or self.STEPS[0]
        if _mem.wide < len(self.MODES):
            mem.mode = self.MODES[_mem.wide]
        return mem

    def set_memory(self, mem):
        _mem = self._get_raw_memory(mem.number)
        super().set_memory(mem)
        _mem.step = self.STEPS.index(mem.tuning_step)
        _mem.wide = self.MODES.index(mem.mode)
        if _mem.rxtone == 0:
            _mem.rxtone = 0xFFFF
        if _mem.txtone == 0:
            _mem.txtone = 0xFFFF

    def get_features(self):
        rf = super().get_features()
        rf.has_tuning_step = True
        rf.has_bank = False
        return rf
