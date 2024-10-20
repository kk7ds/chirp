# Copyright 2021-2023 Jim Unroe <rock.unroe@gmail.com>
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

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];       // RX Frequency           0-3
  lbcd txfreq[4];       // TX Frequency           4-7
  ul16 rx_tone;         // PL/DPL Decode          8-9
  ul16 tx_tone;         // PL/DPL Encode          A-B
  u8 unknown1:3,        //                        C
     bcl:2,             // Busy Lock
     unknown2:3;
  u8 unknown3:2,        //                        D
     highpower:1,       // Power Level
     wide:1,            // Bandwidth
     unknown4:4;
  u8 unknown7:1,        //                        E
     scramble_type:3,   // Scramble Type
     unknown5:4;
  u8 unknown6:5,
     scramble_type2:3;  // Scramble Type 2        F
} memory[%d];

#seekto 0x011D;
struct {
  u8 unused:4,
     pf1:4;             // Programmable Function Key 1
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;      // Scramble Enable
  u8 unknown1[2];
  u8 voice;             // Voice Annunciation
  u8 tot;               // Time-out Timer
  u8 totalert;          // Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;           // Squelch Level
  u8 save;              // Battery Saver
  u8 unknown3[3];
  u8 use_vox;           // VOX Enable
  u8 vox;               // VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[2];       // SCAN_ADD
"""

MEM_FORMAT_RB17A = """
struct memory {
  lbcd rxfreq[4];      // 0-3
  lbcd txfreq[4];      // 4-7
  ul16 rx_tone;        // 8-9
  ul16 tx_tone;        // A-B
  u8 unknown1:1,       // C
     compander:1,      // Compand
     bcl:2,            // Busy Channel Lock-out
     cdcss:1,          // Cdcss Mode
     scramble_type:3;  // Scramble Type
  u8 unknown2:4,       // D
     middlepower:1,    // Power Level-Middle
     unknown3:1,       //
     highpower:1,      // Power Level-High/Low
     wide:1;           // Bandwidth
  u8 unknown4;         // E
  u8 unknown5;         // F
};

#seekto 0x0010;
  struct memory lomems[16];

#seekto 0x0200;
  struct memory himems[14];

#seekto 0x011D;
struct {
  u8 pf1;              // 011D PF1 Key
  u8 topkey;           // 011E Top Key
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;     // 012C Scramble Enable
  u8 channel;          // 012D Channel Number
  u8 alarm;            // 012E Alarm Type
  u8 voice;            // 012F Voice Annunciation
  u8 tot;              // 0130 Time-out Timer
  u8 totalert;         // 0131 Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;          // 0134 Squelch Level
  u8 save;             // 0135 Battery Saver
  u8 unknown3[3];
  u8 use_vox;          // 0139 VOX Enable
  u8 vox;              // 013A VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[4];       // Scan Add
"""

MEM_FORMAT_RB26 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     unknown1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     bcl:1,            // Busy Lock  OFF=0 ON=1
     unknown2:3;       //
  u8 reserved[3];      // Reserved               D-F
} memory[30];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     chnumberd:1,      // Channel Number Disable
     gain:1,           // MIC Gain
     savem:1,          // Battery Save Mode
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:1,          // Voice Prompts
     unknown_2:1;      //
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unknown_3[3];     //                        003D-003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_6;        //                        005D
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 warn;             // Warn Mode              006D
  u8 pf1;              // Key Set PF1            006E
  u8 pf2;              // Key Set PF2            006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_8;        //                        007D
  u8 tail;             // QT/DQT Tail(inverted)  007E
  u8 tailmode;         // QT/DQT Tail Mode       007F
} settings;

#seekto 0x01F0;
u8 skipflags[4];       // Scan Add

#seekto 0x029F;
struct {
  u8 chnumber;         // Channel Number         029F
} settings2;

#seekto 0x031D;
struct {
  u8 unused:7,         //                        031D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              031E
  u8 voxd;             // Vox Delay              031F
} settings3;
"""

MEM_FORMAT_RT76 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     hop:1,            // Frequency Hop
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     scramble:4;       // Scramble
  u8 reserved[3];      // Reserved               D-F
} memory[30];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     chnumberd:1,      // Channel Number Disable
     gain:1,           // MIC Gain                                 ---
     savem:1,          // Battery Save Mode                        ---
     save:1,           // Battery Save                             ---
     beep:1,           // Beep                                     ---
     voice:2;          // Voice Prompts                            ---
  u8 squelch;          // Squelch                002E              ---
  u8 tot;              // Time-out Timer         002F              ---
  u8 channel_4[13];    //                        0030-003C
  u8 unused:7,         //                        003D
     vox:1;            // Vox                                      ---
  u8 voxl;             // Vox Level              003E              ---
  u8 voxd;             // Vox Delay              003F              ---
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 chnumber;         // Channel Number         005D              ---
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 warn;             //                        006D              ---
  u8 scan;             //                        006E
  u8 unknown_8;        //                        006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_9[3];     //                        007D-007F
  u8 channel_9[13];    //                        0080-008C
  u8 unknown_a;        //                        008D
  u8 tailmode;         // DCS Tail Mode          008E
  u8 hop;              // Hop Mode               008F
} settings;

#seekto 0x004E;
u8 skipflags[2];       // SCAN_ADD
"""

MEM_FORMAT_RT29 = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];       // RX Frequency           0-3
  lbcd txfreq[4];       // TX Frequency           4-7
  ul16 rx_tone;         // PL/DPL Decode          8-9
  ul16 tx_tone;         // PL/DPL Encode          A-B
  u8 unknown1:2,        //                        C
     compander:1,       // Compander
     bcl:2,             // Busy Lock
     unknown2:3;
  u8 unknown3:1,        //                        D
     txpower:2,         // Power Level
     wide:1,            // Bandwidth
     unknown4:3,
     cdcss:1;           // Cdcss Mode
  u8 unknown5;          //                        E
  u8 unknown6:5,
     scramble_type:3;   // Scramble Type          F
} memory[16];

#seekto 0x011D;
struct {
  u8 unused1:4,
     pf1:4;             // Programmable Function Key 1
  u8 unused2:4,
     pf2:4;             // Programmable Function Key 2
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;      // Scramble Enable
  u8 unknown1[2];
  u8 voice;             // Voice Annunciation
  u8 tot;               // Time-out Timer
  u8 totalert;          // Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;           // Squelch Level
  u8 save;              // Battery Saver
  u8 unknown3[3];
  u8 use_vox;           // VOX Enable
  u8 vox;               // VOX Gain
  u8 voxd;              // Vox Delay
} settings;

#seekto 0x017E;
u8 skipflags[2];       // SCAN_ADD

#seekto 0x01B8;
u8 fingerprint[5];     // Fingerprint
"""

