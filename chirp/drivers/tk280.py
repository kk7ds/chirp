# Copyright 2016 Pavel Milanes, CO7WT, <pavelmc@gmail.com>
# Copyright 2024 Dan Smith <chirp@f.danplanet.com>
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

import collections
import itertools
import logging
import struct
import time

from chirp import chirp_common, directory, memmap, errors, util, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettings, MemSetting, RadioSettingValueInvertedBoolean, \
    RadioSettingValueMap, RadioSettingSubGroup

LOG = logging.getLogger(__name__)

# IMPORTANT DATA:
# This radios have a span of
# 0x00000 - 0x07FFF => Radio Memory / Settings data
# 0x08000 -         => FIRMWARE... hum...

# Notes: March 5 2024
# This file was heavily modified from tk760g.py for use with TK-380 by
# Thomas P. It is far from perfect but the main objective was to map a
# Kenwood x80 series to help further development. If radio is programmed in
# trunked mode, this module won't work as the mem map changes drastically.
# Stick to Conventional.
# FYI: Tk-981, 980, 480 and 481 are ONLY trunked mode so have different mem
# map.
#
# I believe the memmap is complete-ish but most likely needs corrections
# (data types, etc) if planning on completing a functional UI section.
#
# Many features are missing from the UI. Such as...
#   2-Tone, FleetSync, Emergency Information, Operator Selectable Tone,
#   Test Frequency
#
# Some features are shown in UI but incomplete. Such as...
#   Scan Information, DTMF
#
#


def choose_step(step_map, freq, default=5.0):
    """Choose the proper step index for a given frequency.

    @step_map should be a dict of step (in kHz) to index, in order of
              preference.
    @freq should be a frequency in Hz.
    Returns the step index from step_map to use.
    """
    try:
        step = chirp_common.required_step(freq, step_map.keys())
    except errors.InvalidDataError:
        step = default
        LOG.warning('Frequency %s requires step not in availble map, '
                    'using %s kHz by default',
                    chirp_common.format_freq(freq), step)
    return step_map[step]


CONVENTIONAL_DEFS = """
struct conv_settings {
  // x00-x01, Edit>>Model Information>>Radio Format,
  // '03 00':Conventional Format, '00 03':Trunked Format
  u8 format[2];
  u8 unknown0[12];          // unknown, all xFF in UNPROGRAM mode
  u8 groups;                // How many banks are programmed
  u8 channels;              // How many total channels are programmed
  ul16 tot;                 // TOT value: range(15, 600, 15); x04b0 = off
  u8 tot_rekey;             // TOT Re-key value range(0, 60); off= 0
  u8 unknown1;              // unknown
  u8 tot_reset;             // TOT Re-key value range(0, 60); off= 0
  u8 unknown2;              // unknowns
  u8 tot_alert;             // TOT pre alert: range(0,10); 0 = off
  u8 unknown3[7];           // 1d, unknown
  u8 sql_level;             // SQ reference level
  u8 battery_save;          // Portable: FF=off,32=Long,30=Short,31=Middle
  u8 sc_nfo_priority;       // Scan '31'=Selected, '30'=Fixed, 'FF'=None
  ul16 sc_nfo_lbt_a;        // Scan Look Back Time A[sec],range(0.35, 5.0, .05)
  ul16 sc_nfo_lbt_b;        // Scan Look Back Time B[sec],range(0.5, 5.0, .05)
  ul16 sc_nfo_ddtime;       // Scan Dropout Delay Time[sec],range(0, 300, 1)
  ul16 sc_nfo_dwell;        // Scan Dwell Time[sec], range(0, 300, 1)
  // Scan Revert Ch 30=Last Called, 31=Last Used, 34=Priority,
  // 35=Priority+TalkBack)
  u8 sc_nfo_revert;
  u8 sc_nfo_grp_scan;       // 8th bit, Scan Info, Group, 30=Single, 31=Multi
  u8 sc_nfo_prio_grp;       // Scan Priority Group, [None,1-32?]
  u8 sc_nfo_prio_ch;        // Scan Priority Channel, [None,1-128?]
  u8 unknown5:2,            // unknown
     ptt_release_tone:1,    // PTT Release Tone, '1'=off, '0'=on
     sc_nfo_rev_disp:1,     // Scan Revert Ch Display, '1'=disable, '0'=enable
     c2t:1,                 // Clear to transpond: 1=off,
     ost_direct:1,          // Operator Sel Tone, Direct (1=disable, 0=enable)
     ost_backup:1,          // Operator Sel Tone, Back Up (1=disable, 0=enable)
     unknown117:1;          // unknown
  u8 unknown113[2];         // 2 bytes, unknown
  u8 2t_a_tone_x[6];        // 2-Tone, A Tone [Hz], (41 24 FB 24 87 23)
  u8 2t_b_tone_x[6];        // 2-Tone, B Tone [Hz], (41 24 FB 24 87 23)
  u8 unknown8[4];
  u8 unknown9[16];
  u8 unknown10[16];
  lbit add[256];            //corresponding chan add/skip values, UNCONFIRMED
  u8 unknown12:1,
     ptt_inhib_ta:1,        // Inhibit PTT ID in TA(TalkAround), 1=off
     sel_call_alert_led:1,  // Sel Call Alert LED, '1'=enable, '0'=disable
     battery_warn:1,        // Battery Warning, '0'=enable, '1'=disable
     off_hook_decode:1,     // off hook decode enabled: 1-off
     off_hook_horn_alert:1, // off hook horn alert: 1-off
     busy_led:1,            // Busy LED, '0'=enable, '1'=disable
     disp_char:1;           // Opt 1, Display Character (1=ChName, 0=Grp#/Ch#)
  u8 unknown14;
};
// Conventional ends here?
"""

