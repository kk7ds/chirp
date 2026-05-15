# Copyright 2023 Jim Unroe <rock.unroe@gmail.com>
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
from enum import Enum

from chirp import chirp_common, directory, memmap, checksum
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings

from chirp.drivers.iradio_common import enter_programming_mode, \
    exit_programming_mode

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  u8 unknown_1[16];                   // 0000-000f
  u8 startup_image_enable;            // 0010
  u8 unknown_2[2];                    // 0011-0012
  u8 startup_ringtone_enable;         // 0013
  u8 welcome_message_enable;          // 0014
  ul16 welcome_text_color;            // 0015-0016
  ul16 welcome_start_line;            // 0017-0018
  ul16 welcome_start_column;          // 0019-001a
  u8 startup_password_enable;         // 001b
  char startup_password[16];          // 001c-002b
  char welcome_message[32];           // 002c-004b
  char name_callsign[16];             // 004c-005b
  u8 voice_prompt;                    // 005c
  u8 key_beep;                        // 005d
  u8 unknown_3;                       // 005e
  u8 lock_timer;                      // 005f
  u8 key_led;                         // 0060
  u8 brightness;                      // 0061
  u8 lcd_timer;                       // 0062
  u8 save_mode;                       // 0063
  u8 save_start_timer;                // 0064
  u8 menu_exit;                       // 0065
  u8 tx_priority;                     // 0066
  u8 talkaround;                      // 0067
  u8 alarm_type;                      // 0068
  u8 auto_power_off;                  // 0069
  ul32 auto_power_off_time;           // 006a-006d
  u8 auto_wake_up;                    // 006e
  ul32 auto_wake_up_time;             // 006f-0072
  u8 multi_ptt;                       // 0073
  u8 work_range;                      // 0074
  u8 current_area;                    // 0075
  u8 multi_standby;                   // 0076
  u8 uv_repeater;                     // 0077
  u8 freq_step;                       // 0078
  u8 area_a_mode;                     // 0079
  u8 area_a_show;                     // 007a
  u8 area_a_zone;                     // 007b
  ul16 area_a_channel;                // 007c-007d
  u8 area_b_mode;                     // 007e
  u8 area_b_show;                     // 007f
  u8 area_b_zone;                     // 0080
  ul16 area_b_channel;                // 0081-0082
  u8 area_c_mode;                     // 0083
  u8 area_c_show;                     // 0084
  u8 area_c_zone;                     // 0085
  ul16 area_c_channel;                // 0086-0087
  u8 lock_range_1_type;               // 0088
  ul16 lock_range_1_start;            // 0089-008a
  ul16 lock_range_1_end;              // 008b-008c
  u8 lock_range_2_type;               // 008d
  ul16 lock_range_2_start;            // 008e-008f
  ul16 lock_range_2_end;              // 0090-0091
  u8 lock_range_3_type;               // 0092
  ul16 lock_range_3_start;            // 0093-0094
  ul16 lock_range_3_end;              // 0095-0096
  u8 lock_range_4_type;               // 0097
  ul16 lock_range_4_start;            // 0098-0099
  ul16 lock_range_4_end;              // 009a-009b
  u8 scan_direction;                  // 009c
  u8 scan_mode;                       // 009d
  u8 scan_return;                     // 009e
  u8 scan_dwell_timer;                // 009f
  u8 tx_voice_refresh;                // 00a0
  u8 rx_rssi_refresh;                 // 00a1
  ul16 single_tone;                   // 00a2-00a3
  u8 squelch_level;                   // 00a4
  u8 tx_start_tone;                   // 00a5
  u8 tx_end_tone;                     // 00a6
  u8 vox;                             // 00a7
  u8 vox_threshold;                   // 00a8
  u8 vox_delay;                       // 00a9
  u8 detect_range;                    // 00aa
  u8 repeater_delay;                  // 00ab
  u8 noaa_monitor;                    // 00ac
  u8 mic_gain;                        // 00ad
  u8 fm_spk_gain;                     // 00ae
  u8 fm_dac_gain;                     // 00af
  u8 am_spk_gain;                     // 00b0
  u8 am_dac_gain;                     // 00b1
  u8 glitch_threshold;                // 00b2
  u8 tt_rx_test;                      // 00b3
  u8 tt_rssi_threshold;               // 00b4
  u8 tt_noise_threshold;              // 00b5
  u8 tt_power_test;                   // 00b6
  u8 tt_power_136_174;                // 00b7
  u8 tt_power_400_480;                // 00b8
  u8 tt_power_18_64;                  // 00b9
  u8 tt_power_64_136;                 // 00ba
  u8 tt_power_173_240;                // 00bb
  u8 tt_power_240_320;                // 00bc
  u8 tt_power_320_400;                // 00bd
  u8 tt_power_480_560;                // 00be
  u8 tt_power_560_620;                // 00bf
  u8 tt_power_840_920;                // 00c0
  u8 tt_power_920_1000;               // 00c1
  u8 tt_power_1000_1080;              // 00c2
  u8 tt_power_1080_1160;              // 00c3
  u8 tt_power_1160_1240;              // 00c4
  u8 tt_power_1240_1300;              // 00c5
  u8 side_key_1_s;                    // 00c6
  u8 side_key_1_l;                    // 00c7
  u8 side_key_2_s;                    // 00c8
  u8 side_key_2_l;                    // 00c9
  u8 alarm_key_2_s;                   // 00ca
  u8 alarm_key_2_l;                   // 00cb
  u8 key_0_long;                      // 00cc
  u8 key_1_long;                      // 00cd
  u8 key_2_long;                      // 00ce
  u8 key_3_long;                      // 00cf
  u8 key_4_long;                      // 00d0
  u8 key_5_long;                      // 00d1
  u8 key_6_long;                      // 00d2
  u8 key_7_long;                      // 00d3
  u8 key_8_long;                      // 00d4
  u8 key_9_long;                      // 00d5
  u8 gps_enable;                      // 00d6
  u8 gps_baud_rate;                   // 00d7
  u8 gps_utc_zone;                    // 00d8
  u8 unknown_4;                       // 00d9
  u8 gps_auto_record;                 // 00da
  u8 gps_auto_record_interval;        // 00db
  u8 unknown_5[40];                   // 00dc-0103
  u8 freq_input;                      // 0104
  u8 fm_rx_standby;                   // 0105              *    bool
  u8 fm_channel;                      // 0106              *    1-128
  u8 repeater_monitor;                // 0107
  u8 denoise;                         // 0108
} settings;

struct tone {
  ul16 unknown:2,
       is_dtcs:1,
       // when is_dtcs is false, tone_or_inverted specifies if mode is tone
       // when is_dtcs is true, tone_or_inverted specifies if dtcs is inverted
       tone_or_inverted:1,
       tone_val:12;
};

struct memory {
  u8 rx_mode;                         //   00
  u8 limit_rx_tx;                     //   01
  u8 enabled;                         //   02
  u8 isnarrow;                        //   03
  struct tone rx_tone;                //   04-05
  ul32 rxfreq;                        //   06-0a
  ul32 txfreq;                        //   0b-0e
  struct tone tx_tone;                //   0f-10
  u8 power;                           //   11
  u8 bcl;                             //   12
  u8 dcs_encrypt:3,                   //   13
     tot:5;                           //
  u8 scan_remove:1,                   //   14
     tail_tone:3,                     //
     scrambler:4;                     //
  ul32 mutecode;                      //   15-18
  u8 unknown[8];                      //   19-20
  char name[16];                      //   21-2f
};

struct dtmf_code {
  char code[14];                      //   00-0d
  u8 unknown;                         //   0e
  u8 code_length;                     //   0f
};

#seekto 0x200;
struct {
  u8 dtmf_delay;                      // 0200
  u8 dtmf_interval;                   // 0201
  u8 dtmf_duration;                   // 0202
  u8 dtmf_mode;                       // 0203
  u8 dtmf_select;                     // 0204
  u8 dtmf_display;                    // 0205
  u8 dtmf_tx_gain;                    // 0206
  u8 dtmf_rx_threshold;               // 0207
  u8 dtmf_control;                    // 0208
  u8 time_calibrate;                  // 0209
  struct dtmf_code dtmf_codes[16];    // 020a
  struct dtmf_code remote_stun;       // 030a
  struct dtmf_code remote_kill;       // 031a
  struct dtmf_code remote_wake;       // 032a
  struct dtmf_code remote_monitor;    // 033a
} dtmf;

#seekto 0x34a;
struct {
  u8 reverse_channel;                 // 034a
  u8 ctdcs_code_show;                 // 034b
  u8 ch_alias_color;                  // 034c
  u8 unknown[3];                      // 034d-034f
  u8 tx_unlimit;                      // 0350
} settings2;

#seekto 0x400;
struct {
  struct memory vfo_uv_a;             // 0400
  struct memory vfo_uv_b;             // 0430
  struct memory vfo_uv_c;             // 0460
  struct memory vfo_cb_a;             // 0490
  struct memory vfo_cb_b;             // 04c0
  struct memory vfo_cb_c;             // 04f0
  struct memory vfo_850_a;            // 0520
  struct memory vfo_850_b;            // 0550
  struct memory vfo_850_c;            // 0580
} vfo;

#seekto 0xc00;
struct {
  u8 gps_coord_type;                  // 0c00
  u8 gps_speed_unit;                  // 0c01
  u8 gps_distance_unit;               // 0c02
  u8 gps_altitude_unit;               // 0c03
  char gps_fixed_lat[7];              // 0c04-0c0a
  u8 unknown_1[3];                    // 0c0b-0c0d
  char gps_fixed_lat_dir;             // 0c0e
  char gps_fixed_long[8];             // 0c0f-0c16
  u8 unknown_2[3];                    // 0c17-0c19
  char gps_fixed_long_dir;            // 0c1a
  char gps_fixed_altitude[7];         // 0c1b-0c21
  u8 unknown_3[4];                    // 0c22-0c25
  u8 gps_mileage_type;                // 0c26
} gps;

