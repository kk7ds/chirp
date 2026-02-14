# Copyright 2024 Tommy <tommy83033@gmail.com>
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

import logging
from chirp import chirp_common, bitwise, directory
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingSubGroup,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueFloat,
    RadioSettingValueInteger
)
from chirp.drivers import retevis_ha1g

LOG = logging.getLogger(__name__)

SETTING_FORMAT = """
struct {
  u8 readpwd[8];
  u8 writepwd[8];
  u8 poweronpwd[8];
  u8 squelch;
  u8 powersavingdelaytime:4,
     powersavingmode:4;
  u8 tk1_short;
  u8 tk1_long;
  u8 sk1_short;
  u8 sk1_long;
  u8 sk2_short;
  u8 sk2_long;
  u8 rev_2;
  u8 chknoblock:1,
     sidekeylock:1,
     panellock:1,
     rev_3:3,
     autoormanuallock:1,
     keylockswitch:1;
  u8 rev_4:5,
     lowbattery:1,
     stunmode:2;
  u8 voiceprompts:1,
     touchtone:1,
     txpermittone:1,
     rev_5:1,
     screenlight:1,
     DualWatch:1,
     rogerbeep:2;
  ul16 poweron_type_1:4,
       homepoweronzone_1:12;
  ul16 homepoweronch_1;
  u8 rev_6[27];
  u8 micgain;
  u8 rev_7[2];
  u8 autooff;
  u8 menuouttime;
  u8 voxthreshold:4,
     voxdelaytime:4;
  u8 rev_8:1,
     homeselect:3,
     homeindex:2,
     chdisplay:2;
  ul16 poweron_type_2:4,
     homepoweronzone_2:12;
  ul16 homepoweronch_2;
  u8 rev_9[4];
  u8 freqstep;
  u8 rev_10[2];
  u8 backlightbrightness:4,
     backlighttime:4;
  u8 wxch;
  u8 calltone;
  u8 rev_11:5,
     homechtype_3:1,
     homechtype_2:1,
     homechtype_1:1;
  u8 spreadspectrummode;
  u8 salezone;
  u8 tailsoundeliminationsfre:7,
     tailsoundeliminationswitch:1;
  u8 singletone;
  u8 rev_12:3,
     btswitch:1,
     rev_13:1,
     aviationfreqrx:1,
     fmchtype:1,
     aliasdisplay:1;
  u8 btinmic:1,
     btinspk:1,
     rev_14:6;
  u8 scanlist;
  u8 rev_15[2];
  u16 radioid;
  u8 rev_16[12];
  u8 pttidaliastxmode;
  u8 batterydisplaymode;
  u8 rev_17[28];
  u8 fmchannel;
  u8 rev_18;
  u8 aliasnum;
  u8 timezone;
  u8 rev_19[6];
} settings;
"""

CHANNEL_FORMAT = """
struct channel {
    char alias[14];
    u8 chmode:4,
       chpro:4;
    u8 fixedpower:1,
       fixedbandwidth:1,
       rev_20:2,
       power:2,
       bandwidth:2;
    ul32 rxfreq;
    ul32 txfreq;
    u16 rxctcvaluetype:2,
        rxctctypecode:1,
        rev_1:1,
        rxctc:12;
    u8 rxsqlmode;
    u16 txctcvaluetype:2,
        txctctypecode:1,
        rev_2:1,
        txctc:12;
    u8 totpermissions:2,
       tottime:6;
    u8 vox:1,
       offlineorreversal:2,
       companding:2,
       scramble:1,
       rev_3:2;
    u8 scrambleFreq;
    u8 freqdiff;
    u8 autoscan:1,
       scanlist:7;
    u8 alarmlist;
    u8 rev_4:2,
       pttidtype:2,
       dtmfsignalinglist:4;
    ul32 difffreq;
};

#seekto 0x0a16;
struct {
    ul16 chnum;
    ul16 chindex[1024];
    struct channel channels[1024];
} channeldata;

#seekto 0xb218;
struct {
    ul16 chnum;
    ul16 chindex[3];
    struct channel vfochannels[3];
} vfochanneldata;

"""

FM_FORMAT = """
struct {
    ul16 fmnum;
    ul16 fmindex[64];
    struct {
        char name[14];
        ul32 freq;
        u8 bandwidth;
        u8 rev_1[3];
    } fms[64];
} fmdata;
"""

APRS_FORMAT = """
struct callsign {
   char callsign[8];
   u8 ssid;
};


struct {
   u8 rev_1:4,
      anaptttype:2,
      aprsswitch:2;
   u8 smartbeaconing:2,
      rev_2:2,
      beaconmode:2,
      positionorgps:1,
      beaconreceivetone:1;
   u8 rev_3[3];
   u8 digi_path:4,
      aprsaudio:1,
      rev_4:3;
   struct callsign call;
   struct callsign digi_path_p1[2];
   struct callsign digi_path_p2[2];
   struct callsign digi_path_p3[2];
   struct callsign digi_path_p4[2];
   struct callsign digi_path_f1[8];
   struct callsign digi_path_f2[8];
   char fixsymbol[2];
   u8 rev_5[5];
   struct {
      char degrees[2];
      char minutes[2];
      char dot;
      char seconds[2];
      u8 direction;
   } latitude;
   struct {
      char degrees[3];
      char minutes[2];
      char dot;
      char seconds[2];
      u8 direction;
   } longitude;
   u8 rev_6;
   u8 tx_delay;
   u8 autointerval;
   u8 rev_7;
   u8 screenhold;
   u8 rev_8[4];
   u8 ana_ch;
   u8 rev_9[9];
   struct {
      u8 lowspeed;
      u8 highspeed;
      u8 slowrate;
      u8 fastrate;
      u8 turnangle;
      u8 turnslope;
      u8 turntime;
      u8 rev_10;
   } smartbeacons[4];
   u8 rev_11[64];
   struct {
      ul32 freq;
      u8 band;
   } ana_chs[8];
   u8 rev_12[188];
   char commenttext[64];
} aprsinfo;
"""