DEFS = """
struct settings {
  u8 unknown15:3,
     self_prog:1,           // Self programming enabled: 1-on
     clone:1,               // clone enabled: 1-on
     firmware_prog:1,       // firmware programming enabled: 1-on
     panel_tuning:1,        // Panel Tuning, 1-on, Requires panel_test=on
     panel_test:1;          // Panel test enabled, 1-on
  u8 unknown17;
  u8 unknown18:5,
     warn_tone:1,           // warning tone, enabled: 1-on
     control_tone:1,        // control tone (key tone), enabled: 1-on
     poweron_tone:1;        // power on tone, enabled: 1-on
  u8 unknown19[5];
  u8 min_vol;               // minimum volume possible: range(0,32); 0 = off
  u8 tone_vol;              // minimum tone volume FF=Continuous, range(0, 31)
  u8 sub_lcd_disp;          // Sub LCD Display (FF=none, 30=Group, 31=Channel)
  u8 grp_name_len;          // Group Name text length (0-10)
  u8 unknown119[2];         // unknown
  u8 unknown21:3,           // unknown
     access_log_sig:1,      // Access Logic Signal, '1'=Continuous, '0'=Pulse
     sq_logic_sig:1,        // Squelch Logic Signal, '1'=COR, '0'=TOR
     unknown111:1,
     access_log_type:1,     // Access Logic, '1'=Active Low, '0'=Active High
     sq_logic_type:1;       // Squelch Logic, '1'=Active Low, '0'=Active High
  u8 unknown106:4,
     em_type:2,             // Emergency, '11'=None, '10'=DTMF, '00'=FleetSync
     em_mode_type:1,        // Emergency Mode Type, '1'=Silent, '0'=Audible
     em_display:1;          // Emergency Display, 'FE'=Revert, 'FF'=Text'
  u8 unknown107[2];
  char poweronmesg[12];     // Power on mesg 12 bytes, off is "xFF" * 12
  u8 unknown23[6];
  u8 unknown133;            // FleetSync Enhanced, 00:enable, FF:disable
  char ident[8];            // radio identification string
  struct {
    char radio[6];        // 0xAF-0xB4, 6 digit Radio Password
    char data[6];         // 0xB5-0xBA, 6 digit Data Password
  } passwords;
  char lastsoftversion[5];  // software version employed to program the radio
  char dtmf_prim_code[7];   // DTMF Decode, Primary Code
  char dtmf_sec_code[7];    // DTMF Decode, Secondary Code
  char dtmf_DBD_code[7];    // DTMF Decode, Dead Beat Disable Code
  char ptt_id_bot[16];      // PTT ID Begin of TX
  char ptt_id_eot[16];      // PTT ID End of TX
  ul16 d_auto_r_timer;      // DTMF Auto Reset Timer [sec], 'Off', '0-300'
  u8 d_enc_dig_time;        // DTMF Encode Digit Time [dig/sec], 6,8,10,15
  u8 unknown100;
  ul16 d_enc_first_d;       // DTMF Encode First Digit [msec], 0,100,500,1000
  ul16 d_enc_sym_d;         // DTMF Encode * and # Digit [msec], 0,100,500,1000
  u8 d_dir_access:1,        // DTMF Encode * Direct, '1'=disable, '0'=enable
     unknown101:1,
     d_store_send:1,        // DTMF Enc Store and Send, '1'=disable, '0'=enable
     d_man_dial:1,          // DTMF Manual Dial, '1'=enable, '0'=disable
     d_side_tone:1,         // DTMF Side Tone, '1'=enable, '0'=disable
     d_db_dis_resp:1,       // DTMF Dead Beat Disable, 1=TX Inh, 0=TX/RX Inh
     d_sec_dec_resp:1,      // DTMF Secondary Decode, 1=Alert, 0=Transpond
     d_prim_dec_resp:1;     // DTMF Primary Decode, 1=Alert, 0=Transpond
  u8 unknown102:1,
     d_call_alert:1,        // DTMF Call Alert, '1'=Normal, '0'=Continuous
     // Decode Response, changes to '1' when "Alert+Transpond" selected
     unknown103:1,          // Secondary
     unknown132:1,          // Primary
     d_kp_auto_ptt:1,       // DTMF Keypad Auto-PTT, '0'=enable, '1'=disable
     ptt_id_when:2,         // PTT ID, '10'=BOT, '01'=EOT, '00'=Both
     signalling_type:1;     //Signalling, '1'=OR, '0'=AND
};
struct keys {
  u8 kA;            // A button
  u8 kLEFT;         // Triangle to Left on portable, B
  u8 kRIGHT;        // Triangle to Right on portable, C
  u8 kSIDE1;        // Side button 1 (lamp), D on mobile
  u8 kSCN;          // S switch
  u8 kMON;          // Side button 2 (mon)
  u8 kORANGE;       // Orange button on portable, Foot Switch on mobile
  // PF1(ORANGE) on portable, Group Up (Right Side Up Arrow) on mobile
  u8 kPF1;
  // PF2(BLACK) on portable, Group Down (Right Side Down Arrow) on mobile
  u8 kPF2;
  u8 kVOL_UP;       // Volume Up (Left Side Up Arrow), Mobile only
  u8 kVOL_DOWN;     // Volume Down (Left Side Down Arrow), Mobile only
  u8 unknown30[9];  // unknown
  u8 kP_KNOB;       // Just portable: channel knob
  u8 unknown131[4]; // unknown
  u8 unknown31[7];  // unknown
  u8 k0;            // Numkey 0
  u8 k1;            // Numkey 1
  u8 k2;            // Numkey 2
  u8 k3;            // Numkey 3
  u8 k4;            // Numkey 4
  u8 k5;            // Numkey 5
  u8 k6;            // Numkey 6
  u8 k7;            // Numkey 7
  u8 k8;            // Numkey 8
  u8 k9;            // Numkey 9
  u8 unknown130[4]; // Unknown
  u8 kASTR;         // Numkey *
  u8 kPOUND;        // Numkey #
};
struct misc {
  u8 d_enc_hold_time; // DTMF Encode Hold Time [sec], Off, 0.5-2.0, .1 incr
  u8 unknown120;      // unknown
  u8 ptt_id_type;     // PTT ID Type, '00'=DTMF, '01'=FleetSync, NOT emergency
  u8 unknown112;      // unknown
  // Com 0(Accessory Connector), FF=none, 33=rem, 30=Data,
  // 35=Data+GPS NOT related to emergency
  u8 com_0;
  // Com 1(Internal Port), FF=none, 33=rem, 36=man down in, 31=GPS,
  // NOT related to emergency but convenient to put here
  u8 com_1;
  // Com 2(Internal Port), FF=none, 33=rem, 36=man down in, 31=GPS,
  // 32=AUX Hook/PTT, 34=Data PTT, 35=Data+GPS
  u8 com_2;
  u8 em_group;        // Emergency Group
  u8 em_chan;         // Emergency Channel
  ul16 em_key_delay;  // Emergency Key Delay Time [sec] Off, .1-5.0 in .1 incr
  u8 em_active_time;  // Emergency Active time [sec], 1-60
  u8 unknown_105;     // unknown
  u8 em_int_time;     // Emergency Interval Time [sec], 30-180
  u8 unknown107;      // unknown
  char em_text[10];   // Emergency Text
  char line1[32];     // Embedded Message Line 1
  char line2[32];     // Embedded Message Line 2
  u8 em_dtmf_id[16];  // x240-x24F, 16 bytes, Emergency DTMF ID
};
"""