MEM_FORMAT_RT19 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 function:2,       // Function               C
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     unknown_1:1,      //
     scramble_type:3;  // Scramble #
  u8 reserved[3];      // Reserved               D-F
} memory[%d];

#seekto 0x002D;
struct {
  u8 bootsel:1,        // Boot Select            002D
     unknown_1:2,      //
     savem:1,          // Battery Save Mode
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:2;          // Voice Prompts
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unused:7,         //                        003D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              003E
  u8 voxd;             // Vox Delay              003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_6;        //                        005D
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 voicel:4,         // Voice Level            006D
     unknown_9:3,      //
     warn:1;           // Warn Mode
} settings;

#seekto 0x%X;
struct {
  u8 freqhop;          // Frequency Hop
} freqhops[%d];
"""

MEM_FORMAT_RT40B = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     unknown1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     unknown2:4;       //
  u8 reserved[3];      // Reserved               D-F
} memory[%d];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     unknown_2:1,      //
     savem:2,          // Battery Save Mode
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:2;          // Voice Prompts
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unknown_3:7,      //                        003D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              003E
  u8 voxd;             // Vox Delay              003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4[2];     //                        004D-004F
  u8 channel_6[13];    //                        0050-005C
  u8 chnumber;         // Channel Number         005D
  u8 unknown_5[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 unknown_6:7,      //                        006D
     pttstone:1;       // PTT Start Tone
  u8 unknown_7:7,      //                        006E
     pttetone:1;       // PTT End Tone
} settings;

#seekto 0x00AD;
u8 skipflags[3];       // SCAN_ADD
"""

MEM_FORMAT_RB28B = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     unused_1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     bcl:1,            // Busy Lock
     unused_2:3;       //
  u8 reserved[3];      // Reserved               D-F
} memory[30];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     unknown_2:1,      //
     gain:1,           // MIC Gain
     savem:1,          // Battery Save Mode
     save:1,           // Battery Save
     voice:1,          // Voice Prompts
     beep:1,           // Beep
     unused_3:1;       // Power on Type
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unused_3d:7,       //                        003D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              003E
  u8 voxd;             // Vox Delay              003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_3[3];     //                        004D-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_4[3];     //                        005D-005F
  u8 channel_7[13];    //                        0060-006C
  u8 volume;           // Volume                 006D
  u8 pfkey_lt;         // Key Set <              006E
  u8 pfkey_gt;         // Key Set >              006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_5;        //                        007D
  u8 unused_7e6:7,     //                        007E
     pwrontype:1;      // Power on Type
  u8 unused_7f:7,       //                        007F
     keylock:1;        // Key Lock
  u8 channel_9[13];    //                        0080-008C
  u8 unknown_7;        //                        008D
  u8 chnumber;         // Channel                008E
} settings;
"""

MEM_FORMAT_RT86 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 audio:2,          // Audio                  C
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     bcl:1,            // Busy Lock  OFF=0 ON=1
     scramble_type:3;  // Scramble
  u8 reserved[3];      // Reserved               D-F
} memory[16];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     chnumberd:1,      // Channel Number Disable
     gain:1,           // MIC Gain
     savem:1,          // Battery Save Mode
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:1,          // Voice Prompts
     unknown_2:1;      //
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unused_3d:7,      //                        003D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              003E
  u8 voxd;             // Vox Delay              003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_6;        //                        005D
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 warn;             // Warn Mode              006D
  u8 pf1;              // Key Set PF1            006E
  u8 pf2;              // Key Set PF2            006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_8;        //                        007D
  u8 tail;             // QT/DQT Tail(inverted)  007E
  u8 tailmode;         // QT/DQT Tail Mode       007F
  u8 channel_9[13];    //                        0080-008C
  u8 unknown_9[3];     //                        008D-008F
  u8 channel_10[13];   //                        0090-009C
  u8 unknown_10[3];    //                        009D-009F
  u8 channel_11[13];   //                        00A0-00AC
  u8 unknown_11[2];    //                        00AD-00AE
  u8 chnumber;         // Channel Number         00AF
} settings;

#seekto 0x004E;
u8 skipflags[2];       // SCAN_ADD

#seekto 0x0100;
struct {
  u8 freqhop;          // Frequency Hop
} freqhops[16];
"""

CMD_ACK = b"\x06"

ALARM_LIST = ["Local Alarm", "Remote Alarm"]
BCL_LIST = ["Off", "Carrier", "QT/DQT"]
BOOTSEL_LIST = ["Channel Mode", "Voice Mode"]
CDCSS_LIST = ["Normal Code", "Special Code 2", "Special Code 1"]
CDCSS2_LIST = ["Normal Code", "Special Code"]  # RT29 UHF and RT29 VHF
FREQHOP_LIST = ["Off", "Hopping 1", "Hopping 2", "Hopping 3"]
FUNCTION_LIST = ["Off", "Scramble", "Compand"]
GAIN_LIST = ["Standard", "Enhanced"]
HOP_LIST = ["Mode A", "Mode B", "Mode C", "Mode D", "Mode E"]
HOP86_LIST = ["Off", "Mode 1", "Mode 2", "Mode 3", "Mode 4"]
PFKEY_LIST = ["None", "Monitor", "Lamp", "Warn", "VOX", "VOX Delay",
              "Key Lock", "Scan"]
PFKEY28B_LIST = ["None", "Scan", "Warn", "TX Power", "Monitor"]
PFKEY86_LIST = ["None", "Monitor", "Lamp", "Warn", "VOX", "VOX Delay",
                "Key Lock", "TX Power", "Scan"]