GNSS_FORMAT = """
struct {
   u8 gnssswtich:1,
      pttuploadmode:2,
      rev_1:5;
   u8 rev_2[4];
   u8 txtype:4,
      autotxtime:4;
   char replaytext[60];
   u8 rev_3[10];
} gnssinfo;
"""

RADIO_ALIAS_FORMAT = """
struct {
    ul16 aliasnum;
    ul16 aliasindex[30];
   struct {
      char alias[8];
   } alias[30];
} aliaslist;
"""

MEM_FORMAT = f"""
#seekto 0x0E;
{retevis_ha1g.RADIOINFO_FORMAT}
#seekto 0x52;
{retevis_ha1g.DATAVER_FORMAT}
#seekto 0x5C;
{SETTING_FORMAT}
#seekto 0xf4;
{retevis_ha1g.ZONE_FORMAT}
{CHANNEL_FORMAT}
#seekto 0xb298;
{retevis_ha1g.SCAN_FORMAT}
#seekto 0xc0ba;
{retevis_ha1g.VFOSCAN_FORMAT}
#seekto 0xc0fe;
{retevis_ha1g.ALARM_FORMAT}
#seekto 0xc200;
{FM_FORMAT}
#seekto 0xc802;
{retevis_ha1g.DTMF_FORMAT}
#seekto 0xcc6e;
{APRS_FORMAT}
#seekto 0x11812;
{GNSS_FORMAT}
#seekto 0x1185e;
{RADIO_ALIAS_FORMAT}
"""

COMPANDER_LIST = ["OFF", "Tx/Rx", "Rx", "Tx"]

SCRAMBLE_LIST = [
    {"id": 255, "name": "Off"},
    {"id": 0, "name": "2800"},
    {"id": 1, "name": "2900"},
    {"id": 2, "name": "3000"},
    {"id": 3, "name": "3100"},
    {"id": 4, "name": "3200"},
    {"id": 5, "name": "3290"},
    {"id": 6, "name": "3300"},
    {"id": 7, "name": "3380"},
    {"id": 8, "name": "3400"},
    {"id": 9, "name": "3450"}
]

SIDE_KEY_LIST = [
    {"name": "OFF", "id": 0},
    {"name": "TX Power", "id": 1},
    {"name": "Scan", "id": 2},
    {"name": "FM Radio", "id": 3},
    {"name": "Talkaround/Reversal", "id": 5},
    {"name": "Monitor", "id": 15},
    {"name": "Zone Plus", "id": 20},
    {"name": "Zone Minus", "id": 21},
    {"name": "Squelch", "id": 28},
    {"name": "Emergency Start", "id": 29},
    {"name": "Emergency Stop", "id": 30},
    {"name": "Optional DTMF Code", "id": 32},
    {"name": "Switch To QuickZone", "id": 35},
    {"name": "Prog PTT", "id": 31}
]


def _get_memory(self, mem, _mem, ch_index, isvfo=False):
    mem.extra = RadioSettingGroup("Extra", "extra")
    mem.extra.append(
        RadioSetting(
            "tottime",
            "TOT",
            RadioSettingValueList(
                retevis_ha1g.get_namedict_by_items(
                    retevis_ha1g.TIMEOUTTIMER_LIST),
                current_index=(_mem.tottime - 1))))
    mem.extra.append(
        RadioSetting(
            "totpermissions",
            "TX Permissions",
            RadioSettingValueList(retevis_ha1g.TOTPERMISSIONS_LIST,
                                  current_index=_mem.totpermissions)))
    mem.extra.append(
        RadioSetting(
            "rxsqlmode",
            "Squelch Level",
            RadioSettingValueList(retevis_ha1g.SQUELCHLEVEL_LIST,
                                  current_index=_mem.rxsqlmode)))
    mem.extra.append(
        RadioSetting(
            "alarmlist",
            "Alarm System",
            RadioSettingValueList(
                retevis_ha1g.get_namedict_by_items(self._alarm_list),
                current_index=retevis_ha1g.get_item_by_id(self._alarm_list,
                                                          _mem.alarmlist))))
    mem.extra.append(
        RadioSetting(
            "dtmfsignalinglist",
            "DTMF System",
            RadioSettingValueList(
                retevis_ha1g.get_namedict_by_items(self._dtmf_list),
                current_index=retevis_ha1g.get_item_by_id(
                    self._dtmf_list, _mem.dtmfsignalinglist))))
    mem.extra.append(
        RadioSetting(
            "offlineorreversal",
            "Talkaround & Reversal",
            RadioSettingValueList(retevis_ha1g.OFFLINE_REVERSAL_LIST,
                                  current_index=_mem.offlineorreversal)))
    mem.extra.append(
        RadioSetting(
            "companding", "Compander",
            RadioSettingValueList(COMPANDER_LIST,
                                  current_index=_mem.companding)))

    scramble_index = (0 if _mem.scramble == 0
                      else retevis_ha1g.get_item_by_id(
                          SCRAMBLE_LIST, _mem.scrambleFreq))
    mem.extra.append(
        RadioSetting("scrambleFreq", "Scramble",
                     RadioSettingValueList(
                         retevis_ha1g.get_namedict_by_items(SCRAMBLE_LIST),
                         current_index=scramble_index)))
    mem.extra.append(
        RadioSetting(
            "vox", "VOX",
            RadioSettingValueBoolean(_mem.vox)))

    if not isvfo:
        ch_index_dict = retevis_ha1g.get_ch_index(self)
        if ch_index not in ch_index_dict:
            mem.freq = 0
            mem.empty = True
            return mem

    mem.freq = int(_mem.rxfreq)
    mem.name = self.filter_name(str(_mem.alias).rstrip())
    if isvfo:
        mem.immutable += ["name"]
    tx_freq = int(_mem.txfreq)

    if mem.freq == 0 or mem.freq == 0xFFFFFFFF:
        mem.freq = 0
        mem.empty = True
        return mem

    if mem.freq == tx_freq:
        mem.duplex = ""
        mem.offset = 0
    elif tx_freq == 0xFFFFFFFF:
        mem.duplex = "off"
        mem.offset = 0
    else:
        mem.duplex = mem.freq > tx_freq and "-" or "+"
        mem.offset = abs(mem.freq - tx_freq)

    mem.mode = retevis_ha1g.MODES[(1 if _mem.bandwidth >= 3 else 0)]
    if chirp_common.in_range(mem.freq, [self._airband]):
        mem.mode = "AM"

    rxtone = txtone = None
    if _mem.rxctcvaluetype == 1:
        tone_value = _mem.rxctc / 10.0
        if tone_value in chirp_common.TONES:
            rxtone = tone_value
    elif _mem.rxctcvaluetype in [2, 3]:
        rxtone = int("%03o" % _mem.rxctc)

    if _mem.txctcvaluetype == 1:
        tone_value = _mem.txctc / 10.0
        if tone_value in chirp_common.TONES:
            txtone = tone_value
    elif _mem.txctcvaluetype in [2, 3]:
        txtone = int("%03o" % _mem.txctc)

    rx_tone = (("" if _mem.rxctcvaluetype == 0
                else "Tone" if _mem.rxctcvaluetype == 1 else "DTCS"),
               rxtone, (_mem.rxctcvaluetype == 0x3) and "R" or "N")
    tx_tone = (("" if _mem.txctcvaluetype == 0
                else "Tone" if _mem.txctcvaluetype == 1 else "DTCS"),
               txtone, (_mem.txctcvaluetype == 0x3) and "R" or "N")
    chirp_common.split_tone_decode(mem, tx_tone, rx_tone)
    mem.power = retevis_ha1g.POWER_LEVELS[(1 if _mem.power == 2 else 0)]
    return mem