MEM_FORMAT = DEFS + CONVENTIONAL_DEFS + """
  // #seekto 0x0000;
  struct conv_settings conv;
  // #seekto 0x0082;
  struct settings settings;
//These are ALL the keys on TK-380 keypad version. These locations are assigned
// functions from values in KEYS below
#seekto 0x0110;
struct keys keys;

//#seekto 0x0140;
struct {
  lbcd tf01_rx[4];
  lbcd tf01_tx[4];
  u8 tf01_u_rx;
  u8 tf01_u_tx;
  lbcd tf02_rx[4];
  lbcd tf02_tx[4];
  u8 tf02_u_rx;
  u8 tf02_u_tx;
  lbcd tf03_rx[4];
  lbcd tf03_tx[4];
  u8 tf03_u_rx;
  u8 tf03_u_tx;
  lbcd tf04_rx[4];
  lbcd tf04_tx[4];
  u8 tf04_u_rx;
  u8 tf04_u_tx;
  lbcd tf05_rx[4];
  lbcd tf05_tx[4];
  u8 tf05_u_rx;
  u8 tf05_u_tx;
  lbcd tf06_rx[4];
  lbcd tf06_tx[4];
  u8 tf06_u_rx;
  u8 tf06_u_tx;
  lbcd tf07_rx[4];
  lbcd tf07_tx[4];
  u8 tf07_u_rx;
  u8 tf07_u_tx;
  lbcd tf08_rx[4];
  lbcd tf08_tx[4];
  u8 tf08_u_rx;
  u8 tf08_u_tx;
  lbcd tf09_rx[4];
  lbcd tf09_tx[4];
  u8 tf09_u_rx;
  u8 tf09_u_tx;
  lbcd tf10_rx[4];
  lbcd tf10_tx[4];
  u8 tf10_u_rx;
  u8 tf10_u_tx;
  lbcd tf11_rx[4];
  lbcd tf11_tx[4];
  u8 tf11_u_rx;
  u8 tf11_u_tx;
  lbcd tf12_rx[4];
  lbcd tf12_tx[4];
  u8 tf12_u_rx;
  u8 tf12_u_tx;
  lbcd tf13_rx[4];
  lbcd tf13_tx[4];
  u8 tf13_u_rx;
  u8 tf13_u_tx;
  lbcd tf14_rx[4];
  lbcd tf14_tx[4];
  u8 tf14_u_rx;
  u8 tf14_u_tx;
  lbcd tf15_rx[4];
  lbcd tf15_tx[4];
  u8 tf15_u_rx;
  u8 tf15_u_tx;
  lbcd tf16_rx[4];
  lbcd tf16_tx[4];
  u8 tf16_u_rx;
  u8 tf16_u_tx;
} test_freq;

#seekto 0x1E7;
struct misc misc;

#seekto 0x0300;
struct {
    u8 group;      // Group number
    u8 number;     // Memory number in zone
    u8 group_index;// The *index* of the group record
    u8 index;      // Index of memory in array
} group_mapping[250];

#seekto 0x700;
struct {
  ul16 ost_dec_tone;    // Operator Selectable Tones, QT/DQT Decode
  ul16 ost_enc_tone;    // Operator Selectable Tones, QT/DQT Encode
  char ost_name[10];    // Operator Selectable Tones, OST Name
  u8 unknown118[2];     // unknown
} ost[16];

//#seekto 0x800;
struct {
  u8 2t_a_tone_y[4];    // 2t_a_tone_x and 2t_a_tone_z
  u8 2t_b_tone_y[4];    // 2t_b_tone_x and 2t_b_tone_z
  u8 2t_c_tone_y[4];    // 2t_c_tone_z
  u8 2t_a_tone_z[2];    // 2t_a_tone_x and 2t_a_tone_y
  u8 2t_b_tone_z[2];    // 2t_b_tone_x and 2t_b_tone_y
  u8 2t_c_tone_z[2];    // 2t_c_tone_y
  // Decoder1 Call Format, (30=A-B, 31=A-C, 32=C-B, 33=A, 34=B, 35=C)
  u8 2t_dec1_ca_form;
  // Decoder2 Call Format, (FF=None, 30=A-B, 31=A-C, 32=C-B, 33=A, 34=B, 35=C)
  u8 2t_dec2_ca_form;
  u8 2t_call_alert;     // 2-Tone, Call Alert, (FF=no, x30=Normal, x31=Cont)
  u8 2t_ar_timer[2];    // 2-Tone, Auto Reset[sec], range(Off, 1-300) incr of 1
  u8 unknown115:5,
     2t_transpond:1,    // Transpond (1=disable, 0=enable)
     2t_dec2_c_type:1,  // Decoder2 Call Type, (1=Individual, 0=Group)
     2t_dec1_c_type:1;  // Decoder1 Call Type, (1=Individual, 0=Group)
  u8 unknown116[8];

} 2tone[3];     // Attempt at capturing 2-Tone 1, 2 and 3

#seekto 0x1000;
struct {
  u8 number;        // Group Number
  u8 channels;      // Channels in Group
  char name[10];    // Group Name
  u8 data_grp;      // Data Group
  u8 data_chan;     // Data Channel
  u8 unknown108;
  u8 unknown109;
} groups[250];

#seekto 0x2000;
struct {
  u8 number;         // Channel Number
  u8 group;          // to which bank/group it belongs
  char name[10];     // Channel name, 10 chars
  lbcd rxfreq[4];    // rx freq
  lbcd txfreq[4];    // tx freq
  u8 unknown_rx:4,
     rx_step:4;      // rx tuning step
  u8 unknown_tx:4,
     tx_step:4;
  ul16 rx_tone;      // rx tone
  ul16 tx_tone;      // tx tone
  u8 unknown23[5];   // unknown yet
  u8 signalling;     // Option Sig, FF=off, 30=DTMF, 32=2-Tone 1,32=FleetSync,
  u8 unknown24:1,    // unknown
     ptt_id:1,       // PTT ID, '1'=off, '0'=on
     beat_shift:1,   // Beat Shift, 1 = off
     busy_lock:1,    // BCL, 1=none, 0=QT/DQT Tone, see also 2 bits in x2021
     data_en:1,      // Data, 1=enable
     power:1,        // TX Power: 0 low / 1 high
     compander:1,    // Compander, 1 = off
     wide:1;         // Wide/Narrow, wide 1 / 0 narrow
  u8 unknown27:4,    // unknown
     busy_lock_opt:2,// Busy Lock, 11=none, 00=Carrier, 01=OptSig,
     unknown28:2;    // unknown
  u8 unknown29[14];  // unknown yet
} memory[250];

#seekto 0x5000;
struct {
  u8 d_num;         // DTMF Memory number
  u8 unknown32;     // unknown
  char d_an[10];    // A/N
  u8 unknown33[4];  // unknown
  u8 d_code[8];     // Code
  u8 unknown34[8];  // unknown
} dtmf_memory[32];

#seekto 0x6000;
struct {
  // method unknown so far
  u8 fs_fleet_id[3]; // FleetSync, Fleet(Own):100-349 and ID(Own): 1000-3999
  u8 unknown126[2];
  ul16 fs_max_ack_wt;   // FleetSync, Maximum ACK Wait [sec]: 0.5-60, .10 incr
  ul16 fs_dtx_mod_dt;   // FleetSync, Data TX Mod Delay [msec]: 0-6000, 1 incr
  u8 unknown125[3];
  u8 fs_uid_enc_blk[4]; // FleetSync, UnitID Enc Block: 1000-4999, method unk
  u8 fs_gtc_count;      // FleetSync, GTC Count: 0-5
  ul16 fs_tx_bw_time;   // FleetSync, TX Busy Wait [sec]: 0.5-60.0, .10 incr
  ul16 fs_ack_delay;    // FleetSync, ACK Delay Time[sec]: 0.1-60.0, .10 incr
  u8 fs_num_retries;    // FleetSync, Number of Retries: 0-8
  ul16 fs_txdel_rxcap;  // FleetSync, TX Delay (RX Capt): 0.0-25.0, .10 incr
  u8 unknown124[3];
  u8 fs_baud;           // FleetSync, Baud Rate [bps]: (x31=2400, 30=1200)
  ul16 fs_mm_timer;     // FleetSync, Message Mode Timer[sec]: (off, 1-300)
  u8 fs_em_stat_resp;   // FleetSync, Emerg Status Resp: (x00=none, x01=Alert)
  u8 fs_ptt_st;         // FleetSync, PTT ID Side Tone: (1=enable, 0=disable)
  u8 unknown127[3];
  u8 fs_stat_m_data;    // FleetSync, Status Msg on Data Ch 1=dis, 0=en
  u8 fs_caller_id_st:1, // FleetSync, Caller ID Stack: 1=dis, 0=en
     unknown121:1,
     fs_stat_8090:1,    // FleetSync, Status 80-99(Special): 1=dis, 0=en
     unknown122:1,
     data_tx_qt:1,      // Opt Feat2, Data TX with QT/DQT, '1'=dis, '0'en
     fs_man_dial:1,     // FleetSync, Manual Dial: 0=disable, 1=enable
     fs_if_call:1,      // FleetSync, Inter-fleet Call: 1=disable, 0=enable
     fs_rand_acc:1;     // FleetSync, Random Access (Cont): 0=enable, 1=disable
  u8 unknown123:5,
     fs_ss_val:1,       // FleetSync, Stun Status Valid: (1=enable, 0=disable)
     fs_ca_cont:1,      // FleetSync, Call Alert(Cont): (1=enable, 0=disable)
     fs_call_id_disp:1; // FleetSync, Caller ID Display (1=disable, 0=enable)
} fleetsync;

#seekto 0x6040;
struct {
  u8 em_call_fleet; // x6040, 1 byte, Emergency FleetSync Call Fleet #, 100-350
  u8 em_call_id[2]; // x6041, 2 byte, Emergency FleetSync Call ID #, 1000-3999
} emergency;

#seekto 0x6C00;
struct {
  u8 fs_idl_fleet;      // FleetSync, ID List, Fleet: 100-349
  ul16 fs_idl_id;       // FleetSync, ID: 1000-4999 x004E=ALL
  char fs_id_name[10];  // FleetSync, ID List, ID Name
  u8 fs_idl_tx_inhibit; // FleetSync, ID List, TX Inhibit: FF=No, FE=Yes
  u8 unknown127[2];
} fs_id_list[64];

//#seekto 0x7000;
struct {
  u8 fs_sl_status;       // FleetSync, Status List, Status: 10-99
  u8 unknown120;
  char fs_stat_name[16]; // FleetSync, Status List, Status Name
  u8 fs_sl_tx_inhibit;   // FleetSync, Status List, TX Inhibit: FE=Yes, FF=No
  u8 unknown128[13];
} fs_stat_list[50];
"""

NOTE = """ MENTAL NOTE ABOUT RADIO MEM

The OEM insist on not reading/writing some mem segments, see below

read: (hex)
    00 - 03
    07 - 08
    10
    20 - 21
    58 - 7F

write: (hex)
    00 - 03
    07 - 08
    10
    20 - 21
    60 - 7F


This can be an artifact to just read/write in the needed mem space and speed
up things, if so the first read blocks has all the data about channel groups
and freq/tones & names employed.

This is a copied trick from the "60G series" ones and may use the same schema.

I must investigate further on this.
"""