PFKEY89_LIST = PFKEY_LIST + ["Bluetooth ON/OFF"]
POT_LIST = ["Channel Type", "Volume Type"]
SAVE_LIST = ["Standard", "Super"]
SAVEM_LIST = ["1-5", "1-8", "1-10", "1-15"]
SCRAMBLE_LIST = ["OFF"] + ["%s" % x for x in range(1, 9)]
SPECIAL_LIST = ["Standard", "Special"]
TAIL_LIST = ["134.4 Hz", "55 Hz"]
TIMEOUTTIMER_LIST = ["Off"] + ["%s seconds" % x for x in range(15, 615, 15)]
TOTALERT_LIST = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOICE_LIST2 = ["Off", "English"]
VOICE_LIST3 = VOICE_LIST2 + ["Chinese"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
VOXL_LIST = ["OFF"] + ["%s" % x for x in range(1, 10)]
WARN_LIST = ["OFF", "Native Warn", "Remote Warn"]
PF1_CHOICES = ["None", "Monitor", "Scan", "Scramble", "Alarm"]
PF1_VALUES = [0x0F, 0x04, 0x06, 0x08, 0x0C]
PF1_17A_CHOICES = ["None", "Monitor", "Scan", "Scramble"]
PF1_17A_VALUES = [0x0F, 0x04, 0x06, 0x08]
PFKEY23_CHOICES = ["None", "Monitor", "Warn", "VOX", "VOX Delay", "Scan"]
PFKEY23_VALUES = [0x00, 0x01, 0x03, 0x04, 0x05, 0x07]
PFKEY_CHOICES = ["None", "Monitor", "Scan", "Scramble", "VOX", "Alarm"]
PFKEY_VALUES = [0x0F, 0x04, 0x06, 0x08, 0x09, 0x0A]
TOPKEY_CHOICES = ["None", "Alarming"]
TOPKEY_VALUES = [0xFF, 0x0C]

GMRS_FREQS1 = [462562500, 462587500, 462612500, 462637500, 462662500,
               462687500, 462712500]
GMRS_FREQS2 = [467562500, 467587500, 467612500, 467637500, 467662500,
               467687500, 467712500]
GMRS_FREQS3 = [462550000, 462575000, 462600000, 462625000, 462650000,
               462675000, 462700000, 462725000]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2

FRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3

PMR_FREQS1 = [446006250, 446018750, 446031250, 446043750, 446056250,
              446068750, 446081250, 446093750]
PMR_FREQS2 = [446106250, 446118750, 446131250, 446143750, 446156250,
              446168750, 446181250, 446193750]
PMR_FREQS = PMR_FREQS1 + PMR_FREQS2

DTCS_EXTRA = tuple(sorted(chirp_common.DTCS_CODES + (645,)))


def _enter_programming_mode(radio):
    serial = radio.pipe

    _magic = radio._magic

    try:
        serial.write(_magic)
        if radio._echo:
            chew = serial.read(len(_magic))  # Chew the echo
        for i in range(1, 5):
            ack = serial.read(1)
            if ack == CMD_ACK:
                break
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x02")
        if radio._echo:
            serial.read(1)  # Chew the echo
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    itis = False
    for fp in radio._fingerprint:
        if fp in ident:
            # got it!
            itis = True

            break

    if itis is False:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        if radio._echo:
            serial.read(1)  # Chew the echo
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
        if radio._echo:
            chew = serial.read(1)  # Chew the echo
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        if radio._echo:
            serial.read(4)  # Chew the echo
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        if block_addr != 0 or radio._ack_1st_block:
            serial.write(CMD_ACK)
            if radio._echo:
                serial.read(1)  # Chew the echo
            ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if block_addr != 0 or radio._ack_1st_block:
        if ack != CMD_ACK:
            raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if radio._echo:
            serial.read(4 + len(data))  # Chew the echo
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
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
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x01B8:0x01BE]

    return rid.startswith(b"P3207")