def _set_memory(self, mem, _mem, ch_index, isvfo=False):
    if not isvfo:
        ch_index_dict = retevis_ha1g.get_ch_index(self)
        flag = ch_index not in ch_index_dict and mem.freq != 0
        if mem.freq != 0xFFFFFFFF and flag:
            ch_index_dict.append(ch_index)
        elif ch_index in ch_index_dict and mem.freq <= 0:
            ch_index_dict.remove(ch_index)
        retevis_ha1g.set_ch_index(self, ch_index_dict)

    _mem.fill_raw(b"\x00")
    if mem.empty:
        return

    _mem.rxfreq = mem.freq
    _mem.alias = mem.name.ljust(14)
    txfrq = (int(mem.freq - mem.offset)
             if mem.duplex == "-" and mem.offset > 0
             else (int(mem.freq + mem.offset)
                   if mem.duplex == "+" and mem.offset > 0
                   else mem.freq))
    _mem.txfreq = txfrq
    _mem.bandwidth = 3 if mem.mode == "FM" else 1

    if mem.power in retevis_ha1g.POWER_LEVELS:
        _mem.power = (2 if retevis_ha1g.POWER_LEVELS.index(mem.power) == 1
                      else 0)
    else:
        _mem.power = 0

    ((txmode, txtone, txpol),
     (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

    if rxmode == "Tone":
        _mem.rxctcvaluetype = 1
        _mem.rxctc = int(rxtone * 10)
    elif rxmode == "DTCS":
        _mem.rxctcvaluetype = 3 if rxpol == "R" else 2
        _mem.rxctc = int(str(rxtone), 8)
    else:
        _mem.rxctcvaluetype = 0

    if txmode == "Tone":
        _mem.txctcvaluetype = 1
        _mem.txctc = int(txtone * 10)
    elif txmode == "DTCS":
        _mem.txctcvaluetype = 3 if txpol == "R" else 2
        _mem.txctc = int(str(txtone), 8)
    else:
        _mem.txctcvaluetype = 0

    for setting in mem.extra:
        name = setting.get_name()
        if name == "tottime":
            _mem.tottime = retevis_ha1g.get_item_by_name(
                retevis_ha1g.TIMEOUTTIMER_LIST, str(setting.value))
        elif name == "alarmlist":
            _mem.alarmlist = retevis_ha1g.get_item_by_name(
                self._alarm_list, setting.value)
        elif name == "dtmfsignalinglist":
            _mem.dtmfsignalinglist = retevis_ha1g.get_item_by_name(
                self._dtmf_list, setting.value)
        elif name == "scrambleFreq":
            _mem.scrambleFreq = retevis_ha1g.get_item_by_name(
                SCRAMBLE_LIST, setting.value)
            _mem.scramble = 0 if _mem.scrambleFreq == 255 else 1
        else:
            setattr(_mem, name, setting.value)
    return _mem


def _get_common_setting(self, common):
    _settings = self._memobj.settings
    opts = ["Low", "Normal", "Strengthen"]
    common.append(RadioSetting(
        "settings.micgain", "Mic Gain",
        RadioSettingValueList(opts, current_index=_settings.micgain)))

    opts = ["Stun WakeUp", "Stun TX", "Stun TX/RX"]
    common.append(
        RadioSetting("settings.stunmode", "Stun Type",
                     RadioSettingValueList(opts,
                                           current_index=_settings.stunmode)))

    opts_dict = [{"name": "%s" % (x + 1), "id": x} for x in range(0, 10, 1)]
    common.append(retevis_ha1g.get_radiosetting_by_key(
        self, _settings, "calltone", "Call Tone",
        _settings.calltone, opts_dict))

    opts = ["2.5kHz", "5kHz", "6.25kHz", "7.5kHz",
            "8.33kHz", "10kHz", "12.5kHz", "15kHz",
            "20kHz", "25kHz", "30kHz", "50kHz", "100kHz"]
    common.append(
        RadioSetting(
            "settings.freqstep", "Frequency Step",
            RadioSettingValueList(opts, current_index=_settings.freqstep)))

    opts = ["OFF", "1:1", "1:2", "1:4"]
    common.append(
        RadioSetting(
            "settings.powersavingmode", "Battery Mode",
            RadioSettingValueList(
                opts, current_index=_settings.powersavingmode)))

    opts_dict = [
        {"name": "%ss" % ((x + 1) * 5), "id": x} for x in range(0, 16, 1)]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "powersavingdelaytime", "Battery Delay Time",
            _settings.powersavingdelaytime, opts_dict))

    opts_dict = [{"name": "%s" % x, "id": x} for x in range(1, 16, 1)]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "backlightbrightness", "Backlight Brightness",
            _settings.backlightbrightness, opts_dict))

    opts = [
        "Always", "5s", "10s", "15s", "20s", "25s", "30s",
        "1min", "2min", "3min", "4min", "5min", "15min", "30min",
        "45min", "1h"]
    common.append(
        RadioSetting("settings.backlighttime", "Backlight Time",
                     RadioSettingValueList(
                         opts, current_index=_settings.backlighttime)))

    opts_dict = [{"name": "%s" % x, "id": x} for x in range(1, 16, 1)]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "voxthreshold", "VOX Level",
            _settings.voxthreshold, opts_dict))

    opts_dict = [
        {"name": "%sms" % (x * 500), "id": x} for x in range(1, 5, 1)]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "voxdelaytime", "VOX Delay Time",
            _settings.voxdelaytime, opts_dict))

    opts_dict = [{"name": "OFF", "id": 0}] + [
        {"name": "%ss" % x, "id": x} for x in range(5, 256, 5)]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "menuouttime", "Menu Timeout Setting",
            _settings.menuouttime, opts_dict))

    opts = ["Manual", "Auto"]
    common.append(
        RadioSetting(
            "settings.autoormanuallock", "Key Lock Mode",
            RadioSettingValueList(opts,
                                  current_index=_settings.autoormanuallock)))

    opts = ["Frequency", "Name", "Channel"]
    common.append(
        RadioSetting(
            "settings.chdisplay", "Display Mode",
            RadioSettingValueList(opts, current_index=_settings.chdisplay)))

    opts = ["Band A", "Band B", "Band A & Band B", "Band B & Band A"]
    rs = RadioSetting(
        "settings.homeselect",
        "Band Selection",
        RadioSettingValueList(
            opts,
            current_index=retevis_ha1g.get_band_selection(
                _settings.homeselect, _settings.homeindex)))
    rs.set_apply_callback(
        retevis_ha1g.set_band_selection, _settings, opts,
        "homeselect", "homeindex")
    common.append(rs)

    opts = ["Channel", "VFO Frequency"]
    common.append(
        RadioSetting(
            "settings.homechtype_1",
            "Channel Type A",
            RadioSettingValueList(opts, current_index=_settings.homechtype_1)))
    common.append(
        RadioSetting(
            "settings.homechtype_2",
            "Channel Type B",
            RadioSettingValueList(opts, current_index=_settings.homechtype_2)))

    opts = ["Last Active Channel", "Designated Channel"]
    common.append(
        RadioSetting(
            "settings.poweron_type_1",
            "Power On A",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_1)))
    common.append(
        RadioSetting(
            "settings.poweron_type_2",
            "Power On B",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_2)))

    opts = ["Icon", "Percent", "Voltage"]
    common.append(RadioSetting(
        "settings.batterydisplaymode", "Battery Display Mode",
        RadioSettingValueList(
            opts, current_index=_settings.batterydisplaymode)))

    opts_dict = self.get_scan_item_list()
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "scanlist", "Enable Scan List",
            _settings.scanlist, opts_dict))

    short_dict = SIDE_KEY_LIST[:13]
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "tk1_short", "Short Press Top Key",
            _settings.tk1_short, short_dict))
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "tk1_long", "Long Press Top Key",
            _settings.tk1_long, short_dict))
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "sk1_short", "Short Press Side Key 1",
            _settings.sk1_short, short_dict))
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "sk1_long", "Long Press Side Key 1",
            _settings.sk1_long, SIDE_KEY_LIST))
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "sk2_short", "Short Press Side Key 2",
            _settings.sk2_short, short_dict))
    common.append(
        retevis_ha1g.get_radiosetting_by_key(
            self, _settings, "sk2_long", "Long Press Side Key 2",
            _settings.sk2_long, retevis_ha1g.SIDE_KEY_LIST))

    opts = ["55Hz", "120°", "180°", "240°"]
    common.append(
        RadioSetting(
            "settings.tailsoundeliminationsfre", "CTC Tail Elimination",
            RadioSettingValueList(
                opts, current_index=_settings.tailsoundeliminationsfre)))

    if _settings.salezone != 2:
        opts = ["NOAA-%s" % x for x in range(1, 13, 1)]
        common.append(
            RadioSetting(
                "settings.wxch", "NOAA Channel",
                RadioSettingValueList(opts, current_index=_settings.wxch)))

    opts = ["1000Hz", "1450Hz", "1750Hz", "2100Hz"]
    common.append(
        RadioSetting(
            "settings.singletone", "Single Tone",
            RadioSettingValueList(opts, current_index=_settings.singletone)))

    opts = ["OFF", "Roger Beep", "MDC"]
    common.append(
        RadioSetting(
            "settings.rogerbeep", "Roger Beep",
            RadioSettingValueList(opts, current_index=_settings.rogerbeep)))

    opts = ["OFF", "0.5h", "1.0h", "1.5h", "2.0h", "2.5h", "3.0h"]
    common.append(
        RadioSetting(
            "settings.autooff", "Auto Power Off",
            RadioSettingValueList(opts, current_index=_settings.autooff)))

    opts = ["OFF", "BOT", "EOT", "BOTH"]
    common.append(
        RadioSetting(
            "settings.pttidaliastxmode", "PTTID Alias TX Mode",
            RadioSettingValueList(opts,
                                  current_index=_settings.pttidaliastxmode)))

    opts = ["Alias-%s" % x for x in range(1, 31, 1)]
    rs = RadioSetting(
            "settings.aliasnum", "Radio Alias",
            RadioSettingValueList(opts, current_index=_settings.aliasnum))
    rs.set_doc("Radio Alias can quickly identify who is calling")
    common.append(rs)

    opts = [("UTC%s" % x if x < 0 else "UTC+%s" % x)
            for x in range(-12, 14, 1)]
    common.append(
        RadioSetting(
            "settings.timezone", "Time Zone",
            RadioSettingValueList(opts, current_index=_settings.timezone)))

    common.append(
        RadioSetting(
            "settings.tailsoundeliminationswitch",
            "Tail Elimination Switch",
            RadioSettingValueBoolean(_settings.tailsoundeliminationswitch)))
    common.append(
        RadioSetting(
            "settings.touchtone", "Key Beep",
            RadioSettingValueBoolean(_settings.touchtone)))
    common.append(
        RadioSetting(
            "settings.txpermittone", "TX Permit Tone",
            RadioSettingValueBoolean(_settings.txpermittone)))
    common.append(
        RadioSetting(
            "settings.voiceprompts", "Voice Broadcast",
            RadioSettingValueBoolean(_settings.voiceprompts)))
    common.append(
        RadioSetting(
            "settings.chknoblock", "Channel Knob Lock",
            RadioSettingValueBoolean(_settings.chknoblock)))
    common.append(
        RadioSetting(
            "settings.panellock", "Keyboard Lock",
            RadioSettingValueBoolean(_settings.panellock)))
    common.append(
        RadioSetting(
            "settings.sidekeylock", "Side Key Lock",
            RadioSettingValueBoolean(_settings.sidekeylock)))
    common.append(
        RadioSetting(
            "settings.lowbattery", "Low Battery Alert",
            RadioSettingValueBoolean(_settings.lowbattery)))
    common.append(
        RadioSetting(
            "settings.btswitch", "BT Switch",
            RadioSettingValueBoolean(_settings.btswitch)))
    common.append(
        RadioSetting(
            "settings.screenlight", "Call in Light",
            RadioSettingValueBoolean(_reverse_state(_settings.screenlight))))
    common.append(
        RadioSetting(
            "settings.btinspk", "BT + INT Spk",
            RadioSettingValueBoolean(_settings.btinspk)))