MEM_SIZE = 0x8000  # 32,768 bytes (128 blocks of 256 bytes)
BLOCK_SIZE = 256
MEM_BLOCKS = range(0, MEM_SIZE // BLOCK_SIZE)

# define and empty block of data, as it will be used a lot in this code
EMPTY_BLOCK = b"\xFF" * 256

ACK_CMD = b"\x06"
NAK_CMD = b"\x15"

# TK-280:1,5 TK-380:1,4 TK-780:25 TK-880:5,25

MODES = ["NFM", "FM"]  # 12.5 / 25 Khz
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + "_-*()/\\-+=)."
SKIP_VALUES = ["", "S"]

TONES = chirp_common.TONES
# TONES.remove(254.1)
DTCS_CODES = chirp_common.DTCS_CODES


TOT = [("off", 0x04B0)] + [("%s" % x, x) for x in range(15, 615, 15)]
TOT_PRE = ["off"] + ["%s" % x for x in range(1, 11)]
TOT_REKEY = ["off"] + ["%s" % x for x in range(1, 61)]
TOT_RESET = ["off"] + ["%s" % x for x in range(1, 16)]
VOL = ["off"] + ["%s" % x for x in range(1, 32)]
TVOL = ["%s" % x for x in range(0, 33)]
TVOL[32] = "Continuous"
SQL = ["off"] + ["%s" % x for x in range(1, 10)]
SIG_TYPE = ["AND", "OR"]
CM0 = {
    0xFF: "None",
    0x30: "Data",
    0x31: "GPS",
    0x32: "AUX Hook/PTT",
    0x33: "REM",
    0x34: "Data PTT",
    0x35: "Data+GPS",
    0x36: "Man Down In",
}
BSAVE = {0xFF: "Off", 0x32: "Long", 0x30: "Short", 0x31: "Middle"}
PIDT = {0x00: "DTMF", 0x01: "FleetSync"}
PID = {0o10: "BOT", 0o01: "EOT", 0o00: "Both"}
SLT = {1: "Active Low", 0: "Active High"}
SLS = {1: "COR", 0: "TOR"}
ALT = {1: "Active Low", 0: "Active High"}
ALS = {1: "Continuous", 0: "Pulse"}
SIP = {0x31: "Selected", 0x30: "Fixed", 0xFF: "None"}
PG = ["None"] + ["%s" % x for x in range(1, 32)]
PCH = ["None"] + ["%s" % x for x in range(1, 250)]
LBTA = [x / 100.0 for x in range(35, 505, 5)]
LBTB = [x / 100.0 for x in range(50, 505, 5)]
REVCH = {
    0x30: "Last Called",
    0x31: "Last Used",
    0x34: "Priority",
    0x35: "Priority+TalkBack",
}
DDT = ["%s" % x for x in range(0, 300)]
DWT = ["%s" % x for x in range(0, 300)]
GRPSC = {0x30: "Single", 0x31: "Multi"}
BCL_OPTS = ['Off', 'QT/DQT', 'Option Signalling', 'Carrier Only']

KEYS = {
    0x30: "Memory(RCL/STO)",
    0x31: "DTMF ID(BOT)",
    0x32: "DTMF ID(EOT)",
    0x33: "Display character",
    0x34: "Emergency",
    0x35: "Home Channel",                   # Possible portable only, check it
    0x36: "Function",
    0x37: "Channel down",
    0x38: "Channel up",
    0x39: "Key lock",
    0x3b: "Public address",
    0x3c: "Reverse",                        # Not all firmware versions?
    0x3d: "Horn alert",
    0x3e: "Memory(RCL)",
    0x3f: "Memory(STO)",
    0x40: "Monitor A: Open Momentary",
    0x41: "Monitor B: Open Toggle",
    0x42: "Monitor C: Carrier Squelch Momentary",
    0x43: "Monitor D: Carrier Squelch Toggle",
    0x45: "Redial",
    0x47: "Scan",
    0x48: "Scan Del/Add",
    0x4a: "Group Down",
    0x4b: "Group Up",
    0x4e: "Operator Selectable Tone",
    0x4f: "None",
    0x50: "Volume down",
    0x51: "Volume up",
    0x52: "Talk around",
}
PORTABLE_KEYS = {
    0x3a: "Lamp",
    0x5d: "AUX",
    0x46: "RF Power Low",
}
MOBILE_KEYS = {
    0x5D: 'AUX A',  # Same as AUX on portable
    0x44: 'AUX B',
}


def _close_radio(radio):
    """Get the radio out of program mode"""
    try:
        radio.pipe.write(b"E")
    except Exception as e:
        LOG.error('Failed to close radio: %s' % e)


def _checksum(data):
    """the radio block checksum algorithm"""
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _make_frame(cmd, addr):
    """Pack the info in the format it likes"""
    return struct.pack(">BH", cmd[0], addr)


def _open_radio(radio, status):
    """Open the radio into program mode and check if it's the correct model"""
    radio.pipe.baudrate = 9600
    radio.pipe.parity = "E"
    radio.pipe.timeout = 1

    LOG.debug("Entering program mode.")
    tries = 10

    status.msg = "Entering program mode..."
    radio.status_fn(status)

    for i in range(0, tries):
        radio.pipe.write(b"PROGRAM")
        ack = radio.pipe.read(1)
        LOG.debug('Ack: %r' % ack)
        if not ack:
            LOG.debug('No response from radio, will retry')
            time.sleep(0.5)
        elif ack != ACK_CMD:
            LOG.debug('Received unexpected response from radio: %r' % ack)
            radio.pipe.flush()
            time.sleep(0.5)
        else:
            break

    if ack != ACK_CMD:
        raise errors.RadioError('Failed to put radio into programming mode')

    radio.pipe.write(b"\x02")
    rid = radio.pipe.read(8)
    if radio.TYPE not in rid:
        LOG.debug("Incorrect model ID:")
        LOG.debug(util.hexprint(rid))
        raise errors.RadioError(
            "Incorrect model ID, got %s, it doesn't contain %s" %
            (rid.strip(b"\xff"), radio.TYPE))

    LOG.debug("Full ident string is:")
    LOG.debug(util.hexprint(rid))
    exchange_ack(radio.pipe)

    status.msg = "Radio ident success!"
    radio.status_fn(status)

    radio.pipe.write(b"P")
    ver = radio.pipe.read(10)
    LOG.debug("Version returned by the radios is:")
    LOG.debug(util.hexprint(ver))
    exchange_ack(radio.pipe)
    # the radio that was processed returned this:
    # v2.00k.. [76 32 2e 30 30 6b ef ff]
    # version 1 TK-280:
    # v1.04.. 76 31 2e 30 34 20 ff ff

    # now the OEM writes simply "O" and gets no answer...
    # after that we are ready to receive the radio image or to write to it
    radio.pipe.write(b'O')

    radio.metadata = {'tkx80_ver': ver.strip(b'\xFF').decode('ascii',
                                                             errors='ignore'),
                      'tkx80_rid': list(rid.strip(b'\xFF'))}


def exchange_ack(pipe):
    pipe.write(ACK_CMD)
    ack = pipe.read(1)
    if ack == NAK_CMD:
        LOG.debug('Radio sent explicit NAK')
        raise errors.RadioError('Radio sent NAK')
    elif ack != ACK_CMD:
        LOG.debug('Radio sent unexpected response: %r' % ack)
        raise errors.RadioError('Radio did not ack')


def read_block(pipe):
    cmd = pipe.read(1)
    if cmd == b'Z':
        block = b'\xFF' * BLOCK_SIZE
    else:
        block = pipe.read(BLOCK_SIZE)
    checksum = pipe.read(1)
    calc = _checksum(block)
    if calc != checksum[0] and cmd != b'Z':
        LOG.debug('Checksum %i does not match %i', calc, checksum[0])
        raise errors.RadioError('Checksum reading block from radio')
    exchange_ack(pipe)
    return block


def do_download(radio):
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    radio.status_fn(status)

    data = b""
    count = 0
    _open_radio(radio, status)

    status.msg = "Cloning from radio..."
    for addr in MEM_BLOCKS:
        radio.pipe.write(_make_frame(b"R", addr))
        block = read_block(radio.pipe)
        data += block
        status.cur = count
        radio.status_fn(status)
        count += 1

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    _open_radio(radio, status)

    status.msg = "Cloning to radio..."
    for block in MEM_BLOCKS:
        if 0x50 < block < 0x60:
            # This causes a NAK if the radio does not have this feature
            LOG.debug('Skipping DTMF memory block 0x%x', block)
            continue
        data = radio.get_mmap()[block * BLOCK_SIZE:(block + 1) * BLOCK_SIZE]
        if data == EMPTY_BLOCK:
            frame = _make_frame(b'Z', block) + b'\xFF'
        else:
            cs = _checksum(data)
            frame = _make_frame(b'W', block) + data + bytes([cs])
        radio.pipe.write(frame)
        try:
            exchange_ack(radio.pipe)
        except Exception:
            LOG.error('Failed to send block 0x%x', block)
            raise
        status.cur = block
        radio.status_fn(status)


class TKx80SubdevMeta(type):
    """Metaclass for generating subdevice subclasses"""
    def __new__(cls, name, bases, dct):
        return super(TKx80SubdevMeta, cls).__new__(cls, name, bases, dct)

    @staticmethod
    def make_subdev(parent_dev, child_cls, key, to_copy, **args):
        """parent_dev: An instance of the parent class
           child_cls: The class of the child device
           key: Some class-name-suitable value to set this off from others
           to_copy: Class variables tp copy from the parent
           args: Class variables to set on the new class
        """
        return TKx80SubdevMeta('%s_%s' % (child_cls.__name__, key),
                               (child_cls, parent_dev.__class__),
                               dict({k: getattr(parent_dev, k)
                                     for k in to_copy}, **args))


class KenwoodTKx80(chirp_common.CloneModeRadio):
    """Kenwood Series 80 Radios base class"""
    VENDOR = "Kenwood"
    BAUD_RATE = 9600
    _memsize = MEM_SIZE
    NAME_LENGTH = 8
    _range = []
    _upper = 250
    _steps = chirp_common.COMMON_TUNING_STEPS
    # Ver1 and Ver2 radios use a different multiplier for in-memory frequency
    _freqmult = 10
    VARIANT = ""
    MODEL = ""
    FORMATS = [directory.register_format('Kenwood KPG-49D', '.dat')]
    POWER_LEVELS = []

    def load_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'rb') as f:
                f.seek(0x32)
                self._mmap = memmap.MemoryMapBytes(f.read())
                LOG.info('Loaded DAT file at offset 0x32')
            self.process_mmap()
        else:
            return super().load_mmap(filename)

    @property
    def dat_header(self):
        return (b'KPG49D\xFF\xFF\xFF\xFFV4.02P0' +
                self.MODEL[3:].encode() +
                b'\x04\xFF\xF1\xFF' +
                b'\xFF' * 26)

    def save_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'wb') as f:
                f.write(self.dat_header)
                f.write(self._mmap.get_packed())
                LOG.info('Write DAT file')
        else:
            super().save_mmap(filename)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental and supports only conventional '
             'zones.')
        return rp

    def get_features(self):
        """Return information about this radio's features"""
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_tuning_step = False
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_dynamic_subdevices = True
        rf.valid_modes = MODES
        rf.valid_duplexes = ["", "-", "+", "off", "split"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = VALID_CHARS
        rf.valid_skips = SKIP_VALUES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_bands = self._range
        rf.valid_tuning_steps = self._steps
        rf.valid_name_length = 10
        rf.memory_bounds = (1, self._upper)
        rf.has_sub_devices = True
        rf.has_bank = False
        rf.can_odd_split = True
        return rf

    def get_sub_devices(self):
        to_copy = ('MODEL', 'TYPE', 'POWER_LEVELS', '_range', '_steps',
                   '_freqmult')
        if not self._memobj:
            return [TKx80SubdevMeta.make_subdev(
                self, TKx80Group, 1, to_copy)(self, 1)]
        return sorted([
            TKx80SubdevMeta.make_subdev(
                self, TKx80Group, i,
                to_copy, VARIANT=str(self._memobj.groups[i].name).strip())(
                    self, self._memobj.groups[i].number)
            for i in range(250)
            if self._memobj.groups[i].number <= 250],
            key=lambda z: z.group)

    def sync_in(self):
        """Do a download of the radio eeprom"""
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unexpected radio error: %s' % e)
            raise errors.RadioError(str(e))
        finally:
            _close_radio(self)
        self.process_mmap()

    def sync_out(self):
        """Do an upload to the radio eeprom"""

        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            _close_radio(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        self._compact_mappings()

    def _decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        val = int(val)
        if val == 65535:
            return '', None, None
        elif val >= 0x2800:
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return 'DTCS', code, pol
        else:
            a = val / 10.0
            return 'Tone', a, None

    def _encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval.set_raw(b"\xff\xff")
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            val = int("%i" % value, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            memval.set_value(val)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def _get_scan(self, chan):
        """Get the channel scan status from the 16 bytes array on the eeprom
        then from the bits on the byte, return '' or 'S' as needed"""
        return '' if bool(self._memobj.conv.add[chan]) else 'S'

    def _set_scan(self, chan, value):
        """Set the channel scan status from UI to the mem_map"""
        self._memobj.conv.add[chan] = value == ''

    def _get_memory_mapping(self, group, number, allocate=False):
        """Find a virtual memory mapping in the group's index.

        Raise IndexError if not mapped.
        """
        try:
            return self._map_cache[(group, number)]
        except KeyError:
            if not allocate:
                raise IndexError('Memory %i-%i not mapped' % (group, number))

        LOG.debug('Cache miss for allocating %i,%i' % (group, number))
        empty = None
        free_memories = set(range(250))
        this_group_index = None
        # Count to 250 and...
        for i in range(250):
            mapping = self._memobj.group_mapping[i]
            if mapping.group == group and mapping.number == number:
                # Direct hit, return it. But, we should have found this in the
                # cache
                LOG.warning('Found mapping for %i-%i but was not in cache?',
                            group, number)
                return mapping
            elif empty is None and mapping.group == 0xFF:
                # Record the earliest-available mapping
                empty = i
            elif mapping.index < 255:
                # Any valid mapping consumes a slot in the memory array,
                # so keep track of which ones are unused
                free_memories.remove(int(mapping.index))

            # Also record the index of this group in case we have to allocate
            # below
            if self._memobj.groups[i].number == group:
                this_group_index = i

        if this_group_index is None:
            raise errors.RadioError(
                'Allocate for group %i did not find a record' % group)
        # Use the first available memory location
        memory = list(sorted(free_memories))[0]
        mapping = self._memobj.group_mapping[empty]
        mapping.group = group
        mapping.number = number
        mapping.group_index = this_group_index
        mapping.index = memory
        self._memobj.groups[this_group_index].channels += 1
        LOG.info(('Allocating slot %i memory %i for %i-%i '
                  'grp index %i channels %i') % (
            empty, memory,  group, number, this_group_index,
            self._memobj.groups[this_group_index].channels))
        self._compact_mappings()
        # The above may have rearranged things so re-search for our
        # new slot
        return self._get_memory_mapping(group, number)

    def _delete_memory_mapping(self, group, number):
        mapping = self._parent._get_memory_mapping(group, number)
        mem = self._memobj.memory[mapping.index]
        group_rec = self._memobj.groups[mapping.group_index]
        group_rec.channels -= 1
        LOG.info(
            'Deleting memory mapping for %i-%i memory %i (%i in group)' % (
                group, number, mapping.index, group_rec.channels))
        mem.fill_raw(b'\xFF')
        mapping.fill_raw(b'\xFF')
        self._compact_mappings()

    def _compact_mappings(self):
        """Survey all the memories in mapping list and update."""
        group_counts = collections.defaultdict(lambda: 0)
        valid = []
        # Count to 250 and ...
        for i in range(250):
            # Find all the valid mappings and count up number of valid
            # memories in each group
            mapping = self._memobj.group_mapping[i]
            if mapping.group < 255 and mapping.number < 255:
                valid.append((int(mapping.group), int(mapping.number),
                              int(mapping.group_index), int(mapping.index)))
                group_counts[int(mapping.group)] += 1

        # The mappings need to be in order, at least by group, perhaps by
        # memory number as well
        valid.sort(key=lambda x: (x[0], x[1]))

        memories = 0
        groups = set()
        self._map_cache = {}
        # Count to 250 again and...
        for i in range(250):
            # Update all the mappings with the new sorted survey results
            try:
                group, number, group_index, index = valid[i]
                memories += 1
                groups.add(group)
            except IndexError:
                group = number = group_index = index = 0xFF
            mapping = self._memobj.group_mapping[i]
            mapping.group = group
            mapping.number = number
            mapping.group_index = group_index
            mapping.index = index

            # Rebuild our cache
            self._map_cache[int(mapping.group), int(mapping.number)] = mapping

            # Also update the groups with correct memory counts
            group = int(self._memobj.groups[i].number)
            if group in group_counts:
                self._memobj.groups[i].channels = group_counts[group]

        # Radio-wide group and memory counts need to be updated
        self._memobj.conv.groups = len(groups)
        self._memobj.conv.channels = memories
        LOG.info('%i groups, %i memories',
                 self._memobj.conv.groups,
                 self._memobj.conv.channels)

    @classmethod
    def match_model(cls, filedata, filename):
        model = cls.MODEL[3:].encode()
        if (filename.lower().endswith('.dat') and
                b'KPG49D' in filedata and model in filedata[:0x32]):
            return True
        return False

    def _get_settings_groups(self, groups):
        group_index = {}
        unused_slots = set()

        # Survey the currently-mapped groups
        for i in range(250):
            if self._memobj.groups[i].number < 0xFF:
                group_index[int(self._memobj.groups[i].number)] = i
            else:
                unused_slots.add(i)

        for i in range(250):
            group_number = i + 1
            try:
                group = self._memobj.groups[group_index[group_number]]
                group_name = str(group.name).strip('\xFF')
                group_count = int(group.channels)
                enabled = True
            except KeyError:
                group_name = ''
                group_count = 0
                enabled = False
            name = RadioSetting('group-%i-name' % group_number, 'Name',
                                RadioSettingValueString(
                                    0, 10, group_name))
            enable = RadioSetting('group-%i-enable' % group_number, 'Enabled',
                                  RadioSettingValueBoolean(enabled))
            enable.set_volatile(True)
            count = RadioSetting('group-%i-count' % group_number,
                                 'Active Memories',
                                 RadioSettingValueInteger(0, 250, group_count))
            if group_count:
                # Can't delete groups with active memories
                enable.value.set_mutable(False)
                enable.set_doc('Delete all memories from group to disable')
            else:
                name.value.set_mutable(False)
            count.value.set_mutable(False)
            groups.append(RadioSettingSubGroup(
                'group-%i' % group_number,
                'Group %i' % group_number,
                name, enable, count))

    def _parse_qtdqt(self, v):
        v = v.upper().strip()
        if v.startswith('D'):
            try:
                val = int(v[1:4])
                pol = v[4]
                return 'DTCS', val, pol
            except (ValueError, IndexError):
                raise errors.InvalidValueError(
                    'DCS value must be in the form "D023N"')
        elif v:
            try:
                val = float(v)
                return 'Tone', val, ''
            except ValueError:
                raise errors.InvalidValueError(
                    'Tone value must be in the form 103.5')
        else:
            return '', None, None

    def _format_qtdtq(self, raw):
        mode, val, pol = self._decode_tone(raw)
        if mode == 'DTCS':
            return 'D%03.3i%s' % (val, pol)
        elif mode == 'Tone':
            return '%3.1f' % val
        else:
            return ''

    def _get_settings_ost(self, ost):
        rs = MemSetting('conv.ost_backup', 'OST Backup',
                        RadioSettingValueInvertedBoolean(
                            not self._memobj.conv.ost_backup))
        rs.set_doc('Store OST on channel even if dialed away')
        ost.append(rs)

        rs = MemSetting('conv.ost_direct', 'OST Direct',
                        RadioSettingValueInvertedBoolean(
                            not self._memobj.conv.ost_direct))
        ost.append(rs)

        def apply_ost(setting, index, which):
            try:
                mode, val, pol = self._parse_qtdqt(str(setting.value))
            except Exception:
                LOG.error('Failed to parse %r', str(setting.value))
                raise
            self._encode_tone(getattr(self._memobj.ost[index], which),
                              mode, val, pol)

        for i in range(16):
            name = MemSetting(
                'ost[%i].ost_name' % i, 'Name',
                RadioSettingValueString(
                    0, 10, str(self._memobj.ost[i].ost_name).rstrip('\xFF')))
            rxt = RadioSetting(
                'ost[%i].ost_dec_tone' % i, 'RX Tone',
                RadioSettingValueString(
                    0, 5,
                    self._format_qtdtq(self._memobj.ost[i].ost_dec_tone)))
            rxt.set_apply_callback(apply_ost, i, 'ost_dec_tone')
            rxt.set_doc('Receive squelch mode and value '
                        '(either like 103.5 or D023N)')
            txt = RadioSetting(
                'ost[%i].ost_enc_tone' % i, 'TX Tone',
                RadioSettingValueString(
                    0, 5,
                    self._format_qtdtq(self._memobj.ost[i].ost_enc_tone)))
            txt.set_apply_callback(apply_ost, i, 'ost_enc_tone')
            txt.set_doc('Transmit mode and value '
                        '(either like 103.5 or D023N)')
            sg = RadioSettingSubGroup('ost%i' % i, 'OST %i' % (i + 1))
            sg.append(name)
            sg.append(rxt)
            sg.append(txt)
            ost.append(sg)

    def _get_settings_format(self, optfeat1, optfeat2, scaninf):
        conv = self._memobj.conv

        if self.TYPE[0:1] == b"P":
            bsav = MemSetting(
                "conv.battery_save", "Battery Save",
                RadioSettingValueMap([(v, k) for k, v in BSAVE.items()],
                                     conv.battery_save))
            optfeat1.append(bsav)

        tot = MemSetting("conv.tot", "Time Out Timer (TOT)",
                         RadioSettingValueMap(
                             TOT, conv.tot))
        optfeat1.append(tot)

        totalert = MemSetting("conv.tot_alert", "TOT pre alert",
                              RadioSettingValueList(
                                  TOT_PRE,
                                  current_index=conv.tot_alert))
        optfeat1.append(totalert)

        totrekey = MemSetting("conv.tot_rekey", "TOT re-key time",
                              RadioSettingValueList(
                                  TOT_REKEY,
                                  current_index=conv.tot_rekey))
        optfeat1.append(totrekey)

        totreset = MemSetting("conv.tot_reset", "TOT reset time",
                              RadioSettingValueList(
                                  TOT_RESET,
                                  current_index=conv.tot_reset))
        optfeat1.append(totreset)

        c2t = MemSetting("conv.c2t", "Clear to Transpond",
                         RadioSettingValueInvertedBoolean(not conv.c2t))
        optfeat1.append(c2t)

        bled = MemSetting('conv.busy_led', 'Busy LED',
                          RadioSettingValueInvertedBoolean(
                              not bool(conv.busy_led)))
        optfeat1.append(bled)

        scled = MemSetting("conv.sel_call_alert_led",
                           "Selective Call Alert LED",
                           RadioSettingValueBoolean(conv.sel_call_alert_led))
        optfeat1.append(scled)

        pttr = MemSetting("conv.ptt_release_tone", "PTT Release Tone",
                          RadioSettingValueInvertedBoolean(
                              not conv.ptt_release_tone))
        optfeat2.append(pttr)

        inhta = MemSetting("conv.ptt_inhib_ta",
                           "PTT Inhibit ID in TA(TalkAround)",
                           RadioSettingValueInvertedBoolean(
                               not conv.ptt_inhib_ta))
        optfeat2.append(inhta)

        drdt = MemSetting("conv.sc_nfo_ddtime",
                          "Dropout Delay Time[sec]",
                          RadioSettingValueList(
                              DDT, current_index=conv.sc_nfo_ddtime))
        scaninf.append(drdt)

        dwet = MemSetting("conv.sc_nfo_dwell", "Dwell Time[sec]",
                          RadioSettingValueList(
                              DWT,
                              current_index=conv.sc_nfo_dwell))
        scaninf.append(dwet)

        rchd = MemSetting("conv.sc_nfo_rev_disp",
                          "Revert Channel Display",
                          RadioSettingValueInvertedBoolean(
                              not bool(conv.sc_nfo_rev_disp)))
        scaninf.append(rchd)

    def _get_settings_misc(self, optfeat2, dealer):
        msc = self._memobj.misc
        # PTT ID Section
        pdt = MemSetting("misc.ptt_id_type", "PTT ID Type",
                         RadioSettingValueList(
                             PIDT.values(),
                             current_index=msc.ptt_id_type))
        optfeat2.append(pdt)

        l1 = str(msc.line1).strip("\xFF")
        line1 = MemSetting("misc.line1", "Comment 1",
                           RadioSettingValueString(0, 32, l1,
                                                   mem_pad_char='\xFF'))
        dealer.append(line1)

        l2 = str(msc.line2).strip("\xFF")
        line2 = MemSetting("misc.line2", "Comment 2",
                           RadioSettingValueString(0, 32, l2,
                                                   mem_pad_char='\xFF'))
        dealer.append(line2)

    def _get_settings_keys(self, fkeys):
        keys = self._memobj.keys

        if self.TYPE[0] == ord("P"):
            model_keys = PORTABLE_KEYS
        else:
            model_keys = MOBILE_KEYS
        key_map = sorted([(v, k) for k, v in itertools.chain(
            KEYS.items(),
            model_keys.items())])

        mobile_keys = {
            'VOL_UP': 'Volume Up (Left Arrow Up)',
            'VOL_DOWN': 'Volume Down (Left Arrow Down)',
            'PF1': 'Group Up (Right Side Up Arrow)',
            'PF2': 'Group Down (Right Side Down Arrow)',
            'ORANGE': 'Foot Switch',
            'MON': 'MON',
            'SCN': 'SCN',
            'A': 'A',
            'LEFT': 'B',
            'RIGHT': 'C',
            'SIDE1': 'D',
        }
        portable_keys = {
            'PF1': 'Orange',
            'SIDE1': 'Side 1',
            'MON': 'Side 2',
            'SCN': 'S',
            'A': 'A',
            'LEFT': 'B',
            'RIGHT': 'C',
        }

        if self.TYPE[0] == ord("P"):
            knob_map = {'Channel Up/Down': 0xa1,
                        'Group Up/Down': 0xa2}
            knob = MemSetting("keys.kP_KNOB", "Knob",
                              RadioSettingValueMap(
                                  knob_map.items(),
                                  keys.kP_KNOB))
            fkeys.append(knob)

        if self.TYPE[0] == ord('M'):
            model_keys = mobile_keys
        else:
            model_keys = portable_keys

        for key, name in model_keys.items():
            rs = MemSetting("keys.k%s" % key, name,
                            RadioSettingValueMap(
                                key_map, getattr(keys, 'k%s' % key)))
            fkeys.append(rs)

        # TODO Make the following (keypad 0-9,*,#) contingent on variant.
        # Only concerned with TK-380 for now
        for key in '0123456789*#':
            xlate = {'*': 'ASTR', '#': 'POUND'}
            name = xlate.get(key, key)
            btn = MemSetting("keys.k%s" % name, "Keypad %s" % key,
                             RadioSettingValueMap(
                                 key_map, getattr(keys, 'k%s' % name)))
            fkeys.append(btn)

    def _get_settings_fsync(self, optfeat2):
        fsync = self._memobj.fleetsync

        # Extended Function Section
        dtxqt = MemSetting("fleetsync.data_tx_qt", "Data TX with QT/DQT",
                           RadioSettingValueInvertedBoolean(
                               not fsync.data_tx_qt))
        optfeat2.append(dtxqt)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        sett = self._memobj.settings
        passwd = self._memobj.settings.passwords

        optfeat1 = RadioSettingSubGroup("optfeat1", "Optional Features 1")
        optfeat2 = RadioSettingSubGroup("optfeat2", "Optional Features 2")
        optfeat = RadioSettingGroup("optfeat", "Optional Features",
                                    optfeat1, optfeat2)
        dealer = RadioSettingGroup("dealer", "Dealer Settings")
        fkeys = RadioSettingGroup("keys", "Keys")
        scaninf = RadioSettingGroup("scaninf", "Scan Information")
        dtmfset = RadioSettingGroup("dtmfset", "DTMF")
        ost = RadioSettingGroup("ost", "OST")
        groups = RadioSettingGroup("groups", "Groups")

        top = RadioSettings(optfeat, dealer, fkeys, scaninf,
                            dtmfset, ost, groups)

        self._get_settings_groups(groups)
        self._get_settings_format(optfeat1, optfeat2, scaninf)
        self._get_settings_ost(ost)
        self._get_settings_misc(optfeat2, dealer)
        self._get_settings_keys(fkeys)
        self._get_settings_fsync(optfeat2)
        # If user changes passwords to blank, which is actually x20 not xFF,
        # that sets impossible password.
        # Read-only to view unknown passwords only
        radiop = RadioSetting(
            "passwords.radio", "Radio Password",
            RadioSettingValueString(0, 6,
                                    str(passwd.radio).strip('\xFF')))
        radiop.value.set_mutable(False)
        optfeat1.append(radiop)

        datap = RadioSetting(
            "passwords.data", "Data Password",
            RadioSettingValueString(0, 6, str(passwd.data).strip('\xFF')))
        datap.value.set_mutable(False)
        optfeat1.append(datap)

        pom = MemSetting(
            "settings.poweronmesg", "Power on message",
            RadioSettingValueString(0, 12,
                                    str(sett.poweronmesg).strip('\xFF')))
        optfeat1.append(pom)

        sigtyp = MemSetting(
            "settings.signalling_type", "Signalling Type",
            RadioSettingValueList(SIG_TYPE,
                                  current_index=int(sett.signalling_type)))
        optfeat1.append(sigtyp)

        if self.TYPE[0] == "P":
            bw = MemSetting("settings.battery_warn", "Battery Warning",
                            RadioSettingValueInvertedBoolean(
                                sett.battery_warn))
            optfeat1.append(bw)

        if self.TYPE[0] == "M":
            ohd = MemSetting("settings.off_hook_decode", "Off Hook Decode",
                             RadioSettingValueInvertedBoolean(
                                 sett.off_hook_decode))
            optfeat1.append(ohd)

            ohha = MemSetting("settings.off_hook_horn_alert",
                              "Off Hook Horn Alert",
                              RadioSettingValueInvertedBoolean(
                                  sett.off_hook_horn_alert))
            optfeat1.append(ohha)

        minvol = MemSetting("settings.min_vol", "Minimum Volume",
                            RadioSettingValueList(
                                VOL, current_index=sett.min_vol))
        optfeat2.append(minvol)

        tv = int(sett.tone_vol)
        if tv == 255:
            tv = 32
        tvol = MemSetting("settings.tone_vol", "Tone Volume",
                          RadioSettingValueList(TVOL, current_index=tv))
        optfeat2.append(tvol)

        """sql = RadioSetting("settings.sql_level", "SQL Ref Level",
                           RadioSettingValueList(
                           SQL, SQL[int(sett.sql_level)]))
        optfeat1.append(sql)"""

        # Tone Volume Section
        ptone = MemSetting("settings.poweron_tone", "Power On Tone",
                           RadioSettingValueBoolean(sett.poweron_tone))
        optfeat2.append(ptone)

        wtone = MemSetting("settings.warn_tone", "Warning Tone",
                           RadioSettingValueBoolean(sett.warn_tone))
        optfeat2.append(wtone)

        ctone = MemSetting("settings.control_tone", "Control (Key) Tone",
                           RadioSettingValueBoolean(sett.control_tone))
        optfeat2.append(ctone)

        bot = str(sett.ptt_id_bot).strip("\xFF")
        pttbot = MemSetting("settings.ptt_id_bot", "PTT Begin of TX",
                            RadioSettingValueString(0, 16, bot,
                                                    mem_pad_char='\xFF'))
        optfeat2.append(pttbot)

        eot = str(sett.ptt_id_eot).strip("\xFF")
        ptteot = MemSetting("settings.ptt_id_eot", "PTT End of TX",
                            RadioSettingValueString(0, 16, eot,
                                                    mem_pad_char='\xFF'))
        optfeat2.append(ptteot)

        svp = str(sett.lastsoftversion).strip("\xFF")
        sver = RadioSetting("not.softver", "Last Used Software Version",
                            RadioSettingValueString(0, 5, svp,
                                                    mem_pad_char='\xFF'))
        sver.value.set_mutable(False)
        dealer.append(sver)

        try:
            vtmp = str(self.metadata.get('tkx80_ver', '(unknown)'))
        except AttributeError:
            vtmp = ''
        frev = RadioSetting("not.ver", "Radio Version",
                            RadioSettingValueString(0, 10, vtmp))
        frev.set_doc('Radio version (as downloaded)')
        frev.value.set_mutable(False)
        dealer.append(frev)

        panel = MemSetting("settings.panel_test", "Panel Test",
                           RadioSettingValueBoolean(sett.panel_test))
        optfeat2.append(panel)

        ptun = MemSetting("settings.panel_tuning", "Panel Tuning",
                          RadioSettingValueBoolean(sett.panel_tuning))
        optfeat2.append(ptun)

        fmw = MemSetting("settings.firmware_prog", "Firmware Programming",
                         RadioSettingValueBoolean(sett.firmware_prog))
        optfeat2.append(fmw)

        clone = MemSetting("settings.clone", "Allow clone",
                           RadioSettingValueBoolean(sett.clone))
        optfeat2.append(clone)

        sprog = MemSetting("settings.self_prog", "Self Programming",
                           RadioSettingValueBoolean(sett.self_prog))
        optfeat2.append(sprog)

        # Logic Signal Section
        sqlt = MemSetting("settings.sq_logic_type", "Squelch Logic Type",
                          RadioSettingValueList(
                              SLT.values(),
                              current_index=sett.sq_logic_type))
        optfeat2.append(sqlt)

        sqls = MemSetting("settings.sq_logic_sig", "Squelch Logic Signal",
                          RadioSettingValueList(
                              SLS.values(),
                              current_index=sett.sq_logic_sig))
        optfeat2.append(sqls)

        aclt = MemSetting("settings.access_log_type", "Access Logic Type",
                          RadioSettingValueList(
                              ALT.values(),
                              current_index=sett.access_log_type))
        optfeat2.append(aclt)

        acls = MemSetting("settings.access_log_sig", "Access Logic Signal",
                          RadioSettingValueList(
                              ALS.values(),
                              current_index=sett.access_log_sig))
        optfeat2.append(acls)

        # DTMF Settings
        # Decode Section
        deccode = str(sett.dtmf_prim_code).strip("\xFF")
        decpc = MemSetting("settings.dtmf_prim_code", "Decode Primary Code",
                           RadioSettingValueString(0, 7, deccode))
        dtmfset.append(decpc)

        deccode = str(sett.dtmf_sec_code).strip("\xFF")
        decpc = MemSetting("settings.dtmf_sec_code", "Decode Secondary Code",
                           RadioSettingValueString(0, 7, deccode))
        dtmfset.append(decpc)

        deccode = str(sett.dtmf_DBD_code).strip("\xFF")
        decpc = MemSetting("settings.dtmf_DBD_code",
                           "Decode Dead Beat Disable Code",
                           RadioSettingValueString(0, 7, deccode,
                                                   mem_pad_char='\xFF'))
        dtmfset.append(decpc)

        return top

    def _set_settings_groups(self, settings):
        group_index = {}
        unused_slots = []

        # Survey the currently-mapped groups
        for i in range(250):
            if self._memobj.groups[i].number < 0xFF:
                group_index[int(self._memobj.groups[i].number)] = i
            else:
                unused_slots.append(i)

        allocated = False
        for i in range(250):
            group_number = i + 1
            enable_setting = settings.get('group-%i-enable' % group_number)
            name_setting = settings.get('group-%i-name' % group_number)
            try:
                group = self._memobj.groups[group_index[group_number]]
            except KeyError:
                if enable_setting and enable_setting.value:
                    slot = unused_slots.pop(0)
                    LOG.debug('Allocating group slot %i for group %i',
                              slot, group_number)
                    group = self._memobj.groups[slot]
                    group.number = group_number
                    group.channels = 0
                    group.name = (name_setting and str(name_setting.value) or
                                  str(group_number).ljust(10))
                    allocated = True
                group = None
            if enable_setting and not enable_setting.value and group:
                # Group is allocated, UI asked to disable it
                group.fill_raw(b'\xFF')
            elif group and name_setting:
                # Group is allocated, set name
                group.name = name_setting.value
        if allocated:
            LOG.debug('Compacting group mappings after new allocation')
            self._compact_mappings()

    def set_settings(self, settings):
        # All the actual settings we care about are MemSetting and can be
        # direct applied.
        all_other_settings = settings.apply_to(self._memobj)
        # This should just be group geometry settings at this point
        other_settings = {s.get_name(): s for s in all_other_settings}
        self._set_settings_groups(other_settings)
        for setting in all_other_settings:
            if setting.has_apply_callback():
                setting.run_apply_callback()

    def _get_memory_base(self, mem, _mem):
        mem.number = int(_mem.number)
        mem.freq = int(_mem.rxfreq) * self._freqmult
        if _mem.txfreq.get_raw()[0] == 0xFF:
            mem.offset = 0
            mem.duplex = "off"
        else:
            chirp_common.split_to_offset(
                mem, mem.freq, int(_mem.txfreq) * self._freqmult)

        mem.name = str(_mem.name).rstrip()

        txtone = self._decode_tone(_mem.tx_tone)
        rxtone = self._decode_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)
        if self.POWER_LEVELS:
            mem.power = self.POWER_LEVELS[_mem.power]

    def _set_memory_base(self, mem, _mem):
        _mem.number = mem.number

        _mem.rxfreq = mem.freq // self._freqmult

        _mem.unknown_rx = 0x3
        _mem.unknown_tx = 0x3

        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) // self._freqmult
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) // self._freqmult
        elif mem.duplex == "off":
            _mem.txfreq.fill_raw(b'\xFF')
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset // self._freqmult
        else:
            _mem.txfreq = mem.freq // self._freqmult

        step_lookup = {
            12.5: 0x5,
            6.25: 0x2,
            5.0: 0x1,
            2.5: 0x0,
        }
        _mem.rx_step = choose_step(step_lookup, int(_mem.rxfreq) * 10)
        _mem.tx_step = choose_step(step_lookup, int(_mem.txfreq) * 10)

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.tx_tone, txmode, txtone, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxtone, rxpol)

        _namelength = self.get_features().valid_name_length
        _mem.name = mem.name.ljust(_namelength)

        if self.POWER_LEVELS:
            try:
                _mem.power = self.POWER_LEVELS.index(mem.power)
            except ValueError:
                _mem.power = self.POWER_LEVELS[0]