@directory.register
class RT21Radio(chirp_common.CloneModeRadio):
    """RETEVIS RT21"""
    VENDOR = "Retevis"
    MODEL = "RT21"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x10
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = sorted(chirp_common.DTCS_CODES + (17, 50, 645))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.50),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    VALID_BANDS = [(400000000, 480000000)]

    _magic = b"PRMZUNE"
    _fingerprint = [b"P3207s\xF8\xFF", ]
    _upper = 16
    _mem_params = (_upper,  # number of channels
                   )
    _ack_1st_block = True
    _skipflags = True
    _reserved = False
    _mask = 0x2000  # bit mask to identify DTCS tone decoding is used
    _gmrs = _frs = _pmr = False
    _echo = False

    _ranges = [
               (0x0000, 0x0400),
              ]
    _memsize = 0x0400

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
        if self.MODEL == "RT76" or \
                self.MODEL == "RT19" or self.MODEL == "RT619" or \
                self.MODEL == "RB28B" or self.MODEL == "RB628B":
            rf.valid_skips = []
        else:
            rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = self.VALID_BANDS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params,
                                     self._mmap)

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

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol

        tpol = False
        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > self._mask:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        rpol = False
        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > self._mask:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        # always set it even if no dtcs is used
        mem.dtcs_polarity = "%s%s" % (tpol or "N", rpol or "N")

        LOG.debug("Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.tx_tone, rxmode, _mem.rx_tone))

    def get_memory(self, number):
        if self._skipflags:
            bitpos = (1 << ((number - 1) % 8))
            bytepos = ((number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        mem = chirp_common.Memory()

        mem.number = number

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[number - 1]
            else:
                _mem = self._memobj.himems[number - 17]
        else:
            _mem = self._memobj.memory[number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw(asbytes=False)

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        self._get_tone(_mem, mem)

        if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            # set the power level
            if _mem.txpower == self.TXPOWER_LOW:
                mem.power = self.POWER_LEVELS[2]
            elif _mem.txpower == self.TXPOWER_MED:
                mem.power = self.POWER_LEVELS[1]
            elif _mem.txpower == self.TXPOWER_HIGH:
                mem.power = self.POWER_LEVELS[0]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.txpower))
        else:
            mem.power = self.POWER_LEVELS[1 - _mem.highpower]

        if self._skipflags:
            mem.skip = "" if (_skp & bitpos) else "S"
            LOG.debug("mem.skip %s" % mem.skip)

        mem.extra = RadioSettingGroup("Extra", "extra")

        if self.MODEL == "RT21" or self.MODEL == "RB17A" or \
                self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF" or \
                self.MODEL == "RT21V":
            rs = RadioSettingValueList(BCL_LIST, current_index=_mem.bcl)
            rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
            rset.set_doc('QT is the same as Tone/CTCSS, '
                         'DQT is the same as DTCS/DCS')
            mem.extra.append(rset)

            rs = RadioSettingValueInteger(1, 8, _mem.scramble_type + 1)
            rset = RadioSetting("scramble_type", "Scramble Type", rs)
            mem.extra.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(
                    CDCSS_LIST, current_index=_mem.cdcss)
                rset = RadioSetting("cdcss", "Cdcss Mode", rs)
                mem.extra.append(rset)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                rs = RadioSettingValueList(CDCSS2_LIST,
                                           current_index=_mem.cdcss)
                rset = RadioSetting("cdcss", "Cdcss Mode", rs)
                mem.extra.append(rset)

            if self.MODEL == "RB17A" or self.MODEL == "RT29_UHF" or \
                    self.MODEL == "RT29_VHF":
                rs = RadioSettingValueBoolean(_mem.compander)
                rset = RadioSetting("compander", "Compander", rs)
                mem.extra.append(rset)

        if self.MODEL == "RB26" or self.MODEL == "RT76" \
                or self.MODEL == "RB23" or self.MODEL == "AR-63" \
                or self.MODEL == "RB89":
            if self.MODEL == "RB26" or self.MODEL == "RB23" \
                    or self.MODEL == "RB89":
                rs = RadioSettingValueBoolean(_mem.bcl)
                rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
                mem.extra.append(rset)

            rs = RadioSettingValueBoolean(_mem.compander)
            rset = RadioSetting("compander", "Compander", rs)
            mem.extra.append(rset)

            if self.MODEL == "AR-63":
                rs = RadioSettingValueList(SCRAMBLE_LIST,
                                           current_index=_mem.scramble)
                rset = RadioSetting("scramble", "Scramble", rs)
                mem.extra.append(rset)

                rs = RadioSettingValueBoolean(not _mem.hop)
                rset = RadioSetting("hop", "Frequency Hop", rs)
                mem.extra.append(rset)

        if self.MODEL == "RT19" or self.MODEL == "RT619":
            _freqhops = self._memobj.freqhops[number - 1]

            rs = RadioSettingValueList(FUNCTION_LIST,
                                       current_index=_mem.function)
            rset = RadioSetting("function", "Function", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueInteger(1, 8, _mem.scramble_type + 1)
            rset = RadioSetting("scramble_type", "Scramble Type", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueList(FREQHOP_LIST,
                                       current_index=_freqhops.freqhop)
            rset = RadioSetting("freqhop", "Frequency Hop", rs)
            mem.extra.append(rset)

        if self.MODEL == "RT40B":
            rs = RadioSettingValueBoolean(_mem.compander)
            rset = RadioSetting("compander", "Compander", rs)
            mem.extra.append(rset)

        if self.MODEL == "RB28B" or self.MODEL == "RB628B":
            rs = RadioSettingValueBoolean(_mem.compander)
            rset = RadioSetting("compander", "Compander", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueBoolean(_mem.bcl)
            rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
            mem.extra.append(rset)

        if self.MODEL == "RT86":
            _freqhops = self._memobj.freqhops[number - 1]

            rs = RadioSettingValueList(FUNCTION_LIST,
                                       current_index=_mem.audio)
            rset = RadioSetting("audio", "Audio", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueInteger(1, 8, _mem.scramble_type + 1)
            rset = RadioSetting("scramble_type", "Scramble", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueList(HOP86_LIST,
                                       current_index=_freqhops.freqhop)
            rset = RadioSetting("freqhop", "Frequency Hop", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueBoolean(_mem.bcl)
            rset = RadioSetting("bcl", "Busy Lock", rs)
            mem.extra.append(rset)

        immutable = []

        if self._frs:
            if mem.number >= 1 and mem.number <= 22:
                FRS_FREQ = FRS_FREQS[mem.number - 1]
                mem.freq = FRS_FREQ
                mem.duplex == ''
                mem.offset = 0
                mem.mode = "NFM"
                if mem.number >= 8 and mem.number <= 14:
                    mem.power = self.POWER_LEVELS[1]
                    immutable = ["empty", "freq", "duplex", "offset", "mode",
                                 "power"]
                else:
                    immutable = ["empty", "freq", "duplex", "offset", "mode"]
        elif self._pmr:
            if mem.number >= 1 and mem.number <= 16:
                PMR_FREQ = PMR_FREQS[mem.number - 1]
                mem.freq = PMR_FREQ
                mem.duplex = ''
                mem.offset = 0
                mem.mode = "NFM"
                mem.power = self.POWER_LEVELS[1]
                immutable = ["empty", "freq", "duplex", "offset", "mode",
                             "power"]
        elif self._gmrs:
            if mem.number >= 1 and mem.number <= 30:
                GMRS_FREQ = GMRS_FREQS[mem.number - 1]
                mem.freq = GMRS_FREQ
                immutable = ["empty", "freq"]
            if mem.number >= 1 and mem.number <= 7:
                mem.duplex == ''
                mem.offset = 0
                immutable += ["duplex", "offset"]
            elif mem.number >= 8 and mem.number <= 14:
                mem.duplex == ''
                mem.offset = 0
                mem.mode = "NFM"
                mem.power = self.POWER_LEVELS[1]
                immutable += ["duplex", "offset", "mode", "power"]
            elif mem.number >= 15 and mem.number <= 22:
                mem.duplex == ''
                mem.offset = 0
                immutable += ["duplex", "offset"]
            elif mem.number >= 23 and mem.number <= 30:
                mem.duplex == '+'
                mem.offset = 5000000
                immutable += ["duplex", "offset"]
            elif mem.freq in FRS_FREQS1:
                mem.duplex == ''
                mem.offset = 0
                immutable += ["duplex", "offset"]
            elif mem.freq in FRS_FREQS2:
                mem.duplex == ''
                mem.offset = 0
                mem.mode = "NFM"
                mem.power = self.POWER_LEVELS[1]
                immutable += ["duplex", "offset", "mode", "power"]
            elif mem.freq in FRS_FREQS3:
                if mem.duplex == '':
                    mem.offset = 0
                if mem.duplex == '+':
                    mem.offset = 5000000
            else:
                if mem.freq not in GMRS_FREQS:
                    immutable = ["duplex", "offset"]

        mem.immutable = immutable

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + self._mask
            if pol == "R":
                val += 0x8000
            return val

        rx_mode = tx_mode = None
        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            tx_tone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = int(mem.ctone * 10)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.tx_tone, rx_mode, _mem.rx_tone))

    def set_memory(self, mem):
        if self._skipflags:
            bitpos = (1 << ((mem.number - 1) % 8))
            bytepos = ((mem.number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[mem.number - 1]
            else:
                _mem = self._memobj.himems[mem.number - 17]
        elif self.MODEL == "RT19" or self.MODEL == "RT619":
            _mem = self._memobj.memory[mem.number - 1]
            _freqhops = self._memobj.freqhops[mem.number - 1]
        else:
            _mem = self._memobj.memory[mem.number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw(asbytes=False)

        if self.MODEL == "RT86":
            _freqhops = self._memobj.freqhops[mem.number - 1]

        if mem.empty:
            if self.MODEL in ["RB23",
                              "RB26",
                              "RT40B",
                              "RT76",
                              "RT86",
                              ]:
                _mem.set_raw("\xFF" * 13 + _rsvd)
            elif self.MODEL in ["RT19",
                                "RT86",
                                "RT619",
                                ]:
                _mem.set_raw("\xFF" * 13 + _rsvd)
                _freqhops.freqhop.set_raw("\x00")
            elif self.MODEL == "AR-63":
                _mem.set_raw("\xFF" * 13 + _rsvd)
            else:
                _mem.set_raw("\xFF" * (_mem.size() // 8))

            return

        if self.MODEL == "RB17A":
            _mem.set_raw("\x00" * 14 + "\xFF\xFF")
        elif self._reserved:
            _mem.set_raw("\x00" * 13 + _rsvd)
        elif self.MODEL == "AR-63":
            _mem.set_raw("\x00" * 13 + _rsvd)
        else:
            _mem.set_raw("\x00" * 13 + "\x30\x8F\xF8")

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.wide = mem.mode == "FM"

        self._set_tone(mem, _mem)

        if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            # set the power level
            if mem.power == self.POWER_LEVELS[2]:
                _mem.txpower = self.TXPOWER_LOW
            elif mem.power == self.POWER_LEVELS[1]:
                _mem.txpower = self.TXPOWER_MED
            elif mem.power == self.POWER_LEVELS[0]:
                _mem.txpower = self.TXPOWER_HIGH
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))
        else:
            _mem.highpower = mem.power == self.POWER_LEVELS[0]

        if self._skipflags:
            if mem.skip != "S":
                _skp |= bitpos
            else:
                _skp &= ~bitpos
            LOG.debug("_skp %s" % _skp)

        for setting in mem.extra:
            if setting.get_name() == "scramble_type":
                setattr(_mem, setting.get_name(), int(setting.value) - 1)
                if self.MODEL == "RT21" or self.MODEL == "RT21V":
                    setattr(_mem, "scramble_type2", int(setting.value) - 1)
            elif setting.get_name() == "freqhop":
                setattr(_freqhops, setting.get_name(), setting.value)
            elif setting.get_name() == "hop":
                setattr(_mem, setting.get_name(), not int(setting.value))
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        if self.MODEL == "RT21" or self.MODEL == "RB17A" or \
                self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF" or \
                self.MODEL == "RT21V":
            _keys = self._memobj.keys

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       current_index=_settings.tot)
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TOTALERT_LIST,
                                       current_index=_settings.totalert)
            rset = RadioSetting("totalert", "TOT Pre-alert", rs)
            basic.append(rset)

            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(
                VOICE_LIST, current_index=_settings.voice)
            rset = RadioSetting("voice", "Voice Annunciation", rs)
            basic.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(ALARM_LIST,
                                           current_index=_settings.alarm)
                rset = RadioSetting("alarm", "Alarm Type", rs)
                basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Saver", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_scramble)
            rset = RadioSetting("use_scramble", "Scramble", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_vox)
            rset = RadioSetting("use_vox", "VOX", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOX_LIST, current_index=_settings.vox)
            rset = RadioSetting("vox", "VOX Gain", rs)
            basic.append(rset)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

            def apply_pf1_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(
                          setting.value) + " from list")
                val = str(setting.value)
                index = PF1_CHOICES.index(val)
                val = PF1_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RT21" or self.MODEL == "RT21V":
                if _keys.pf1 in PF1_VALUES:
                    idx = PF1_VALUES.index(_keys.pf1)
                else:
                    idx = LIST_DTMF_SPECIAL_VALUES.index(0x04)
                rs = RadioSettingValueList(PF1_CHOICES, current_index=idx)
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pf1_listvalue, _keys.pf1)
                basic.append(rset)

            def apply_pf1_17a_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(
                          setting.value) + " from list")
                val = str(setting.value)
                index = PF1_17A_CHOICES.index(val)
                val = PF1_17A_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RB17A":
                if _keys.pf1 in PF1_17A_VALUES:
                    idx = PF1_17A_VALUES.index(_keys.pf1)
                else:
                    idx = LIST_DTMF_SPECIAL_VALUES.index(0x04)
                rs = RadioSettingValueList(PF1_17A_CHOICES,
                                           current_index=idx)
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pf1_17a_listvalue, _keys.pf1)
                basic.append(rset)

            def apply_topkey_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = TOPKEY_CHOICES.index(val)
                val = TOPKEY_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RB17A":
                if _keys.topkey in TOPKEY_VALUES:
                    idx = TOPKEY_VALUES.index(_keys.topkey)
                else:
                    idx = TOPKEY_VALUES.index(0x0C)
                rs = RadioSettingValueList(TOPKEY_CHOICES, current_index=idx)
                rset = RadioSetting("keys.topkey", "Top Key Function", rs)
                rset.set_apply_callback(apply_topkey_listvalue, _keys.topkey)
                basic.append(rset)

            def apply_pfkey_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = PFKEY_CHOICES.index(val)
                val = PFKEY_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                if _keys.pf1 in PFKEY_VALUES:
                    idx = PFKEY_VALUES.index(_keys.pf1)
                else:
                    idx = PFKEY_VALUES.index(0x04)
                rs = RadioSettingValueList(PFKEY_CHOICES, current_index=idx)
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pfkey_listvalue, _keys.pf1)
                basic.append(rset)

                if _keys.pf2 in PFKEY_VALUES:
                    idx = PFKEY_VALUES.index(_keys.pf2)
                else:
                    idx = PFKEY_VALUES.index(0x0A)
                rs = RadioSettingValueList(PFKEY_CHOICES, current_index=idx)
                rset = RadioSetting("keys.pf2", "PF2 Key Function", rs)
                rset.set_apply_callback(apply_pfkey_listvalue, _keys.pf2)
                basic.append(rset)

        if self.MODEL in ["AR-63",
                          "RB23",
                          "RB26",
                          "RT19",
                          "RT40B",
                          "RT76",
                          "RT86",
                          "RT619",
                          "RB89",
                          ]:
            if self.MODEL == "RB26" or self.MODEL == "RB23" \
                    or self.MODEL == "RB89":
                _settings2 = self._memobj.settings2
                _settings3 = self._memobj.settings3

            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       current_index=_settings.tot)
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            if self.MODEL == "RT19" or self.MODEL == "RT619":
                rs = RadioSettingValueList(VOICE_LIST,
                                           current_index=_settings.voice)
                rset = RadioSetting("voice", "Voice Prompts", rs)
                basic.append(rset)

                rs = RadioSettingValueList(BOOTSEL_LIST,
                                           current_index=_settings.bootsel)
                rset = RadioSetting("bootsel", "Boot Select", rs)
                basic.append(rset)

                rs = RadioSettingValueInteger(1, 10, _settings.voicel + 1)
                rset = RadioSetting("voicel", "Voice Level", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings.voxl)
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

            if self.MODEL == "AR-63":
                rs = RadioSettingValueList(VOICE_LIST,
                                           current_index=_settings.voice)
                rset = RadioSetting("voice", "Voice Prompts", rs)
                basic.append(rset)

            if self.MODEL in ["RT76",
                              "RT86",
                              ]:
                rs = RadioSettingValueList(VOICE_LIST3,
                                           current_index=_settings.voice)
                rset = RadioSetting("voice", "Voice Annumciation", rs)
                basic.append(rset)

            if self.MODEL == "RB26" or self.MODEL == "RB23" \
                    or self.MODEL == "RB89":
                rs = RadioSettingValueList(VOICE_LIST2,
                                           current_index=_settings.voice)
                rset = RadioSetting("voice", "Voice Annumciation", rs)
                basic.append(rset)

            if self.MODEL == "RB26":
                rs = RadioSettingValueBoolean(not _settings.chnumberd)
                rset = RadioSetting("chnumberd", "Channel Number Enable", rs)
                basic.append(rset)

            if self.MODEL == "RT86" or self.MODEL == "RB89":
                rs = RadioSettingValueList(SPECIAL_LIST,
                                           current_index=_settings.tailmode)
                rset = RadioSetting("tailmode", "QT/DQT Tail Mode", rs)
                basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Save", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.beep)
            rset = RadioSetting("beep", "Beep", rs)
            basic.append(rset)

            if self.MODEL in ["RB23",
                              "RB26",
                              "RT86",
                              "RB89",
                              ]:
                rs = RadioSettingValueBoolean(not _settings.tail)
                rset = RadioSetting("tail", "QT/DQT Tail", rs)
                basic.append(rset)

            if self.MODEL != "AR-63" and self.MODEL != "RT40B":
                rs = RadioSettingValueList(SAVE_LIST,
                                           current_index=_settings.savem)
                rset = RadioSetting("savem", "Battery Save Mode", rs)
                basic.append(rset)

            if self.MODEL != "RT19" and self.MODEL != "RT619" and \
                    self.MODEL != "AR-63" and \
                    self.MODEL != "RT40B":
                rs = RadioSettingValueList(GAIN_LIST,
                                           current_index=_settings.gain)
                rset = RadioSetting("gain", "MIC Gain", rs)
                basic.append(rset)

                rs = RadioSettingValueList(WARN_LIST,
                                           current_index=_settings.warn)
                rset = RadioSetting("warn", "Warn Mode", rs)
                basic.append(rset)

            if self.MODEL == "RT86":
                rs = RadioSettingValueInteger(1, 16, _settings.chnumber + 1)
                rset = RadioSetting("settings.chnumber", "Channel Number", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings.voxl)
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

            if self.MODEL == "RB26" or self.MODEL == "RB23" \
                    or self.MODEL == "RB89":
                rs = RadioSettingValueBoolean(_settings3.vox)
                rset = RadioSetting("settings3.vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings3.voxl)
                rset = RadioSetting("settings3.voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings3.voxd)
                rset = RadioSetting("settings3.voxd", "Vox Delay", rs)
                basic.append(rset)

                if self.MODEL == "RB26":
                    rs = RadioSettingValueList(PFKEY_LIST,
                                               current_index=_settings.pf1)
                    rset = RadioSetting("pf1", "PF1 Key Set", rs)
                    basic.append(rset)

                    rs = RadioSettingValueList(PFKEY_LIST,
                                               current_index=_settings.pf2)
                    rset = RadioSetting("pf2", "PF2 Key Set", rs)
                    basic.append(rset)
                elif self.MODEL == "RB23":
                    def apply_pfkey_listvalue(setting, obj):
                        LOG.debug("Setting value: " + str(setting.value) +
                                  " from list")
                        val = str(setting.value)
                        index = PFKEY23_CHOICES.index(val)
                        val = PFKEY23_VALUES[index]
                        obj.set_value(val)

                    if _settings.pf1 in PFKEY23_VALUES:
                        idx = PFKEY23_VALUES.index(_settings.pf1)
                    else:
                        idx = PFKEY23_VALUES.index(0x01)
                    rs = RadioSettingValueList(PFKEY23_CHOICES,
                                               current_index=idx)
                    rset = RadioSetting("settings.pf1", "PF1 Key Function", rs)
                    rset.set_apply_callback(apply_pfkey_listvalue,
                                            _settings.pf1)
                    basic.append(rset)

                    if _settings.pf2 in PFKEY23_VALUES:
                        idx = PFKEY23_VALUES.index(_settings.pf2)
                    else:
                        idx = PFKEY23_VALUES.index(0x03)
                    rs = RadioSettingValueList(PFKEY23_CHOICES,
                                               current_index=idx)
                    rset = RadioSetting("settings.pf2", "PF2 Key Function", rs)
                    rset.set_apply_callback(apply_pfkey_listvalue,
                                            _settings.pf2)
                    basic.append(rset)

                rs = RadioSettingValueInteger(1, 30, _settings2.chnumber + 1)
                rset = RadioSetting("settings2.chnumber", "Channel Number", rs)
                basic.append(rset)

            if self.MODEL == "RT76":
                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings.voxl)
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

                rs = RadioSettingValueInteger(1, 30, _settings.chnumber + 1)
                rset = RadioSetting("chnumber", "Channel Number", rs)
                basic.append(rset)

            if self.MODEL == "AR-63":
                rs = RadioSettingValueBoolean(_settings.warn)
                rset = RadioSetting("warn", "Warn", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.scan)
                rset = RadioSetting("scan", "Scan", rs)
                basic.append(rset)

                rs = RadioSettingValueList(HOP_LIST,
                                           current_index=_settings.hop)
                rset = RadioSetting("hop", "Hop Mode", rs)
                basic.append(rset)

                rs = RadioSettingValueList(TAIL_LIST,
                                           current_index=_settings.tailmode)
                rset = RadioSetting("tailmode", "DCS Tail Mode", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings.voxl)
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

            if self.MODEL == "RT40B":
                rs = RadioSettingValueList(VOICE_LIST,
                                           current_index=_settings.voice)
                rset = RadioSetting("voice", "Voice Prompts", rs)
                basic.append(rset)

                rs = RadioSettingValueList(SAVEM_LIST,
                                           current_index=_settings.savem)
                rset = RadioSetting("savem", "Battery Save Mode", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.pttstone)
                rset = RadioSetting("pttstone", "PTT Start Tone", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.pttetone)
                rset = RadioSetting("pttetone", "PTT End Tone", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           current_index=_settings.voxl)
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           current_index=_settings.voxd)
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

        if self.MODEL == "RT86":
            rs = RadioSettingValueList(PFKEY86_LIST,
                                       current_index=_settings.pf1)
            rset = RadioSetting("pf1", "PF1 Key Set", rs)
            basic.append(rset)

            rs = RadioSettingValueList(PFKEY86_LIST,
                                       current_index=_settings.pf2)
            rset = RadioSetting("pf2", "PF2 Key Set", rs)
            basic.append(rset)

        if self.MODEL == "RB89":
            rs = RadioSettingValueList(PFKEY89_LIST,
                                       current_index=_settings.pf1)
            rset = RadioSetting("pf1", "PF1 Key Set", rs)
            basic.append(rset)

            rs = RadioSettingValueList(PFKEY89_LIST,
                                       current_index=_settings.pf2)
            rset = RadioSetting("pf2", "PF2 Key Set", rs)
            basic.append(rset)

        if self.MODEL == "RB28B" or self.MODEL == "RB628B":
            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       current_index=_settings.tot)
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOICE_LIST2,
                                       current_index=_settings.voice)
            rset = RadioSetting("voice", "Voice Annumciation", rs)
            basic.append(rset)

            rs = RadioSettingValueList(POT_LIST,
                                       current_index=_settings.pwrontype)
            rset = RadioSetting("pwrontype", "Power on Type", rs)
            basic.append(rset)

            rs = RadioSettingValueList(SAVE_LIST,
                                       current_index=_settings.savem)
            rset = RadioSetting("savem", "Battery Save Mode", rs)
            basic.append(rset)

            rs = RadioSettingValueList(GAIN_LIST,
                                       current_index=_settings.gain)
            rset = RadioSetting("gain", "MIC Gain", rs)
            basic.append(rset)

            rs = RadioSettingValueInteger(1, 10, _settings.volume + 1)
            rset = RadioSetting("volume", "Volume", rs)
            basic.append(rset)

            rs = RadioSettingValueInteger(1, 22, _settings.chnumber + 1)
            rset = RadioSetting("chnumber", "Channel Number", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Save", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.beep)
            rset = RadioSetting("beep", "Beep", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.keylock)
            rset = RadioSetting("keylock", "Key Lock", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.vox)
            rset = RadioSetting("vox", "Vox Function", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOXL_LIST,
                                       current_index=_settings.voxl)
            rset = RadioSetting("voxl", "Vox Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOXD_LIST,
                                       current_index=_settings.voxd)
            rset = RadioSetting("voxd", "Vox Delay", rs)
            basic.append(rset)

            rs = RadioSettingValueList(PFKEY28B_LIST,
                                       current_index=_settings.pfkey_lt)
            rset = RadioSetting("pfkey_lt", "Key Set <", rs)
            basic.append(rset)

            rs = RadioSettingValueList(PFKEY28B_LIST,
                                       current_index=_settings.pfkey_gt)
            rset = RadioSetting("pfkey_gt", "Key Set >", rs)
            basic.append(rset)

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
                    elif setting == "channel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "chnumber":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "chnumberd":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "tail":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "voicel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "volume":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        if cls.MODEL == "RT21":
            # The RT21 is pre-metadata, so do old-school detection
            match_size = False
            match_model = False

            # testing the file data size
            if len(filedata) in [0x0400, ]:
                match_size = True

            # testing the model fingerprint
            match_model = model_match(cls, filedata)

            if match_size and match_model:
                return True
            else:
                return False
        else:
            # Radios that have always been post-metadata, so never do
            # old-school detection
            return False


@directory.register
class RB17ARadio(RT21Radio):
    """RETEVIS RB17A"""
    VENDOR = "Retevis"
    MODEL = "RB17A"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PROA8US"
    _fingerprint = [b"P3217s\xF8\xFF", ]
    _upper = 30
    _skipflags = True
    _reserved = False
    _gmrs = True

    _ranges = [
               (0x0000, 0x0300),
              ]
    _memsize = 0x0300

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB17A, self._mmap)