def _get_vfo_scan(self, vfoscan):
    _vfo_scan = self._memobj.vfoscandata.vfoscans[0]
    opts = ["Carrier", "Time", "Search"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scanmode", "Scan Mode",
            RadioSettingValueList(opts, current_index=_vfo_scan.scanmode)))

    opts = ["Carrier", "CTC/DCS"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scancondition", "Scan Condition",
            RadioSettingValueList(opts,
                                  current_index=_vfo_scan.scancondition)))

    opts = ["%s" % (x + 1) for x in range(0, 16, 1)]
    vfoscan.append(
        RadioSetting(
            "vfoscan.hangtime", "Scan Hang Time[s]",
            RadioSettingValueList(opts, current_index=_vfo_scan.hangtime)))
    vfoscan.append(
        RadioSetting(
            "vfoscan.talkback", "Talk Back Enable",
            RadioSettingValueBoolean(_vfo_scan.talkback)))

    opts = ["Current Frequency", "Preset Frequency"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.startcondition", "Start Condition",
            RadioSettingValueList(opts,
                                  current_index=_vfo_scan.startcondition)))

    freq_start = retevis_ha1g.from_MHz(_vfo_scan.vhffreq_start)
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_start", "Start Frequency",
            RadioSettingValueFloat(108, 600, freq_start, 0.00001, 5)))

    freq_end = retevis_ha1g.from_MHz(_vfo_scan.vhffreq_end)
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_end", "End Frequency",
            RadioSettingValueFloat(108, 600, freq_end, 0.00001, 5)))