#seekto 0xc20;
struct {
  u8 unknown_1[7];                    // 0c20-0c26
  u8 aprs_station_mode;               // 0c27
  u8 aprs_rx_ch;                      // 0c28
  u8 aprs_tx_ch;                      // 0c29
  u8 aprs_ptt_priority;               // 0c2a
  u8 aprs_ptt_delay;                  // 0c2b
  u8 aprs_beacon_popup;               // 0c2c
  u8 unknown_2[3];                    // 0c2d-0c2f
  char aprs_callsign[6];              // 0c30-0c35
  u8 aprs_ssid;                       // 0c36
  u8 aprs_symbol_table;               // 0c37
  u8 aprs_symbol;                     // 0c38
  char aprs_comment[128];             // 0c39-0cb8
  u8 aprs_mice_enable;                // 0cb9
  u8 aprs_mice_mode;                  // 0cba
  char aprs_path_1[6];                // 0cbb-0cc0
  u8 aprs_path_1_count;               // 0cc1
  char aprs_path_2[6];                // 0cc2-0cc7
  u8 aprs_path_2_count;               // 0cc8
  u8 aprs_tx_voltage;                 // 0cc9
  u8 unknown_3[2];                    // 0cca-0ccb
  u8 aprs_tx_star;                    // 0ccc
  u8 aprs_tx_mileage;                 // 0ccd
  u8 aprs_beacon_ptt_after;           // 0cce
  u8 aprs_smart_beacon;               // 0ccf
  u8 aprs_beacon_time_mode;           // 0cd0
  ul32 aprs_beacon_time;              // 0cd1-0cd4
  u8 aprs_queue_beacon;               // 0cd5
  u8 aprs_queue_interval;             // 0cd6
  u8 aprs_digi_rep_ch;                // 0cd7
  u8 aprs_digi_1_enable;              // 0cd8
  char aprs_digi_1_name[6];           // 0cd9-0cde
  u8 aprs_digi_2_enable;              // 0cdf
  char aprs_digi_2_name[6];           // 0ce0-0ce5
  u8 aprs_digi_wait_before_rep;       // 0ce6
  char aprs_digi_remote_password[6];  // 0ce7-0cec
  u8 aprs_enable;                     // 0ced
  u8 unknown_4[2];                    // 0cee-0cef
  u8 aprs_demod_tone;                 // 0cf0
  u8 aprs_tx_level;                   // 0cf1
  u8 aprs_rx_level;                   // 0cf2
  u8 aprs_beacon_save;                // 0cf3
  u8 aprs_beacon_ptt_after_ch;        // 0cf4
  u8 aprs_rx_ch_mute;                 // 0cf5
  u8 unknown_5[10];                   // 0cf6-0cff
} aprs;

#seekto 0x2000;
struct memory channels[1024];

struct zone {
  u8 channel_count1;                  // 0000
  u8 channel_count2;                  // 0001
  u8 unknown1[2];                     // 0002-0003
  char name[16];                      // 0004-0013
  ul16 channels[200];                 // 0014-01a3
  u8 unknown2[92];                    // 01a4-01ff
};

#seekto 0x1a000;
struct zone zones[256];

struct fm_memory {
  // 64-108 MHz, 2.0-30.0 MHz, 520-1710 KHz, 153-279 KHz
  u8 range;                           //   00              *
  // FM, AM, LSB, USB, CW
  u8 demodulation;                    //   01              *
  // 1 K, 5 K, 10 K, 50 K, 100 K, 500 K, 1 M, 9 K
  u8 step;                            //   02              *
  // 0.5 K, 1.0 K, 1.2 K, 2.2 K, 3.0 K, 4.0 K
  u8 bandwidth;                       //   03              *
  // AGC, 0, -1, -2, ..., -37
  u8 attenuation;                     //   04              *
  // x-32768?
  ul16 bfo;                           //   05-06           *
  ul16 frequency;                     //   07-08           *
  // bool
  u8 enabled;                         //   09              *
  u8 unknown[6];                      //   0a-0f
  char name[16];                      //   10-1f           *
};