@directory.register
class RT21VRadio(RT21Radio):
    """RETEVIS RT21V"""
    VENDOR = "Retevis"
    MODEL = "RT21V"
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]
    VALID_BANDS = [(137000000, 174000000)]

    _fingerprint = [b"P2207\x01\xF8\xFF", ]
    _murs = False  # sold as MURS radio but supports full band TX/RX
    _upper = 5
    _mem_params = (_upper,  # number of channels
                   )


@directory.register
class RB26Radio(RT21Radio):
    """RETEVIS RB26"""
    VENDOR = "Retevis"
    MODEL = "RB26"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = DTCS_EXTRA
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=3.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR" + b"\x01" + b"0"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 30
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _gmrs = True

    _ranges = [
               (0x0000, 0x0320),
              ]
    _memsize = 0x0320

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB26, self._mmap)


@directory.register
class RB626(RB26Radio):
    MODEL = 'RB626'
    _gmrs = False


@directory.register
class RT76Radio(RT21Radio):
    """RETEVIS RT76"""
    VENDOR = "Retevis"
    MODEL = "RT76"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = DTCS_EXTRA
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR\x14\xD4"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 30
    _ack_1st_block = False
    _skipflags = False
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _gmrs = True

    _ranges = [
               (0x0000, 0x01E0),
              ]
    _memsize = 0x01E0

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT76, self._mmap)