def _get_aprs_setting(self, aprs):
    _aprsinfo = self._memobj.aprsinfo
    aprs.append(
        RadioSetting(
            "aprsinfo.aprsswitch", "APRS Switch",
            RadioSettingValueBoolean(_aprsinfo.aprsswitch)))

    opts = ["Auto", "Manual", "Smart"]
    aprs.append(RadioSetting(
        "aprsinfo.beaconmode", "Beacon TX Mode",
        RadioSettingValueList(opts, current_index=_aprsinfo.beaconmode)))

    opts = ["100ms", "150ms", "200ms", "250ms",
            "300ms", "400ms", "500ms", "750ms", "1000ms"]
    aprs.append(RadioSetting(
        "aprsinfo.tx_delay", "APRS Tx Delay",
        RadioSettingValueList(opts, current_index=_aprsinfo.tx_delay)))

    opts = ["%ss" % x for x in range(3, 16, 1)] + ["Infinite"]
    aprs.append(RadioSetting(
        "aprsinfo.screenhold", "APRS Screen Hold Time",
        RadioSettingValueList(opts, current_index=_aprsinfo.screenhold)))

    opts = [
        "30s", "1min", "2min", "3min", "5min", "10min", "15min",
        "20min", "30min", "60min"
    ]
    aprs.append(RadioSetting(
        "aprsinfo.autointerval", "APRS Beacon Interval",
        RadioSettingValueList(opts, current_index=_aprsinfo.autointerval)))

    aprs.append(
        RadioSetting(
            "aprsinfo.beaconreceivetone", "APRS Ringer",
            RadioSettingValueBoolean(
                _reverse_state(_aprsinfo.beaconreceivetone))))

    opts = ["GNSS", "Manual"]
    aprs.append(RadioSetting(
        "aprsinfo.positionorgps", "My Position",
        RadioSettingValueList(opts, current_index=_aprsinfo.positionorgps)))

    opts = ["OFF", "Type 1", "Type 2", "Type 3"]
    aprs.append(RadioSetting(
        "aprsinfo.smartbeaconing", "Smart Beacon",
        RadioSettingValueList(opts, current_index=_aprsinfo.smartbeaconing)))

    for i in range(3):
        smartbeacon = _aprsinfo.smartbeacons[i]
        rsg = RadioSettingSubGroup(
            "Type-%d" % (i + 1), "Smart Beacon Type %d" % (i + 1))
        rs = RadioSetting(
            "aprsinfo.smartbeacons.lowspeed_%d" % i, "Low Speed (km/h)",
            RadioSettingValueInteger(2, 30, smartbeacon.lowspeed))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "lowspeed")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.highspeed_%d" % i, "High Speed (km/h)",
            RadioSettingValueInteger(3, 90, smartbeacon.highspeed))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "highspeed")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.slowrate_%d" % i, "Slow Rate (min)",
            RadioSettingValueInteger(1, 100, smartbeacon.slowrate))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "slowrate")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.fastrate_%d" % i, "Fast Rate (s)",
            RadioSettingValueInteger(10, 180, smartbeacon.fastrate))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "fastrate")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.turnangle_%d" % i, "Turn Angle (deg)",
            RadioSettingValueInteger(1, 100, smartbeacon.turnangle))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "turnangle")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.turnslope_%d" % i, "Turn Slope (deg)",
            RadioSettingValueInteger(10, 180, smartbeacon.turnslope))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "turnslope")
        rsg.append(rs)
        rs = RadioSetting(
            "aprsinfo.smartbeacons.turntime_%d" % i, "Turn Time (s)",
            RadioSettingValueInteger(1, 100, smartbeacon.turntime))
        rs.set_apply_callback(_set_int_callback, smartbeacon, "turntime")
        rsg.append(rs)
        aprs.append(rsg)