#seekto 0xd4000;
struct fm_memory fm_channels[128];    //                   *
"""

CMD_ACK = b"\x06"

DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

LIST_ALARMTYPE = ["Local Alarm", "Remote Alarm", "Local + Remote"]
LIST_APRSBEACONAFTER = ["Off", "Area Match", "All Area"]
LIST_APRSBEACONSAVE = ["Not Stored", "FCS Check OK", "Stored All"]
LIST_APRSCHANNEL = ["Off", "CH-A", "CH-B", "CH-C"]
LIST_APRSCHANNELCOMBOS = ["CH-A", "CH-B", "CH-C", "CH-A + CH-B", "CH-A + CH-C",
                          "CH-B + CH-C", "CH-A + CH-B + CH-C"]
LIST_APRSLEVEL = ["-10.5dB", "-9.0dB", "-7.5dB", "-6.0dB",
                  "-4.5dB", "-3.0dB", "-1.5dB", "0dB"]
LIST_APRESMICEMODE = ["M0: Off Duty", "M1: En Route", "M2: In Service",
                      "M3: Returning", "M4: Committed", "M5: Special",
                      "M6: Priority", "Emergency"]
LIST_APRSPTTDELAY = LIST_DELAY = ["%s ms" % x for x in range(200, 650, 50)]
LIST_APRSPTTPRIORITY = ["Call", "APRS"]
LIST_APRSSMARTBEACON = ["Off", "Type 1", "Type 2", "Type 3"]
LIST_APRSSTATIONMODE = ["Fixed", "GPS"]
LIST_APRSSYMBOLS = chirp_common.APRS_SYMBOLS + \
    ("| TNC Stream Sw", "}", "~ TNC Stream Sw")
LIST_APRSSYMBOLTABLE = ["/", "\\"]
LIST_AREA = ["A", "B", "C"]
LIST_AREAMODE = ["Frequency", "Channel", "Zone"]
LIST_AREASHOW = ["Channel Number", "Frequency"]
LIST_BCL = ["Off", "Carrier Match", "CTC/DCS Match"]
LIST_BRIGHTNESS = ["%s" % x for x in range(0, 5, 1)]
LIST_COLOR = ["Blue", "Green", "Red", "Yellow", "White",
              "Fuchsia", "Pink", "Orange", "Tomato", "Cyan", "Golden"]
LIST_DCSENCRYPT = ["Standard", "Encrypt 1",
                   "Encrypt 2", "Encrypt 3", "Mute Code"]
LIST_DELAY = ["%s ms" % x for x in range(0, 2100, 100)]
LIST_DENOISE = ["Off", "On", "840-1000MHz"]
LIST_DETECTRANGE = ["18-64 MHz", "64-136 MHz", "136-174 MHz", "174-240 MHz",
                    "240-320 MHz", "320-400 MHz", "400-480 MHz", "480-560 MHz",
                    "560-620 MHz", "840-920 MHz", "920-1000 MHz"]
LIST_DIRECTION = ["Up", "Down"]
LIST_DTMFMODE = ["Off", "TX Start", "TX End"]
LIST_DTMFSELECT = ["DTMF-%s" % x for x in range(1, 17)]
LIST_FREQINPUT = ["6 digit", "8 digit"]
LIST_FREQSTEP = ["0.25K", "1.25K", "2.5K", "5K", "6.25K", "10K", "12.5K",
                 "20K", "25K", "50K", "100K", "500K", "1M", "5M"]
LIST_GPSALT = ["m", "foot"]
LIST_GPSBAUD = ["4800", "9600", "14400", "19200", "38400",
                "56000", "57600", "115200", "128000", "256000"]
LIST_GPSCOORD = ["degree", "degree.min", "degree.min.sec"]
LIST_GPSDIST = ["km", "n mile", "mile"]
LIST_GPSLATDIR = ["N", "S"]
LIST_GPSLONGDIR = ["E", "W"]
LIST_GPSMILEAGE = ["Startup Zero", "Keep"]
LIST_GPSSPEED = ["km/h", "knot", "mph"]
LIST_GPSUTC = ["UTC 0", "UTC+1", "UTC+2", "UTC+3",
               "UTC+3.5", "UTC+4", "UTC+5", "UTC+5.5"] + \
              ["UTC+%s" % x for x in range(6, 13, 1)] + \
              ["UTC-%s" % x for x in range(1, 13, 1)]
LIST_INTERVAL = ["%s ms" % x for x in range(30, 210, 10)]
LIST_KEYDEFINE = ["None", "Monitor", "Power Switch", "Scanning", "VOX",
                  "Squelch", "Frequency Step", "Multi Standby", "Tx Priority",
                  "Roger Beep", "FM Radio", "Talkaround", "Alarm",
                  "Send Single Tone", "Frequency Detect", "CTC/DCS Scan",
                  "Spectrum", "Radio Sleep", "Query Status", "Save Channel",
                  "Rx Demodulation", "NOAA Channels", "LCD On-Off",
                  "LCD Brightness", "Key LED On-Off", "U/V Repeater", "GPS",
                  "GPS Manual REC", "GPS Track Query", "APRS Beacon REC",
                  "Zone Selection", "Work Range"]
LIST_LIMITRXTX = ["Rx+Tx", "Only Rx", "Only Tx"]
LIST_LOCK = ["Unlock", "Rx Only", "Lock"]
LIST_SAVEMODE = ["Off", "1:1", "1:2", "1:3"]
LIST_SCANMODE = ["CO", "TO", "SE"]
LIST_SCANRETURN = ["Original Channel", "Current Channel"]
LIST_SCANTIMER = ["Off"] + ["%s seconds" % x for x in range(1, 31, 1)]
LIST_SCRAMBLER = ["Off"] + ["%s" % x for x in range(1, 9, 1)]
LIST_TAILTONE = ["Off", "55Hz No Shift",
                 "120° Shift", "180° Shift", "240° Shift", ]
LIST_TALKAROUND = ["Off", "Talkaround", "Invert Frequency"]
LIST_TIMER = ["Off", "5 seconds", "10 seconds"] + [
    "%s seconds" % x for x in range(15, 615, 15)]
LIST_TXENDTONE = ["Off", "Roger Beep 1",
                  "Roger Beep 2", "Send Radio Name", "Send GPS"]
LIST_TXPRI = ["Edit", "Busy"]
LIST_WORKRANGE = ["64-620MHz", "18-64MHz", "840-1000MHz"]

VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"
DTMF_CHARS = list("0123456789ABCD*#")
HEX_CHARS = "0123456789ABCDEF"


class MemoryRegions(Enum):
    """
    Defines the logical memory regions for this radio model.
    """
    settingData = 0
    channelData = 1
    zoneData = 2
    fmData = 3


MEMORY_REGIONS_RANGES = {
    # (Start addr, length in blocks, region id)
    MemoryRegions.settingData: (0x0000,  4,   0x90),
    MemoryRegions.channelData: (0x2000,  48,  0x91),
    MemoryRegions.zoneData:    (0x1a000, 128, 0x92),
    MemoryRegions.fmData:      (0xd4000, 4,   0x99),
}


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">BH", ord(b'R'), block_addr)
    ccs = bytes([checksum.checksum_8bit(cmd)])

    expectedresponse = b"R" + cmd[1:]

    cmd = cmd + ccs

    LOG.debug("Reading block %04x..." % block_addr)

    try:
        serial.write(cmd)
        response = serial.read(3 + block_size + 1)

        cs = checksum.checksum_8bit(response[:-1])

        if response[:3] != expectedresponse:
            raise Exception("Error reading block %04x." % block_addr)

        chunk = response[3:]

        if chunk[-1] != cs:
            raise Exception("Block failed checksum!")

        block_data = chunk[:-1]
    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_number, block_size, region, data):
    serial = radio.pipe

    # map the upload address to the mmap start and end addresses
    start_addr = block_number * block_size
    end_addr = start_addr + block_size

    block_data = data[start_addr:end_addr]

    cmd = struct.pack(">BH", region, block_number)

    cs = bytes([checksum.checksum_8bit(cmd + block_data)])
    block_data += cs

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + block_data))

    try:
        serial.write(cmd + block_data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_number)


def do_download(radio):
    LOG.debug("download")

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio.END_ADDR

    for addr in range(radio.START_ADDR, radio.END_ADDR, 1):
        status.cur = addr
        radio.status_fn(status)

        block = _read_block(radio, addr + radio.READ_OFFSET, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    status.cur = 0
    status.max = get_total_upload_blocks()

    # The OEM software reads the 1st block from the radio before commencing
    # with the upload. That behavior will be mirrored here.
    _read_block(radio, radio.START_ADDR, radio.BLOCK_SIZE)

    data_bytes = radio.get_mmap()

    for item in MemoryRegions:
        _, length, regionId = MEMORY_REGIONS_RANGES[item]
        item_bytes = get_bytes_for_region(data_bytes, item, radio.BLOCK_SIZE)

        for block in range(0, length):
            status.cur += 1
            radio.status_fn(status)
            _write_block(radio, block, radio.BLOCK_SIZE, regionId, item_bytes)


def get_bytes_for_region(all_bytes: bytearray, item, blockSize):
    start, length, _ = MEMORY_REGIONS_RANGES[item]
    return all_bytes[start:start+(length*blockSize)]


def get_total_upload_blocks():
    return sum(length for _, length, _ in MEMORY_REGIONS_RANGES.values())


class RT880GBank(chirp_common.NamedBank):

    def get_name(self):
        _bank = self._model._radio._memobj.zones[self.index]
        return str(_bank.name).rstrip().replace("\xFF", "")

    def set_name(self, name):
        _bank = self._model._radio._memobj.zones[self.index]
        _bank.name = str(name)[:16].rstrip().ljust(16, '\xFF')


class RT880GBankModel(chirp_common.BankModel):

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.zones
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = RT880GBank(self, "%i" % index, "b%i" % (index + 1))
            bank.index = index
            bank_mappings.append(bank)

        return bank_mappings

    def _get_channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.zones[bank.index].channel_count1 > 0
        if not _bank_used:
            return set()

        _members = self._radio._memobj.zones[bank.index].channels
        return set([int(ch) + 1 for ch in _members if ch != 0xFFFF])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _zone = self._radio._memobj.zones[bank.index]
        if len(channels_in_bank) > len(_zone.channels):
            raise Exception("Too many entries in bank %d" % bank.index)

        _channel_count = len(channels_in_bank)
        _zone.channel_count1 = _channel_count
        _zone.channel_count2 = _channel_count

        for index, item in enumerate(channels_in_bank):
            _zone.channels[index] = item - 1

        for index in range(_channel_count, len(_zone.channels)):
            _zone.channels[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._get_channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._get_channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


@directory.register
class RT880G(chirp_common.CloneModeRadio):
    """Radtel RT-880G"""
    VENDOR = "Radtel"
    MODEL = "RT-880G"
    NAME_LENGTH = 16
    BAUD_RATE = 115200

    _channelCount = 1024

    _airband = (108000000, 135999999)
    _work_range_1 = (64000000, 620000000)
    _work_range_2 = (18000000, 64000000)
    _work_range_3 = (840000000, 1000000000)

    SPECIALS = {
        "VFO UV-A": (_channelCount + 1, _work_range_1),
        "VFO UV-B": (_channelCount + 2, _work_range_1),
        "VFO UV-C": (_channelCount + 3, _work_range_1),
        "VFO CB-A": (_channelCount + 4, _work_range_2),
        "VFO CB-B": (_channelCount + 5, _work_range_2),
        "VFO CB-C": (_channelCount + 6, _work_range_2),
        "VFO 850-A": (_channelCount + 7, _work_range_3),
        "VFO 850-B": (_channelCount + 8, _work_range_3),
        "VFO 850-C": (_channelCount + 9, _work_range_3),
    }

    BLOCK_SIZE = 0x400
    magic_enter = b"4R" + b"\x05\x10\x9b"
    magic_exit = b"4R" + b"\x05\xEE\x79"

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                    chirp_common.PowerLevel("Medium", watts=5),
                    chirp_common.PowerLevel("High", watts=10)]

    # Radio's write address starts at 0x0000
    # Radio's write address ends at 0x0140
    START_ADDR = 0
    END_ADDR = 0x035b
    # Radio's read address starts at 0x7820
    # Radio's read address ends at 0x795F
    READ_OFFSET = 0x0008

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split"]
        # SSB is included as USB here since SSB isn't in the master list
        # of chirp modes
        rf.valid_modes = ["FM", "NFM", "AM", "USB"]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.memory_bounds = (1, self._channelCount)
        rf.has_nostep_tuning = True
        rf.valid_bands = [self._work_range_2, self._work_range_1,
                          self._work_range_3]
        rf.valid_special_chans = list(self.SPECIALS.keys())

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            enter_programming_mode(self.pipe, self.magic_enter)
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        finally:
            exit_programming_mode(self.pipe, self.magic_exit)

        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            enter_programming_mode(self.pipe, self.magic_enter)
            self.pipe.timeout = 1
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        finally:
            self.pipe.timeout = 0.25
            exit_programming_mode(self.pipe, self.magic_exit)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_bank_model(self):
        return RT880GBankModel(self)

    @staticmethod
    def _decode_tone(tone: bitwise.structDataElement):
        if not tone.is_dtcs and not tone.tone_or_inverted:
            return '', None, None
        elif tone.is_dtcs and tone.tone_or_inverted:
            code = int('%o' % tone.tone_val)
            return 'DTCS', code, 'R'
        elif tone.is_dtcs and not tone.tone_or_inverted:
            code = int('%o' % tone.tone_val)
            return 'DTCS', code, 'N'
        elif not tone.is_dtcs and tone.tone_or_inverted:
            return 'Tone', (tone.tone_val / 10.0), None
        else:
            raise errors.RadioError('Unsupported tone value')

    @staticmethod
    def _encode_tone(mode, val, pol):
        if not mode:
            return 0, 0, 0
        elif mode == 'Tone':
            code = int(val * 10)
            return 0, 1, code
        elif mode == 'DTCS':
            code = int('%i' % val, 8)
            inverted = 0
            if pol == 'R':
                inverted = 1
            return 1, inverted, code
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return getattr(
                self._memobj.vfo,
                number.lower().replace(" ", "_").replace("-", "_"))
        elif number > self._channelCount:
            for k, v in list(self.SPECIALS.items()):
                ch_num, _ = v
                if number == ch_num:
                    return getattr(
                        self._memobj.vfo,
                        k.lower().replace(" ", "_").replace("-", "_"))
        else:
            return self._memobj.channels[number - 1]

    def get_memory(self, number):
        _mem = self._get_memobjs(number)
        mem = chirp_common.Memory()
        if isinstance(number, str):
            ch_num, _ = self.SPECIALS[number]
            mem.number = ch_num
            mem.extd_number = number
        else:
            mem.number = number

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # TX freq set
        offset = (int(_mem.txfreq) * 10) - mem.freq
        if offset != 0:
            if chirp_common.is_split(self.get_features().valid_bands,
                                     mem.freq, int(_mem.txfreq) * 10):
                mem.duplex = "split"
                mem.offset = int(_mem.txfreq) * 10
            elif offset < 0:
                mem.offset = abs(offset)
                mem.duplex = "-"
            elif offset > 0:
                mem.offset = offset
                mem.duplex = "+"
        else:
            mem.offset = 0

        mem.name = str(_mem.name).rstrip(" ").replace("\xFF", "")

        mem.mode = _mem.isnarrow and "NFM" or "FM"

        chirp_common.split_tone_decode(mem,
                                       self._decode_tone(_mem.tx_tone),
                                       self._decode_tone(_mem.rx_tone))

        # mode
        if _mem.rx_mode == 0x02:
            mem.mode = "USB"
        elif _mem.rx_mode == 0x01:
            mem.mode = "AM"
        elif _mem.rx_mode == 0x00 and _mem.isnarrow == 0x01:
            mem.mode = "NFM"
        else:
            mem.mode = "FM"

        # power
        if _mem.power == 0x02:
            mem.power = self.POWER_LEVELS[2]
        elif _mem.power == 0x01:
            mem.power = self.POWER_LEVELS[1]
        else:
            mem.power = self.POWER_LEVELS[0]

        if _mem.scan_remove:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSettingValueList(
            LIST_DCSENCRYPT, current_index=_mem.dcs_encrypt)
        rset = RadioSetting("dcs_encrypt", "DCS Encrypt", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueString(
            0, 8, f"{_mem.mutecode.get_value():x}".upper(), False, HEX_CHARS)
        rset = RadioSetting("mutecode", "Mute Code", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(
            LIST_TAILTONE, current_index=_mem.tail_tone)
        rset = RadioSetting("tail_tone", "Tail Tone", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(
            LIST_SCRAMBLER, current_index=_mem.scrambler)
        rset = RadioSetting("scrambler", "Scrambler", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(
            LIST_BCL, current_index=_mem.bcl if _mem.bcl <= 2 else 0)
        rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(
            LIST_LIMITRXTX, current_index=_mem.limit_rx_tx)
        rset = RadioSetting("limit_rx_tx", "Limit Rx/Tx", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(
            LIST_TIMER, current_index=_mem.tot)
        rset = RadioSetting("tot", "Time Out Timer", rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
        _mem = self._get_memobjs(mem.number)

        # if empty memory
        if mem.empty:
            _mem.set_raw("\xFF" * 48)
            return

        _mem.set_raw("\x00" * 32 + "\x20" * 16)

        _mem.enabled = 0x01

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.name = mem.name.rstrip(' ').ljust(self.NAME_LENGTH, '\xFF')

        _mem.scan_remove = mem.skip == "S"

        # mode
        if str(mem.mode) == "NFM":
            _mem.rx_mode = 0x00
            _mem.isnarrow = 0x01
        elif str(mem.mode) == "AM":
            _mem.rx_mode = 0x01
            _mem.isnarrow = 0x00
        elif str(mem.mode) == "USB":
            _mem.rx_mode = 0x02
            _mem.isnarrow = 0x00
        else:  # FM
            _mem.rx_mode = 0x00
            _mem.isnarrow = 0x00

        # power
        if str(mem.power) == str(self.POWER_LEVELS[2]):
            _mem.power = 0x02
        elif str(mem.power) == str(self.POWER_LEVELS[1]):
            _mem.power = 0x01
        else:
            _mem.power = 0x00

        # tones
        txtone, rxtone = chirp_common.split_tone_encode(mem)

        is_dtcs, tone_or_inverted, tone_val = self._encode_tone(*txtone)
        _mem.tx_tone.is_dtcs = is_dtcs
        _mem.tx_tone.tone_or_inverted = tone_or_inverted
        _mem.tx_tone.tone_val = tone_val

        is_dtcs, tone_or_inverted, tone_val = self._encode_tone(*rxtone)
        _mem.rx_tone.is_dtcs = is_dtcs
        _mem.rx_tone.tone_or_inverted = tone_or_inverted
        _mem.rx_tone.tone_val = tone_val

        # extras
        for setting in mem.extra:
            if setting.get_name() == "mutecode":
                setattr(_mem, setting.get_name(), int(str(setting.value), 16))
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def validate_memory(self, mem):
        msgs = []

        # airband should always be AM
        if (chirp_common.in_range(mem.freq, [self._airband])
                and mem.mode != 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                'Frequency in this range requires AM mode'))

        # adjust VFO channels to their appropriate work range
        if mem.number > self._channelCount:
            _, work_range = self.SPECIALS[mem.extd_number]

            if not chirp_common.in_range(mem.freq, [work_range]):
                msgs.append(chirp_common.ValidationError(
                    'Frequency out of valid range'))

        return msgs + super().validate_memory(mem)

    def apply_string(self, setting, obj):
        """
        Callback for set_apply_callback to pad with 0xFF instead of spaces
        """
        length = len(str(setting.value))
        setattr(obj, setting.get_name().rsplit('.', 1)[-1],
                str(setting.value).rstrip(' ').ljust(length, '\xFF'))

    def get_settings(self):
        basic = RadioSettingGroup("basic", "Basic Settings")
        startup = RadioSettingGroup("startup", "Startup Settings")
        keydefine = RadioSettingGroup("keydefine", "Key Define Settings")
        analog = RadioSettingGroup("analog", "Analog Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        gps = RadioSettingGroup("gps", "GPS Settings")
        aprs = RadioSettingGroup("aprs", "APRS Settings")
        time = RadioSettingGroup("time", "Time Settings")
        top = RadioSettings(basic, startup, keydefine, analog,
                            dtmf, gps, aprs, time)
        try:
            self.get_basic_settings(basic)
            self.get_startup_settings(startup)
            self.get_keydefine_settings(keydefine)
            self.get_analog_settings(analog)
            self.get_dtmf_settings(dtmf)
            self.get_gps_settings(gps)
            self.get_aprs_settings(aprs)
            self.get_time_settings(time)
        except Exception as e:
            LOG.exception("Error getting settings: %s", e)
        return top

    def get_basic_settings(self, group):
        _settings = self._memobj.settings
        _settings2 = self._memobj.settings2

        # Name/Callsign
        _codeobj = _settings.name_callsign
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 16, _code, True)
        rset = RadioSetting("name_callsign", "Name/Callsign", rs)
        rset.set_apply_callback(self.apply_string, _settings)
        group.append(rset)

        # Voice Prompt
        rs = RadioSettingValueBoolean(_settings.voice_prompt)
        rset = RadioSetting("voice_prompt", "Voice Prompt", rs)
        group.append(rset)

        # Key Beep
        rs = RadioSettingValueBoolean(_settings.key_beep)
        rset = RadioSetting("key_beep", "Key Beep", rs)
        group.append(rset)

        # Key Lock Timer
        rs = RadioSettingValueList(
            LIST_TIMER, current_index=_settings.lock_timer)
        rset = RadioSetting("lock_timer", "Key Lock Timer", rs)
        group.append(rset)

        # Key LED
        rs = RadioSettingValueBoolean(_settings.key_led)
        rset = RadioSetting("key_led", "Key LED", rs)
        group.append(rset)

        # Display Timer
        rs = RadioSettingValueList(
            LIST_TIMER, current_index=_settings.lcd_timer)
        rset = RadioSetting("lcd_timer", "Display Timer", rs)
        group.append(rset)

        # LCD Brightness
        rs = RadioSettingValueList(
            LIST_BRIGHTNESS, current_index=_settings.brightness)
        rset = RadioSetting("brightness", "LCD Brightness", rs)
        group.append(rset)

        # Menu Exit Timer
        rs = RadioSettingValueList(
            LIST_TIMER, current_index=_settings.menu_exit)
        rset = RadioSetting("menu_exit", "Menu Exit Timer", rs)
        group.append(rset)

        # Tx Priority
        rs = RadioSettingValueList(
            LIST_TXPRI, current_index=_settings.tx_priority)
        rset = RadioSetting("tx_priority", "Tx Priority", rs)
        group.append(rset)

        # Frequency Step
        rs = RadioSettingValueList(
            LIST_FREQSTEP, current_index=_settings.freq_step)
        rset = RadioSetting("freq_step", "Frequency Step", rs)
        group.append(rset)

        # Talkaround
        rs = RadioSettingValueList(
            LIST_TALKAROUND, current_index=_settings.talkaround)
        rset = RadioSetting("talkaround", "Talkaround", rs)
        group.append(rset)

        # Save Mode
        rs = RadioSettingValueList(
            LIST_SAVEMODE, current_index=_settings.save_mode)
        rset = RadioSetting("save_mode", "Save Mode", rs)
        group.append(rset)

        # Save Start Timer
        rs = RadioSettingValueList(
            LIST_TIMER, current_index=_settings.save_start_timer)
        rset = RadioSetting("save_start_timer", "Save Start Timer", rs)
        group.append(rset)

        # Scan Mode
        rs = RadioSettingValueList(
            LIST_SCANMODE, current_index=_settings.scan_mode)
        rset = RadioSetting("scan_mode", "Scan Mode", rs)
        group.append(rset)

        # Scan Direction
        rs = RadioSettingValueList(
            LIST_DIRECTION, current_index=_settings.scan_direction)
        rset = RadioSetting("scan_direction", "Scan Direction", rs)
        group.append(rset)

        # Scan Return
        rs = RadioSettingValueList(
            LIST_SCANRETURN, current_index=_settings.scan_return)
        rset = RadioSetting("scan_return", "Scan Return", rs)
        group.append(rset)

        # Scan Dwell Timer
        rs = RadioSettingValueList(
            LIST_SCANTIMER, current_index=_settings.scan_dwell_timer)
        rset = RadioSetting("scan_dwell_timer", "Scan Dwell Timer", rs)
        group.append(rset)

        # Alarm Type
        rs = RadioSettingValueList(
            LIST_ALARMTYPE, current_index=_settings.alarm_type)
        rset = RadioSetting("alarm_type", "Alarm Type", rs)
        group.append(rset)

        # Work Range
        rs = RadioSettingValueList(
            LIST_WORKRANGE, current_index=_settings.work_range)
        rset = RadioSetting("work_range", "Work Range", rs)
        group.append(rset)

        # Denoise
        rs = RadioSettingValueList(
            LIST_DENOISE, current_index=_settings.denoise)
        rset = RadioSetting("denoise", "Denoise", rs)
        group.append(rset)

        # Multi Standby
        rs = RadioSettingValueBoolean(_settings.multi_standby)
        rset = RadioSetting("multi_standby", "Multi Standby", rs)
        group.append(rset)

        # U/V Repeater
        rs = RadioSettingValueBoolean(_settings.uv_repeater)
        rset = RadioSetting("uv_repeater", "U/V Repeater", rs)
        group.append(rset)

        # Repeater Monitor
        rs = RadioSettingValueBoolean(_settings.repeater_monitor)
        rset = RadioSetting("repeater_monitor", "Repeater Monitor", rs)
        group.append(rset)

        # NOAA Monitor
        rs = RadioSettingValueBoolean(_settings.noaa_monitor)
        rset = RadioSetting("noaa_monitor", "NOAA Monitor", rs)
        group.append(rset)

        # Frequency Input
        rs = RadioSettingValueList(
            LIST_FREQINPUT, current_index=_settings.freq_input)
        rset = RadioSetting("freq_input", "Frequency Input", rs)
        group.append(rset)

        # Reverse Channel
        rs = RadioSettingValueBoolean(_settings2.reverse_channel)
        rset = RadioSetting("settings2.reverse_channel", "Reverse Channel", rs)
        group.append(rset)

        # CT/DCS Code Show
        rs = RadioSettingValueBoolean(_settings2.ctdcs_code_show)
        rset = RadioSetting("settings2.ctdcs_code_show",
                            "CT/DCS Code Show", rs)
        group.append(rset)

        # Channel Alias Color
        rs = RadioSettingValueList(
            LIST_COLOR, current_index=_settings2.ch_alias_color)
        rset = RadioSetting("settings2.ch_alias_color",
                            "Channel Alias Color", rs)
        group.append(rset)

        # Tx Limit
        rs = RadioSettingValueBoolean(_settings2.tx_unlimit)
        rset = RadioSetting("settings2.tx_unlimit", "Tx Limit", rs)
        group.append(rset)

        area_group = RadioSettingGroup("basic_area", "Areas")
        group.append(area_group)

        def apply_with_offset(setting, obj, offset):
            setattr(obj, setting.get_name(), int(setting.value) + offset)

        # Current Area
        rs = RadioSettingValueList(
            LIST_AREA, current_index=_settings.current_area)
        rset = RadioSetting("current_area", "Current Area", rs)
        area_group.append(rset)

        # Area A Mode
        rs = RadioSettingValueList(
            LIST_AREAMODE, current_index=_settings.area_a_mode)
        rset = RadioSetting("area_a_mode", "Area A Mode", rs)
        area_group.append(rset)

        # Area A Show
        rs = RadioSettingValueList(
            LIST_AREASHOW, current_index=_settings.area_a_show)
        rset = RadioSetting("area_a_show", "Area A Show", rs)
        area_group.append(rset)

        # Area A Zone
        rs = RadioSettingValueInteger(1, 256, _settings.area_a_zone + 1)
        rset = RadioSetting("area_a_zone", "Area A Zone", rs)
        rset.set_doc('Value between 1-256')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        # Area A Channel
        rs = RadioSettingValueInteger(1, self._channelCount,
                                      _settings.area_a_channel + 1)
        rset = RadioSetting("area_a_channel", "Area A Channel", rs)
        rset.set_doc(f'Value between 1-{self._channelCount}')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        # Area B Mode
        rs = RadioSettingValueList(
            LIST_AREAMODE, current_index=_settings.area_b_mode)
        rset = RadioSetting("area_b_mode", "Area B Mode", rs)
        area_group.append(rset)

        # Area B Show
        rs = RadioSettingValueList(
            LIST_AREASHOW, current_index=_settings.area_b_show)
        rset = RadioSetting("area_b_show", "Area B Show", rs)
        area_group.append(rset)

        # Area B Zone
        rs = RadioSettingValueInteger(1, 256, _settings.area_b_zone + 1)
        rset = RadioSetting("area_b_zone", "Area B Zone", rs)
        rset.set_doc('Value between 1-256')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        # Area B Channel
        rs = RadioSettingValueInteger(1, self._channelCount,
                                      _settings.area_b_channel + 1)
        rset = RadioSetting("area_b_channel", "Area B Channel", rs)
        rset.set_doc(f'Value between 1-{self._channelCount}')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        # Area C Mode
        rs = RadioSettingValueList(
            LIST_AREAMODE, current_index=_settings.area_c_mode)
        rset = RadioSetting("area_c_mode", "Area C Mode", rs)
        area_group.append(rset)

        # Area C Show
        rs = RadioSettingValueList(
            LIST_AREASHOW, current_index=_settings.area_c_show)
        rset = RadioSetting("area_c_show", "Area C Show", rs)
        area_group.append(rset)

        # Area C Zone
        rs = RadioSettingValueInteger(1, 256, _settings.area_c_zone + 1)
        rset = RadioSetting("area_c_zone", "Area C Zone", rs)
        rset.set_doc('Value between 1-256')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        # Area C Channel
        rs = RadioSettingValueInteger(1, self._channelCount,
                                      _settings.area_c_channel + 1)
        rset = RadioSetting("area_c_channel", "Area C Channel", rs)
        rset.set_doc(f'Value between 1-{self._channelCount}')
        rset.set_apply_callback(apply_with_offset, _settings, -1)
        area_group.append(rset)

        lock_group = RadioSettingGroup("basic_lock", "Lock Ranges")
        group.append(lock_group)

        # Lock Range 1 Type
        rs = RadioSettingValueList(
            LIST_LOCK, current_index=_settings.lock_range_1_type)
        rset = RadioSetting("lock_range_1_type", "Lock Range 1 Type", rs)
        lock_group.append(rset)

        # Lock Range 1 Start
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_1_start)
        rset = RadioSetting("lock_range_1_start", "Lock Range 1 Start", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 1 End
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_1_end)
        rset = RadioSetting("lock_range_1_end", "Lock Range 1 End", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 2 Type
        rs = RadioSettingValueList(
            LIST_LOCK, current_index=_settings.lock_range_2_type)
        rset = RadioSetting("lock_range_2_type", "Lock Range 2 Type", rs)
        lock_group.append(rset)

        # Lock Range 2 Start
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_2_start)
        rset = RadioSetting("lock_range_2_start", "Lock Range 2 Start", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 2 End
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_2_end)
        rset = RadioSetting("lock_range_2_end", "Lock Range 2 End", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 3 Type
        rs = RadioSettingValueList(
            LIST_LOCK, current_index=_settings.lock_range_3_type)
        rset = RadioSetting("lock_range_3_type", "Lock Range 3 Type", rs)
        lock_group.append(rset)

        # Lock Range 3 Start
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_3_start)
        rset = RadioSetting("lock_range_3_start", "Lock Range 3 Start", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 3 End
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_3_end)
        rset = RadioSetting("lock_range_3_end", "Lock Range 3 End", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 4 Type
        rs = RadioSettingValueList(
            LIST_LOCK, current_index=_settings.lock_range_4_type)
        rset = RadioSetting("lock_range_4_type", "Lock Range 4 Type", rs)
        lock_group.append(rset)

        # Lock Range 4 Start
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_4_start)
        rset = RadioSetting("lock_range_4_start", "Lock Range 4 Start", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

        # Lock Range 4 End
        rs = RadioSettingValueInteger(18, 1000, _settings.lock_range_4_end)
        rset = RadioSetting("lock_range_4_end", "Lock Range 4 End", rs)
        rset.set_doc('Value between 18-1000 (MHz)')
        lock_group.append(rset)

    def get_startup_settings(self, group):
        _settings = self._memobj.settings

        # Welcome Message
        _codeobj = _settings.welcome_message
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 32, _code, True)
        rset = RadioSetting("welcome_message", "Welcome Message", rs)
        rset.set_apply_callback(self.apply_string, _settings)
        group.append(rset)

        # Welcome Message Enable
        rs = RadioSettingValueBoolean(_settings.welcome_message_enable)
        rset = RadioSetting("welcome_message_enable",
                            "Welcome Message Enable", rs)
        group.append(rset)

        # Welcome Message Color
        rs = RadioSettingValueInteger(0, 65536, _settings.welcome_text_color)
        rset = RadioSetting("welcome_text_color", "Welcome Message Color", rs)
        rset.set_doc('Value between 0-65536')
        group.append(rset)

        # Welcome Message Start Line
        rs = RadioSettingValueInteger(0, 319, _settings.welcome_start_line)
        rset = RadioSetting("welcome_start_line",
                            "Welcome Message Start Line", rs)
        rset.set_doc('Value between 0-319')
        group.append(rset)

        # Welcome Message Start Column
        rs = RadioSettingValueInteger(0, 239, _settings.welcome_start_column)
        rset = RadioSetting("welcome_start_column",
                            "Welcome Message Start Column", rs)
        rset.set_doc('Value between 0-239')
        group.append(rset)

        # Startup Image Enable
        rs = RadioSettingValueBoolean(_settings.startup_image_enable)
        rset = RadioSetting("startup_image_enable",
                            "Startup Image Enable", rs)
        group.append(rset)

        # Startup Ringtone Enable
        rs = RadioSettingValueBoolean(_settings.startup_ringtone_enable)
        rset = RadioSetting("startup_ringtone_enable",
                            "Startup Ringtone Enable", rs)
        group.append(rset)

        # Startup Password
        _codeobj = _settings.startup_password
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 16, _code, True)
        rset = RadioSetting("startup_password", "Startup Password", rs)
        rset.set_apply_callback(self.apply_string, _settings)
        group.append(rset)

        # Startup Password Enable
        rs = RadioSettingValueBoolean(_settings.startup_password_enable)
        rset = RadioSetting("startup_password_enable",
                            "Startup Password Enable", rs)
        group.append(rset)

    def get_keydefine_settings(self, group):
        _settings = self._memobj.settings

        # Multi PTT
        rs = RadioSettingValueBoolean(_settings.multi_ptt)
        rset = RadioSetting("multi_ptt", "Multi PTT", rs)
        group.append(rset)

        # Side Key 1 Short
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.side_key_1_s)
        rset = RadioSetting("side_key_1_s", "Side Key 1 Short", rs)
        group.append(rset)

        # Side Key 1 Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.side_key_1_l)
        rset = RadioSetting("side_key_1_l", "Side Key 1 Long", rs)
        group.append(rset)

        # Side Key 2 Short
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.side_key_2_s)
        rset = RadioSetting("side_key_2_s", "Side Key 2 Short", rs)
        group.append(rset)

        # Side Key 2 Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.side_key_2_l)
        rset = RadioSetting("side_key_2_l", "Side Key 2 Long", rs)
        group.append(rset)

        # Alarm Key 2 Short
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.alarm_key_2_s)
        rset = RadioSetting("alarm_key_2_s", "Alarm Key 2 Short", rs)
        group.append(rset)

        # Alarm Key 2 Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.alarm_key_2_l)
        rset = RadioSetting("alarm_key_2_l", "Alarm Key 2 Long", rs)
        group.append(rset)

        # 0 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_0_long)
        rset = RadioSetting("key_0_long", "0 Press Long", rs)
        group.append(rset)

        # 1 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_1_long)
        rset = RadioSetting("key_1_long", "1 Press Long", rs)
        group.append(rset)

        # 2 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_2_long)
        rset = RadioSetting("key_2_long", "2 Press Long", rs)
        group.append(rset)

        # 3 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_3_long)
        rset = RadioSetting("key_3_long", "3 Press Long", rs)
        group.append(rset)

        # 4 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_4_long)
        rset = RadioSetting("key_4_long", "4 Press Long", rs)
        group.append(rset)

        # 5 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_5_long)
        rset = RadioSetting("key_5_long", "5 Press Long", rs)
        group.append(rset)

        # 6 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_6_long)
        rset = RadioSetting("key_6_long", "6 Press Long", rs)
        group.append(rset)

        # 7 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_7_long)
        rset = RadioSetting("key_7_long", "7 Press Long", rs)
        group.append(rset)

        # 8 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_8_long)
        rset = RadioSetting("key_8_long", "8 Press Long", rs)
        group.append(rset)

        # 9 Press Long
        rs = RadioSettingValueList(
            LIST_KEYDEFINE, current_index=_settings.key_9_long)
        rset = RadioSetting("key_9_long", "9 Press Long", rs)
        group.append(rset)

    def get_analog_settings(self, group):
        _settings = self._memobj.settings

        # Squelch Level
        rs = RadioSettingValueInteger(0, 10, _settings.squelch_level)
        rset = RadioSetting("squelch_level", "Squelch Level", rs)
        rset.set_doc('Value between 0-10')
        group.append(rset)

        # Tx Start Tone
        rs = RadioSettingValueBoolean(_settings.tx_start_tone)
        rset = RadioSetting("tx_start_tone", "Tx Start Tone", rs)
        group.append(rset)

        # Tx End Tone
        rs = RadioSettingValueList(
            LIST_TXENDTONE, current_index=_settings.tx_end_tone)
        rset = RadioSetting("tx_end_tone", "Tx End Tone", rs)
        group.append(rset)

        # Single Tone
        rs = RadioSettingValueInteger(0, 9999, _settings.single_tone)
        rset = RadioSetting("single_tone", "Single Tone (Hz)", rs)
        rset.set_doc('Value between 0-9999')
        group.append(rset)

        # VOX
        rs = RadioSettingValueBoolean(_settings.vox)
        rset = RadioSetting("vox", "VOX", rs)
        group.append(rset)

        # VOX Threshold
        rs = RadioSettingValueInteger(0, 254, _settings.vox_threshold)
        rset = RadioSetting("vox_threshold", "VOX Threshold", rs)
        rset.set_doc('Value between 0-254')
        group.append(rset)

        # VOX Delay
        rs = RadioSettingValueInteger(0, 5, _settings.vox_delay)
        rset = RadioSetting("vox_delay", "VOX Delay", rs)
        rset.set_doc('Value between 0-5')
        group.append(rset)

        # Detect Range
        rs = RadioSettingValueList(
            LIST_DETECTRANGE, current_index=_settings.detect_range)
        rset = RadioSetting("detect_range", "Detect Range", rs)
        group.append(rset)

        # Repeater Delay
        rs = RadioSettingValueList(
            LIST_DELAY, current_index=_settings.repeater_delay)
        rset = RadioSetting("repeater_delay", "Repeater Delay", rs)
        group.append(rset)

        # Mic Gain
        rs = RadioSettingValueInteger(0, 31, _settings.mic_gain)
        rset = RadioSetting("mic_gain", "Mic Gain", rs)
        rset.set_doc('Value between 0-31')
        group.append(rset)

        # FM Mode SPK Gain
        rs = RadioSettingValueInteger(0, 63, _settings.fm_spk_gain)
        rset = RadioSetting("fm_spk_gain", "FM Mode SPK Gain", rs)
        rset.set_doc('Value between 0-63')
        group.append(rset)

        # FM Mode DAC Gain
        rs = RadioSettingValueInteger(0, 15, _settings.fm_dac_gain)
        rset = RadioSetting("fm_dac_gain", "FM Mode DAC Gain", rs)
        rset.set_doc('Value between 0-15')
        group.append(rset)

        # AM Mode SPK Gain
        rs = RadioSettingValueInteger(0, 63, _settings.am_spk_gain)
        rset = RadioSetting("am_spk_gain", "AM Mode SPK Gain", rs)
        rset.set_doc('Value between 0-63')
        group.append(rset)

        # AM Mode DAC Gain
        rs = RadioSettingValueInteger(0, 15, _settings.am_dac_gain)
        rset = RadioSetting("am_dac_gain", "AM Mode DAC Gain", rs)
        rset.set_doc('Value between 0-15')
        group.append(rset)

        # Glitch Threshold
        rs = RadioSettingValueInteger(0, 10, _settings.glitch_threshold)
        rset = RadioSetting("glitch_threshold", "Glitch Threshold", rs)
        rset.set_doc('Value between 0-10')
        group.append(rset)

        # Voice Level Refresh
        rs = RadioSettingValueList(
            LIST_DELAY, current_index=_settings.tx_voice_refresh)
        rset = RadioSetting("tx_voice_refresh", "Voice Level Refresh", rs)
        group.append(rset)

        # RSSI Level Refresh
        rs = RadioSettingValueList(
            LIST_DELAY, current_index=_settings.rx_rssi_refresh)
        rset = RadioSetting("rx_rssi_refresh", "RSSI Level Refresh", rs)
        group.append(rset)

        tt_group = RadioSettingGroup("analog_tt", "Temporary Tuning")
        group.append(tt_group)

        # Temporary Tuning Rx Test
        rs = RadioSettingValueBoolean(_settings.tt_rx_test)
        rset = RadioSetting("tt_rx_test", "Rx Test", rs)
        tt_group.append(rset)

        # Temporary Tuning RSSI Threshold
        rs = RadioSettingValueInteger(0, 127, _settings.tt_rssi_threshold)
        rset = RadioSetting("tt_rssi_threshold", "RSSI Threshold", rs)
        rset.set_doc('Value between 0-127')
        tt_group.append(rset)

        # Temporary Tuning Noise Threshold
        rs = RadioSettingValueInteger(0, 127, _settings.tt_noise_threshold)
        rset = RadioSetting("tt_noise_threshold", "Noise Threshold", rs)
        rset.set_doc('Value between 0-127')
        tt_group.append(rset)

        # Temporary Tuning Power Test
        rs = RadioSettingValueBoolean(_settings.tt_power_test)
        rset = RadioSetting("tt_power_test", "Power Test", rs)
        tt_group.append(rset)

        # Temporary Tuning 136-174MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_136_174)
        rset = RadioSetting("tt_power_136_174", "136-174MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 400-480MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_400_480)
        rset = RadioSetting("tt_power_400_480", "400-480MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 18-64MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_18_64)
        rset = RadioSetting("tt_power_18_64", "18-64MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 64-136MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_64_136)
        rset = RadioSetting("tt_power_64_136", "64-136MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 173-240MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_173_240)
        rset = RadioSetting("tt_power_173_240", "173-240MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 240-320MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_240_320)
        rset = RadioSetting("tt_power_240_320", "240-320MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 320-400MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_320_400)
        rset = RadioSetting("tt_power_320_400", "320-400MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 480-560MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_480_560)
        rset = RadioSetting("tt_power_480_560", "480-560MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 560-620MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_560_620)
        rset = RadioSetting("tt_power_560_620", "560-620MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 840-920MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_840_920)
        rset = RadioSetting("tt_power_840_920", "840-920MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 920-1000MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_920_1000)
        rset = RadioSetting("tt_power_920_1000", "920-1000MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 1000-1080MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_1000_1080)
        rset = RadioSetting("tt_power_1000_1080", "1000-1080MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 1080-1160MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_1080_1160)
        rset = RadioSetting("tt_power_1080_1160", "1080-1160MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 1160-1240MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_1160_1240)
        rset = RadioSetting("tt_power_1160_1240", "1160-1240MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

        # Temporary Tuning 1240-1300MHz Power
        rs = RadioSettingValueInteger(0, 255, _settings.tt_power_1240_1300)
        rset = RadioSetting("tt_power_1240_1300", "1240-1300MHz Power", rs)
        rset.set_doc('Value between 0-255')
        tt_group.append(rset)

    def get_dtmf_settings(self, group):
        _dtmf = self._memobj.dtmf

        # DTMF Delay
        rs = RadioSettingValueList(
            LIST_DELAY, current_index=_dtmf.dtmf_delay)
        rset = RadioSetting("dtmf.dtmf_delay", "DTMF Delay", rs)
        group.append(rset)

        # DTMF Interval
        rs = RadioSettingValueList(
            LIST_INTERVAL, current_index=_dtmf.dtmf_interval)
        rset = RadioSetting("dtmf.dtmf_interval", "DTMF Interval", rs)
        group.append(rset)

        # DTMF Duration
        rs = RadioSettingValueList(
            LIST_INTERVAL, current_index=_dtmf.dtmf_duration)
        rset = RadioSetting("dtmf.dtmf_duration", "DTMF Duration", rs)
        group.append(rset)

        # DTMF Mode
        rs = RadioSettingValueList(
            LIST_DTMFMODE, current_index=_dtmf.dtmf_mode)
        rset = RadioSetting("dtmf.dtmf_mode", "DTMF Mode", rs)
        group.append(rset)

        # DTMF Select
        rs = RadioSettingValueList(
            LIST_DTMFSELECT, current_index=_dtmf.dtmf_select)
        rset = RadioSetting("dtmf.dtmf_select", "DTMF Select", rs)
        group.append(rset)

        # DTMF Display
        rs = RadioSettingValueBoolean(_dtmf.dtmf_display)
        rset = RadioSetting("dtmf.dtmf_display", "DTMF Display", rs)
        group.append(rset)

        # DTMF Tx Gain
        rs = RadioSettingValueInteger(0, 127, _dtmf.dtmf_tx_gain)
        rset = RadioSetting("dtmf.dtmf_tx_gain", "DTMF Tx Gain", rs)
        rset.set_doc('Value between 0-127')
        group.append(rset)

        # DTMF Rx Threshold
        rs = RadioSettingValueInteger(0, 63, _dtmf.dtmf_rx_threshold)
        rset = RadioSetting("dtmf.dtmf_rx_threshold", "DTMF Rx Threshold", rs)
        rset.set_doc('Value between 0-63')
        group.append(rset)

        # DTMF Control
        rs = RadioSettingValueBoolean(_dtmf.dtmf_control)
        rset = RadioSetting("dtmf.dtmf_control", "DTMF Control", rs)
        group.append(rset)

        # Time Calibrate
        rs = RadioSettingValueBoolean(_dtmf.time_calibrate)
        rset = RadioSetting("dtmf.time_calibrate", "Time Calibrate", rs)
        group.append(rset)

        def apply_code(setting, obj, length):
            code = ""
            for char in str(setting.value):
                if char in DTMF_CHARS:
                    code += char
                else:
                    code += ""
            obj.code_length = len(str(code))
            obj.code = code.ljust(length, chr(255))

        # DTMF Codes
        for i in range(0, 16):
            _codeobj = _dtmf.dtmf_codes[i].code
            _code = str(_codeobj).rstrip('\xFF')
            rs = RadioSettingValueString(0, 14, _code, False, DTMF_CHARS)
            rset = RadioSetting("dtmf.dtmf_codes/%i.code" % i,
                                "Code %i" % (i + 1), rs)
            rset.set_apply_callback(apply_code, _dtmf.dtmf_codes[i], 14)
            group.append(rset)

        # Remote Stun
        _codeobj = _dtmf.remote_stun.code
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 14, _code, False, DTMF_CHARS)
        rset = RadioSetting("dtmf.remote_stun", "Remote Stun", rs)
        rset.set_apply_callback(apply_code, _dtmf.remote_stun, 14)
        group.append(rset)

        # Remote Kill
        _codeobj = _dtmf.remote_kill.code
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 14, _code, False, DTMF_CHARS)
        rset = RadioSetting("dtmf.remote_kill", "Remote Kill", rs)
        rset.set_apply_callback(apply_code, _dtmf.remote_kill, 14)
        group.append(rset)

        # Remote Wake
        _codeobj = _dtmf.remote_wake.code
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 14, _code, False, DTMF_CHARS)
        rset = RadioSetting("dtmf.remote_wake", "Remote Wake", rs)
        rset.set_apply_callback(apply_code, _dtmf.remote_wake, 14)
        group.append(rset)

        # Remote Monitor
        _codeobj = _dtmf.remote_monitor.code
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 14, _code, False, DTMF_CHARS)
        rset = RadioSetting("dtmf.remote_monitor", "Remote Monitor", rs)
        rset.set_apply_callback(apply_code, _dtmf.remote_monitor, 14)
        group.append(rset)

    def get_gps_settings(self, group):
        _settings = self._memobj.settings
        _gps = self._memobj.gps

        # GPS Enable
        rs = RadioSettingValueBoolean(_settings.gps_enable)
        rset = RadioSetting("gps_enable", "GPS Enable", rs)
        group.append(rset)

        # GPS Baud Rate
        rs = RadioSettingValueList(
            LIST_GPSBAUD, current_index=_settings.gps_baud_rate)
        rset = RadioSetting("gps_baud_rate", "Baud Rate", rs)
        group.append(rset)

        # GPS UTC Zone
        rs = RadioSettingValueList(
            LIST_GPSUTC, current_index=_settings.gps_utc_zone)
        rset = RadioSetting("gps_utc_zone", "UTC Zone", rs)
        group.append(rset)

        # GPS Coordinate Type
        rs = RadioSettingValueList(
            LIST_GPSCOORD, current_index=_gps.gps_coord_type)
        rset = RadioSetting("gps.gps_coord_type", "Coordinate Type", rs)
        group.append(rset)

        # GPS Speed Unit
        rs = RadioSettingValueList(
            LIST_GPSSPEED, current_index=_gps.gps_speed_unit)
        rset = RadioSetting("gps.gps_speed_unit", "Speed Unit", rs)
        group.append(rset)

        # GPS Distance Unit
        rs = RadioSettingValueList(
            LIST_GPSDIST, current_index=_gps.gps_distance_unit)
        rset = RadioSetting("gps.gps_distance_unit", "Distance Unit", rs)
        group.append(rset)

        # GPS Altitude Unit
        rs = RadioSettingValueList(
            LIST_GPSALT, current_index=_gps.gps_altitude_unit)
        rset = RadioSetting("gps.gps_altitude_unit", "Altitude Unit", rs)
        group.append(rset)

        # GPS Mileage Type
        rs = RadioSettingValueList(
            LIST_GPSMILEAGE, current_index=_gps.gps_mileage_type)
        rset = RadioSetting("gps.gps_mileage_type", "Mileage Type", rs)
        group.append(rset)

        # GPS Auto Record
        rs = RadioSettingValueBoolean(_settings.gps_auto_record)
        rset = RadioSetting("gps_auto_record", "Auto Record", rs)
        group.append(rset)

        # Fixed coordinates are stored as strings with an implicit decimal
        def fixed_coord_to_float(val, wholeDigits):
            valStr = str(val).replace("-", "0").replace('\00', "0")
            return float(f"{valStr[:wholeDigits]}.{valStr[wholeDigits:]}")

        def apply_fixed_coord(setting, obj, width, precision):
            setattr(obj, setting.get_name()
                    .rsplit('.', 1)[-1],
                    f"{float(setting.value):0{width}.{precision}f}"
                    .replace(".", ""))

        def fixed_coord_dir_index(list, val):
            try:
                return list.index(str(val))
            except ValueError:
                return 0

        def apply_fixed_coord_dir(setting, obj, dirArray):
            setattr(obj, setting.get_name().rsplit('.', 1)[-1],
                    dirArray[int(setting.value)])

        # GPS Fixed Latitude
        val = fixed_coord_to_float(_gps.gps_fixed_lat, 2)
        rs = RadioSettingValueFloat(0, 99.99999, val, 0.00001, 5)
        rset = RadioSetting("gps.gps_fixed_lat", "Fixed Latitude", rs)
        rset.set_apply_callback(apply_fixed_coord, _gps, 8, 5)
        group.append(rset)

        # GPS Fixed Latitude Direction
        val = fixed_coord_dir_index(LIST_GPSLATDIR, _gps.gps_fixed_lat_dir)
        rs = RadioSettingValueList(LIST_GPSLATDIR, current_index=val)
        rset = RadioSetting("gps.gps_fixed_lat_dir",
                            "Fixed Latitude Direction", rs)
        rset.set_apply_callback(apply_fixed_coord_dir, _gps, LIST_GPSLATDIR)
        group.append(rset)

        # GPS Fixed Longitude
        val = fixed_coord_to_float(_gps.gps_fixed_long, 3)
        rs = RadioSettingValueFloat(0, 999.99999, val, 0.00001, 5)
        rset = RadioSetting("gps.gps_fixed_long", "Fixed Longitude", rs)
        rset.set_apply_callback(apply_fixed_coord, _gps, 9, 5)
        group.append(rset)

        # GPS Fixed Longitude Direction
        val = fixed_coord_dir_index(LIST_GPSLONGDIR, _gps.gps_fixed_long_dir)
        rs = RadioSettingValueList(LIST_GPSLONGDIR, current_index=val)
        rset = RadioSetting("gps.gps_fixed_long_dir",
                            "Fixed Longitude Direction", rs)
        rset.set_apply_callback(apply_fixed_coord_dir, _gps, LIST_GPSLONGDIR)
        group.append(rset)

        # GPS Fixed Altitude
        val = fixed_coord_to_float(_gps.gps_fixed_altitude, 6)
        rs = RadioSettingValueFloat(0, 999999.9, val, 0.1, 1)
        rset = RadioSetting("gps.gps_fixed_altitude", "Fixed Altitude", rs)
        rset.set_apply_callback(apply_fixed_coord, _gps, 8, 1)
        group.append(rset)

    def get_aprs_settings(self, group):
        _aprs = self._memobj.aprs

        # APRS Enable
        rs = RadioSettingValueBoolean(_aprs.aprs_enable)
        rset = RadioSetting("aprs.aprs_enable", "APRS Enable", rs)
        group.append(rset)

        # APRS Station Mode
        rs = RadioSettingValueList(
            LIST_APRSSTATIONMODE, current_index=_aprs.aprs_station_mode)
        rset = RadioSetting("aprs.aprs_station_mode", "Station Mode", rs)
        group.append(rset)

        # APRS Callsign
        _codeobj = _aprs.aprs_callsign
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_callsign", "Callsign", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        group.append(rset)

        # APRS SSID
        rs = RadioSettingValueList(
            chirp_common.APRS_SSID, current_index=_aprs.aprs_ssid)
        rset = RadioSetting("aprs.aprs_ssid", "SSID", rs)
        group.append(rset)

        # APRS Symbol Table
        rs = RadioSettingValueList(
            LIST_APRSSYMBOLTABLE, current_index=_aprs.aprs_symbol_table)
        rset = RadioSetting("aprs.aprs_symbol_table", "Symbol Table", rs)
        group.append(rset)

        # APRS Symbol
        rs = RadioSettingValueList(
            LIST_APRSSYMBOLS, current_index=_aprs.aprs_symbol)
        rset = RadioSetting("aprs.aprs_symbol", "Symbol", rs)
        group.append(rset)

        # APRS Comment
        _codeobj = _aprs.aprs_comment
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 128, _code, True)
        rset = RadioSetting("aprs.aprs_comment", "Comment", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        group.append(rset)

        # APRS MIC-E Enable
        rs = RadioSettingValueBoolean(_aprs.aprs_mice_enable)
        rset = RadioSetting("aprs.aprs_mice_enable", "MIC-E Enable", rs)
        group.append(rset)

        # APRS MIC-E Mode
        rs = RadioSettingValueList(
            LIST_APRESMICEMODE, current_index=_aprs.aprs_mice_mode)
        rset = RadioSetting("aprs.aprs_mice_mode", "MIC-E Mode", rs)
        group.append(rset)

        # APRS Path 1
        _codeobj = _aprs.aprs_path_1
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_path_1", "Path 1", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        group.append(rset)

        # APRS Path 1 Count
        rs = RadioSettingValueInteger(0, 9, _aprs.aprs_path_1_count)
        rset = RadioSetting("aprs.aprs_path_1_count", "Path 1 Count", rs)
        rset.set_doc('Value between 0-9')
        group.append(rset)

        # APRS Path 2
        _codeobj = _aprs.aprs_path_2
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_path_2", "Path 2", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        group.append(rset)

        # APRS Path 2 Count
        rs = RadioSettingValueInteger(0, 9, _aprs.aprs_path_2_count)
        rset = RadioSetting("aprs.aprs_path_2_count", "Path 2 Count", rs)
        rset.set_doc('Value between 0-9')
        group.append(rset)

        # APRS Tx Voltage
        rs = RadioSettingValueBoolean(_aprs.aprs_tx_voltage)
        rset = RadioSetting("aprs.aprs_tx_voltage", "Tx Voltage", rs)
        group.append(rset)

        # APRS Tx Star
        rs = RadioSettingValueBoolean(_aprs.aprs_tx_star)
        rset = RadioSetting("aprs.aprs_tx_star", "Tx Star", rs)
        group.append(rset)

        # APRS Tx Mileage
        rs = RadioSettingValueBoolean(_aprs.aprs_tx_mileage)
        rset = RadioSetting("aprs.aprs_tx_mileage", "Tx Mileage", rs)
        group.append(rset)

        # APRS Rx Channel
        rs = RadioSettingValueList(
            LIST_APRSCHANNEL, current_index=_aprs.aprs_rx_ch)
        rset = RadioSetting("aprs.aprs_rx_ch", "Rx Channel", rs)
        group.append(rset)

        # APRS Tx Channel
        rs = RadioSettingValueList(
            LIST_APRSCHANNELCOMBOS, current_index=_aprs.aprs_tx_ch)
        rset = RadioSetting("aprs.aprs_tx_ch", "Tx Channel", rs)
        group.append(rset)

        # APRS PTT Priority
        rs = RadioSettingValueList(
            LIST_APRSPTTPRIORITY, current_index=_aprs.aprs_ptt_priority)
        rset = RadioSetting("aprs.aprs_ptt_priority", "PTT Priority", rs)
        group.append(rset)

        # APRS PTT Delay
        rs = RadioSettingValueList(
            LIST_APRSPTTDELAY, current_index=_aprs.aprs_ptt_delay)
        rset = RadioSetting("aprs.aprs_ptt_delay", "PTT Delay", rs)
        group.append(rset)

        # APRS Beacon Popup
        rs = RadioSettingValueBoolean(_aprs.aprs_beacon_popup)
        rset = RadioSetting("aprs.aprs_beacon_popup", "Beacon Popup", rs)
        group.append(rset)

        # APRS Beacon After
        rs = RadioSettingValueList(
            LIST_APRSBEACONAFTER, current_index=_aprs.aprs_beacon_ptt_after)
        rset = RadioSetting("aprs.aprs_beacon_ptt_after", "Beacon After", rs)
        group.append(rset)

        # APRS Smart Beacon
        rs = RadioSettingValueList(
            LIST_APRSSMARTBEACON, current_index=_aprs.aprs_smart_beacon)
        rset = RadioSetting("aprs.aprs_smart_beacon", "Smart Beacon", rs)
        group.append(rset)

        # APRS Beacon Time Mode
        rs = RadioSettingValueBoolean(_aprs.aprs_beacon_time_mode)
        rset = RadioSetting("aprs.aprs_beacon_time_mode",
                            "Beacon Time Mode", rs)
        group.append(rset)

        # APRS Beacon Time
        rs = RadioSettingValueInteger(10, 99999999, _aprs.aprs_beacon_time)
        rset = RadioSetting("aprs.aprs_beacon_time", "Beacon Time", rs)
        rset.set_doc('Value between 10-99999999')
        group.append(rset)

        # APRS Queue Beacon
        rs = RadioSettingValueBoolean(_aprs.aprs_queue_beacon)
        rset = RadioSetting("aprs.aprs_queue_beacon", "Queue Beacon", rs)
        group.append(rset)

        # APRS Queue Interval
        rs = RadioSettingValueInteger(0, 59, _aprs.aprs_queue_interval)
        rset = RadioSetting("aprs.aprs_queue_interval", "Queue Interval", rs)
        rset.set_doc('Value between 0-59')
        group.append(rset)

        # APRS Demod Tone
        rs = RadioSettingValueBoolean(_aprs.aprs_demod_tone)
        rset = RadioSetting("aprs.aprs_demod_tone", "Demod Tone", rs)
        group.append(rset)

        # APRS Tx Level
        rs = RadioSettingValueList(
            LIST_APRSLEVEL, current_index=_aprs.aprs_tx_level)
        rset = RadioSetting("aprs.aprs_tx_level", "Tx Level", rs)
        group.append(rset)

        # APRS Rx Level
        rs = RadioSettingValueList(
            LIST_APRSLEVEL, current_index=_aprs.aprs_rx_level)
        rset = RadioSetting("aprs.aprs_rx_level", "Rx Level", rs)
        group.append(rset)

        # APRS Beacon Save
        rs = RadioSettingValueList(
            LIST_APRSBEACONSAVE, current_index=_aprs.aprs_beacon_save)
        rset = RadioSetting("aprs.aprs_beacon_save", "Beacon Save", rs)
        group.append(rset)

        # APRS Beacon After Channel
        rs = RadioSettingValueList(
            LIST_APRSCHANNELCOMBOS,
            current_index=_aprs.aprs_beacon_ptt_after_ch)
        rset = RadioSetting("aprs.aprs_beacon_ptt_after_ch",
                            "Beacon After Channel", rs)
        group.append(rset)

        # APRS Rx Channel Mute
        rs = RadioSettingValueBoolean(_aprs.aprs_rx_ch_mute)
        rset = RadioSetting("aprs.aprs_rx_ch_mute", "Rx Channel Mute", rs)
        group.append(rset)

        digi_group = RadioSettingGroup("aprs_digi", "Digipeater")
        group.append(digi_group)

        # APRS Digipeater Channel
        rs = RadioSettingValueList(
            LIST_APRSCHANNELCOMBOS, current_index=_aprs.aprs_digi_rep_ch)
        rset = RadioSetting("aprs.aprs_digi_rep_ch", "Channel", rs)
        digi_group.append(rset)

        # APRS Digipeater 1 Enable
        rs = RadioSettingValueBoolean(_aprs.aprs_digi_1_enable)
        rset = RadioSetting("aprs.aprs_digi_1_enable",
                            "Digipeater 1 Enable", rs)
        digi_group.append(rset)

        # APRS Digipeater 1 Name
        _codeobj = _aprs.aprs_digi_1_name
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_digi_1_name", "Digipeater 1 Name", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        digi_group.append(rset)

        # APRS Digipeater 2 Enable
        rs = RadioSettingValueBoolean(_aprs.aprs_digi_2_enable)
        rset = RadioSetting("aprs.aprs_digi_2_enable",
                            "Digipeater 2 Enable", rs)
        digi_group.append(rset)

        # APRS Digipeater 2 Name
        _codeobj = _aprs.aprs_digi_2_name
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_digi_2_name", "Digipeater 2 Name", rs)
        rset.set_apply_callback(self.apply_string, _aprs)
        digi_group.append(rset)

        # APRS Digipeater Wait Before Repeat
        rs = RadioSettingValueInteger(0, 9, _aprs.aprs_digi_wait_before_rep)
        rset = RadioSetting("aprs.aprs_digi_wait_before_rep",
                            "Wait Before Repeat", rs)
        rset.set_doc('Value between 0-9')
        digi_group.append(rset)

        # APRS Digipeater Remote Password
        _codeobj = _aprs.aprs_digi_remote_password
        _code = str(_codeobj).rstrip('\xFF')
        rs = RadioSettingValueString(0, 6, _code, True)
        rset = RadioSetting("aprs.aprs_digi_remote_password",
                            "Remote Password", rs)
        digi_group.append(rset)

    def get_time_settings(self, group):
        _settings = self._memobj.settings

        # Automatic Power Off
        rs = RadioSettingValueBoolean(_settings.auto_power_off)
        rset = RadioSetting("auto_power_off",
                            "Automatic Power Off", rs)
        group.append(rset)

        # Automatic Power Off Time
        rs = RadioSettingValueInteger(0, 235929599,
                                      _settings.auto_power_off_time)
        rset = RadioSetting("auto_power_off_time", "Auto Power Off Time", rs)
        rset.set_doc('Value between 0-235929599')
        group.append(rset)

        # Automatic Wake Up
        rs = RadioSettingValueBoolean(_settings.auto_wake_up)
        rset = RadioSetting("auto_wake_up",
                            "Automatic Wake Up", rs)
        group.append(rset)

        # Automatic Wake Up Time
        rs = RadioSettingValueInteger(0, 235929599,
                                      _settings.auto_wake_up_time)
        rset = RadioSetting("auto_wake_up_time", "Auto Wake Up Time", rs)
        rset.set_doc('Value between 0-235929599')
        group.append(rset)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
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
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name(), e)
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False