@directory.register
class RT29UHFRadio(RT21Radio):
    """RETEVIS RT29UHF"""
    VENDOR = "Retevis"
    MODEL = "RT29_UHF"
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x10

    TXPOWER_MED = 0x00
    TXPOWER_HIGH = 0x01
    TXPOWER_LOW = 0x02

    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (17, 50, 55, 135,
                              217, 254, 305, 345, 425, 466, 534, 645, 765)))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10.00),
                    chirp_common.PowerLevel("Mid", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    _magic = b"PROHRAM"
    _fingerprint = [b"P3207" + b"\x13\xF8\xFF", ]  # UHF model
    _upper = 16
    _skipflags = True
    _reserved = False

    _ranges = [
               (0x0000, 0x0300),
              ]
    _memsize = 0x0400

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT29, self._mmap)


@directory.register
class RT29VHFRadio(RT29UHFRadio):
    """RETEVIS RT29VHF"""
    VENDOR = "Retevis"
    MODEL = "RT29_VHF"

    TXPOWER_MED = 0x00
    TXPOWER_HIGH = 0x01
    TXPOWER_LOW = 0x02

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10.00),
                    chirp_common.PowerLevel("Mid", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    VALID_BANDS = [(136000000, 174000000)]

    _magic = b"PROHRAM"
    _fingerprint = [b"P2207" + b"\x01\xF8\xFF", ]  # VHF model


@directory.register
class RB23Radio(RT21Radio):
    """RETEVIS RB23"""
    VENDOR = "Retevis"
    MODEL = "RB23"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR" + b"\x01" + b"0"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 30
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _gmrs = True

    _ranges = [
               (0x0000, 0x0320),
              ]
    _memsize = 0x0320

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB26, self._mmap)