def _get_ana_aprs_setting(self, aprs):
    _aprsinfo = self._memobj.aprsinfo
    aprs.append(
        RadioSetting(
            "aprsinfo.anaptttype", "PTT Report Mode",
            RadioSettingValueBoolean(_reverse_state(_aprsinfo.anaptttype))))
    aprs.append(
        RadioSetting(
            "aprsinfo.aprsaudio", "Aprs Audio",
            RadioSettingValueBoolean(_aprsinfo.aprsaudio)))
    _get_callsign_setting(aprs, [_aprsinfo.call], "_aprsinfo.Mycall", "My")
    opts = [
        "Selected Channel", "Channel 1", "Channel 2", "Channel 3",
        "Channel 4", "Channel 5", "Channel 6", "Channel 7",
        "Channel 8"]
    aprs.append(RadioSetting(
        "aprsinfo.ana_ch", "Channel",
        RadioSettingValueList(opts, current_index=_aprsinfo.ana_ch)))

    opts = [
        "None", "WIDE1-1", "WIDE1-1 WIDE1-2", "Path1",
        "Path2", "Path3", "Path4", "Full1", "Full2"]
    aprs.append(RadioSetting(
        "aprsinfo.digi_path", "DIGI Path",
        RadioSettingValueList(opts, current_index=_aprsinfo.digi_path)))

    rsg = RadioSettingSubGroup("AnaChannel", "Channel")
    for i in range(len(_aprsinfo.ana_chs)):
        ch_freq = _aprsinfo.ana_chs[i].freq / 100000
        rs = RadioSetting(
            "aprsinfo.ana_ch_%d" % i, "Channel %d" % (i + 1),
            RadioSettingValueFloat(108, 600, ch_freq, 0.00001, 5))
        rs.set_apply_callback(_set_freq_callback,
                              _aprsinfo.ana_chs[i], "freq", 100000)
        rsg.append(rs)
    aprs.append(rsg)

    path_names = ["Path1", "Path2", "Path3", "Path4", "Full1", "Full2"]
    path_objs = [
        _aprsinfo.digi_path_p1, _aprsinfo.digi_path_p2,
        _aprsinfo.digi_path_p3, _aprsinfo.digi_path_p4,
        _aprsinfo.digi_path_f1, _aprsinfo.digi_path_f2]
    for name, obj in zip(path_names, path_objs):
        rsg = RadioSettingSubGroup(name, name)
        _get_callsign_setting(rsg, obj, name)
        aprs.append(rsg)