class TKx80Group:
    def __init__(self, parent, group):
        self._parent = parent
        self._group = int(group)

    @property
    def group(self):
        return self._group

    @property
    def _memobj(self):
        return self._parent._memobj

    def load_mmap(self, filename):
        self._parent.load_mmap(filename)

    def _compact_mappings(self):
        self._parent._compact_mappings()

    def get_sub_devices(self):
        return []

    def get_features(self):
        rf = self._parent.get_features()
        rf.has_sub_devices = False
        rf.memory_bounds = (1, 250)
        return rf

    def get_raw_memory(self, number):
        """Return a raw representation of the memory object, which
        is very helpful for development"""
        try:
            mapping = self._parent._get_memory_mapping(self.group, number)
        except IndexError:
            return 'Memory not set'
        return repr(self._memobj.memory[mapping.index])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        try:
            mapping = self._parent._get_memory_mapping(self.group, number)
        except IndexError:
            mem.empty = True
            return mem

        _mem = self._memobj.memory[mapping.index]

        self._get_memory_base(mem, _mem)
        mem.mode = MODES[_mem.wide]
        mem.skip = self._get_scan(mapping.index)

        mem.extra = RadioSettingGroup("extra", "Extra")

        bs = MemSetting("beat_shift", "Beat shift",
                        RadioSettingValueInvertedBoolean(
                            not bool(_mem.beat_shift)))
        mem.extra.append(bs)

        cp = MemSetting("compander", "Compander",
                        RadioSettingValueInvertedBoolean(
                            not bool(_mem.compander)))
        mem.extra.append(cp)

        pttid = MemSetting("ptt_id", "PTTID",
                           RadioSettingValueInvertedBoolean(not _mem.ptt_id))
        mem.extra.append(pttid)

        if _mem.busy_lock == 1:
            index = 0
        elif _mem.busy_lock_opt == 1:
            index = 2
        elif _mem.busy_lock_opt == 0:
            index = 3
        else:
            index = 1
        bl = RadioSetting("busy_lock", "Busy Channel lock",
                          RadioSettingValueList(BCL_OPTS, current_index=index))

        mem.extra.append(bl)

        return mem

    def set_memory(self, mem):
        try:
            mapping = self._parent._get_memory_mapping(self.group, mem.number,
                                                       allocate=True)
        except IndexError as e:
            # Out of memory
            raise errors.RadioError(str(e))

        _mem = self._memobj.memory[mapping.index]

        if mem.empty:
            self._delete_memory_mapping(self.group, mem.number)
            return

        self._set_memory_base(mem, _mem)

        _mem.wide = MODES.index(mem.mode)
        self._set_scan(mapping.index, mem.skip)

        _mem.number = mem.number
        _mem.group = self.group

        if mem.extra:
            bcl = int(mem.extra['busy_lock'].value)
            if bcl == 0:
                _mem.busy_lock = 1
                _mem.busy_lock_opt = 3
            elif bcl == 2:
                _mem.busy_lock = 0
                _mem.busy_lock_opt = 1
            elif bcl == 3:
                _mem.busy_lock = 0
                _mem.busy_lock_opt = 0
            elif bcl == 1:
                _mem.busy_lock = 0
                _mem.busy_lock_opt = 3

            # extra settings
            mem.extra['ptt_id'].apply_to_memobj(_mem)
            mem.extra['compander'].apply_to_memobj(_mem)
            mem.extra['beat_shift'].apply_to_memobj(_mem)

        return mem