@directory.register
class RT19Radio(RT21Radio):
    """RETEVIS RT19"""
    VENDOR = "Retevis"
    MODEL = "RT19"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGRQ^"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 22
    _mem_params = (_upper,  # number of channels
                   0x160,   # memory start
                   _upper   # number of freqhops
                   )
    _ack_1st_block = False
    _skipflags = False
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _frs = True

    _ranges = [
               (0x0000, 0x0180),
              ]
    _memsize = 0x0180

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT19 % self._mem_params,
                                     self._mmap)


@directory.register
class RT619Radio(RT19Radio):
    """RETEVIS RT619"""
    VENDOR = "Retevis"
    MODEL = "RT619"

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=0.50),
                    chirp_common.PowerLevel("Low", watts=0.49)]

    _magic = b"PHOGRS]"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 16
    _mem_params = (_upper,  # number of channels
                   0x100,   # memory start
                   _upper   # number of freqhops
                   )
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _frs = False
    _pmr = True

    _ranges = [
               (0x0000, 0x0120),
              ]
    _memsize = 0x0120


@directory.register
class AR63Radio(RT21Radio):
    """ABBREE AR-63"""
    VENDOR = "Abbree"
    MODEL = "AR-63"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=3.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    _magic = b"PHOGR\xF5\x9A"
    _fingerprint = [b"P32073" + b"\x02\xFF",
                    b"P32073" + b"\x03\xFF", ]
    _upper = 16
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _gmrs = False

    _ranges = [
               (0x0000, 0x0140),
              ]
    _memsize = 0x0140

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT76, self._mmap)