def _get_gnss_setting(self, gnss):
    _gnssinfo = self._memobj.gnssinfo
    gnss.append(
        RadioSetting(
            "gnssinfo.gnssswtich", "GNSS On/Off",
            RadioSettingValueBoolean(_gnssinfo.gnssswtich)))

    opts = ["OFF", "TX Start", "TX End"]
    gnss.append(RadioSetting(
        "gnssinfo.pttuploadmode", "PTT Report Mode",
        RadioSettingValueList(opts, current_index=_gnssinfo.pttuploadmode)))

    opts = ["Manual", "Auto"]
    gnss.append(RadioSetting(
        "gnssinfo.txtype", "TX Type",
        RadioSettingValueList(opts, current_index=_gnssinfo.txtype)))

    opts = [
        "30s", "1min", "2min", "3min", "5min",
        "10min", "20min", "30min", "60min"
    ]
    gnss.append(RadioSetting(
        "gnssinfo.autotxtime", "Auto TX Interval",
        RadioSettingValueList(opts, current_index=_gnssinfo.autotxtime)))

    replay_text_len = 60
    rs = RadioSetting(
        "gnssinfo.replaytext", "Comment Text",
        RadioSettingValueString(
            0, replay_text_len,
            "".join(retevis_ha1g.filter(
                _gnssinfo.replaytext, retevis_ha1g.NAMECHARSET,
                replay_text_len, True)),
            False, retevis_ha1g.NAMECHARSET))
    rs.set_apply_callback(
        _set_char_callback, _gnssinfo, "replaytext",
        replay_text_len, retevis_ha1g.NAMECHARSET)
    gnss.append(rs)


def _get_fm_setting(self, fm):
    _fminfo = self._memobj.fmdata.fms
    _settings = self._memobj.settings
    fm.append(
        RadioSetting(
            "settings.DualWatch", "dual watch",
            RadioSettingValueBoolean(_reverse_state(_settings.DualWatch))))

    opts = ["Channel", "VFO Frequency"]
    fm.append(RadioSetting(
        "settings.fmchtype", "Channel Type",
        RadioSettingValueList(opts, current_index=_settings.fmchtype)))

    opts = ["FM-%d" % x for x in range(1, 65)]
    fm.append(RadioSetting(
        "settings.fmchannel", "Channel",
        RadioSettingValueList(opts, current_index=_settings.fmchannel)))

    for i in range(len(_fminfo)):
        fm_freq = retevis_ha1g.from_MHz(_fminfo[i].freq)
        rs = RadioSetting(
            "fms.freq_%s" % i, "freq %s" % (i + 1),
            RadioSettingValueFloat(50, 115, fm_freq, 0.01, 2))
        rs.set_apply_callback(_set_freq_callback,
                              _fminfo[i], "freq", 1000000)
        fm.append(rs)


def _get_radio_alias_setting(self, radioalias):
    _radioaliasinfo = self._memobj.aliaslist.alias
    alias_len = 8
    for i in range(len(_radioaliasinfo)):
        rs = RadioSetting(
            "radioalias.alias_%s" % i, "alias %s" % (i + 1),
            RadioSettingValueString(
                0, alias_len,
                "".join(retevis_ha1g.filter(
                    _radioaliasinfo[i].alias, retevis_ha1g.NAMECHARSET,
                    alias_len, True)),
                False, retevis_ha1g.NAMECHARSET))
        rs.set_apply_callback(
            _set_char_callback, _radioaliasinfo[i], "alias", alias_len)
        radioalias.append(rs)


def _get_model_info(self, model_info):
    rs_value = RadioSettingValueString(0, 20, self.current_model)
    rs_value.set_mutable(False)
    rs = RadioSetting("modelinfo.Machinecode", "Machine Code", rs_value)
    model_info.append(rs)
    rs_value = RadioSettingValueString(0, 100, "108.00000-600.00000")
    rs_value.set_mutable(False)
    rs = RadioSetting("modelinfo.freqrange", "Frequency Range[MHz]", rs_value)
    model_info.append(rs)


def _get_callsign_setting(rsg, item, name, name_prefix=""):
    callsign_input_len = 6
    callsign_max_len = 8
    opts = ["-%d" % x for x in range(0, 16, 1)]
    item_len = len(item)
    for i in range(item_len):
        cs_name = ("%s Callsign %d" % (name_prefix, (i + 1))
                   if item_len > 1 else "%s Callsign" % name_prefix)
        rs = RadioSetting(
            "%s.callsign_%s" % (name, i), cs_name,
            RadioSettingValueString(
                0, callsign_input_len,
                "".join(retevis_ha1g.filter(
                    item[i].callsign, retevis_ha1g.NAMECHARSET,
                    callsign_input_len, True)),
                False, retevis_ha1g.NAMECHARSET))
        rs.set_apply_callback(
            _set_char_callback, item[i], "callsign",
            callsign_max_len, retevis_ha1g.NAMECHARSET)
        rsg.append(rs)
        ssid_name = ("%s SSID %d" % (name_prefix, (i + 1))
                     if item_len > 1 else "%s SSID" % name_prefix)
        rs = RadioSetting(
            "%s.ssid_%s" % (name, i), ssid_name,
            RadioSettingValueList(opts, current_index=item[i].ssid))
        rs.set_apply_callback(_set_ssid_callback, item[i], "ssid")
        rsg.append(rs)


def _set_char_callback(set_item, obj, name: str, charlen: int, charset=None):
    if charset is None:
        setattr(obj, name, str(set_item.value).ljust(charlen, "\x00"))
    else:
        setattr(obj, name, retevis_ha1g.filter(
            set_item.value, retevis_ha1g.NAMECHARSET, charlen, True
        ).ljust(charlen, "\x00"))


def _set_freq_callback(set_item, obj, name: str, freq_hz):
    setattr(obj, name, int(round(set_item.value * freq_hz)))


def _set_int_callback(set_item, obj, name: str):
    setattr(obj, name, int(set_item.value))


def _set_ssid_callback(set_item, obj, name: str):
    setattr(obj, name, int(set_item.value))


def _reverse_state(value):
    return value == 0


