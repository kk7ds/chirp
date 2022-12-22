# encoding=utf-8
# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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
import time
import logging
import binascii

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import InvalidValueError, RadioSetting, RadioSettingGroup, RadioSettingValue, RadioSettingValueFloat, \
                           RadioSettingValueList, RadioSettingValueBoolean, RadioSettingValueString, RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(thread)d][%(filename)s][line: %(lineno)d][%(levelname)s] ## %(message)s')
ch.setFormatter(formatter)
LOG.addHandler(ch)

MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  u8 rxtone[2];
  u8 txtone[2]; 
  u8 unused1;
  u8 pttid:2,
     skip:1,
     unused3:1,
     unused4:1,
     bcl:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpower:2,
     wide:1,
     unused8:1,
     offset:2;
  u8 unused10;  
} memory[200];

#seekto 0x0D38;
struct {
  char name[8];
  u8 unknown2[8];
} names[200];

#seekto 0x0CA8;
struct {
  u8 txled:1,
     rxled:1,
     unused11:1,
     ham:1,
     gmrs:1,      
     unused14:1,
     unused15:1,
     pritx:1;
  u8 scanmode:2,
     unused16:1,
     keyautolock:1,
     unused17:1,
     btnvoice:1,
     unknown18:1,
     voiceprompt:1;
  u8 fmworkmode:1,
     sync:1,
     tonevoice:2,     
     fmrec:1,
     mdfa:1,
     aworkmode:2;
  u8 openmes:2,       
     unused19:1,
     mdfb:1,
     unused20:1,
     dbrx:1,
     bworkmode:2;
  u8 ablock;
  u8 bblock;
  u8 fmroad;
  u8 unused21:1,
     tailclean:1,        
     rogerprompt:1,
     unused23:1,
     unused24:1,
     voxgain:3;
  u8 astep:4,
     bstep:4;   
  u8 squelch;
  u8 tot;
  u8 lang;
  u8 save;
  u8 ligcon;         
  u8 voxdelay;   
  u8 alarm;           
} settings;

#seekto 0x0CB8;
struct {
    u8 ofseta[4];
    u8 ununsed26[12];
} aoffset;

#seekto 0x0CBC;
struct {
    u8 ofsetb[4];
    u8 ununsed27[12];
} boffset;

#seekto 0x0CD8;
struct{
    u8 fmblock[4];
}fmmode[25];

#seekto 0x1A08;
struct{
    u8 block8:1,
       block7:1,
       block6:1,
       block5:1,
       block4:1,
       block3:1,
       block2:1,
       block1:1; 
} blockfirm[25];

#seekto 0x1a28;
struct{
  u8 scan8:1,
     scan7:1,
     scan6:1,
     scan5:1,
     scan4:1,
     scan3:1,
     scan2:1,
     scan1:1;
} scanadd[25];

#seekto 0x1B38;
struct{
    u8 vfo[4];
}fmvfo;

#seekto 0x1B58;
struct {
  lbcd rxfreqa[4];
  lbcd txfreq[4];
  u8 rxtone[2];
  u8 txtone[2]; 
  u8 unused1;
  u8 pttid:2,
     skip:1,
     unused3:1,
     unused4:1,
     bcl:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpower:2,
     wide:1,
     unused8:1,
     offset:2;
  u8 unused10;  
} vfoa;

#seekto 0x1B68;
struct {
  lbcd rxfreqb[4];
  lbcd txfreq[4];
  u8 rxtoneb[2];
  u8 txtone[2]; 
  u8 unused1;
  u8 pttid:2,
     skipb:1,
     unused3:1,
     unused4:1,
     bclb:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpowerb:2,
     wideb:1,
     unused8:1,
     offsetb:2;
  u8 unused10;  
} vfob;

#seekto 0x1B78;
struct{
   u8  block8:1,
       block7:1,
       block6:1,
       block5:1,
       block4:1,
       block3:1,
       block2:1,
       block1:1; 
} fmblockfirm[4];

#seekto 0x1CC8;
struct{
  u8 stopkey1;
  u8 ssidekey1;
  u8 ssidekey2;
  u8 ltopkey2;
  u8 lsidekey3;
  u8 lsidekey4;
  u8 unused25[10];
} press;

#seekto 0x1E28;
struct{
    u8 idcode[3];
}icode;

#seekto 0x1E31;
struct{
    u8 gcode;
}groupcode;

#seekto 0x1E38;
struct{
    u8 group1[7];
}group1;

#seekto 0x1E48;
struct{
    u8 group2[7];
}group2;

#seekto 0x1E58;
struct{
    u8 group3[7];
}group3;

#seekto 0x1E68;
struct{
    u8 group4[7];
}group4;

#seekto 0x1E78;
struct{
    u8 group5[7];
}group5;

#seekto 0x1E88;
struct{
    u8 group6[7];
}group6;

#seekto 0x1E98;
struct{
    u8 group7[7];
}group7;

#seekto 0x1EA8;
struct{
    u8 group8[7];
}group8;

#seekto 0x1EC8;
struct{
    u8 scode[7];
}startcode;

#seekto 0x1ED8;
struct{
    u8 ecode[7];
}endcode;