@directory.register
class RT40BRadio(RT21Radio):
    """RETEVIS RT40B"""
    VENDOR = "Retevis"
    MODEL = "RT40B"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = DTCS_EXTRA
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    VALID_BANDS = [(400000000, 480000000)]

    _magic = b"PHOGRH" + b"\x5C"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 22
    _mem_params = (_upper,  # number of channels
                   )
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _gmrs = True
    _echo = True

    _ranges = [
               (0x0000, 0x0160),
              ]
    _memsize = 0x0160

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT40B % self._mem_params,
                                     self._mmap)


@directory.register
class RB28BRadio(RT21Radio):
    """RETEVIS RB28B"""
    VENDOR = "Retevis"
    MODEL = "RB28B"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = DTCS_EXTRA
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR\x08\xB2"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 22
    _ack_1st_block = False
    _skipflags = False
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _frs = True

    _ranges = [
               (0x0000, 0x01F0),
              ]
    _memsize = 0x01F0

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB28B, self._mmap)


@directory.register
class RB628BRadio(RB28BRadio):
    """RETEVIS RB628B"""
    VENDOR = "Retevis"
    MODEL = "RB628B"

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=0.50),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR\x09\xB2"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 16
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used
    _frs = False
    _pmr = True


@directory.register
class RT86Radio(RT21Radio):
    """RETEVIS RT86"""
    VENDOR = "Retevis"
    MODEL = "RT86"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    DTCS_CODES = DTCS_EXTRA
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    VALID_BANDS = [(400000000, 480000000)]

    _magic = b"PHOGR" + b"\xCD\x91"
    _fingerprint = [b"P32073" + b"\x02\xFF", ]
    _upper = 16
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _mask = 0x2800  # bit mask to identify DTCS tone decoding is used

    _ranges = [
               (0x0000, 0x01A0),
              ]
    _memsize = 0x01A0

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT86, self._mmap)


@directory.register
class RB89Radio(RT21Radio):
    """RETEVIS RB89"""
    VENDOR = "Retevis"
    MODEL = "RB89"
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR" + b"\x01" + b"0"
    _fingerprint = [b"P32073" + b"\x01\xFF", ]
    _upper = 30
    _ack_1st_block = False
    _skipflags = True
    _reserved = True
    _gmrs = False  # sold as GMRS radio but supports full band TX/RX

    _ranges = [
               (0x0000, 0x0330),
              ]
    _memsize = 0x0340

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB26, self._mmap)