@directory.register
class HA2(retevis_ha1g.HA1G):
    """Retevis HA2 Driver Implementation"""

    MODEL = "HA2"
    current_model = "Ailunce HA2"
    NEEDS_VER_CHECK = False
    REQUIRED_VER = "v1.0.0.0"
    CH_SKIP_INDEX = 0

    MEMORY_REGIONS_RANGES = {
        "radioHead": (2, 0, 14),
        "radioInfo": (3, 14, 68),
        "radioVer": (4, 82, 10),
        "settingData": (6, 92, 152),
        "zoneData": (7, 244, 2338),
        "channelData": (8, 2582, 43010),
        "vfoChannelData": (9, 45592, 128),
        "scanData": (11, 45720, 3618),
        "vfoScanData": (12, 49338, 68),
        "alarmData": (13, 49406, 258),
        "fmdata": (14, 49664, 1538),
        "dTMFData": (15, 51202, 842),
        "aprsData": (38, 52334, 19364),
        "gnssData": (51, 71698, 76),
        "aliasData": (53, 71774, 302)
    }
    _memsize = max(start + size for _, start,
                   size in MEMORY_REGIONS_RANGES.values())
    _airband = (108000000, 135999999)
    _vhf_uhf = (136000000, 600000001)

    def get_features(self):
        rf = super().get_features()
        rf.memory_bounds = (1, 1024)
        rf.valid_bands = [self._airband, self._vhf_uhf]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self.MEM_FORMAT_VALUE,
                                     self._mmap)
        self._dtmf_list = self.get_dtmf_item_list()
        self._alarm_list = self.get_alarm_item_list()

    def get_memory(self, number):
        mem = chirp_common.Memory()
        _chs = self._memobj.channeldata.channels
        _vfochs = self._memobj.vfochanneldata.vfochannels
        channels_len = len(_chs)
        if isinstance(number, str):
            mem.extd_number = number
            ch_index = 0 if number == "VFOA" else 1
            mem.number = channels_len + ch_index + 1
            _mem = _vfochs[ch_index]
        elif number > channels_len:
            mem.extd_number = "VFOA" if number - channels_len == 1 else "VFOB"
            ch_index = 0 if mem.extd_number == "VFOA" else 1
            _mem = _vfochs[ch_index]
            mem.number = channels_len + ch_index + 1
        else:
            mem.number = number
            ch_index = number - 1
            _mem = _chs[ch_index]
        return _get_memory(self, mem, _mem, ch_index,
                           mem.number > channels_len)

    def set_memory(self, mem):
        _chs = self._memobj.channeldata.channels
        _vfochs = self._memobj.vfochanneldata.vfochannels
        channels_len = len(_chs)
        if mem.number > channels_len:
            ch_index = 0 if mem.extd_number == "VFOA" else 1
            _mem = _vfochs[ch_index]
            _set_memory(self, mem, _mem, ch_index, True)
        else:
            _mem = _chs[mem.number - 1]
            _set_memory(self, mem, _mem, mem.number - 1)
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))

    def get_settings(self):
        model_info = RadioSettingGroup("info", "Model Information")
        common = RadioSettingGroup("basic", "Common Settings")
        dtmf = RadioSettingGroup("dtmfe", "DTMF Settings")
        vfoscan = RadioSettingGroup("vfoscan", "VFO Scan")
        aprs = RadioSettingGroup("aprsinfo", "APRS Settings")
        ana_aprs = RadioSettingGroup("aprsinfo", "Analog APRS Settings")
        gnss = RadioSettingGroup("gnssinfo", "GNSS Settings")
        fm = RadioSettingGroup("fminfo", "FM Settings")
        radioalias = RadioSettingGroup("aliasinfo", "Radio Alias Settings")
        setmode = RadioSettings(model_info, common, dtmf,
                                vfoscan, aprs, ana_aprs, gnss, fm, radioalias)
        try:
            _get_model_info(self, model_info)
            _get_common_setting(self, common)
            retevis_ha1g.get_dtmf_setting(self, dtmf)
            _get_vfo_scan(self, vfoscan)
            _get_aprs_setting(self, aprs)
            _get_ana_aprs_setting(self, ana_aprs)
            _get_gnss_setting(self, gnss)
            _get_fm_setting(self, fm)
            _get_radio_alias_setting(self, radioalias)
        except Exception as e:
            LOG.exception("Error getting settings: %s", e)
        return setmode

    def set_settings(self, uisettings):
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    name = element.get_name()
                    value = element.value
                    if name.startswith("settings."):
                        name = name[9:]
                        if name == "screenlight" or name == "DualWatch":
                            value = 0 if value else 1
                        _settings = self._memobj.settings
                        setattr(_settings, name, value)
                    elif name.startswith("aprsinfo."):
                        name = name[9:]
                        if name == "beaconreceivetone" or name == "anaptttype":
                            value = 0 if value else 1
                        _settings = self._memobj.aprsinfo
                        setattr(_settings, name, value)
                    elif name.startswith("gnssinfo."):
                        name = name[9:]
                        _settings = self._memobj.gnssinfo
                        setattr(_settings, name, value)
                    elif name.startswith("dtmfsetting."):
                        name = name[12:]
                        _dtmfcomm = self._memobj.dtmfdata.dtmfcomm
                        if name in ["callid", "stunid", "revive"]:
                            value = retevis_ha1g.filter(
                                value, retevis_ha1g.DTMFCHARSET, 10, True)
                            value = value.ljust(10, "\x00")
                        elif name in ["bot", "eot"]:
                            value = retevis_ha1g.filter(
                                value, retevis_ha1g.DTMFCHARSET, 16, True)
                            value = value.ljust(16, "\x00")
                        setattr(_dtmfcomm, name, value)
                    elif name.startswith("vfoscan."):
                        name = name[8:]
                        _vfo_scan = self._memobj.vfoscandata.vfoscans[0]
                        if name in ["vhffreq_start", "vhffreq_end"]:
                            value = chirp_common.to_MHz(value)
                        setattr(_vfo_scan, name, value)
                    LOG.debug("Setting %s: %s", name, value)
            except Exception:
                LOG.exception(element.get_name())
                raise

    def supports_airband(self):
        return True

    def supports_banks(self):
        return False