"""

# 0x1EC0 - 0x2000

vhf_220_radio = "\x06"

# mode
MODE_RADIO = ""

# basic settings
SQUELCH = ['%s' % x for x in range(0, 10)]
LIGHT_LIST = ["CONT", "5s", "10s", "15s", "30s"]
VOICE_PRMPT_LIST = ["OFF", "ON"]
AUTOLOCK_LIST = ["OFF", "ON"]
TIME_OUT_LIST = ["OFF", "60s", "120s", "180s"]
MDFA_LIST = ["Frequency", "Name"]
MDFB_LIST = ["Frequency", "Name"]
SYNC_LIST = ["ON", "OFF"]
LANG_LIST = ["Chinese", "English"]
BTV_SAVER_LIST = ["OFF", "1:1", "1:2", "1:3", "1:4"]
DBRX_LIST = ["OFF", "ON"]
ASTEP_LIST = ["2.50K", "5.00K", "6.25K", "10.00K", "12.00K", "25.00K", "50.00K"]
BSTEP_LIST = ["2.50K", "5.00K", "6.25K", "10.00K", "12.00K", "25.00K", "50.00K"]
SCAN_MODE_LIST = ["TO", "CO", "SE"]
PRIO_LIST = ["Edit", "Busy"]
SHORT_KEY_LIST = ["None", "FM Radio", "Lamp", "Monitor", "TONE", "Alarm", "Weather"]
LONG_KEY_LIST = ["None", "FM Radio", "Lamp", "Monitor", "TONE", "Alarm", "Weather"]
BUSYLOCK_LIST = ["Off", "On"]
PRESS_NAME = ["stopkey1", "ssidekey1", "ssidekey2", "ltopkey2", "lsidekey3", "lsidekey4",]
 
VFOA_NAME = ["rxfreqa",
            "txfreq",
            "rxtone",
            "txtone", 
            "pttid",
            "skip",
            "bcl",
            "lowpower",
            "wide",
            "offset"]

VFOB_NAME =["rxfreqb",
            "txfreq",
            "rxtoneb",
            "txtone",
            "pttid",
            "skipb",
            "bclb",
            "lowpowerb",
            "wideb",
            "offsetb"]

# KEY
VOX_GAIN = ["OFF", "1", "2", "3", "4", "5"]
VOX_DELAY = ["1.05s", "2.0s", "3.0s"]
PTTID_VALUES = ["Off", "BOT", "EOT", "BOTH"]
BCLOCK_VALUES = ["Off", "On"]
FREQHOP_VALUES = ["Off", "On"]
SCAN_VALUES = ["Del", "Add"]

# AB CHANNEL
A_OFFSET = ["Off", "-", "+"]
A_QTDQT_DTCS = ['Off', '67.0', '69.3', '71.9', '74.4', '77.0', 
                '79.7', '82.5', '85.4', '88.5', '91.5', '94.8', 
                '97.4', '100.0', '103.5', '107.2', '110.9', 
                '114.8', '118.8', '123.0', '127.3', '131.8', 
                '136.5', '141.3', '146.2', '151.4', '156.7', 
                '159.8', '162.2', '165.5', '167.9', '171.3', 
                '173.8', '177.3', '179.9', '183.5', '186.2', 
                '189.9', '192.8', '196.6', '199.5', '203.5', 
                '206.5', '210.7', '218.1', '225.7', '229.1', 
                '233.6', '241.8', '250.3', '254.1',
                'D023N', 'D025N', 'D026N', 'D031N', 'D032N', 'D036N', 
                'D043N', 'D047N', 'D051N', 'D053N', 'D054N', 'D065N', 
                'D071N', 'D072N', 'D073N', 'D074N', 'D114N', 'D115N', 
                'D116N', 'D122N', 'D125N', 'D131N', 'D132N', 'D134N', 
                'D143N', 'D145N', 'D152N', 'D155N', 'D156N', 'D162N', 
                'D165N', 'D172N', 'D174N', 'D205N', 'D212N', 'D223N', 
                'D225N', 'D226N', 'D243N', 'D244N', 'D245N', 'D246N', 
                'D251N', 'D252N', 'D255N', 'D261N', 'D263N', 'D265N', 
                'D266N', 'D271N', 'D274N', 'D306N', 'D311N', 'D315N', 
                'D325N', 'D331N', 'D332N', 'D343N', 'D346N', 'D351N', 
                'D356N', 'D364N', 'D365N', 'D371N', 'D411N', 'D412N', 
                'D413N', 'D423N', 'D431N', 'D432N', 'D445N', 'D446N', 
                'D452N', 'D454N', 'D455N', 'D462N', 'D464N', 'D465N', 
                'D466N', 'D503N', 'D506N', 'D516N', 'D523N', 'D526N', 
                'D532N', 'D546N', 'D565N', 'D606N', 'D612N', 'D624N', 
                'D627N', 'D631N', 'D632N', 'D654N', 'D662N', 'D664N', 
                'D703N', 'D712N', 'D723N', 'D731N', 'D732N', 'D734N', 
                'D743N', 'D754N', 'D023I', 'D025I', 'D026I', 'D031I', 
                'D032I', 'D036I', 'D043I', 'D047I', 'D051I', 'D053I', 
                'D054I', 'D065I', 'D071I', 'D072I', 'D073I', 'D074I', 
                'D114I', 'D115I', 'D116I', 'D122I', 'D125I', 'D131I', 
                'D132I', 'D134I', 'D143I', 'D145I', 'D152I', 'D155I', 
                'D156I', 'D162I', 'D165I', 'D172I', 'D174I', 'D205I', 
                'D212I', 'D223I', 'D225I', 'D226I', 'D243I', 'D244I', 
                'D245I', 'D246I', 'D251I', 'D252I', 'D255I', 'D261I', 
                'D263I', 'D265I', 'D266I', 'D271I', 'D274I', 'D306I', 
                'D311I', 'D315I', 'D325I', 'D331I', 'D332I', 'D343I', 
                'D346I', 'D351I', 'D356I', 'D364I', 'D365I', 'D371I', 
                'D411I', 'D412I', 'D413I', 'D423I', 'D431I', 'D432I', 
                'D445I', 'D446I', 'D452I', 'D454I', 'D455I', 'D462I', 
                'D464I', 'D465I', 'D466I', 'D503I', 'D506I', 'D516I', 
                'D523I', 'D526I', 'D532I', 'D546I', 'D565I', 'D606I', 
                'D612I', 'D624I', 'D627I', 'D631I', 'D632I', 'D654I', 
                'D662I', 'D664I', 'D703I', 'D712I', 'D723I', 'D731I', 
                'D732I', 'D734I', 'D743I', 'D754I']


A_TX_POWER = ["Low", "Mid", "High"]
A_BAND = ["Wide", "Narrow"]
A_BUSYLOCK = ["Off", "On"]
A_SPEC_QTDQT = ["Off", "On"]
A_WORKMODE = ["VFO", "VFO+CH", "CH Mode"]

B_OFFSET = ["Off", "-", "+"]
B_QTDQT_DTCS = ['Off', '67.0', '69.3', '71.9', '74.4', '77.0', 
                '79.7', '82.5', '85.4', '88.5', '91.5', '94.8', 
                '97.4', '100.0', '103.5', '107.2', '110.9', 
                '114.8', '118.8', '123.0', '127.3', '131.8', 
                '136.5', '141.3', '146.2', '151.4', '156.7', 
                '159.8', '162.2', '165.5', '167.9', '171.3', 
                '173.8', '177.3', '179.9', '183.5', '186.2', 
                '189.9', '192.8', '196.6', '199.5', '203.5', 
                '206.5', '210.7', '218.1', '225.7', '229.1', 
                '233.6', '241.8', '250.3', '254.1',
                'D023N', 'D025N', 'D026N', 'D031N', 'D032N', 'D036N', 
                'D043N', 'D047N', 'D051N', 'D053N', 'D054N', 'D065N', 
                'D071N', 'D072N', 'D073N', 'D074N', 'D114N', 'D115N', 
                'D116N', 'D122N', 'D125N', 'D131N', 'D132N', 'D134N', 
                'D143N', 'D145N', 'D152N', 'D155N', 'D156N', 'D162N', 
                'D165N', 'D172N', 'D174N', 'D205N', 'D212N', 'D223N', 
                'D225N', 'D226N', 'D243N', 'D244N', 'D245N', 'D246N', 
                'D251N', 'D252N', 'D255N', 'D261N', 'D263N', 'D265N', 
                'D266N', 'D271N', 'D274N', 'D306N', 'D311N', 'D315N', 
                'D325N', 'D331N', 'D332N', 'D343N', 'D346N', 'D351N', 
                'D356N', 'D364N', 'D365N', 'D371N', 'D411N', 'D412N', 
                'D413N', 'D423N', 'D431N', 'D432N', 'D445N', 'D446N', 
                'D452N', 'D454N', 'D455N', 'D462N', 'D464N', 'D465N', 
                'D466N', 'D503N', 'D506N', 'D516N', 'D523N', 'D526N', 
                'D532N', 'D546N', 'D565N', 'D606N', 'D612N', 'D624N', 
                'D627N', 'D631N', 'D632N', 'D654N', 'D662N', 'D664N', 
                'D703N', 'D712N', 'D723N', 'D731N', 'D732N', 'D734N', 
                'D743N', 'D754N', 'D023I', 'D025I', 'D026I', 'D031I', 
                'D032I', 'D036I', 'D043I', 'D047I', 'D051I', 'D053I', 
                'D054I', 'D065I', 'D071I', 'D072I', 'D073I', 'D074I', 
                'D114I', 'D115I', 'D116I', 'D122I', 'D125I', 'D131I', 
                'D132I', 'D134I', 'D143I', 'D145I', 'D152I', 'D155I', 
                'D156I', 'D162I', 'D165I', 'D172I', 'D174I', 'D205I', 
                'D212I', 'D223I', 'D225I', 'D226I', 'D243I', 'D244I', 
                'D245I', 'D246I', 'D251I', 'D252I', 'D255I', 'D261I', 
                'D263I', 'D265I', 'D266I', 'D271I', 'D274I', 'D306I', 
                'D311I', 'D315I', 'D325I', 'D331I', 'D332I', 'D343I', 
                'D346I', 'D351I', 'D356I', 'D364I', 'D365I', 'D371I', 
                'D411I', 'D412I', 'D413I', 'D423I', 'D431I', 'D432I', 
                'D445I', 'D446I', 'D452I', 'D454I', 'D455I', 'D462I', 
                'D464I', 'D465I', 'D466I', 'D503I', 'D506I', 'D516I', 
                'D523I', 'D526I', 'D532I', 'D546I', 'D565I', 'D606I', 
                'D612I', 'D624I', 'D627I', 'D631I', 'D632I', 'D654I', 
                'D662I', 'D664I', 'D703I', 'D712I', 'D723I', 'D731I', 
                'D732I', 'D734I', 'D743I', 'D754I']

B_TX_POWER = ["Low", "Mid", "High"]
B_BAND = ["Wide", "Narrow"]
B_BUSYLOCK = ["Off", "On"]
B_SPEC_QTDQT = ["Off", "On"]
B_WORKMODE = ["VFO", "VFO+CH", "CH Mode"]

# FM
FM_WORKMODE = ["CH", "VFO"]
FM_CHANNEL = ['%s' % x for x in range(0, 26)]

# DTMF
GROUPCODE = ["","Off", "*", "#", "A", "B", "C", "D"]


BASETYPE_UV5R = ["BFS", "BFB", "N5R-2", "N5R2", "N5RV", "BTS", "D5R2", "B5R2"]
BASETYPE_F11 = ["USA"]
BASETYPE_UV82 = ["US2S2", "B82S", "BF82", "N82-2", "N822"]
BASETYPE_BJ55 = ["BJ55"]  # needed for for the Baojie UV-55 in bjuv55.py
BASETYPE_UV6 = ["BF1", "UV6"]
BASETYPE_KT980HP = ["BFP3V3 B"]
BASETYPE_F8HP = ["BFP3V3 F", "N5R-3", "N5R3", "F5R3", "BFT", "N5RV"]
BASETYPE_UV82HP = ["N82-3", "N823", "N5R2"]
BASETYPE_UV82X3 = ["HN5RV01"]
BASETYPE_LIST = BASETYPE_UV5R + BASETYPE_F11 + BASETYPE_UV82 + \
    BASETYPE_BJ55 + BASETYPE_UV6 + BASETYPE_KT980HP + \
    BASETYPE_F8HP + BASETYPE_UV82HP + BASETYPE_UV82X3

AB_LIST = ["A", "B"]
ALMOD_LIST = ["Site", "Tone", "Code"]
BANDWIDTH_LIST = ["Wide", "Narrow"]
COLOR_LIST = ["Off", "Blue", "Orange", "Purple"]
DTMFSPEED_LIST = ["%s ms" % x for x in range(50, 2010, 10)]
DTMFST_LIST = ["OFF", "DT-ST", "ANI-ST", "DT+ANI"]
MODE_LIST = ["Channel", "Name", "Frequency"]
PONMSG_LIST = ["Full", "Message"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
RTONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100Hz"]
RESUME_LIST = ["TO", "CO", "SE"]
ROGERRX_LIST = ["Off"] + AB_LIST
RPSTE_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
SAVE_LIST = ["Off", "1:1", "1:2", "1:3", "1:4"]
SCODE_LIST = ["%s" % x for x in range(1, 16)]
SHIFTD_LIST = ["Off", "+", "-"]
STEDELAY_LIST = ["OFF"] + ["%s ms" % x for x in range(100, 1100, 100)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
STEP_LIST = [str(x) for x in STEPS]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
STEP291_LIST = [str(x) for x in STEPS]
TDRAB_LIST = ["Off"] + AB_LIST
TDRCH_LIST = ["CH%s" % x for x in range(1, 129)]
TIMEOUT_LIST = ["%s sec" % x for x in range(15, 615, 15)] + \
    ["Off (if supported by radio)"]
TXPOWER_LIST = ["High", "Low"]
TXPOWER3_LIST = ["High", "Mid", "Low"]
VOICE_LIST = ["Off", "English", "Chinese"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
WORKMODE_LIST = ["Frequency", "Channel"]

SETTING_LISTS = {
    "almod": ALMOD_LIST,
    "aniid": PTTID_LIST,
    "displayab": AB_LIST,
    "dtmfst": DTMFST_LIST,
    "dtmfspeed": DTMFSPEED_LIST,
    "mdfa": MODE_LIST,
    "mdfb": MODE_LIST,
    "ponmsg": PONMSG_LIST,
    "pttid": PTTID_LIST,
    "rtone": RTONE_LIST,
    "rogerrx": ROGERRX_LIST,
    "rpste": RPSTE_LIST,
    "rxled": COLOR_LIST,
    "save": SAVE_LIST,
    "scode": PTTIDCODE_LIST,
    "screv": RESUME_LIST,
    "sftd": SHIFTD_LIST,
    "stedelay": STEDELAY_LIST,
    "step": STEP_LIST,
    "step291": STEP291_LIST,
    "tdrab": TDRAB_LIST,
    "tdrch": TDRCH_LIST,
    "timeout": TIMEOUT_LIST,
    "txled": COLOR_LIST,
    "txpower": TXPOWER_LIST,
    "txpower3": TXPOWER3_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    "widenarr": BANDWIDTH_LIST,
    "workmode": WORKMODE_LIST,
    "wtled": COLOR_LIST
}

GMRS_FREQS1 = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625,
               462.6875, 462.7125]
GMRS_FREQS2 = [467.5625, 467.5875, 467.6125, 467.6375, 467.6625,
               467.6875, 467.7125]
GMRS_FREQS3 = [462.5500, 462.5750, 462.6000, 462.6250, 462.6500,
               462.6750, 462.7000, 462.7250]
GMRS_FREQS_B = GMRS_FREQS2 * 3 + GMRS_FREQS3 * 2

GMRS_FREQ_A = GMRS_FREQS1 + GMRS_FREQS3

HAM_FREQS = [162.55000, 162.40000, 162.47500, 162.42500, 162.45000,
             162.50000, 162.52500, 161.65000, 161.77500, 161.75000, 162.00000]
HAM_NAME = ["NOAA 1", "NOAA 2", "NOAA 3", "NOAA 4", "NOAA 5", "NOAA 6",
            "NOAA 7", "NOAA 8", "NOAA 9", "NOAA 10", "NOAA 11"]

def _do_status(radio, block):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = block
    status.max = radio._memsize
    radio.status_fn(status)

TD_H8 = "\x50\x56\x4f\x4a\x48\x1c\x14"

CMD_ACK = "\x06"

def _upper_band_from_data(data):
    return data[0x03:0x04]


def _upper_band_from_image(radio):
    return _upper_band_from_data(radio.get_mmap())


def _firmware_version_from_data(data, version_start, version_stop):
    version_tag = data[version_start:version_stop]
    return version_tag


# def _firmware_version_from_image(radio):
#     version = _firmware_version_from_data(radio.get_mmap(),
#                                           radio._fw_ver_file_start,
#                                           radio._fw_ver_file_stop)
#     LOG.debug("_firmware_version_from_image: " + util.hexprint(version))
#     return version


def _do_ident(radio, magic, secondack=True):
    serial = radio.pipe
    serial.timeout = 1
    
    #LOG.info("Sending Magic: %s" % util.hexprint(magic))
    # for byte in magic:
    serial.write(magic)
    ack = serial.read(1)

    if ack != "\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    serial.write("\x02")

    # Until recently, the "ident" returned by the radios supported by this
    # driver have always been 8 bytes long. The image sturcture is the 8 byte
    # "ident" followed by the downloaded memory data. So all of the settings
    # structures are offset by 8 bytes. The ident returned from a UV-6 radio
    # can be 8 bytes (original model) or now 12 bytes.
    #
    # To accomodate this, the "ident" is now read one byte at a time until the
    # last byte ("\xdd") is encountered. The bytes containing the value "\x01"
    # are discarded to shrink the "ident" length down to 8 bytes to keep the
    # image data aligned with the existing settings structures.
    

    # Ok, get the response
    response = ""
    for i in range(1, 9):
        byte = serial.read(1)
        response += byte
        # stop reading once the last byte ("\xdd") is encountered
        # if byte == "\xff":
        #     break

    # check if response is OK
    if len(response) in [8, 12]:
        # DEBUG
        LOG.info("Valid response, got this:")
        LOG.debug(util.hexprint(response))
        # print(util.hexprint(response)[31:37])
        
        # 判断对讲机模式
        global MODE_RADIO 
        MODE_RADIO = util.hexprint(response)[31:37]
        
        if len(response) == 12:
            ident = response[0] + response[3] + response[5] + response[7:]
        else:
            ident = response
    else:
        # bad response
        msg = "Unexpected response, got this:"
        msg += util.hexprint(response)
        LOG.debug(msg)
        raise errors.RadioError("Unexpected response from radio.")
    
    
    if secondack:
        serial.write("\x06")
        ack = serial.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio refused clone")

    return ident

def response_mode(mode):
    data = mode
    return data

def _read_block(radio, start, size):
    serial = radio.pipe
    
    cmd = struct.pack(">cHb", 'R', start, size)
    expectedresponse = "W" + cmd[1:]
    # LOG.debug("Reading block %04x..." % (start))

    try:
        serial.write(cmd)
        response = serial.read(5 + size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (start))

        block_data = response[4:-1]
        # print("block_data = {}".format(str(binascii.b2a_hex(block_data))))
        
    except:
        raise errors.RadioError("Failed to read block at %04x" % start)
    
    return block_data


def _get_radio_firmware_version(radio):
    if radio.MODEL == "TD-H8_HAM":
        block = _read_block(radio, 0x1B40, 0x20)
        version = block[0:6]
    # else:
    #     block1 = _read_block(radio, 0x1EC0, 0x40, True)
    #     block2 = _read_block(radio, 0x1F00, 0x40, False)
    #     block = block1 + block2
    #     version = block[48:62]
    return version


IDENT_BLACKLIST = {
    "\x50\x56\x4F\x4A\x48\x1C\x14": "Radio identifies as TDH8",
}

# def mode_data(radio):
#     for magic in radio._idents:
#         try:
#             data = _do_mode(radio, magic)
#             return data
#         except errors.RadioError, e:
#             LOG.error("tdh8._mode_radio: %s")
#             time.sleep(2)
            
            
# def _do_mode(radio, magic, secondack=True):
#     serial = radio.pipe
#     serial.timeout = 1
    
#     #LOG.info("Sending Magic: %s" % util.hexprint(magic))
#     # for byte in magic:
#     serial.write(magic)
#     ack = serial.read(1)

#     if ack != "\x06":
#         if ack:
#             LOG.debug(repr(ack))
#         raise errors.RadioError("Radio did not respond")

#     serial.write("\x02")

#     response = ""
#     for i in range(1, 9):
#         byte = serial.read(1)
#         response += byte

#     if len(response) in [8, 12]:
#         # DEBUG
#         LOG.info("Valid response, got this:")
#         LOG.debug(util.hexprint(response))
#         # print(util.hexprint(response)[31:37])
#         response_mode(util.hexprint(response)[31:37])
#         if len(response) == 12:
#             ident = response[0] + response[3] + response[5] + response[7:]
#         else:
#             ident = response
#     else:
#         # bad response
#         msg = "Unexpected response, got this:"
#         msg += util.hexprint(response)
#         LOG.debug(msg)
#         raise errors.RadioError("Unexpected response from radio.") 
            
            
            
            
            
            
            
            
            


def _ident_radio(radio):
    for magic in radio._idents:
        error =  None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError, e:
            LOG.error("tdh8._ident_radio: %s", e)
            error = e
            time.sleep(2)

    for magic, reason in IDENT_BLACKLIST.items():
        try:
            _do_ident(radio, magic, secondack=False)
        except errors.RadioError as e:
            # No match, try the next one
            continue

        # If we got here, it means we identified the radio as
        # something other than one of our valid idents. Warn
        # the user so they can do the right thing.
        LOG.warning(('Identified radio as a blacklisted model '
                     '(details: %s)') % reason)
        raise errors.RadioError(('%s. Please choose the proper vendor/'
                                 'model and try again.') % reason)

    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _do_download(radio):
    data = _ident_radio(radio)

    radio_version = _get_radio_firmware_version(radio)
    LOG.info("Radio Version is %s" % repr(radio_version))

    append_model = False
 
    # Main block
    LOG.debug("Downloading...")
    
    for i in range(0, radio._memsize, 0x20):
        block = _read_block(radio, i, 0x20)
        data += block
        _do_status(radio, i)
    _do_status(radio, radio._memsize)
    LOG.debug("done.")

    if append_model:
        data += radio.MODEL.ljust(8)

    # LOG.debug("done.")
    return memmap.MemoryMap(data)

def _exit_write_block(radio):
    serial = radio.pipe
    try:
        serial.write("E")
       
    except:
        raise errors.RadioError("Radio refused to exit programming mode")

def _write_block(radio, addr, data):
    serial = radio.pipe
    cmd = struct.pack(">cHb", 'W', addr, 0x20)
    data = radio.get_mmap()[addr + 8 : addr + 40]
    data_cmd = bytearray(data)
    cmd_str = str(hex(sum(data_cmd) & 0xff)[2:])
    data_bused = chr(int(cmd_str, 16))
    data += data_bused
    used_data = cmd + data
    # used_data = used_data.rstrip()
    serial.write(used_data)
    
    ack = radio.pipe.read(1)
    # f = open("C:/Users/33095/Desktop/test_ack.txt","a")
    # f.write(str(binascii.b2a_hex(ack)) + "\n")
    # f.close
    # print("数据打印完成！已保存到桌面！")
    # print("response = {}".format(str(binascii.b2a_hex(ack))))
    # ack = ack.strip('\n')
    if ack != "\x06":
        raise errors.RadioError("Radio refused to accept block 0x%04x" % addr)

def _do_upload(radio):
    ident = _ident_radio(radio)
    # image_version = _firmware_version_from_image(radio)
    radio_version = _get_radio_firmware_version(radio)
    # LOG.info("Image Version is %s" % repr(image_version))
    LOG.info("Radio Version is %s" % repr(radio_version))

    # Main block
    LOG.debug("Uploading...")

    for start_addr, end_addr in radio._ranges_main:
        for addr in range(start_addr, end_addr, 0x20):
            _write_block(radio, addr, 0x20)
            _do_status(radio, addr)
    # LOG.debug("Upload block 1~188 done.")
    # for start_addr, end_addr in radio._other_main:
    #     for addr in range(start_addr, end_addr, 0x20):
    #         _write_block(radio, addr, 0x20)
    #         _do_status(radio, addr)
    _exit_write_block(radio)
    LOG.debug("Upload all done.")
    


UV5R_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=4.00),
                     chirp_common.PowerLevel("Low",  watts=1.00)]

TX_POWER = [chirp_common.PowerLevel("Low",  watts=1.00),
            chirp_common.PowerLevel("Mid",  watts=4.00),
            chirp_common.PowerLevel("High", watts=8.00),]

UV5R_DTCS = sorted(chirp_common.DTCS_CODES + [645])

UV5R_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + \
    "!@#$%^&*()+-=[]:\";'<>?,./"


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == 0x1950:
        rid = data[0x1948:0x1950]
        return rid.startswith(cls.MODEL)
    elif len(data) == 0x1948:
        rid = data[cls._fw_ver_file_start:cls._fw_ver_file_stop]
        if any(type in rid for type in cls._basetype):
            return True
    else:
        return False

@directory.register
class TDH8(chirp_common.CloneModeRadio):
    """TID TD-H8_HAM"""
    VENDOR = "TID"
    MODEL = "TD-H8_HAM"
    BAUD_RATE = 38400
    _memsize = 0x1eef
    _ranges_main = [(0x0000, 0x1eef)]
    # _other_main = [(0x1868, 0x1eff)]
    _basetype = BASETYPE_UV5R
    _idents = [TD_H8]
    _vhf_range = (136000000, 174000000)
    _220_range = (220000000, 260000000)
    _uhf_range = (400000000, 520000000)
    _aux_block = True
    _tri_power = True
    _gmrs = True
    _ham = True
    _mem_params = (0x1F2F) # poweron_msg offset

    # offset of fw version in image file
    _fw_ver_file_start = 0x1838
    _fw_ver_file_stop = 0x1846

    
    
    # _ranges_aux = [
    #                (0x1EC0, 0x2000),
    #               ]
    
    
    _valid_chars = UV5R_CHARSET

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('Due to the fact that the manufacturer continues to '
             'release new versions of the firmware with obscure and '
             'hard-to-track changes, this driver may not work with '
             'your device. Thus far and to the best knowledge of the '
             'author, no UV-5R radios have been harmed by using CHIRP. '
             'However, proceed at your own risk!')
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to download image from device."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to upload image to device."""))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        # rf.valid_bcloc = ["Off", "On"]
        rf.has_bank = False
        rf.has_cross = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.has_ctone = True
        rf.can_odd_split = True
        rf.valid_name_length = 8
        rf.valid_characters = self._valid_chars
        rf.valid_skips = []
        # rf.valid_ptid = ["Off", "BOT", "EOT", "BOTH"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
                                "Tone->Tone",
                                "DTCS->",
                                "->DTCS",
                                "Tone->DTCS",
                                "DTCS->Tone",
                                "->Tone",
                                "DTCS->DTCS"]
        rf.valid_power_levels = TX_POWER
        rf.valid_duplexes = ["", "-", "+", "split", "Off"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tuning_steps = STEPS
        # rf.valid_dtcs_codes = UV5R_DTCS

        normal_bands = [self._vhf_range, self._uhf_range]
        rax_bands = [self._vhf_range, self._220_range]

        if self._mmap is None:
            rf.valid_bands = [normal_bands[0], rax_bands[1], normal_bands[1]]
        # elif not self._is_orig() and self._my_upper_band() == vhf_220_radio:
        #     rf.valid_bands = rax_bands
        else:
            rf.valid_bands = normal_bands
        rf.memory_bounds = (1, 199)
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False
        if len(filedata) in [0x1808, 0x1948, 0x1950]:
            match_size = True
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
        
        
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        _msg_duplex2 = 'Memory location only supports "(None)" or "off"'
        _msg_duplex3 = 'Memory location only supports "(None)", "+" or "off"'

        if self._gmrs:
            if mem.number < 1 or mem.number > 30:
                if float(mem.freq) / 1000000 in GMRS_FREQS1:
                    if mem.duplex not in ['', 'off']:
                        # warn user wrong Duplex
                        msgs.append(chirp_common.ValidationError(_msg_duplex2))

                if float(mem.freq) / 1000000 in GMRS_FREQS2:
                    if mem.duplex not in ['', 'off']:
                        # warn user wrong Duplex
                        msgs.append(chirp_common.ValidationError(_msg_duplex2))

                if float(mem.freq) / 1000000 in GMRS_FREQS3:
                    if mem.duplex not in ['', '+', 'off']:
                        # warn user wrong Duplex
                        msgs.append(chirp_common.ValidationError(_msg_duplex3))

        return msgs
    
    # def mode_block(self):
    #     if MODE_RADIO == 'P31185': #ham
    #         return 1
    #     else:
    #         return 

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()
        # HAM OR GMRS
        print(MODE_RADIO)
        if MODE_RADIO == 'P31185': #ham
            self._memobj.settings.ham = 1
            self._memobj.settings.gmrs = 0
        else:
            msg = ("Please check your walkie-talkie mode, the current mode is not Ham mode.")
            raise InvalidValueError(msg)

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    # 编码处理
    def _decode_tone(self, val):
        #模拟哑音
        if int(str(val[:2]), 16) <= 37 and val!='0000':
            return 'Tone', int(str(val)) / 10.0, None
        elif val[:1] == '8':
            # dec2bin = bin(int(str(val[1:]), 16))[2:]
            dec2oct = int(str(val[1:]))
            return 'DTCS', dec2oct, 'N'
        elif val[:1] == 'C':
            # dec2bin = bin(int(str(val[1:])))[2:]
            dec2oct = int(str(val[1:]))
            return 'DTCS', dec2oct, 'R'
        else:
            return '', None, None

    # 解码处理
    def _encode_tone(self, memval, mode, value, pol):
        if mode == '':
            memval.set_value([255, 255])
        elif mode == 'Tone':
            #memval.set_value(int(value * 10))
            val = int(value * 10)
            # stx = '%02X' % val
            stx_f = str(val)[2:]
            stx_b = str(val)[:2]
            #memval=[int(stx[1:], 16), int(stx[:1], 16)]
            memval.set_value([int(stx_f, 16), int(stx_b, 16)])
        elif mode == 'DTCS':
            # DQT = '2' if pol == 'N' else 'A'
            # # 8进制转2  zfill 9位不够 补0
            # b_8 = '100' + bin(int(str(value), 8))[2:].zfill(9)
            # # 2转16
            # # 获取后面2位
            # a_1 = hex(int(b_8, 2))[2:][1:]
            # # 获取前面2位
            # a_2 = DQT + hex(int(b_8, 2))[2:][:1]
            # stx_f = str(val)[1:]
            # stx_b = str(val)[:1]
            val = str(value)
            if pol == 'R':
                memval.set_value([int(str(val[1:]), 16), int('C' + str(val[0]), 16)])
            elif pol == 'N':
                memval.set_value([int(str(val[1:]), 16), int('8' + str(val[0]), 16)])
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def _get_mem(self, number):
        return self._memobj.memory[number]

    def _get_nam(self, number):
        return self._memobj.names[number]
    
    def _get_fm(self, number):
        return self._memobj.fmmode[number]
    
    def _get_get_scanvfo(self, number):
        return self._memobj.fmvfo[number]
    
    def _get_scan(self, number):
        return self._memobj.scanadd[number]

    def _get_block_data(self, number):
        return self._memobj.blockfirm[number]

    def _get_fmblock_data(self, number):
        return self._memobj.fmblockfirm[number]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)
        
        # _scan_val = self._get_scan(0)
        # print(_scan_val)
        
        # for i in _scan.scan:
        #     LOG.debug(i)
        # print(self._memobj.scanadd.scan)
                
        mem = chirp_common.Memory()
        
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem
            
        # 频率
        mem.freq = int(_mem.rxfreq) * 10

        # 偏移量
        if self._gmrs:
            mem.duplex = ""
            mem.offset = 0
        else:
            if self._is_txinh(_mem):
                mem.duplex = ""
                mem.offset = 0
            elif int(_mem.rxfreq) == int(_mem.txfreq):
                mem.duplex = ""
                mem.offset = 0
            elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
                mem.duplex = "split"
                mem.offset = int(_mem.txfreq) * 10
            else:
                mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
                mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        # 信道名
        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # The UV-5R software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        # dtcs_pol = ["N", "N"]

        # 编解码
        lin = '%02X'  % _mem.txtone[1] + '%02X' % _mem.txtone[0]
        lin2 = '%02X' % _mem.rxtone[1] + '%02X' % _mem.rxtone[0]
        rxtone = self._decode_tone(lin2)
        txtone = self._decode_tone(lin)
        chirp_common.split_tone_decode(mem, txtone, rxtone)
        mem.extra = RadioSettingGroup("Extra", "extra")
       
        try:
            mem.power = TX_POWER[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                      (_mem.lowpower, TX_POWER))
            mem.power = TX_POWER[0]

        mem.mode = _mem.wide and "NFM" or "FM" 

        # 隐藏功能
        
        #1 pttid
        mem.extra = RadioSettingGroup("Extra", "extra")
        
        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_VALUES,
                                                PTTID_VALUES[_mem.pttid]))
        mem.extra.append(rs)

        #2 繁忙锁定
        rs = RadioSetting("bcl", "Busy Lock",
                          RadioSettingValueList(BCLOCK_VALUES,
                                                BCLOCK_VALUES[_mem.bcl]))
        mem.extra.append(rs)

        #3 扫描添加
        scan_val_list = []
        for x in range(25):
            a = self._get_scan(x)
            # print("%i to %i scan values" % (fst, sec))
            for i in range(0, 8):
                scan_val = (a._generators["scan" + str(i + 1)])
                # print(str(scan_val)[3])
                used_scan_val = str(scan_val)[3]
                scan_val_list.append(used_scan_val)

        rs = RadioSetting("scanadd", "Scan Add",
                        RadioSettingValueList(SCAN_VALUES,
                                              SCAN_VALUES[int(scan_val_list[number - 1])]))
        mem.extra.append(rs)
        
        #4 跳频
        rs = RadioSetting("skip", "Frequency Hop",
                        RadioSettingValueList(FREQHOP_VALUES,
                                              FREQHOP_VALUES[_mem.skip]))
        mem.extra.append(rs)

        return mem

    def _set_mem(self, number):
        return self._memobj.memory[number]

    def _set_nam(self, number):
        return self._memobj.names[number]
    
    def _get_scan_list(self, scan_data):
        # scan_val_list 获取全部扫描添加数据1-200位
        scan_val_list = []
        for x in range(25):
            a = self._get_scan(x)
            # print("%i to %i scan values" % (fst, sec))
            for i in range(0, 8):
                scan_val = (a._generators["scan" + str(i + 1)])
                # print(str(scan_val)[3])
                # print(str(scan_val))
                used_scan_val = str(scan_val)[3]
                # print(used_scan_val)
                scan_val_list.append(used_scan_val)
        # print(scan_val_list)
        # used_scan_list 25个结构体 将扫描添加数据拆分为25组 每组8位
        used_scan_list = []
        count_num = 1
        for i in range(0, len(scan_val_list), 8):
            # print ("number " + str(x) + " cols" )
            # print (scan_val_list[i:i + 8])
            used_scan_list.append(scan_val_list[i:i + 8])
            count_num += 1
        # 判断是否为可以整除的标准数
        # 定位到所修改的的信道中的扫描添加是那一组 修改
        if scan_data % 8 != 0:
            x_list = scan_data / 8 
            y_list = scan_data % 8
            # end_scan_data = used_scan_list[x_list][y_list]
        else:
            x_list = (scan_data / 8) - 1 
            y_list = scan_data
            # end_scan_data = used_scan_list[x_list][y_list]
        
        return([x_list, y_list])    
        
    def get_block_xy(self, number):
        if number % 8 != 0:
            x_list = number / 8 
            y_list = number % 8
            # end_scan_data = used_scan_list[x_list][y_list]
        else:
            x_list = (number / 8) - 1 
            y_list = number
        
        return([x_list, y_list])  
    

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        _nam = self._get_nam(mem.number)
        
        
        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        was_empty = False
        # same method as used in get_memory to find
        # out whether a raw memory is empty
        if _mem.get_raw()[0] == "\xff":
            was_empty = True
            LOG.debug("UV5R: this mem was empty")
        else:
            # memorize old extra-values before erasing the whole memory
            # used to solve issue 4121
            LOG.debug("mem was not empty, memorize extra-settings")
            prev_bcl = _mem.bcl.get_value()
            # prev_scode = _mem.scode.get_value()
            prev_pttid = _mem.pttid.get_value()

        _mem.set_raw("\x00" * 16)
        
        
        if self._ham and MODE_RADIO == "P31185":
            if mem.number >= 189 and mem.number <= 199:
                ham_freqs = int(HAM_FREQS[mem.number - 189] * 1000000) 
                mem.freq = ham_freqs
                mem.duplex = "" 
                mem.power = TX_POWER[1]
                # mem.freqhop = "Off"
                # mem.name = HAM_NAME[mem.number - 189]
                mem.tmode = ""
                # msg = ("The frequency in channels 189-199 cannot be modified in Ham mode")
                # raise msg
            elif (mem.number >= 1 and mem.number <= 188) and ((mem.freq >= 144000000 and mem.freq <= 148000000) or (mem.freq >= 420000000 and mem.freq <= 450000000)):
                _mem.rxfreq = mem.freq / 10
            else:
                _mem.offset = 0
                msg = ("The frequency in channels 1-188 must be between 144.00000-148.00000 or 420.00000-450.00000")
                raise InvalidValueError(msg)   

        if self._gmrs and MODE_RADIO == "P31184":
            if (mem.number >= 189 and mem.number <= 199):
                ham_freqs = int(HAM_FREQS[mem.number - 189] * 1000000) 
                mem.freq = ham_freqs
                _mem.rxfreq = mem.freq / 10
                mem.power = TX_POWER[1]
            elif (mem.number >=1 and mem.number <= 30):
                if mem.number >= 8 and mem.number <= 14:
                    gmrs_freqs = int(GMRS_FREQS_B[mem.number - 1] * 1000000) 
                    mem.freq = gmrs_freqs
                    _mem.rxfreq = mem.freq / 10
                    mem.power = TX_POWER[0]
                    mem.mode = "NFM"
                    mem.duplex = ""
                else:
                    gmrs_freqs = int(GMRS_FREQS_B[mem.number - 1] * 1000000) 
                    mem.freq = gmrs_freqs
                    _mem.rxfreq = mem.freq / 10
                
            elif float("%i.%06i" % (mem.freq / 1000000, mem.freq % 1000000)) in GMRS_FREQ_A:
                _mem.rxfreq = mem.freq / 10
                _mem.offset = 2
                mem.offset  = 5
                _mem.txfreq = (mem.freq + 5000000) / 10
                
            elif (mem.number >= 55 and mem.number <= 188) and ((mem.freq >= 136000000 and mem.freq <= 174000000) or (mem.freq >= 400000000 and mem.freq <= 520000000)):
                _mem.rxfreq = mem.freq / 10
                
            else:
                _mem.offset = 0
                msg = ("The frequency in channels 31-55 must be between 462.55000-462.72500 in 0.025 increments.")
                raise InvalidValueError(msg)
                
        else:
            _mem.rxfreq = mem.freq / 10


        if int(self._get_mem(mem.number).rxfreq != 166666665):
            block_xy = self.get_block_xy(mem.number)
            _blockfirm = self._get_block_data(block_xy[0])
            if block_xy[1] == 1:
                _blockfirm.block1 = 1
            elif block_xy[1] == 2:
                _blockfirm.block2 = 1
            elif block_xy[1] == 3:
                _blockfirm.block3 = 1
            elif block_xy[1] == 4:
                _blockfirm.block4 = 1
            elif block_xy[1] == 5:
                _blockfirm.block5 = 1
            elif block_xy[1] == 6:
                _blockfirm.block6 = 1
            elif block_xy[1] == 7:
                _blockfirm.block7 = 1
            elif block_xy[1] == 8:
                _blockfirm.block8 = 1 
        else:
            block_xy = self.get_block_xy(mem.number)
            _blockfirm = self._get_block_data(block_xy[0])
            if block_xy[1] == 1:
                _blockfirm.block1 = 0
            elif block_xy[1] == 2:
                _blockfirm.block2 = 0
            elif block_xy[1] == 3:
                _blockfirm.block3 = 0
            elif block_xy[1] == 4:
                _blockfirm.block4 = 0
            elif block_xy[1] == 5:
                _blockfirm.block5 = 0
            elif block_xy[1] == 6:
                _blockfirm.block6 = 0
            elif block_xy[1] == 7:
                _blockfirm.block7 = 0
            elif block_xy[1] == 8:
                _blockfirm.block8 = 0
            
        if self._gmrs:
            pass
        else:
            if mem.duplex == "off" or mem.duplex == '':
                for i in range(0, 4):
                    _mem.txfreq[i].set_raw("\xFF")
            elif mem.duplex == "split":
                _mem.txfreq = mem.offset / 10
            elif mem.duplex == "+":
                _mem.txfreq = (mem.freq + mem.offset) / 10
            elif mem.duplex == "-":
                _mem.txfreq = (mem.freq - mem.offset) / 10
            elif self._gmrs:
                pass
            elif self._ham:
                pass
            else:
                _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)
        
        
        # _mem.scan = mem.skip != "S"
        # _mem.wide = mem.mode == "FM"
        if mem.mode == "FM":
            _mem.wide = 0
        else:
            _mem.wide = 1
            
        if str(mem.power) == "Low":
            _mem.lowpower = 0
        elif str(mem.power) == "Mid":
            _mem.lowpower = 1
        elif str(mem.power) == "High":
            _mem.lowpower = 10
        else:
            _mem.lowpower = 0
        
        if not was_empty:
            # restoring old extra-settings (issue 4121
            _mem.bcl.set_value(prev_bcl)
            # _mem.scode.set_value(prev_scode)
            _mem.pttid.set_value(prev_pttid)

        for setting in mem.extra:
            if setting.get_name() == 'scanadd':
                
                index_scanadd =  [i for i in SCAN_VALUES]
                # scanadd_data 所修改的值
                scanadd_data = index_scanadd.index(str(setting.value))
                scanlist = self._get_scan_list(mem.number)
                _scan = self._get_scan(scanlist[0])
                
                if scanlist[1] == 1:
                    _scan.scan1 = scanadd_data
                elif scanlist[1] == 2:
                    _scan.scan2 = scanadd_data
                elif scanlist[1] == 3:
                    _scan.scan3 = scanadd_data
                elif scanlist[1] == 4:
                    _scan.scan4 = scanadd_data
                elif scanlist[1] == 5:
                    _scan.scan5 = scanadd_data
                elif scanlist[1] == 6:
                    _scan.scan6 = scanadd_data
                elif scanlist[1] == 7:
                    _scan.scan7 = scanadd_data
                elif scanlist[1] == 8:
                    _scan.scan8 = scanadd_data    
            else:
                if MODE_RADIO == "P31185" and mem.number >= 189 and mem.number <= 199:
                    if setting.get_name() == 'pttid':
                        setting.value = 'Off'
                        setattr(_mem, setting.get_name(), setting.value)
                    elif setting.get_name() == 'bcl':
                        setting.value = 'Off'
                        setattr(_mem, setting.get_name(), setting.value)
                    elif setting.get_name() == 'skip':
                        setting.value = 'Off'
                        setattr(_mem, setting.get_name(), setting.value)
                else:
                    setattr(_mem, setting.get_name(), setting.value)
        
    def _my_upper_band(self):
        band_tag = _upper_band_from_image(self)
        return band_tag

    def _get_settings(self):       
        _settings = self._memobj.settings
        _press = self._memobj.press
        _aoffset = self._memobj.aoffset
        _boffset = self._memobj.boffset
        _vfoa = self._memobj.vfoa       
        _vfob = self._memobj.vfob
        _gcode = self._memobj.groupcode
   
        basic = RadioSettingGroup("basic", "Basic Settings")
        abblock = RadioSettingGroup("abblock", "A/B Channel")
        fmmode = RadioSettingGroup("fmmode", "FM")
        dtmf = RadioSettingGroup("dtmf", "DTMF")

        # group = RadioSettings(fmmode, dtmf)
        group = RadioSettings(basic, abblock, fmmode, dtmf)
        
        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueList(SQUELCH,
                                                SQUELCH[_settings.squelch]))
        basic.append(rs)
        
        rs = RadioSetting("ligcon", "Light Control",
                          RadioSettingValueList(LIGHT_LIST,
                                                LIGHT_LIST[_settings.ligcon]))
        basic.append(rs)
        
        rs = RadioSetting("voiceprompt", "Voice Prompt",
                          RadioSettingValueList(VOICE_PRMPT_LIST,
                                                VOICE_PRMPT_LIST[_settings.voiceprompt]))
        basic.append(rs)
        
        rs = RadioSetting("keyautolock", "Auto Lock",
                          RadioSettingValueList(AUTOLOCK_LIST,
                                                AUTOLOCK_LIST[_settings.keyautolock]))
        basic.append(rs)
        
        # 发射限时缺失
        # rs = RadioSetting("timeout", "Time out(sec)",
        #                   RadioSettingValueList(TIME_OUT_LIST,
        #                                         TIME_OUT_LIST[1]))
        # basic.append(rs)
        
        rs = RadioSetting("mdfa", "MDF-A",
                          RadioSettingValueList(MDFA_LIST,
                                                MDFA_LIST[_settings.mdfa]))
        basic.append(rs)
        
        rs = RadioSetting("mdfb", "MDF-B",
                          RadioSettingValueList(MDFB_LIST,
                                                MDFB_LIST[_settings.mdfb]))
        basic.append(rs)
        
        rs = RadioSetting("sync", "SYNC",
                          RadioSettingValueList(SYNC_LIST,
                                                SYNC_LIST[_settings.sync]))
        basic.append(rs)
        
        if _settings.lang == 1:
            langs = 0
        else:
            langs = 1
        rs = RadioSetting("lang", "Language",
                          RadioSettingValueList(LANG_LIST,
                                                LANG_LIST[langs]))
        basic.append(rs)
        
        rs = RadioSetting("save", "Battery Save",
                          RadioSettingValueList(BTV_SAVER_LIST,
                                                BTV_SAVER_LIST[_settings.save]))
        basic.append(rs)
        
        rs = RadioSetting("dbrx", "Double Rx",
                          RadioSettingValueList(DBRX_LIST,
                                                DBRX_LIST[_settings.dbrx]))
        basic.append(rs)
        
        rs = RadioSetting("astep", "A Step",
                          RadioSettingValueList(ASTEP_LIST,
                                                ASTEP_LIST[_settings.astep]))
        basic.append(rs)
        
        rs = RadioSetting("bstep", "B Step",
                          RadioSettingValueList(BSTEP_LIST,
                                                BSTEP_LIST[_settings.bstep]))
        basic.append(rs)
        
        rs = RadioSetting("scanmode", "Scan Mode",
                          RadioSettingValueList(SCAN_MODE_LIST,
                                                SCAN_MODE_LIST[_settings.scanmode]))
        basic.append(rs)
        
        rs = RadioSetting("pritx", "Priority TX",
                          RadioSettingValueList(PRIO_LIST,
                                                PRIO_LIST[_settings.pritx]))
        basic.append(rs)
        
        rs = RadioSetting("btnvoice", "Beep",
                            RadioSettingValueBoolean(_settings.btnvoice))
        basic.append(rs)
        
        rs = RadioSetting("rogerprompt", "Roger",
                            RadioSettingValueBoolean(_settings.rogerprompt))
        basic.append(rs)
        
        rs = RadioSetting("txled", "Disp Lcd(TX)",
                          
                            RadioSettingValueBoolean(_settings.txled))
        basic.append(rs)
        
        rs = RadioSetting("rxled", "Disp Lcd(RX)",
                            RadioSettingValueBoolean(_settings.rxled))
        basic.append(rs)
        
        # # 仅频道模式存疑
        # rs = RadioSetting("chmode", "Only CH Mode",
        #                     RadioSettingValueBoolean(0))
        # basic.append(rs)
        
        # print(_press.stopkey1)
        rs = RadioSetting("stopkey1", "SHORT_KEY_TOP",
                          RadioSettingValueList(SHORT_KEY_LIST,
                                                SHORT_KEY_LIST[0]))
        basic.append(rs)
        
        rs = RadioSetting("ssidekey1", "SHORT_KEY_PF1",
                          RadioSettingValueList(SHORT_KEY_LIST,
                                                SHORT_KEY_LIST[_press.ssidekey1]))
        basic.append(rs)
        
        rs = RadioSetting("ssidekey2", "SHORT_KEY_PF2",
                          RadioSettingValueList(SHORT_KEY_LIST,
                                                SHORT_KEY_LIST[_press.ssidekey2]))
        basic.append(rs)
        
        rs = RadioSetting("ltopkey2", "LONG_KEY_TOP",
                          RadioSettingValueList(LONG_KEY_LIST,
                                                LONG_KEY_LIST[_press.ltopkey2]))
        basic.append(rs)
        
        rs = RadioSetting("lsidekey3", "LONG_KEY_PF1",
                          RadioSettingValueList(LONG_KEY_LIST,
                                                LONG_KEY_LIST[_press.lsidekey3]))
        basic.append(rs)
        
        rs = RadioSetting("lsidekey4", "LONG_KEY_PF2",
                          RadioSettingValueList(LONG_KEY_LIST,
                                                LONG_KEY_LIST[_press.lsidekey4]))
        basic.append(rs)
        
        rs = RadioSetting("voxgain", "VOX Gain",
                          RadioSettingValueList(VOX_GAIN,
                                                VOX_GAIN[_settings.voxgain]))
        basic.append(rs)
        
        rs = RadioSetting("voxdelay", "VOX Delay",
                          RadioSettingValueList(VOX_DELAY,
                                                VOX_DELAY[_settings.voxdelay]))
        basic.append(rs)
        
        # def fm_validate(value):
        #         value = chirp_common.parse_freq(value)
        #         if 17400000 <= value and value < 40000000:
        #             msg = ("Can't be between 174.00000-400.00000")
        #             raise InvalidValueError(msg)
        #         return chirp_common.format_freq(value)
        
        # def freq_validate(value):
        #         value = chirp_common.parse_freq(value)
        #         if 13600000 <= value and value < 17300000 and value >= 40000000 and value <= 52000000:
        #             msg = ("Can't be between 136.00000-174.00000 and 400.00000 - 520.00000")
        #             raise InvalidValueError(msg)
        #         return chirp_common.format_freq(value)
        
        # def apply_freq(setting, obj):
        #         value = chirp_common.parse_freq(str(setting.value)) / 10
        #         obj.band = value >= 40000000
        #         for i in range(7, -1, -1):
        #             obj.freq[i] = value % 10
        #             value /= 10
                    
        # val1a = RadioSettingValueString(0, 10, freqa)
        # val1a.set_validate_callback(freq_validate)
        # rs = RadioSetting("rxfreq", "A Channel - Frequency", val1a)
        # # rs.set_apply_callback(apply_freq, _vfoa)
        # abblock.append(rs)
        
        
        # A信道
        a_freq = int(_vfoa.rxfreqa)
        freqa = "%i.%05i" % (a_freq / 100000, a_freq % 100000)     
        if freqa == "0.00000":
            val1a = RadioSettingValueString(0, 7, '0.00000')
        else:
            val1a = RadioSettingValueFloat(136, 520, float(freqa), 0.00001, 5)
        # val1a.set_validate_callback(freq_validate)
        rs = RadioSetting("rxfreqa", "A Channel - Frequency", val1a)
        # rs.set_apply_callback(apply_freq, _vfob)
        abblock.append(rs)
        
        
        # 偏移量
        # 假如偏移量为12.345
        # 则拿到的数据为[0x45, 0x23, 0x01, 0x00]
        a_set_val = _aoffset.ofseta
        a_set_list = len(_aoffset.ofseta) - 1
        real_val = ''
        for i in range(a_set_list, -1, -1):
            real_val += str(a_set_val[i])[2:]
        if real_val == "FFFFFFFF":
            rs = RadioSetting("ofseta", "Offset Frequency",
                          RadioSettingValueString(0, 7, ""))
        else:
            real_val = int(real_val)
            real_val = "%i.%05i" % (real_val / 100000, real_val % 100000)
            rs = RadioSetting("ofseta", "Offset Frequency",
                          RadioSettingValueFloat(0.00000, 59.99750, real_val, 0.00001, 5))
        abblock.append(rs)

        rs = RadioSetting("offset", "Offset",
                          RadioSettingValueList(
                              A_OFFSET, A_OFFSET[_vfoa.offset]))
        abblock.append(rs)
        
        # 对亚音频数据处理
        # 接收到的亚音频数据，例如74.4则得到的是一对象[0x44, 0x07]
        # 按照下面的逻辑进行处理对象得到74.4
        if str(_vfoa.rxtone[1])[2] == 'C':
            # list_aqtdqt = map(str, A_QTDQT_DTCS)
            # I_tone_list = map(lambda x: "D" + str.zfill(list_aqtdqt[x], 3) + "I", range(len(list_aqtdqt)))
            a_tone = "D" + str(_vfoa.rxtone[1])[3:] + str(_vfoa.rxtone[0])[2:] + "I"
            
        elif str(_vfoa.rxtone[1])[2] == '8':
            # list_aqtdqt = map(str, A_QTDQT_DTCS)
            # N_tone_list = map(lambda x: "D" + str.zfill(list_aqtdqt[x], 3) + "N", range(len(list_aqtdqt)))
            a_tone = "D" + str(_vfoa.rxtone[1])[3:] + str(_vfoa.rxtone[0])[2:] + "N"

        elif str(_vfob.rxtoneb[1])[2] == 'F':
            a_tone = 'Off'
        
        else:
            a_tone = int(str(_vfoa.rxtone[1])[2:])* 10 + int(str(_vfoa.rxtone[0])[2]) + int((str(_vfoa.rxtone[0])[2:])[1:]) * 0.1
            a_tone= str(a_tone)
            
        rs = RadioSetting("rxtone", "QT/DQT",
                        RadioSettingValueList(
                            A_QTDQT_DTCS, a_tone))
        abblock.append(rs)
        
        rs = RadioSetting("lowpower", "TX Power",
                          RadioSettingValueList(
                              A_TX_POWER, A_TX_POWER[_vfoa.lowpower]))
        abblock.append(rs)
        
        rs = RadioSetting("wide", "Band",
                          RadioSettingValueList(
                              A_BAND, A_BAND[_vfoa.wide]))
        abblock.append(rs)
        
        rs = RadioSetting("bcl", "Busy Lock",
                          RadioSettingValueList(
                              A_BUSYLOCK, A_BUSYLOCK[_vfoa.bcl]))
        abblock.append(rs)
        
        rs = RadioSetting("skip", "Special QT/DQT",
                          RadioSettingValueList(
                              A_SPEC_QTDQT, A_SPEC_QTDQT[_vfoa.skip]))
        abblock.append(rs)
        
        rs = RadioSetting("aworkmode", "Work Mode",
                          RadioSettingValueList(
                              A_WORKMODE, A_WORKMODE[_settings.aworkmode]))
        abblock.append(rs)
        
        # B信道
        b_freq = int(str(int(_vfob.rxfreqb)).ljust(8, '0'))
        freqb = "%i.%05i" % (b_freq / 100000, b_freq % 100000)
        if freqb == "0.00000":
            val1a = RadioSettingValueString(0, 7, '0.00000')
        else:
            val1a = RadioSettingValueFloat(136, 520, float(freqb), 0.00001, 5)
        # val1a.set_validate_callback(freq_validate)
        rs = RadioSetting("rxfreqb", "B Channel - Frequency", val1a)
        # rs.set_apply_callback(apply_freq, _vfob)
        abblock.append(rs)

        # 偏移量offset frequency
        # 假如偏移量为12.345
        # 则拿到的数据为[0x45, 0x23, 0x01, 0x00]
        # 需要使用下面的匿名函数进行处理数据 
        b_set_val = _boffset.ofsetb
        b_set_list = len(_boffset.ofsetb) - 1
        real_val = ''
        for i in range(b_set_list, -1, -1):
            real_val += str(b_set_val[i])[2:]
        if real_val == "FFFFFFFF":
            rs = RadioSetting("ofsetb", "Offset Frequency",
                          RadioSettingValueString(0, 7, " "))
        else:
            real_val = int(real_val)
            real_val = "%i.%05i" % (real_val / 100000, real_val % 100000)
        # b_temp += str(i)[2:]
        # print(b_temp)
        # result = map(lambda x: int(str(_b_fset.ofsetb[x])[2:]), [0, 1, 2])
        # result = result[2] * 10 + result[1] * 0.1 + result[0] * 0.001
            rs = RadioSetting("ofsetb", "Offset Frequency",
                          RadioSettingValueFloat(0.00000, 59.99750, real_val, 0.00001, 5))
        abblock.append(rs)

        rs = RadioSetting("offsetb", "Offset",
                          RadioSettingValueList(
                              B_OFFSET, B_OFFSET[_vfob.offsetb]))
        abblock.append(rs)
        
        # 对亚音频数据处理
        # 接收到的亚音频数据，例如74.4则得到的是一对象[0x44, 0x07]
        # 按照下面的逻辑进行处理对象得到74.4
        if str(_vfob.rxtoneb[1])[2] == 'C':
            # list_aqtdqt = map(str, A_QTDQT_DTCS)
            # I_tone_list = map(lambda x: "D" + str.zfill(list_aqtdqt[x], 3) + "I", range(len(list_aqtdqt)))
            b_tone = "D" + str(_vfob.rxtoneb[1])[3:] + str(_vfob.rxtoneb[0])[2:] + "I"
            
        elif str(_vfob.rxtoneb[1])[2] == '8':
            # list_aqtdqt = map(str, A_QTDQT_DTCS)
            # N_tone_list = map(lambda x: "D" + str.zfill(list_aqtdqt[x], 3) + "N", range(len(list_aqtdqt)))
            b_tone = "D" + str(_vfob.rxtoneb[1])[3:] + str(_vfob.rxtoneb[0])[2:] + "N"

        elif str(_vfob.rxtoneb[1])[2] == 'F':
            b_tone = 'Off'
        
        else:
            b_tone = int(str(_vfob.rxtoneb[1])[2:])* 10 + int(str(_vfob.rxtoneb[0])[2]) + int((str(_vfob.rxtoneb[0])[2:])[1:]) * 0.1
            b_tone= str(b_tone)
            
        rs = RadioSetting("rxtoneb", "QT/DQT",
                        RadioSettingValueList(
                            B_QTDQT_DTCS, b_tone))
        abblock.append(rs)
        
        rs = RadioSetting("lowpowerb", "TX Power",
                          RadioSettingValueList(
                              B_TX_POWER, B_TX_POWER[_vfob.lowpowerb]))
        abblock.append(rs)
        
        rs = RadioSetting("wideb", "Band",
                          RadioSettingValueList(
                              B_BAND, B_BAND[_vfob.wideb]))
        abblock.append(rs)
        
        rs = RadioSetting("bclb", "Busy Lock",
                          RadioSettingValueList(
                              B_BUSYLOCK, B_BUSYLOCK[_vfob.bclb]))
        abblock.append(rs)
        
        rs = RadioSetting("skipb", "Special QT/DQT",
                          RadioSettingValueList(
                              B_SPEC_QTDQT, B_SPEC_QTDQT[_vfob.skipb]))
        abblock.append(rs)
        
        rs = RadioSetting("bworkmode", "Work Mode",
                          RadioSettingValueList(
                              B_WORKMODE, B_WORKMODE[_settings.bworkmode]))
        abblock.append(rs)
        
        rs = RadioSetting("fmworkmode", "Work Mode",
                          RadioSettingValueList(
                              FM_WORKMODE, FM_WORKMODE[_settings.fmworkmode]))
        fmmode.append(rs)
        
        rs = RadioSetting("fmroad", "Channel",
                          RadioSettingValueList(
                              FM_CHANNEL, FM_CHANNEL[_settings.fmroad]))
        fmmode.append(rs)
        
        rs = RadioSetting("fmrec", "Forbid Receive",
                          RadioSettingValueBoolean(_settings.fmrec))
        fmmode.append(rs)
        
        
        # FM
        for i in range(25):
            _fm = self._get_fm(i).fmblock
            _fm_len = len(_fm) - 1
            _fm_temp = ''
            for x in range(_fm_len, -1, -1):
                _fm_temp += str(_fm[x])[2:]
            if _fm_temp == "00000000" or _fm_temp == 'FFFFFFFF':
                rs = RadioSetting('block'+ str(i), "Channel" + " " + str(i+1),
                            RadioSettingValueString(0, 5, ""))
            else:
                # if int(_fm_temp) >= 760 or int(_fm_temp) <= 1080:
                _fm_block = int(_fm_temp)
                _fm_block = '%i.%i' % (_fm_block / 10 , _fm_block % 10)
                # else:
                #     _fm_block = 76.0
                rs = RadioSetting('block'+ str(i), "Channel" + " " + str(i+1),
                            RadioSettingValueString(0, 5, _fm_block))
            fmmode.append(rs)
        
        _fmv = self._memobj.fmvfo.vfo
        _fmv_len = len(_fmv) - 1
        _fmv_temp = ''
        for x in range(_fmv_len, -1, -1):
            _fmv_temp += str(_fmv[x])[2:]
        _fmv_block = int(_fmv_temp)
        _fmv_block = '%i.%i' % (_fmv_block / 10 , _fmv_block % 10)
        rs = RadioSetting("fmvfo", "VFO",
                        RadioSettingValueFloat(76.0, 108.0, _fmv_block, 0.1, 1))
        fmmode.append(rs)
        
        # DTMF
        gcode_val = str(_gcode.gcode)[2:]
        if gcode_val == "FF":
            gcode_val = "Off"
        elif gcode_val == "0F":
            gcode_val = "#"
        elif gcode_val == "0E":
            gcode_val = "*"
        elif gcode_val =='00':
            gcode_val = ""
        else:
            gcode_val = gcode_val[1]
        rs = RadioSetting("gcode", "Group Code",
                          RadioSettingValueList(GROUPCODE,
                                                gcode_val))
        dtmf.append(rs)
    
        icode_list = self._memobj.icode.idcode
        used_icode = ''
        for i in icode_list:
            if i == 0xFF:
                continue
            used_icode += str(i)[3]
        dtmfcharsani = "0123456789ABCD "
        i_val = RadioSettingValueString(0, 3, used_icode)
        rs = RadioSetting("icode", "ID Code", i_val)
        i_val.set_charset(dtmfcharsani)
        dtmf.append(rs) 
        
        gcode_list_1 = self._memobj.group1.group1
        used_group1 = ''
        for i in gcode_list_1:
            if i == 0xFF:
                continue
            used_group1 += str(i)[3]
        group1_val = RadioSettingValueString(0, 7, used_group1)
        rs = RadioSetting("group1", "1", group1_val)
        group1_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_2 = self._memobj.group2.group2
        used_group2 = ''
        for i in gcode_list_2:
            if i == 0xFF:
                continue
            used_group2 += str(i)[3]
        group2_val = RadioSettingValueString(0, 7, used_group2)
        rs = RadioSetting("group2", "2", group2_val)
        group2_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_3 = self._memobj.group3.group3
        used_group3 = ''
        for i in gcode_list_3:
            if i == 0xFF:
                continue
            used_group3 += str(i)[3]
        group3_val = RadioSettingValueString(0, 7, used_group3)
        rs = RadioSetting("group3", "3", group3_val)
        group3_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_4 = self._memobj.group4.group4
        used_group4 = ''
        for i in gcode_list_4:
            if i == 0xFF:
                continue
            used_group4 += str(i)[3]
        group4_val = RadioSettingValueString(0, 7, used_group4)
        rs = RadioSetting("group4", "4", group4_val)
        group4_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_5 = self._memobj.group5.group5
        used_group5 = ''
        for i in gcode_list_5:
            if i == 0xFF:
                continue
            used_group5 += str(i)[3]
        group5_val = RadioSettingValueString(0, 7, used_group5)
        rs = RadioSetting("group5", "5", group5_val)
        group5_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_6 = self._memobj.group6.group6
        used_group6 = ''
        for i in gcode_list_6:
            if i == 0xFF:
                continue
            used_group6 += str(i)[3]
        group6_val = RadioSettingValueString(0, 7, used_group6)
        rs = RadioSetting("group6", "6", group6_val)
        group6_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_7 = self._memobj.group7.group7
        used_group7 = ''
        for i in gcode_list_7:
            if i == 0xFF:
                continue
            used_group7 += str(i)[3]
        group7_val = RadioSettingValueString(0, 7, used_group7)
        rs = RadioSetting("group7", "7", group7_val)
        group7_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        gcode_list_8 = self._memobj.group8.group8
        used_group8 = ''
        for i in gcode_list_8:
            if i == 0xFF:
                continue
            used_group8 += str(i)[3]
        group8_val = RadioSettingValueString(0, 7, used_group8)
        rs = RadioSetting("group8", "8", group7_val)
        group8_val.set_charset(dtmfcharsani)
        dtmf.append(rs)
        
        scode_list = self._memobj.startcode.scode
        used_scode = ''
        for i in scode_list:
            if i == 0xFF:
                continue
            used_scode += str(i)[3]
        scode_val = RadioSettingValueString(0, 7, used_scode)
        rs = RadioSetting("scode", "PTT ID Starting(BOT)", scode_val)
        scode_val.set_charset(dtmfcharsani)
        dtmf.append(rs) 
        
        ecode_list = self._memobj.endcode.ecode
        used_ecode = ''
        for i in ecode_list:
            if i == 0xFF:
                continue
            used_ecode += str(i)[3]
        ecode_val = RadioSettingValueString(0, 7, used_ecode)
        rs = RadioSetting("ecode", "PTT ID Ending(BOT)", ecode_val)
        # ecode_val.set_charset(dtmfcharsani)
        dtmf.append(rs) 

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    def set_settings(self, settings):
        
        def fm_validate(value):
            if 760 > value or value > 1080:
                msg = ("FM Channel muse be between 76.0-108.0")
                raise InvalidValueError(msg)
            
                    
        _settings = self._memobj.settings
        _press = self._memobj.press
        _aoffset = self._memobj.aoffset
        _boffset = self._memobj.boffset
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _fmmode = self._memobj.fmmode
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
                    self.set_settings(element)
                    continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    elif name in PRESS_NAME:
                        obj = _press
                        setting = element.get_name()
                        
                    elif name in VFOA_NAME:
                        obj = _vfoa
                        setting = element.get_name()
                    elif name == "ofseta":
                        obj = _aoffset
                        setting = element.get_name()
                    elif name in VFOB_NAME:
                        obj = _vfob
                        setting = element.get_name()
                    elif name == "ofsetb":
                        obj = _boffset
                        setting = element.get_name()
                    elif "block" in name:
                        obj = _fmmode
                        setting = element.get_name()
                    elif "fmvfo" in name:
                        obj = self._memobj.fmvfo.vfo
                        setting = element.get_name()
                    elif "gcode" in name:
                        obj = self._memobj.groupcode.gcode
                        setting = element.get_name()
                    elif "idcode" in name:
                        obj = self._memobj.icode.idcode
                        setting = element.get_name()
                    elif "scode" in name:
                        obj = self._memobj.startcode.scode
                        setting = element.get_name()
                    elif "ecode" in name:
                        obj = self._memobj.endcode.ecode
                        setting = element.get_name() 
                    elif "group1" in name:
                        obj = self._memobj.group1.group1
                        setting = element.get_name() 
                    elif "group2" in name:
                        obj = self._memobj.group2.group2
                        setting = element.get_name() 
                    elif "group3" in name:
                        obj = self._memobj.group3.group3
                        setting = element.get_name() 
                    elif "group4" in name:
                        obj = self._memobj.group4.group4
                        setting = element.get_name()
                    elif "group5" in name:
                        obj = self._memobj.group5.group5
                        setting = element.get_name()
                    elif "group6" in name:
                        obj = self._memobj.group6.group6
                        setting = element.get_name()
                    elif "group7" in name:
                        obj = self._memobj.group7.group7
                        setting = element.get_name()
                    elif "group8" in name:
                        obj = self._memobj.group8.group8
                        setting = element.get_name() 
                    
                    else:
                        obj = _settings
                        setting = element.get_name()
                        
                        
                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    
                    # 信道A
                    elif setting == "rxfreqa" and element.value.get_mutable():
                        val = int(str(element.value).replace('.', '').ljust(8, '0'))
                        if (val >= 13600000 and val <= 17400000) or (val >= 40000000 and val <= 52000000):
                            LOG.debug("Setting %s = %s" % (setting, element.value))
                            setattr(obj, setting, val)
                        else:
                            msg = ("Frequency must be between 136.00000-174.00000 or 400.00000-520.00000")
                            raise InvalidValueError(msg)

                    elif setting == "ofseta" and element.value.get_mutable():
                        if '.' in str(element.value):
                            val = str(element.value).replace(' ', '')
                            if len(val[val.index(".") + 1:]) >= 1 and int(val[val.index(".") + 1:]) != 0:
                                val = '00' + val.replace('.', '')
                            else:
                                val = '0' + val.replace('.', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        else:
                            val = '0' + str(element.value).replace(' ', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        if (int(val) >= 0 and int(val) <= 5999750):
                            if int(val) == 0:
                                _aoffset.ofseta = [0xFF, 0xFF, 0xFF, 0xFF]
                            else:
                                while lenth_val < (len(val)):
                                    # list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                    list_val.insert(0, val[lenth_val:lenth_val + 2])
                                    lenth_val += 2
                                for i in range(len(list_val)):
                                    list_val[i] = int(list_val[i], 16) 
                                LOG.debug("Setting %s = %s" % (setting, element.value))
                                _aoffset.ofseta = list_val
                        else:
                            msg = ("Offset must be between 0.00000-59.99750")
                            raise InvalidValueError(msg)
                    
                    elif setting == "rxtone" and element.value.get_mutable():
                        val = str(element.value).replace('.', '') #67.0
                        lenth_val = 0
                        list_val = []
                        if str(element.value)[-1] == 'N':
                            val = '8' + val[1:4]
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        elif str(element.value)[-1] == 'I':
                            val = 'C' + val[1:4]
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        else:
                            if val == 'Off':
                                val = "FFFF"
                            else:
                                val = '0' + val
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                            print(list_val)
                        
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, list_val)
                    
                    # B信道
                    elif setting == "rxfreqb" and element.value.get_mutable():
                        val = 0
                        val = int(str(element.value).replace('.', '').ljust(8, '0'))
                        if (val >= 13600000 and val <= 17400000) or (val >= 40000000 and val <= 52000000):
                            LOG.debug("Setting %s = %s" % (setting, element.value))
                            setattr(obj, setting, val)
                        else:
                            msg = ("Frequency must be between 136.00000-174.00000 or 400.00000-520.00000")
                            raise InvalidValueError(msg)
                        # val = int(str(element.value).replace('.', '').ljust(8, '0'))
                        # LOG.debug("Setting %s = %s" % (setting, element.value))
                        # setattr(obj, setting, val)

                    elif setting == "ofsetb" and element.value.get_mutable():
                        if '.' in str(element.value):
                            val = str(element.value).replace(' ', '')
                            if len(val[val.index(".") + 1:]) >= 1 and int(val[val.index(".") + 1:]) != 0:
                                val = '00' + val.replace('.', '')
                            else:
                                val = '0' + val.replace('.', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        else:
                            val = '0' + str(element.value).replace(' ', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        if (int(val) >= 0 and int(val) <= 5999750):
                            if int(val) == 0:
                                _boffset.ofsetb = [0xFF, 0xFF, 0xFF, 0xFF]
                            else:
                                while lenth_val < (len(val)):
                                    list_val.insert(0, val[lenth_val:lenth_val + 2])
                                    lenth_val += 2
                                for i in range(len(list_val)):
                                    list_val[i] = int(list_val[i], 16) 
                                LOG.debug("Setting %s = %s" % (setting, element.value))
                                _boffset.ofsetb = list_val
                        else:
                            msg = ("Offset must be between 0.00000-59.99750")
                            raise InvalidValueError(msg)
                    
                    elif setting == "rxtoneb"  and element.value.get_mutable():
                        val = str(element.value).replace('.', '') #67.0
                        lenth_val = 0
                        list_val = []
                        if str(element.value)[-1] == 'N':
                            val = '8' + val[1:4]
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        elif str(element.value)[-1] == 'I':
                            val = 'C' + val[1:4]
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        elif str(element.value) == 'Off':
                            list_val = [0xFF, 0xFF]
                        else:
                            if val == 'Off':
                                val = "FFFF"
                            else:
                                val = '0' + val
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                            print(list_val)
                        
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, list_val)
                    
                    # FM
                    elif "block" in name:

                        val = str(element.value).replace('.', '').zfill(8)
                        num = int(element.get_name().replace('block', '')) + 1
                        lenth_val = 0
                        list_val = []
                        if str(element.value)[0] == ' ':
                            list_val = [0, 0, 0, 0]
                        else:
                            val = val.replace(' ', '').zfill(8)
                            fm_validate(int(val))
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.fmmode[num - 1].fmblock = list_val
                        
                        
                       
                        # _fm = self._get_fm(i).fmblock
                        # _fm_len = len(_fm) - 1
                        # _fm_temp = ''
                        # for x in range(_fm_len, -1, -1):
                        #     _fm_temp += str(_fm[x])[2:]
                        # '00000   '
                        if val != '00000   ':
                            fmblock_xy = self.get_block_xy(num)
                            _fmblockfirm = self._get_fmblock_data(fmblock_xy[0])
                            if fmblock_xy[1] == 1:
                                _fmblockfirm.block1 = 1
                            elif fmblock_xy[1] == 2:
                                _fmblockfirm.block2 = 1
                            elif fmblock_xy[1] == 3:
                                _fmblockfirm.block3 = 1
                            elif fmblock_xy[1] == 4:
                                _fmblockfirm.block4 = 1
                            elif fmblock_xy[1] == 5:
                                _fmblockfirm.block5 = 1
                            elif fmblock_xy[1] == 6:
                                _fmblockfirm.block6 = 1
                            elif fmblock_xy[1] == 7:
                                _fmblockfirm.block7 = 1
                            elif fmblock_xy[1] == 8:
                                _fmblockfirm.block8 = 1 
                        else:
                            fmblock_xy = self.get_block_xy(num)
                            _fmblockfirm = self._get_fmblock_data(fmblock_xy[0])
                            if fmblock_xy[1] == 1:
                                _fmblockfirm.block1 = 0
                            elif fmblock_xy[1] == 2:
                                _fmblockfirm.block2 = 0
                            elif fmblock_xy[1] == 3:
                                _fmblockfirm.block3 = 0
                            elif fmblock_xy[1] == 4:
                                _fmblockfirm.block4 = 0
                            elif fmblock_xy[1] == 5:
                                _fmblockfirm.block5 = 0
                            elif fmblock_xy[1] == 6:
                                _fmblockfirm.block6 = 0
                            elif fmblock_xy[1] == 7:
                                _fmblockfirm.block7 = 0
                            elif fmblock_xy[1] == 8:
                                _fmblockfirm.block8 = 0
                        # setattr(obj, setting, list_val)
                    
                    elif setting == 'fmvfo' and element.value.get_mutable():
                        val = str(element.value).replace('.', '').zfill(8)
                        # num = int(element.get_name().replace('block', '')) + 1
                        lenth_val = 0
                        list_val = []
                        if " " in val:
                            list_val = [0, 0, 0, 0]
                        else:
                            while lenth_val < (len(val)):
                                list_val.insert(0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.fmvfo.vfo = list_val
                    
                    elif setting == 'gcode' and element.value.get_mutable():
                        val = str(element.value)
                        if val == 'Off':
                            gcode_used = 0xFF
                        elif val == 'A':
                            gcode_used = 0x0A
                        elif val == 'B':
                            gcode_used = 0x0B
                        elif val == 'C':
                          gcode_used = 0x0C
                        elif val == 'D':
                          gcode_used = 0x0D
                        elif val == '#':
                          gcode_used = 0x0F
                        elif val == '*':
                          gcode_used = 0x0E
                        elif val == '':
                            gcode_used = 0x00
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.groupcode.gcode = gcode_used
                        
                    elif setting == 'icode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.icode.idcode = list_val
                    
                    elif setting == 'scode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.startcode.scode = list_val
                    
                    elif setting == 'ecode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.endcode.ecode = list_val
                    
                    elif setting == 'group1' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group1.group1 = list_val
                        
                    elif setting == 'group2' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group2.group2 = list_val
                    
                    elif setting == 'group3' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group3.group3 = list_val
                    
                    elif setting == 'group4' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group4.group4 = list_val
                    
                    elif setting == 'group5' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group5.group5 = list_val
                    
                    elif setting == 'group6' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group6.group6 = list_val
                    
                    elif setting == 'group7' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group7.group7 = list_val
                    
                    elif setting == 'group8' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        self._memobj.group8.group8 = list_val
                    
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                if self._memobj.fm_presets <= 108.0 * 10 - 650:
                    value = int(val.get_value() * 10 - 650)
                else:
                    value = int(val.get_value() * 10)
                LOG.debug("Setting fm_presets = %s" % (value))
                self._memobj.fm_presets = value
            except Exception, e:
                LOG.debug(element.get_name())
                raise


# class UV5XAlias(chirp_common.Alias):
#     VENDOR = "Baofeng"
#     MODEL = "UV-5X"


# class RT5RAlias(chirp_common.Alias):
#     VENDOR = "Retevis"
#     MODEL = "RT5R"


# class RT5RVAlias(chirp_common.Alias):
#     VENDOR = "Retevis"
#     MODEL = "RT5RV"


# class RT5Alias(chirp_common.Alias):
#     VENDOR = "Retevis"
#     MODEL = "RT5"


# class RT5_TPAlias(chirp_common.Alias):
#     VENDOR = "Retevis"
#     MODEL = "RT5(tri-power)"


# class RH5RAlias(chirp_common.Alias):
#     VENDOR = "Rugged"
#     MODEL = "RH5R"


# class ROUV5REXAlias(chirp_common.Alias):
#     VENDOR = "Radioddity"
#     MODEL = "UV-5R EX"


# class A5RAlias(chirp_common.Alias):
#     VENDOR = "Ansoko"
#     MODEL = "A-5R"


# @directory.register
# class BaofengUV5RGeneric(BaofengUV5R):
#     ALIASES = [UV5XAlias, RT5RAlias, RT5RVAlias, RT5Alias, RH5RAlias,
#                ROUV5REXAlias, A5RAlias]


# @directory.register
# class BaofengF11Radio(BaofengUV5R):
#     VENDOR = "Baofeng"
#     MODEL = "F-11"
#     _basetype = BASETYPE_F11
#     _idents = [UV5R_MODEL_F11]

#     def _is_orig(self):
#         # Override this for F11 to always return False
#         return False


# @directory.register
# class BaofengUV82Radio(BaofengUV5R):
#     MODEL = "UV-82"
#     _basetype = BASETYPE_UV82
#     _idents = [UV5R_MODEL_UV82]
#     _vhf_range = (130000000, 176000000)
#     _uhf_range = (400000000, 521000000)
#     _valid_chars = chirp_common.CHARSET_ASCII

#     def _is_orig(self):
#         # Override this for UV82 to always return False
#         return False


# @directory.register
# class Radioddity82X3Radio(BaofengUV82Radio):
#     VENDOR = "Radioddity"
#     MODEL = "UV-82X3"
#     _basetype = BASETYPE_UV82X3

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.valid_bands = [self._vhf_range,
#                           (200000000, 260000000),
#                           self._uhf_range]
#         return rf


# @directory.register
# class BaofengUV6Radio(BaofengUV5R):

#     """Baofeng UV-6/UV-7"""
#     VENDOR = "Baofeng"
#     MODEL = "UV-6"
#     _basetype = BASETYPE_UV6
#     _idents = [UV5R_MODEL_UV6,
#                UV5R_MODEL_UV6_ORIG
#                ]
#     _aux_block = False

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.memory_bounds = (1, 128)
#         return rf

#     def _get_mem(self, number):
#         return self._memobj.memory[number - 1]

#     def _get_nam(self, number):
#         return self._memobj.names[number - 1]

#     def _set_mem(self, number):
#         return self._memobj.memory[number - 1]

#     def _set_nam(self, number):
#         return self._memobj.names[number - 1]

#     def _is_orig(self):
#         # Override this for UV6 to always return False
#         return False


# @directory.register
# class IntekKT980Radio(BaofengUV5R):
#     VENDOR = "Intek"
#     MODEL = "KT-980HP"
#     _basetype = BASETYPE_KT980HP
#     _idents = [UV5R_MODEL_291]
#     _vhf_range = (130000000, 180000000)
#     _uhf_range = (400000000, 521000000)
#     _tri_power = True

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.valid_power_levels = UV5R_POWER_LEVELS3
#         return rf

#     def _is_orig(self):
#         # Override this for KT980HP to always return False
#         return False


# class ROGA5SAlias(chirp_common.Alias):
#     VENDOR = "Radioddity"
#     MODEL = "GA-5S"


# class UV5XPAlias(chirp_common.Alias):
#     VENDOR = "Baofeng"
#     MODEL = "UV-5XP"


# class TSTIF8Alias(chirp_common.Alias):
#     VENDOR = "TechSide"
#     MODEL = "TI-F8+"


# class TenwayUV5RPro(chirp_common.Alias):
#     VENDOR = 'Tenway'
#     MODEL = 'UV-5R Pro'


# class TSTST9Alias(chirp_common.Alias):
#     VENDOR = "TechSide"
#     MODEL = "TS-T9+"


# class TDUV5RRadio(chirp_common.Alias):
#     VENDOR = "TIDRADIO"
#     MODEL = "TD-UV5R TriPower"


# @directory.register
# class BaofengBFF8HPRadio(BaofengUV5R):
#     VENDOR = "Baofeng"
#     MODEL = "BF-F8HP"
#     ALIASES = [RT5_TPAlias, ROGA5SAlias, UV5XPAlias, TSTIF8Alias,
#                TenwayUV5RPro, TSTST9Alias, TDUV5RRadio]
#     _basetype = BASETYPE_F8HP
#     _idents = [UV5R_MODEL_291,
#                UV5R_MODEL_A58
#                ]
#     _vhf_range = (130000000, 180000000)
#     _uhf_range = (400000000, 521000000)
#     _tri_power = True

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.valid_power_levels = UV5R_POWER_LEVELS3
#         return rf

#     def _is_orig(self):
#         # Override this for BFF8HP to always return False
#         return False


# class TenwayUV82Pro(chirp_common.Alias):
#     VENDOR = 'Tenway'
#     MODEL = 'UV-82 Pro'


# @directory.register
# class BaofengUV82HPRadio(BaofengUV5R):
#     VENDOR = "Baofeng"
#     MODEL = "UV-82HP"
#     ALIASES = [TenwayUV82Pro]
#     _basetype = BASETYPE_UV82HP
#     _idents = [UV5R_MODEL_UV82]
#     _vhf_range = (136000000, 175000000)
#     _uhf_range = (400000000, 521000000)
#     _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
#         "!@#$%^&*()+-=[]:\";'<>?,./"
#     _tri_power = True

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.valid_power_levels = UV5R_POWER_LEVELS3
#         return rf

#     def _is_orig(self):
#         # Override this for UV82HP to always return False
#         return False


# @directory.register
# class RadioddityUV5RX3Radio(BaofengUV5R):
#     VENDOR = "Radioddity"
#     MODEL = "UV-5RX3"

#     def get_features(self):
#         rf = BaofengUV5R.get_features(self)
#         rf.valid_bands = [self._vhf_range,
#                           (200000000, 260000000),
#                           self._uhf_range]
#         return rf

#     @classmethod
#     def match_model(cls, filename, filedata):
#         return False


# @directory.register
# class RadioddityGT5RRadio(BaofengUV5R):
#     VENDOR = 'Baofeng'
#     MODEL = 'GT-5R'

#     vhftx = [144000000, 148000000]
#     uhftx = [420000000, 450000000]

#     def set_memory(self, mem):
#         # If memory is outside the TX limits, the radio will refuse
#         # transmit. Radioddity asked for us to enforce this behavior
#         # in chirp for consistency.
#         if not (mem.freq >= self.vhftx[0] and mem.freq < self.vhftx[1]) and \
#            not (mem.freq >= self.uhftx[0] and mem.freq < self.uhftx[1]):
#             LOG.info('Memory frequency outside TX limits of radio; '
#                      'forcing duplex=off')
#             mem.duplex = 'off'
#             mem.offset = 0
#         BaofengUV5R.set_memory(self, mem)

#     @classmethod
#     def match_model(cls, filename, filedata):
#         return False


# @directory.register
# class RadioddityUV5GRadio(BaofengUV5R):
#     VENDOR = 'Radioddity'
#     MODEL = 'UV-5G'

#     _basetype = BASETYPE_UV5R
#     _idents = [UV5R_MODEL_UV5G]
#     _gmrs = True

#     @classmethod
#     def match_model(cls, filename, filedata):
#         return False