@directory.register
class TK280_Radios(KenwoodTKx80):
    """Kenwood TK-280 Radio"""
    MODEL = "TK-280"
    TYPE = b"P0280"
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                    chirp_common.PowerLevel("High", watts=5)]
    # VARIANTS = {
    #    # VERIFIED variant. Range expanded for ham bands. Orig: 146, 174
    #    b"P0280\x04\xFF":    (250, 144, 174, "K Non-Keypad Model"),
    #    b"P0280\x05\xFF":    (250, 136, 162, "K2 Non-Keypad Model"),
    #    # Range expanded for ham bands. Orig: 146, 174
    #    b"P0280\xFF\xFF":    (250, 144, 174, "K3 Keypad Model"),
    #    b"P0280\xFF\xFF":    (250, 136, 162, "K4 Keypad Model"),
    #    }
    _range = [(136000000, 174000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (2.5, 6.25)


@directory.register
class TK380_Radios(KenwoodTKx80):
    """Kenwood TK-380 Radio """
    MODEL = "TK-380"
    TYPE = b"P0380"
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                    chirp_common.PowerLevel("High", watts=4)]
    # VARIANTS = {
    #    # Range expanded for ham bands. Orig: 450, 490
    #    b"P0380\x06\xFF":    (250, 420, 490, "K Non-Keypad Model"),
    #    # Range expanded for ham bands. Orig: 470, 512
    #    b"P0380\x07\xFF":    (250, 420, 512, "K2 Non-Keypad Model"),
    #    # Range expanded for ham bands. Orig: 400, 430
    #    b"P0380\x08\xFF":    (250, 400, 450, "K3 Non-Keypad Model"),
    #    # VERIFIED variant. Range expanded for ham bands. Orig: 450, 490
    #    b"P0380\x0a\xFF":    (250, 420, 490, "K4 Keypad Model"),
    #    # Range expanded for ham bands. Orig: 400, 430
    #    b"P0380\xFF\xFF":    (250, 400, 450, "K6 Keypad Model"),
    #    # Range expanded for ham bands. Orig: 470, 520
    #    b"P0380\xFF\xFF":    (250, 420, 520, "K5 Keypad Model"),
    #    }
    _range = [(400000000, 520000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (6.25,)


@directory.register
class TK780_Radios(KenwoodTKx80):
    """Kenwood TK-780 Radio """
    MODEL = "TK-780"
    TYPE = b"M0780"
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                    chirp_common.PowerLevel("High", watts=25)]
    # VARIANTS = {
    #    # VERIFIED variant. #Range expanded for ham bands. Orig: 146, 174
    #    b"M0780\x04\xFF":    (250, 144, 174, "K"),
    #    b"M0780\x05\xFF":    (250, 136, 174, "K2"),
    #    }
    _range = [(136000000, 174000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (2.5, 6.25)


@directory.register
class TK880_Radios(KenwoodTKx80):
    """Kenwood TK-880 Radio """
    MODEL = "TK-880"
    TYPE = b"M0880"
    # VARIANTS = {
    #     # VERIFIED variant. #Range expanded for ham bands. Orig: 450, 490
    #     b"M0880\x06\xFF":    (250, 420, 490, "K"),
    #     # Range expanded for ham bands. Orig: 485, 512
    #     b"M0880\x07\xFF":    (250, 420, 512, "K2"),
    #     # Range expanded for ham bands. Orig: 400, 430
    #     b"M0880\x08\xFF":    (250, 400, 450, "K3"),
    #     }
    _range = [(400000000, 520000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (6.25, 12.5)
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                    chirp_common.PowerLevel("High", watts=25)]
