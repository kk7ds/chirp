# Copyright 2026 chaffed
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

"""Baofeng DM-32UV (DMR) driver.

Channels, zones (as banks), DMR lists (radio IDs, contacts, RX groups),
scan lists and radio settings. Upload writes only the pages that differ
from the radio (see UPLOAD_TAGS), one whole aligned 4 KB page per write,
and reads every written page back. The layout was worked out from the
vendor CPS (v1.60) and radio firmware and checked against a real radio
(firmware DM32.01.01.047).

The radio keeps its codeplug in 4 KB flash pages whose last byte is a tag
naming the contents; pages move around as the radio rewrites them. The
image this driver stores is logical: one 4 KB slot per tag in IMAGE_TAGS,
in that order, each holding the page as read (tag byte included), or all
0xFF if the radio has no page with that tag.

The serial link on the tested cable flips bit 7 of about 1 received byte
in 1000 and the protocol has no checksums, so every block is read at
least three times and the copies are merged byte by byte.
"""

import collections
import functools
import logging
import struct
import time

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (RadioSetting, RadioSettingGroup, RadioSettings,
                            RadioSettingValueBoolean,
                            RadioSettingValueInteger, RadioSettingValueList,
                            RadioSettingValueString)

LOG = logging.getLogger(__name__)

PAGE = 0x1000
# The tags the vendor CPS reads (0x12-0x41 are the channel pages).
IMAGE_TAGS = ([0x02, 0x03, 0x04, 0x06, 0x0A, 0x0B, 0x0F, 0x10, 0x11] +
              list(range(0x12, 0x49)) + list(range(0x5C, 0x68)))
CH_TAG0 = 0x12
CH_BASE = IMAGE_TAGS.index(CH_TAG0) * PAGE
CH_SIZE, CH_PER_PAGE, CH_COUNT = 0x30, 85, 4000
VFO_OFFSETS = (0xF9F, 0xFCF)            # in the last channel page
# Zones (tags 0x5C-0x64): the CPS zone accessors (0x482740-0x482cd0) put
# zone z at page (z-1)//28, slot (z-1)%28 of 0x91 bytes, after a 16-byte
# header on the first page only. At most 250 zones of 64 members.
ZONE_TAG0 = 0x5C
ZONE_BASE = IMAGE_TAGS.index(ZONE_TAG0) * PAGE
ZONE_PER_PAGE, ZONE_COUNT, ZONE_MEMBERS = 28, 250, 64
# Longest zone order text on the Settings tab: "1, 2, ..., 250".
ZONE_ORDER_MAX = len(', '.join(str(z) for z in range(1, ZONE_COUNT + 1)))
# Encryption key names (CPS 0x479630): tag, offset of entry 1, entry size,
# name length, entries. Keys are chosen per channel, not edited.
DMR_LISTS = {
    'privacy': (0x10, 0x301, 0x2C, 10, 32),
    'emergency': (0x10, 0x000, 0x14, 10, 8),     # digital emergency systems
}
# DMR lists, from the CPS accessors (see PROTOCOL.md "DMR lists"):
# radio IDs (tag 0x67): count at 0, entry n at 16*n = u24 LE ID + 12-char name
RADIOID_TAG, RADIOID_MAX, RADIOID_NAME = 0x67, 250, 12
# contacts: index page 0x0B (u16 count, counts by call type, free-slot bitmap,
# name- and ID-sorted lists), 24-byte records on pages 0x44-0x48
CONTACT_INDEX_TAG, CONTACT_REC_TAG0 = 0x0B, 0x44
CONTACT_PER_PAGE, CONTACT_REC, CONTACT_MAX, CONTACT_NAME = 170, 0x18, 800, 16
CALL_TYPES = ['Private Call', 'Group Call', 'All Call']
# RX group lists (tag 0x0F): used-bitmap in bytes 0-3, group n at
# 0x6D*n - 0x5C: 11-char name, 32 member IDs (u24 LE)
RXG_TAG, RXG_MAX, RXG_NAME, RXG_MEMBERS, RXG_REC = 0x0F, 32, 11, 32, 0x6D
# Per-channel TX contact (CPS 0x480050), outside the channel record:
# 2 bytes per channel on tags 0x42/0x43, 12-bit contact number + digital flag
TXC_TAGS = (0x42, 0x43)
DMR_ID_MAX, ALL_CALL_ID = 16776415, 16777215
# Scan lists (tag 0x11; CPS 0x483050-0x484160): byte 0 = number of lists;
# list n at 0x39*n - 0x38: 11-char name, +0x0b member count, +0x0c CTC scan
# mode (low nibble) / TX mode (high nibble), +0x0d..+0x17 other options
# (kept as they are), +0x18 up to 16 u16 channel numbers. The members start
# in the first slot (checked on the radio's own display).
SCAN_TAG, SCAN_MAX, SCAN_REC, SCAN_NAME, SCAN_MEMBERS = 0x11, 32, 0x39, 11, 16
# [ScanCtcDcsMode]
SCAN_CTC_MODES = ['Not Detection CTC', 'Detection CTC Non Priority',
                  'Detection CTC Priority', 'Detection CTC']
SCAN_TX_MODES = ['Current Channel', 'Last Active Channel',    # [ScanTxMode]
                 'Designed Channel']
# options of the radio's factory scan lists; bytes 3-4 = designed channel
SCAN_DEFAULT_OPTS = bytes.fromhex('030600010000000000' '0a007f')

# Received bytes sometimes have this bit set when the radio sent it clear.
LINK_FAULT = 0x80
READ_COPIES, READ_TRIES = 3, 10

# The pages upload may write, in the order it writes them: lists before
# what refers to them (contact records before their index, lists before
# channels, zones last), so an interrupted upload leaves few dangling
# references. One whole aligned page per W frame: the firmware erases the
# sector on an aligned W and also erases the next sector if a W crosses
# into it. Tags 0x02 and 0x69 look like calibration: never written.
UPLOAD_TAGS = ([0x03, 0x04, 0x06, RADIOID_TAG] +
               list(range(CONTACT_REC_TAG0, CONTACT_REC_TAG0 + 5)) +
               [CONTACT_INDEX_TAG, RXG_TAG, SCAN_TAG] +
               list(range(0x12, 0x42)) + list(TXC_TAGS) +
               list(range(0x5C, 0x65)))
NEVER_WRITE = (0x02, 0x69)
WRITE_TRIES = 3

CHAN_FORMAT = """
// CTCSS: tenths of a Hz as 4 BCD digits (88.5 Hz = hundreds 0, tens 8,
// low 85). DCS: dcs set, the first octal digit in tens, the other two in
// low (D754I = dcs, inverted, tens 7, low 54). None: ff ff.
struct tone {
  lbcd low;
  u8 dcs:1, inverted:1, hundreds:2, tens:4;
};

struct chan {
  char name[16];
  lbcd rxfreq[4];
  lbcd txfreq[4];
  u8 chtype:4, forbid_tx:1, power:2, lone_work:1;
  u8 wide:1, auto_scan:1, scanlist:6;
  u8 forbid_talkaround:1, tx_admit:3, unknown1a:1, aprs_rx:1, offset_dir:2;
  u8 emerg_indicator:1, emerg_ack:1, unknown1b:1, emerg_system:5;
  u8 squelch:4, aprs_report:2, aprs_ptt_analog:1, aprs_ptt_digital:1;
  u8 private_confirm:1, short_data_confirm:1, tdma_direct:1, timeslot:1,
     colorcode:4;
  u8 privacy;
  u8 unknown1f:1, encrypt:1, rxgroup:6;
  u8 aprs_channel;
  struct tone rxtone;
  struct tone txtone;
  u8 unknown25:2, compander:1, vox:1, unknown25b:4;
  u8 ptt_id_display:1, rx_squelch_mode:3, signaling:3, unknown26:1;
  u8 rx_signal:4, tx_signal:4;
  u8 unknown28;
  u8 step:4, ptt_id:2, unknown29:2;
  u8 unknown2a;
  u8 radio_id;
  lbcd offset[4];
};

struct zone {
  char name[16];
  u8 count;
  ul16 members[64];
};
"""


SETTINGS_FORMAT = """
#seekto 0x%(b)x;
struct {
  u8 poweron_type;
  char line1[14];
  char line2[14];
  u8 unknown1d:7, allow_reset:1;
  u8 auto_power_off;
  u8 unknown1f;
  u8 radio_silent:1, key_tone:1, sms_alert:1, group_call_tone:1,
     private_call_tone:1, call_end_tone:1, talk_permit_tone:1,
     startup_sound:1;
  u8 voice_prompt:1, battery_low:1, tx_end_tone:2, unknown21:4;
} set_power;
#seekto 0x%(b30)x;
struct {
  u8 backlight;
  u8 auto_backlight;
  u8 menu_exit;
  u8 unknown33a:3, volume_prompt:1, date_format:1, unknown33b:2,
     time_display:1;
  u8 call_color;
  u8 standby_color;
  u8 tx_backlight;
  u8 rx_backlight;
  u8 a_name_color;
  u8 b_name_color;
  u8 a_zone_color;
  u8 b_zone_color;
} set_display;
#seekto 0x%(b40)x;
struct {
  u8 unknown40:1, gps_format:1, speed_unit:2, gps_mode:2, distance_unit:1,
     gps_switch:1;
  u8 time_zone;
  u8 measure_period;
  u8 unknown43[2];
  u8 unknown45:5, record_type:2, record_switch:1;
} set_gps;
#seekto 0x%(b60)x;
struct {
  u8 unknown60:6, group_match:1, private_match:1;
  u8 call_hold;
  u8 active_wait;
  u8 active_retries;
  u8 pre_carrier;
  u8 monitor_decode:1, disable_decode:1, check_decode:1, enable_decode:1,
     alert_decode:1, data_service:2, missed_call_alert:1;
  u8 monitor_time;
  u8 name_format:2, unknown67a:2, send_tx_name:1, name_priority:1,
     unknown67b:2;
} set_dmr;
#seekto 0x%(b80)x;
struct {
  u8 dual_watch:2, main_line:1, b_display:1, a_display:1, b_mode:1,
     a_mode:1, only_channel:1;
  u8 dual_watch_hang;
  u8 unknown82[3];
  u8 unknown85:4, forbid_lock:1, side_lock:1, knob_lock:1, lock_mode:1;
  u8 lock_delay;
  u8 key_sk1_short;
  u8 key_sk1_long;
  u8 key_sk2_short;
  u8 key_sk2_long;
  u8 key_tk_short;
  u8 key_tk_long;
  u8 key_p1_short;
  u8 key_p1_long;
  u8 key_p2_short;
  u8 key_p2_long;
  u8 key_p3_short;
  u8 key_p3_long;
  u8 long_press;
} set_work;
#seekto 0x%(ba0)x;
struct {
  u8 tot;
  u8 tot_pre;
  u8 vox_level;
  u8 vox_delay;
  u8 power_save:4, unknowna4:1, weather_alarm:1, language:1,
     disable_leds:1;
  u8 tbst:4, unknowna5:2, tail_mode:2;
  u8 mic_analog;
  u8 mic_digital;
} set_opts;
#seekto 0x%(b301)x;
struct {
  u8 send_interval;
  u8 unknown302:7, fixed_beacon:1;
  u8 unknown303[3];
  char latitude[9];
  u8 lat_hemi;
  char longitude[9];
  u8 lon_hemi;
  u8 unknown31a[4];
  ul16 report_channel[8];
  u8 unknown32e[2];
  u8 active_delay;
  u8 unknown331:7, call_type:1;
  ul24 upload_number;
} set_aprs;
#seekto 0x%(b500)x;
struct {
  u8 unknown500:6, new_zone:1, zone_list:1;
  u8 unknown501:2, measure_period:1, radio_disable:1, radio_enable:1,
     remote_monitor:1, radio_check:1, call_alert:1;
  u8 display_mode:1, match_group:1, match_private:1, lang_select:1,
     start_display:1, tx_power:1, alert_tone:1, talkaround:1;
  u8 unknown503a:1, record:1, aprs:1, gps:1, power_save:1,
     sub_channel_mode:1, unknown503b:2;
  u8 unknown504:1, csv_contacts:1, manual_dial:1, functionality:1,
     send_message:1, del_contact:1, edit_contact:1, add_contact:1;
  u8 unknown505:4, del_log:1, sent_call:1, answered_call:1, missed_call:1;
  u8 radio_name:1, radio_id:1, time_slot:1, color_code:1, tx_contact:1,
     ctc_dcs:1, tx_freq:1, rx_freq:1;
  u8 unknown507:3, channel_name:1, add_channel:1, rx_group:1,
     tdma_direct:1, channel_type:1;
} set_menu;
"""


# DTMF (tag 0x06; CPS dialog 0x421bc0, accessors 0x47bb10-0x47c920). Codes
# are one digit per byte (0-9, A-D = 10-13, * = 14, # = 15), ended by 0xFF.
# 0xA20 on is BDC1200 (not handled; kept as it is).
DTMF_TAG, DTMF_CODES, DTMF_CONTACTS = 0x06, 16, 64
DTMF_CHARS = '0123456789ABCD*#'
CODE_CHARS = {'dtmf': DTMF_CHARS, 'digits': '0123456789',
              'hex': '0123456789ABCDEF'}
DTMF_FORMAT = """
#seekto 0x%%(b)x;
struct {
%s
  u8 pre_carrier;
  u8 first_digit;
  u8 duration;
  u8 interval;
  u8 auto_reset;
  u8 unknown105:7, side_tone:1;
  u8 self_id[3];
  u8 group_code;
  u8 interval_sign;
  u8 auto_answer;
  u8 ptt_id_pause;
  u8 unknown10d;
  u8 min_duration;
  u8 unknown10f;
  u8 ptt_id_up[16];
  u8 ptt_id_down[16];
  u8 stun_code[16];
  u8 kill_code[16];
} dtmf;
#seekto 0x%%(b1ff)x;
u8 dtmf_contact_count;
struct {
  char name[16];
  u8 number[5];
  u8 unknown[11];
} dtmf_contacts[%d];
""" % ('\n'.join('  u8 code%d[16];' % i for i in range(1, DTMF_CODES + 1)),
       DTMF_CONTACTS)
# Two-tone (tag 0x03; CPS dialogs 0x45a760 system, 0x45ac30 decode,
# 0x45ae20 encode; accessors 0x479df0-0x47a7a0). Times in 0.1 s,
# frequencies in 0.1 Hz. Five-tone is on the same page from 0x730.
SIGNAL_TAG, TT_ENCODE, TT_DECODE = 0x03, 32, 4
TT_FORMAT = """
#seekto 0x%%(b1)x;
u8 tt_encode_count;
#seekto 0x%%(b30)x;
struct {
  u8 pre_carrier;
  u8 first_tone;
  u8 second_tone;
  u8 long_tone;
  u8 interval;
  u8 unknown35;
  u8 polite_wait;
  ul16 freq_a;
  ul16 freq_b;
  ul16 freq_c;
  ul16 freq_d;
  u8 unknown3f:6, side_tone:1, idle_ack:1;
  u8 auto_reset;
%s
} twotone;
#seekto 0x%%(b220)x;
struct {
  u8 name[32];
  u8 unknown20:7, single_tone:1;
  u8 unknown21;
  ul16 tone1;
  ul16 tone2;
  u8 unknown26[2];
} tt_encode[%d];
""" % ('\n'.join('  u8 dec%d_format;\n  u8 dec%d_call;\n'
                 '  u8 dec%d_unknown:7, dec%d_reply:1;\n  u8 dec%d_unknown2;'
                 % ((i,) * 5) for i in range(1, TT_DECODE + 1)), TT_ENCODE)
# Five-tone (tag 0x03 from 0x730; CPS dialogs 0x4254c0 system, 0x426240
# message codes, 0x426590 special calls). Codes are hex digits, one per
# byte, 0xFF-terminated.
FT_MSG, FT_SPECIAL = 8, 32
FT_FORMAT = """
#seekto 0x%%(b730)x;
struct {
  u8 self_id[5];
  u8 decode_std;
  u8 unknown736:4, decode_resp:4;
  u8 unknown737[3];
  u8 pre_carrier;
  u8 auto_reset;
  u8 send_delay;
  u8 ptt_id_pause;
  u8 first_delay;
  u8 unknown73f:7, side_tone:1;
  u8 unknown740[16];
%s
  u8 bot_id[16];
  u8 bot_std;
  u8 bot_long;
  u8 unknown7e2[14];
  u8 eot_id[16];
  u8 eot_std;
  u8 eot_long;
} fivetone;
#seekto 0x%%(b820)x;
struct {
  u8 type;
  u8 code[5];
  u8 delimiter;
  u8 standard;
  u8 tone_long;
  u8 unknown9[7];
  u8 data[16];
  u8 name[16];
} ft_special[%d];
""" % ('\n'.join('  u8 msg%d_func;\n  u8 msg%d_unknown:4, msg%d_resp:4;\n'
                 '  u8 msg%d_code[12];\n  u8 msg%d_pad[2];' % ((i,) * 5)
                 for i in range(1, FT_MSG + 1)), FT_SPECIAL)
FT_STANDARDS = ['ZVEI1', 'ZVEI2', 'ZVEI3', 'CCIR1', 'CCIR2', 'CCIR3', 'EEA',
                'EIA']                                # [FiveTone*Standard]
FT_SPECIAL_TYPES = (['Off', 'ANI', 'Data Transmission'],  # [SpecialCallType]
                    [0xFF, 0, 1])
FT_DELIMITERS = ['No Pause in mid', 'A', 'B', 'C', 'D', 'E', 'F']
FT_TONE_LONG = (['%d ms' % i for i in range(30, 101, 10)], 3)
TT_HZ = (2885, 31068)            # frequency limits in 0.1 Hz (CPS 0x45a760)
# [TwoToneDecodeFormat] and the stored codes (CPS 0x47a1f0)
TT_DECODE_FORMATS = ['None', 'A-B', 'A-C', 'A-D', 'B-A', 'B-C', 'B-D', 'C-A',
                     'C-B', 'C-D', 'D-A', 'D-B', 'D-C', 'Long A', 'Long B',
                     'Long C', 'Long D']
TT_DECODE_CODES = [0xFF, 0x01, 0x02, 0x03, 0x10, 0x12, 0x13, 0x20, 0x21,
                   0x23, 0x30, 0x31, 0x32, 0x0F, 0x1F, 0x2F, 0x3F]
# The page each settings struct lives on.
STRUCT_TAGS = {'dtmf': DTMF_TAG, 'twotone': SIGNAL_TAG,
               'fivetone': SIGNAL_TAG}


def _mem_format():
    """Channel pages as the CPS lays them out (see channel_offset)."""
    b = IMAGE_TAGS.index(0x04) * PAGE      # settings come first: lowest slot
    d = IMAGE_TAGS.index(DTMF_TAG) * PAGE
    t = IMAGE_TAGS.index(SIGNAL_TAG) * PAGE
    fmt = [CHAN_FORMAT,
           TT_FORMAT % dict(b1=t + 1, b30=t + 0x30, b220=t + 0x220),
           FT_FORMAT % dict(b730=t + 0x730, b820=t + 0x820),
           SETTINGS_FORMAT % dict(b=b, b30=b + 0x30, b40=b + 0x40,
                                  b60=b + 0x60, b80=b + 0x80, ba0=b + 0xA0,
                                  b301=b + 0x301, b500=b + 0x500),
           DTMF_FORMAT % dict(b=d, b1ff=d + 0x1FF),
           '#seekto 0x%x;\nul16 ch_count;' % CH_BASE,
           '#seekto 0x%x;\nstruct chan page0[84];' % (CH_BASE + 0x10)]
    for p in range(1, 48):
        n = CH_PER_PAGE if p < 47 else CH_COUNT - 47 * CH_PER_PAGE + 1
        fmt.append('#seekto 0x%x;\nstruct chan page%d[%d];' % (
            CH_BASE + p * PAGE, p, n))
    # VFO A and B are back to back (VFO_OFFSETS).
    fmt.append('#seekto 0x%x;\nstruct chan vfo0;\nstruct chan vfo1;' % (
        CH_BASE + 47 * PAGE + VFO_OFFSETS[0]))
    # Bytes 1/3 are the current position in the zone for display lines A/B,
    # bytes 5/7 the current zone for A/B (bounded by 64 and 250 in the CPS).
    fmt.append('#seekto 0x%x;\nstruct {\n  u8 count;\n  u8 a_pos;\n'
               '  u8 unknown2;\n  u8 b_pos;\n  u8 unknown4;\n  u8 a_zone;\n'
               '  u8 unknown6;\n  u8 b_zone;\n} zone_hdr;' % ZONE_BASE)
    for p in range(9):
        fmt.append('#seekto 0x%x;\nstruct zone zpage%d[%d];' % (
            ZONE_BASE + p * PAGE + (0x10 if p == 0 else 0), p, ZONE_PER_PAGE))
    return '\n'.join(fmt)


MEM_FORMAT = _mem_format()

# Radio settings on tag 0x04, from the CPS option dialogs (0x446770 power
# on, 0x4388d0 tones, 0x440260 display, 0x4656a0 work mode, 0x444f60
# options). Each entry: (struct, field, label, kind, extra). kind 'list':
# stored value = index (+ extra[1] offset); 'bool'; 'text' (length).
_SECONDS = ['%d s' % i for i in range(1, 31)]
_COLORS = ['White', 'Black', 'Orange', 'Red', 'Yellow', 'Green', 'Cyan',
           'Blue']                                            # [DisplayColor]
RADIO_SETTINGS = [
    ('Power on', [
        ('set_power', 'poweron_type', 'Power-on screen',
         'list', (['Power On Picture', 'Custom Message', 'Battery Volt'], 0)),
        ('set_power', 'line1', 'Power-on text line 1', 'text', 14),
        ('set_power', 'line2', 'Power-on text line 2', 'text', 14),
        ('set_power', 'auto_power_off', 'Auto power off',
         'list', (['Off', '30 min', '60 min', '120 min', '240 min',
                   '480 min'], 0)),
        ('set_power', 'allow_reset', 'Allow reset', 'bool', None),
    ]),
    ('Tones', [
        ('set_power', 'key_tone', 'Key tone', 'bool', None),
        ('set_power', 'voice_prompt', 'Voice prompt', 'bool', None),
        ('set_power', 'startup_sound', 'Startup sound', 'bool', None),
        ('set_power', 'battery_low', 'Battery low alert', 'bool', None),
        ('set_power', 'talk_permit_tone', 'Talk permit tone', 'bool', None),
        ('set_power', 'call_end_tone', 'Call end tone', 'bool', None),
        ('set_power', 'group_call_tone', 'Group call tone', 'bool', None),
        ('set_power', 'private_call_tone', 'Private call tone', 'bool',
         None),
        ('set_power', 'sms_alert', 'SMS alert', 'bool', None),
        ('set_power', 'radio_silent', 'Radio silent', 'bool', None),
        ('set_power', 'tx_end_tone', 'Analog TX end tone',
         'list', (['Off', 'Tone', 'BDC'], 0)),
    ]),
    ('Display', [
        ('set_display', 'backlight', 'Backlight brightness',
         'list', ([str(i) for i in range(1, 7)], 0)),
        ('set_display', 'menu_exit', 'Menu exit time',
         'list', (['Off'] + ['%d s' % i for i in range(5, 61, 5)], 0)),
        ('set_display', 'tx_backlight', 'TX backlight delay',
         'list', (['Off'] + _SECONDS, 0)),
        ('set_display', 'rx_backlight', 'RX backlight delay',
         'list', (['Always'] + _SECONDS, 0)),
        ('set_display', 'time_display', 'Time display', 'bool', None),
        ('set_display', 'date_format', 'Date format',
         'list', (['yyyy/m/d', 'd/m/yyyy'], 0)),
        ('set_display', 'volume_prompt', 'Volume change prompt', 'bool',
         None),
        ('set_display', 'call_color', 'Call display colour',
         'list', (_COLORS, 0)),
        ('set_display', 'standby_color', 'Standby text colour',
         'list', (_COLORS, 0)),
        ('set_display', 'a_name_color', 'Channel name colour (A)',
         'list', (_COLORS, 0)),
        ('set_display', 'b_name_color', 'Channel name colour (B)',
         'list', (_COLORS, 0)),
        ('set_display', 'a_zone_color', 'Zone colour (A)',
         'list', (_COLORS, 0)),
        ('set_display', 'b_zone_color', 'Zone colour (B)',
         'list', (_COLORS, 0)),
    ]),
    ('Work mode', [
        ('set_work', 'only_channel', 'Only channel mode', 'bool', None),
        ('set_work', 'dual_watch', 'Dual watch',
         'list', (['Single Mode', 'Double Wait', 'Single Wait'], 0)),
        ('set_work', 'dual_watch_hang', 'Dual watch hang time',
         'list', (['%d ms' % i for i in range(0, 6501, 500)], 0)),
    ]),
    ('Options', [
        ('set_opts', 'tot', 'TX timeout (TOT)',
         'list', (['Off'] + ['%d s' % i for i in range(15, 496, 5)], 0)),
        ('set_opts', 'tot_pre', 'TOT pre-alert',
         'list', (['Off'] + ['%d s' % i for i in range(1, 11)], 0)),
        ('set_opts', 'vox_level', 'VOX level',
         'list', ([str(i) for i in range(1, 6)], 0)),
        ('set_opts', 'vox_delay', 'VOX delay',
         'list', (['%.1f s' % (i / 10) for i in range(3, 51)], 3)),
        ('set_opts', 'language', 'Language',
         'list', (['Chinese', 'English'], 0)),
        ('set_opts', 'power_save', 'Power save',
         'list', (['None', '1:1', '1:2', '1:4'], 0)),
        ('set_opts', 'tail_mode', 'Tail noise reduction',
         'list', (['None', '120', '180', '55 Hz'], 0)),
        ('set_opts', 'tbst', 'TBST (tone burst)',
         'list', (['1000 Hz', '1450 Hz', '1750 Hz', '2100 Hz'], 0)),
        ('set_opts', 'mic_analog', 'Analog mic level',
         'list', ([str(i) for i in range(1, 6)], 0)),
        ('set_opts', 'disable_leds', 'Disable all LEDs', 'bool', None),
        ('set_opts', 'weather_alarm', 'Weather alarm', 'bool', None),
    ]),
]
_KEY_FUNCS = [
    'None', 'Power Select', 'Volt', 'Talkaround', 'Digital Encrypt', 'Call',
    'VOX', 'V/M', 'Alarm', 'One Touch Call 1', 'One Touch Call 2',
    'One Touch Call 3', 'One Touch Call 4', 'One Touch Call 5', 'SMS',
    'Contacts', 'Zone Up', 'Zone Down', 'Scan', 'Record Switch',
    'Previous Record', 'Next Record', 'FM Radio', 'FM Search',
    'GPS Information', 'Monitor', 'Switch Main Channel', 'Lone Work',
    'Keypad Lock', 'Nuisance Channel Delete', 'TBST Send', 'APRS Send',
    'Channel Type', 'Display Mode', 'CTC Scan', 'CTC Setting', 'Silent Tone',
    'Roaming', 'Sub-PTT', 'Analog Scramble Switch', 'One Key Scan Freq',
    'Flashlight', 'Man Down Alarm']                           # [KeyFuncData]
_UTC = ['UTC %+d:00' % h if h else 'UTC' for h in range(-12, 14)]
_ONOFF = (['Off', 'On'], 0)
# Which key owns which byte comes from the CPS keys dialog (0x430760: the
# accessor that fills each control, and 0x430600: the control's label).
RADIO_SETTINGS.append(('Keys', [
    ('set_work', 'lock_mode', 'Keypad lock',
     'list', (['Manual', 'Auto'], 0)),
    ('set_work', 'lock_delay', 'Auto keypad lock delay',
     'list', (['%d s' % i for i in range(5, 61)], 0)),
    ('set_work', 'knob_lock', 'Knob lock', 'list', _ONOFF),
    ('set_work', 'side_lock', 'Side key lock', 'list', _ONOFF),
    ('set_work', 'forbid_lock', 'Forbid lock key', 'list', _ONOFF),
    ('set_work', 'long_press', 'Long press time',
     'list', ([str(i) for i in range(1, 6)], 0)),
] + [('set_work', 'key_%s_%s' % (k, p), '%s %s press' % (k.upper(), p),
      'list', (_KEY_FUNCS, 0))
     for k in ('sk1', 'sk2', 'tk', 'p1', 'p2', 'p3')
     for p in ('short', 'long')]))
RADIO_SETTINGS.append(('DMR', [
    ('set_dmr', 'private_match', 'Private call match', 'bool', None),
    ('set_dmr', 'group_match', 'Group call match', 'bool', None),
    ('set_dmr', 'call_hold', 'Call hold time',
     'list', (['%d s' % i for i in range(1, 61)], 0)),
    ('set_dmr', 'active_wait', 'Active wait time',
     'list', (['%d ms' % i for i in range(300, 4801, 30)], 1)),
    ('set_dmr', 'active_retries', 'Active retries',
     'list', ([str(i) for i in range(1, 9)], 1)),
    ('set_dmr', 'pre_carrier', 'Pre-carrier time',
     'list', (['%d ms' % i for i in range(120, 8641, 120)], 0)),
    ('set_dmr', 'monitor_time', 'Remote monitor time',
     'list', (['%d s' % i for i in range(10, 121, 10)], 0)),
    ('set_dmr', 'data_service', 'SMS format',
     'list', (['H-SMS', 'M-SMS', 'D-SMS'], 0)),
    ('set_dmr', 'missed_call_alert', 'Missed call alert', 'bool', None),
    ('set_dmr', 'monitor_decode', 'Remote monitor decode', 'bool', None),
    ('set_dmr', 'disable_decode', 'Radio disable decode', 'bool', None),
    ('set_dmr', 'check_decode', 'Radio check decode', 'bool', None),
    ('set_dmr', 'enable_decode', 'Radio enable decode', 'bool', None),
    ('set_dmr', 'alert_decode', 'Call alert decode', 'bool', None),
    ('set_dmr', 'name_format', 'Name data format',
     'list', (['ISO 8 bit', '16 bit Unicode'], 0)),
    ('set_dmr', 'send_tx_name', 'Send TX name', 'bool', None),
    ('set_dmr', 'name_priority', 'Name display priority',
     'list', (['Contact', 'Name'], 0)),
]))
RADIO_SETTINGS.append(('GPS and recording', [
    ('set_gps', 'gps_switch', 'GPS', 'bool', None),
    ('set_gps', 'gps_mode', 'GPS mode',
     'list', (['GPS', 'BDS', 'GPS+BDS'], 0)),
    ('set_gps', 'time_zone', 'Time zone', 'list', (_UTC, 0)),
    ('set_gps', 'measure_period', 'GPS measure period',
     'list', (['%d s' % i for i in range(5, 256)], 0)),
    ('set_gps', 'distance_unit', 'Distance unit',
     'list', (['Metric', 'Imperial'], 0)),
    ('set_gps', 'speed_unit', 'Speed unit',
     'list', (['km/h', 'mph', 'knots'], 0)),
    ('set_gps', 'gps_format', 'GPS display format',
     'list', (['Degrees', 'Degrees/min/sec'], 0)),
    ('set_gps', 'record_switch', 'Recording', 'bool', None),
    ('set_gps', 'record_type', 'Recording type',
     'list', (['Receive', 'Transmit', 'Receive+Transmit'], 0)),
]))
# APRS (CPS dialog 0x439c00, accessors 0x488580-0x488cb0). The radio
# reports its position over DMR: to the "upload number" (a DMR ID) as a
# private or group call, on one of 8 report channels chosen per channel.
# Coordinates are 9 ASCII characters, e.g. "23.000000" / "118.00000"; the
# hemisphere is separate.
RADIO_SETTINGS.append(('APRS', [
    ('set_aprs', 'send_interval', 'Scheduled send time',
     'list', (['Off'] + ['%d s' % i for i in range(30, 7201, 30)], 0)),
    ('set_aprs', 'fixed_beacon', 'Fixed beacon (use the position below)',
     'bool', None),
    ('set_aprs', 'latitude', 'Latitude (degrees)', 'coord', 90),
    ('set_aprs', 'lat_hemi', 'Latitude N/S', 'list', (['N', 'S'], 0)),
    ('set_aprs', 'longitude', 'Longitude (degrees)', 'coord', 180),
    ('set_aprs', 'lon_hemi', 'Longitude E/W', 'list', (['E', 'W'], 0)),
    ('set_aprs', 'upload_number', 'Upload number (DMR ID, 0 = none)',
     'int', (0, DMR_ID_MAX)),
    ('set_aprs', 'call_type', 'Call type',
     'list', (['Private', 'Group'], 0)),                   # [AprsCallType]
    ('set_aprs', 'active_delay', 'Repeater active delay',
     'list', (['Off'] + ['%d ms' % i for i in range(100, 1001, 100)], 0)),
] + [('set_aprs', 'report_channel', 'Report channel %d' % (i + 1),
      'channel', i) for i in range(8)]))


_MS = '%d ms'
RADIO_SETTINGS.append(('DTMF', [
    ('dtmf', 'self_id', 'Self ID code', 'digits', 3),
    ('dtmf', 'ptt_id_up', 'PTT ID up code (BOT)', 'dtmf', 16),
    ('dtmf', 'ptt_id_down', 'PTT ID down code (EOT)', 'dtmf', 16),
    ('dtmf', 'stun_code', 'Stun code', 'dtmf', 16),
    ('dtmf', 'kill_code', 'Kill code', 'dtmf', 16),
    ('dtmf', 'group_code', 'Group code', 'list', (         # [DtmfGroupCode]
        ['Off', 'A', 'B', 'C', 'D', '*', '#'], [0xFF] + list(range(10, 16)))),
    ('dtmf', 'interval_sign', 'DTMF interval sign', 'list', (
        ['A', 'B', 'C', 'D', '*', '#'], 10)),             # [DtmfIntervalSign]
    ('dtmf', 'auto_answer', 'Auto answer', 'list', (       # [DtmfAutoAck]
        ['Off', 'Alert Tone', 'Alert Tone And Ack'], 0)),
    ('dtmf', 'side_tone', 'Side tone', 'bool', None),
    ('dtmf', 'pre_carrier', 'Pre-carrier time', 'list', (
        [_MS % i for i in range(300, 5001, 50)], 15)),
    ('dtmf', 'first_digit', 'First digit time', 'list', (
        [_MS % i for i in range(100, 1001, 50)], 0)),
    ('dtmf', 'duration', 'Send DTMF duration', 'list', (
        [_MS % i for i in range(80, 2001, 10)], 0)),
    ('dtmf', 'interval', 'Send DTMF interval', 'list', (
        [_MS % i for i in range(80, 2001, 10)], 0)),
    ('dtmf', 'min_duration', 'Dial code minimum duration', 'list', (
        [_MS % i for i in range(25, 2501, 25)], 0)),
    ('dtmf', 'auto_reset', 'Auto reset time', 'list', (
        ['%d s' % i for i in range(1, 256)], 1)),
    ('dtmf', 'ptt_id_pause', 'PTT ID pause time', 'list', (
        ['Off'] + ['%d s' % i for i in range(5, 76)],
        [0] + list(range(5, 76)))),
] + [('dtmf', 'code%d' % i, 'DTMF code %d' % i, 'dtmf', 16)
     for i in range(1, DTMF_CODES + 1)]))


def _tenths(first, last, unit='s'):
    return ['%.1f %s' % (i / 10, unit) for i in range(first, last + 1)]


RADIO_SETTINGS.append(('Two-tone', [
    ('twotone', 'freq_a', 'Tone A frequency (Hz)', 'hz', TT_HZ),
    ('twotone', 'freq_b', 'Tone B frequency (Hz)', 'hz', TT_HZ),
    ('twotone', 'freq_c', 'Tone C frequency (Hz)', 'hz', TT_HZ),
    ('twotone', 'freq_d', 'Tone D frequency (Hz)', 'hz', TT_HZ),
    ('twotone', 'pre_carrier', 'Pre-carrier time', 'list',
     (_tenths(0, 50), 0)),
    ('twotone', 'first_tone', 'First tone duration', 'list',
     (_tenths(5, 40), 5)),
    ('twotone', 'second_tone', 'Second tone duration', 'list',
     (_tenths(5, 40), 5)),
    ('twotone', 'long_tone', 'Long tone duration', 'list',
     (_tenths(5, 100), 5)),
    ('twotone', 'interval', 'Interval time', 'list', (_tenths(0, 20), 0)),
    ('twotone', 'polite_wait', 'Polite wait time', 'list',
     (_tenths(0, 50), 0)),
    ('twotone', 'auto_reset', 'Auto reset time', 'list', (
        ['%d s' % i for i in range(1, 256)], 1)),
    ('twotone', 'idle_ack', 'Idle ack', 'bool', None),
    ('twotone', 'side_tone', 'Side tone', 'bool', None),
] + [entry for i in range(1, TT_DECODE + 1) for entry in (
    ('twotone', 'dec%d_format' % i, 'Decode %d: format' % i, 'list',
     (TT_DECODE_FORMATS, TT_DECODE_CODES)),
    ('twotone', 'dec%d_call' % i, 'Decode %d: call type' % i, 'list', (
        ['None', 'Call Alert', 'Voice Call Alert', 'Select Call'], 0)),
    ('twotone', 'dec%d_reply' % i, 'Decode %d: reply' % i, 'bool', None))]))


_RESPONSES = ['None', 'Alert Tone', 'Alert Tone And ACK']
RADIO_SETTINGS.append(('Five-tone', [
    ('fivetone', 'self_id', 'Self ID code', 'hex', 5),
    ('fivetone', 'decode_std', 'Decode standard', 'list', (FT_STANDARDS, 0)),
    ('fivetone', 'decode_resp', 'Decode response', 'list', (_RESPONSES, 0)),
    ('fivetone', 'pre_carrier', 'Pre-carrier time', 'list', (
        [_MS % i for i in range(300, 5001, 50)], 15)),
    ('fivetone', 'auto_reset', 'Auto reset time', 'list', (
        ['%d s' % i for i in range(1, 256)], 1)),
    ('fivetone', 'send_delay', 'Delay time after send code', 'list', (
        [_MS % i for i in range(10, 2551, 10)], 1)),
    ('fivetone', 'ptt_id_pause', 'PTT ID pause time', 'list', (
        ['Off'] + ['%d s' % i for i in range(5, 76)],
        [0] + list(range(5, 76)))),
    ('fivetone', 'first_delay', 'First delay time', 'list', (
        [str(i) for i in range(10, 2551, 10)], 1)),
    ('fivetone', 'side_tone', 'Side tone', 'bool', None),
    ('fivetone', 'bot_id', 'PTT ID start (BOT): encode ID', 'hex', 16),
    ('fivetone', 'bot_std', 'PTT ID start (BOT): standard', 'list',
     (FT_STANDARDS, 0)),
    ('fivetone', 'bot_long', 'PTT ID start (BOT): tone long', 'list',
     FT_TONE_LONG),
    ('fivetone', 'eot_id', 'PTT ID end (EOT): encode ID', 'hex', 16),
    ('fivetone', 'eot_std', 'PTT ID end (EOT): standard', 'list',
     (FT_STANDARDS, 0)),
    ('fivetone', 'eot_long', 'PTT ID end (EOT): tone long', 'list',
     FT_TONE_LONG),
] + [entry for i in range(1, FT_MSG + 1) for entry in (
    ('fivetone', 'msg%d_code' % i, 'Message code %d: code' % i, 'hex', 12),
    ('fivetone', 'msg%d_func' % i, 'Message code %d: function' % i, 'list', (
        ['Squelch', 'All Call', 'Emergency Alarm', 'Stun', 'Kill', 'Wake Up',
         'Group Call'], 0)),                           # [FiveToneMsgCodeFunc]
    ('fivetone', 'msg%d_resp' % i, 'Message code %d: response' % i, 'list',
     (_RESPONSES, 0)))]))


def _pick(options, value):
    return RadioSettingValueList(options, current_index=options.index(value))


def _list_index(stored, offset):
    """List position of a stored value; offset is added to the position,
    or is the list of stored values."""
    if isinstance(offset, list):
        return offset.index(stored) if stored in offset else -1
    return stored - offset


def _list_stored(index, offset):
    return offset[index] if isinstance(offset, list) else index + offset


def _parse_hz(text, limits, label):
    """'321.7' -> 3217 (0.1 Hz), within limits."""
    try:
        tenths = round(float(text) * 10)
    except ValueError:
        tenths = -1
    if not limits[0] <= tenths <= limits[1]:
        raise errors.InvalidValueError('%s must be %.1f to %.1f Hz' % (
            label, limits[0] / 10, limits[1] / 10))
    return tenths


def _dtmf_text(raw, chars=DTMF_CHARS):
    """Code bytes (digit values, 0xFF-terminated) -> text."""
    text = ''
    for b in raw:
        if b >= len(chars):
            break
        text += chars[b]
    return text


def _dtmf_bytes(text, length, chars=DTMF_CHARS):
    return bytes(chars.index(c) for c in text.upper()).ljust(length, b'\xFF')


def _format_coord(value, limit):
    """A coordinate as the CPS stores it (0x488750, 0x488950): 9 chars,
    e.g. "05.500000", "23.000000", "118.00000"; at most `limit`."""
    for decimals in (6, 5):
        text = '%.*f' % (decimals, value)
        if len(text) < 9:
            text = '0' + text
        if len(text) == 9:
            break
    if float(text) >= limit:
        text = '%.*f' % (6 if limit < 100 else 5, limit)
    return text


def _parse_coord(raw):
    """Stored coordinate bytes -> text as the CPS shows it, or ''."""
    text = raw.split(b'\x00')[0].split(b'\xFF')[0].decode('latin-1')
    try:
        float(text)
    except ValueError:
        return ''
    return text[1:] if text.startswith('0') and len(text) > 1 else text


_MENU = [
    ('zone_list', 'Zone list'), ('new_zone', 'New zone'),
    ('call_alert', 'Call alert'), ('radio_check', 'Radio check'),
    ('remote_monitor', 'Remote monitor'), ('radio_enable', 'Radio enable'),
    ('radio_disable', 'Radio disable'), ('measure_period', 'Measure period'),
    ('talkaround', 'Talkaround'), ('alert_tone', 'Alert tone'),
    ('tx_power', 'TX power'), ('start_display', 'Start display'),
    ('lang_select', 'Language'), ('match_private', 'Match private'),
    ('match_group', 'Match group'), ('display_mode', 'Display mode'),
    ('sub_channel_mode', 'Sub channel mode'), ('power_save', 'Power save'),
    ('gps', 'GPS'), ('aprs', 'APRS'), ('record', 'Record'),
    ('add_contact', 'Add contact'), ('edit_contact', 'Edit contact'),
    ('del_contact', 'Delete contact'), ('send_message', 'Send message'),
    ('functionality', 'Functionality'), ('manual_dial', 'Manual dial'),
    ('csv_contacts', 'CSV contacts'), ('missed_call', 'Missed calls'),
    ('answered_call', 'Answered calls'), ('sent_call', 'Sent calls'),
    ('del_log', 'Delete call log'), ('rx_freq', 'RX frequency'),
    ('tx_freq', 'TX frequency'), ('ctc_dcs', 'CTC/DCS'),
    ('tx_contact', 'TX contact'), ('color_code', 'Color code'),
    ('time_slot', 'Time slot'), ('radio_id', 'Radio ID'),
    ('radio_name', 'Radio name'), ('channel_type', 'Channel type'),
    ('tdma_direct', 'TDMA direct mode'), ('rx_group', 'RX group list'),
    ('add_channel', 'Add channel'), ('channel_name', 'Channel name')]
RADIO_SETTINGS.append(('Menu items', [
    ('set_menu', f, 'Menu: %s' % label, 'bool', None) for f, label in _MENU]))

# Bits of 0x80 that follow the radio's current display (A/B mode, display
# mode, main line); upload keeps the radio's own values for these.
WORK_STATE_MASK = 0x3E


def zone_offset(z):
    """(page, index) of zone z (1-250), as the CPS computes it (0x482830)."""
    return (z - 1) // ZONE_PER_PAGE, (z - 1) % ZONE_PER_PAGE


def channel_offset(n):
    """(page, index) of channel n, as the CPS computes it (0x47dcc0)."""
    if n < CH_PER_PAGE:
        return 0, n - 1
    return n // CH_PER_PAGE, n % CH_PER_PAGE


CHTYPES = ['Analog', 'Digital', 'Fixed Analog', 'Fixed Digital']
# Value lists of the channel options, from the CPS language file sections
# (in brackets); the stored field is the index.
LIST_EXTRAS = {
    'rx_squelch_mode': ('RX squelch mode', [      # [RxSquelchMode]
        'Carrier/CTC', 'Optional Signaling', 'CTC & Optional Signaling',
        'CTC | Optional Signaling']),
    'signaling': ('Signaling type', [             # [ChannelSignalingType]
        'None', 'DTMF', 'Two Tone', 'Five Tone', 'BDC1200']),
    'ptt_id': ('PTT ID', ['Off', 'BOT', 'EOT', 'Both']),   # [ChannelPttId]
    # [ChannelAprsReport]
    'aprs_report': ('APRS report (DMR)', ['Off', 'Digital']),
    # one of the 8 report channels of the APRS settings
    'aprs_channel': ('APRS report channel', [str(i) for i in range(1, 9)]),
    # which two-tone (1-8) or BDC1200 (1-4) entry, per signaling type
    # (CPS 0x414470)
    'rx_signal': ('RX signaling system', ['None'] + [
        str(i) for i in range(1, 9)]),
    'tx_signal': ('TX signaling system', ['None'] + [
        str(i) for i in range(1, 9)]),
}
# [ChAnaTxAdmit] for analog channels, [ChDigTxAdmit] for digital ones
TX_ADMIT = {False: ['Allow TX', 'Channel Idle', 'Match CTC', 'Non Match CTC'],
            True: ['Always', 'Channel Idle', 'Color Code Idle']}
BOOL_EXTRAS = [
    ('vox', 'VOX'),
    ('compander', 'Compander'),
    ('ptt_id_display', 'PTT ID display'),
    ('lone_work', 'Lone worker'),
    ('auto_scan', 'Auto scan'),
    ('aprs_rx', 'APRS receive'),
    ('aprs_ptt_analog', 'Analog APRS PTT mode'),
    ('aprs_ptt_digital', 'Digital APRS PTT mode'),
    ('emerg_indicator', 'Emergency indicator (DMR)'),
    ('emerg_ack', 'Emergency ACK (DMR)'),
    ('private_confirm', 'Private call confirm (DMR)'),
    ('short_data_confirm', 'Short data confirm (DMR)'),
    ('tdma_direct', 'TDMA direct mode (DMR)'),
]
POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=1),
                chirp_common.PowerLevel('Middle', watts=2.5),
                chirp_common.PowerLevel('High', watts=5)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]


# --- Serial link ------------------------------------------------------------

def _marker_ok(got, want):
    """Check a one-byte reply marker, allowing for the known link fault."""
    return got in (want, want | LINK_FAULT)


def _merge_copies(copies):
    """Merge copies of one block byte by byte, or None if more are needed.

    Where copies differ only in bit 7, the value with bit 7 clear wins, as
    the link fault only ever sets it. Anything else needs a strict majority
    of at least 3 copies.
    """
    first = copies[0]
    if all(c == first for c in copies[1:]):
        return first
    out = bytearray(first)
    for i, vals in enumerate(zip(*copies)):
        if min(vals) == max(vals):
            continue
        votes = collections.Counter(vals)
        if len({v & ~LINK_FAULT for v in votes}) == 1:
            out[i] = min(votes)
            continue
        value, n = votes.most_common(1)[0]
        if n < 3 or n * 2 <= len(copies):
            return None
        out[i] = value
    return bytes(out)


class _Link:
    def __init__(self, pipe):
        self.pipe = pipe

    def send(self, data):
        time.sleep(0.01)
        self.pipe.reset_input_buffer()
        self.pipe.write(data)

    def recv(self, n, timeout=0.5):
        self.pipe.timeout = timeout
        return self.pipe.read(n)

    def drain(self):
        time.sleep(0.1)
        self.pipe.reset_input_buffer()

    def xfer(self, data, n, timeout=0.5):
        self.send(data)
        resp = self.recv(n, timeout)
        if len(resp) != n:
            raise errors.RadioError('No reply from radio to %r' % data[:7])
        return resp

    def query_v(self, cmd, agree=3, tries=10):
        """Repeat a V query until `agree` identical replies have been seen."""
        seen = collections.Counter()
        for _attempt in range(tries):
            self.send(cmd)
            hdr = self.recv(3)
            n = hdr[2] if len(hdr) == 3 else 0
            body = self.recv(n) if n else b''
            if len(hdr) != 3 or len(body) != n or not _marker_ok(hdr[0], 0x56):
                self.drain()
                continue
            seen[hdr + body] += 1
            reply, count = seen.most_common(1)[0]
            if count >= agree:
                return reply[3:]
        raise errors.RadioError('Unreliable reply to radio info query')

    def read_block(self, addr, length, timeout=5.0):
        cmd = b'R' + struct.pack('<I', addr)[:3] + struct.pack('<H', length)
        good = []
        for _attempt in range(READ_TRIES):
            self.send(cmd)
            resp = self.recv(6 + length, timeout)
            if len(resp) != 6 + length or resp[:6] != b'W' + cmd[1:6]:
                self.drain()
                continue
            good.append(resp[6:])
            if len(good) >= READ_COPIES:
                merged = _merge_copies(good)
                if merged is not None:
                    return merged
        raise errors.RadioError('Could not read flash at %06x reliably' % addr)


MODEL_ID = b'DP570UV'                  # PSEARCH reply of the DM-32UV
TESTED_FIRMWARE = ('DM32.01.01.047',)


def _search(link):
    """Send PSEARCH; return the model ID the radio reports."""
    for _attempt in range(5):
        link.send(b'PSEARCH')
        resp = link.recv(8)
        if len(resp) == 8 and _marker_ok(resp[0], 0x06):
            # ASCII: clearing bit 7 undoes the link fault
            return bytes(b & 0x7F for b in resp[1:])
    raise errors.RadioError('Radio did not respond. Is it switched on '
                            'and connected?')


def _check_model(model):
    if model != MODEL_ID:
        raise errors.RadioError(
            'This radio identifies as %r, not as a Baofeng DM-32UV (%r)' % (
                model.decode('ascii', 'replace'), MODEL_ID.decode()))


PASSWORD_SET = 0xA5


def _identify(link, writing=False):
    _check_model(_search(link))
    # PASSSTA: 'P', write password flag (settings 0x439), read password
    # flag (0x43A). The radio doesn't enforce them; the vendor CPS asks for
    # the password. CHIRP can't ask, so the driver refuses instead.
    resp = link.xfer(b'PASSSTA', 3)
    if not _marker_ok(resp[0], ord('P')):
        raise errors.RadioError('Unexpected reply to PASSSTA')
    if resp[2] == PASSWORD_SET:
        raise errors.RadioError(
            'The radio has a read password. CHIRP cannot enter passwords; '
            'remove it with the vendor programming software first')
    if writing and resp[1] == PASSWORD_SET:
        raise errors.RadioError(
            'The radio has a write password. CHIRP cannot enter passwords; '
            'remove it with the vendor programming software first')
    if not _marker_ok(link.xfer(b'SYSINFO', 1)[0], 0x06):
        raise errors.RadioError('Radio refused SYSINFO')
    link.query_v(b'V\x00\x00\x40\x0D')
    info = {}
    for i in range(1, 17):
        if i != 12:
            info[i] = link.query_v(b'V\x00\x00\x00' + bytes([i]))
    start, end = struct.unpack('<II', info[10][:8])
    if (start | end) >> 24 or start >= end:
        raise errors.RadioError('Unexpected codeplug range from radio')
    firmware = info[1].decode('ascii', 'replace')
    if firmware not in TESTED_FIRMWARE:
        LOG.warning('DM-32UV firmware %s has not been tested with this '
                    'driver (tested: %s)', firmware,
                    ', '.join(TESTED_FIRMWARE))
    return firmware, start, end


def _enter_program(link):
    # G only reads, so a corrupted reply can simply be asked for again.
    for _attempt in range(3):
        if _marker_ok(link.xfer(b'G\x00\x00\x00\x00\x01', 0x106)[0],
                      ord('S')):
            break
        link.drain()
    else:
        raise errors.RadioError('Unexpected reply to G')
    link.send(b'\xFF\xFF\xFF\xFF\x0C')
    if not _marker_ok(link.xfer(b'PROGRAM', 1)[0], 0x06):
        raise errors.RadioError('Radio refused programming mode')
    link.xfer(b'\x02', 8)
    if not _marker_ok(link.xfer(b'\x06', 1)[0], 0x06):
        raise errors.RadioError('Radio did not acknowledge')


def _scan(link, start, end, radio, status):
    """Tag of every page: ({tag: [addresses]}, [free page addresses])."""
    pages = list(range(start, end + 1 - PAGE + 1, PAGE))
    where = collections.defaultdict(list)
    for i, addr in enumerate(pages):
        where[link.read_block(addr + PAGE - 1, 1, timeout=0.5)[0]].append(addr)
        status.cur = i
        radio.status_fn(status)
    return where, where.pop(0xFF, [])


def do_download(radio):
    link = _Link(radio.pipe)
    firmware, start, end = _identify(link)
    LOG.info('DM-32UV firmware %s, codeplug %06x-%06x', firmware, start, end)
    _enter_program(link)

    status = chirp_common.Status()
    status.msg = 'Scanning flash pages'
    status.max = (end + 1 - start) // PAGE + len(IMAGE_TAGS)
    where, _free = _scan(link, start, end, radio, status)

    status.msg = 'Cloning from radio'
    base = status.cur + 1
    image = bytearray(b'\xFF' * (len(IMAGE_TAGS) * PAGE))
    for i, tag in enumerate(IMAGE_TAGS):
        if len(where.get(tag, [])) > 1:
            LOG.warning('Radio has %d pages with tag %02x; using the first. '
                        'Upload will refuse until the radio has tidied up.',
                        len(where[tag]), tag)
        if where.get(tag):
            data = link.read_block(where[tag][0], PAGE)
            image[i * PAGE:(i + 1) * PAGE] = data
        status.cur = base + i
        radio.status_fn(status)
    radio._metadata['dm32uv_firmware'] = firmware
    return memmap.MemoryMapBytes(bytes(image))


def _write_page(link, addr, data, start, end, reconnect=None):
    """Write one whole page with W and read it back until it matches.

    reconnect() starts a new session; it is needed when an ACK is lost,
    because the radio ends the session after 2 s without traffic."""
    if (len(data) != PAGE or addr % PAGE or addr < start or
            addr + PAGE - 1 > end or data[-1] in NEVER_WRITE):
        raise errors.RadioError('Refusing unsafe write at %06x' % addr)
    frame = (b'W' + struct.pack('<I', addr)[:3] + struct.pack('<H', PAGE) +
             bytes(data))
    for _attempt in range(WRITE_TRIES):
        link.send(frame)
        ack = link.recv(1, timeout=5.0)
        if not ack:
            # The radio may still be waiting for data; after 2 s it gives
            # up and ends the session. Start a new one to check the page.
            LOG.warning('No reply to W %06x; reconnecting', addr)
            time.sleep(2.5)
            if reconnect is None:
                raise errors.RadioError('No reply to write at %06x' % addr)
            reconnect()
        elif not _marker_ok(ack[0], 0x06):
            LOG.warning('Unexpected reply %s to W %06x', ack.hex(), addr)
        if link.read_block(addr, PAGE) == bytes(data):
            return
        LOG.warning('Page %06x did not verify, writing it again', addr)
    raise errors.RadioError('Page at %06x did not verify after %d writes' % (
        addr, WRITE_TRIES))


def _zone_record(rec):
    """(name bytes, [members]) of a raw 0x91-byte zone record."""
    count = min(rec[16], ZONE_MEMBERS)
    return (rec[:16].split(b'\x00')[0].split(b'\xFF')[0],
            [int.from_bytes(rec[17 + 2 * i:19 + 2 * i], 'little')
             for i in range(count)])


def _follow_display(want, current, radio_zone, zones):
    """Zone header bytes 1-7 for the upload.

    Bytes 5/7 are the zone lines A/B show and bytes 1/3 the position in it.
    They change whenever someone browses on the radio, so the radio's own
    values are used, moved to where that zone and channel are in the new
    list `zones` ([(name bytes, [members])]), in case zones were reordered
    or deleted. radio_zone(z) gives zone z as the radio has it now.
    """
    want = bytearray(want)
    want[1:8] = current[1:8]
    for pos, zone in ((1, 5), (3, 7)):
        z, old = current[zone], None
        if 1 <= z <= ZONE_COUNT:
            old = radio_zone(z)
        new = None
        if old:
            new = next((i for i, zn in enumerate(zones, 1) if zn == old),
                       next((i for i, zn in enumerate(zones, 1)
                             if zn[0] == old[0]), None))
        if new is None:             # deleted, or unknown to the radio
            new = z if not old and 1 <= z <= len(zones) else 1
        members = zones[new - 1][1] if zones else []
        p = current[pos]
        if old:                     # follow the channel, or start over
            channel = old[1][p - 1] if 1 <= p <= len(old[1]) else None
            p = members.index(channel) + 1 if channel in members else 1
        if not 1 <= p <= max(len(members), 1):
            p = 1
        want[zone], want[pos] = new, p
    return bytes(want)


def do_upload(radio):
    """Write changed channel pages back to the radio, verifying each one.

    A page is written to wherever the radio keeps that tag now, or to the
    first free page if the radio has none yet. Pages that already match the
    image are left alone, so an unchanged image writes nothing. Returns the
    number of pages written.
    """
    image = radio.get_mmap().get_packed()
    link = _Link(radio.pipe)
    firmware, start, end = _identify(link, writing=True)
    LOG.info('Upload to DM-32UV firmware %s', firmware)
    _enter_program(link)

    def reconnect():
        _identify(link, writing=True)
        _enter_program(link)

    def radio_zone(z):
        page, index = zone_offset(z)
        addrs = where.get(ZONE_TAG0 + page)
        if not addrs:
            return None
        return _zone_record(link.read_block(
            addrs[0] + (0x10 if page == 0 else 0) + index * 0x91, 0x91))
    zones = [(_name_bytes(name, 16).rstrip(b'\x00'), members)
             for name, members in radio._zone_list()]

    status = chirp_common.Status()
    status.msg = 'Scanning flash pages'
    status.max = (end + 1 - start) // PAGE + len(UPLOAD_TAGS)
    where, free = _scan(link, start, end, radio, status)
    dupes = [t for t in UPLOAD_TAGS if len(where.get(t, [])) > 1]
    if dupes:
        raise errors.RadioError(
            'The radio has more than one page with tag %s; not writing' %
            ', '.join('%02x' % t for t in dupes))

    status.msg = 'Cloning to radio'
    base = status.cur + 1
    written = 0
    for i, tag in enumerate(UPLOAD_TAGS):
        slot = IMAGE_TAGS.index(tag) * PAGE
        want = image[slot:slot + PAGE - 1] + bytes([tag])
        # A slot is in use if it holds data, or if it came from the radio
        # (tag byte set) and has since been emptied, e.g. all its channels
        # deleted: then the radio's page must be emptied too.
        if (image[slot:slot + PAGE - 1] != b'\xFF' * (PAGE - 1) or
                image[slot + PAGE - 1] == tag and where.get(tag)):
            if where.get(tag):
                addr = where[tag][0]
                current = link.read_block(addr, PAGE)
                if tag == ZONE_TAG0:
                    want = _follow_display(want, current, radio_zone, zones)
                elif tag == 0x04:
                    want = bytearray(want)
                    want[0x80] = (want[0x80] & ~WORK_STATE_MASK & 0xFF |
                                  current[0x80] & WORK_STATE_MASK)
                    want = bytes(want)
                if current == want:
                    addr = None
            elif free:
                addr = free.pop(0)
            else:
                raise errors.RadioError('No free page left on the radio')
            if addr is not None:
                _write_page(link, addr, want, start, end, reconnect)
                written += 1
        status.cur = base + i
        radio.status_fn(status)
    return written


# --- Tones ------------------------------------------------------------------

def _decode_tone(tone):
    """A struct tone -> (mode, value, polarity) for split_tone_decode."""
    if tone.get_raw() != b'\xFF\xFF':
        try:
            if tone.dcs:
                code = int(tone.tens) * 100 + int(tone.low)
                if code in chirp_common.DTCS_CODES:
                    return 'DTCS', code, 'R' if tone.inverted else 'N'
            else:
                value = (int(tone.hundreds) * 100 + int(tone.tens) * 10 +
                         int(tone.low) / 10.0)
                if value in chirp_common.TONES:
                    return 'Tone', value, None
        except ValueError:          # not BCD
            pass
        LOG.warning('Unknown tone bytes %s', tone.get_raw().hex())
    return '', None, None


def _encode_tone(tone, mode, value, pol):
    if mode == 'Tone':
        tenths = round(value * 10)
        tone.set_raw(b'\x00\x00')
        tone.hundreds, tone.tens = tenths // 1000, tenths // 100 % 10
        tone.low = tenths % 100
    elif mode == 'DTCS':
        tone.set_raw(b'\x00\x00')
        tone.dcs, tone.inverted = 1, int(pol == 'R')
        tone.tens, tone.low = value // 100, value % 100
    else:
        tone.set_raw(b'\xFF\xFF')


def _shown(name):
    """A name as CHIRP can show it: characters outside its charset as '?'."""
    return ''.join(c if c in chirp_common.CHARSET_ASCII else '?'
                   for c in name)


def _edited(value, old):
    """The name to store for a setting that showed `old`: `old` itself,
    byte for byte, unless the user changed it."""
    value = str(value).strip()
    return old if value == _shown(old).strip() else value


def _name_bytes(name, length):
    return name.encode('latin-1', 'replace')[:length].ljust(length, b'\x00')


def _cached(method):
    """Cache a lookup on the image until the driver next changes it (see
    DM32UV._forget). Callers must not modify the result."""
    @functools.wraps(method)
    def wrapper(self, *args):
        cache = self.__dict__.setdefault('_lookups', {})
        key = (method.__name__,) + args
        if key not in cache:
            cache[key] = method(self, *args)
        return cache[key]
    return wrapper


class DM32UVZone(chirp_common.NamedBank):
    """A zone on the radio; its index is the zone number minus 1.

    One zone after the last existing one is offered as "New zone"; adding
    a channel to it creates it (see DM32UVZoneModel)."""

    def _zone(self):
        return self._model._radio._zone(self.index + 1)

    def get_name(self):
        name = str(self._zone().name).rstrip('\x00\xFF ')
        if self.index + 1 > self._model._radio._zone_count() and (
                not name or not name.isprintable()):
            return 'New zone'
        return name

    def set_name(self, name):
        self._zone().name = str(name)[:16].ljust(16, '\x00')


class DM32UVZoneModel(chirp_common.MTOBankModel):
    """The radio's zones. A channel can be in several zones; the order of
    channels in a zone is kept, new ones are added at the end.

    Zones are numbered 1..count without gaps, so the only zone that can be
    created is count + 1: it is offered as a spare, and becomes a real zone
    when a channel is added to it. A last zone left empty is removed."""

    def __init__(self, radio):
        super().__init__(radio, 'Zones')

    def get_num_mappings(self):
        return min(self._radio._zone_count() + 1, ZONE_COUNT)

    def get_mappings(self):
        zones = []
        for i in range(self.get_num_mappings()):
            zone = DM32UVZone(self, '%i' % (i + 1), 'Zone %i' % (i + 1))
            zone.index = i
            zones.append(zone)
        return zones

    def add_memory_to_mapping(self, memory, bank):
        z = bank.index + 1
        if z > self._radio._zone_count():
            self._radio._create_zone(z)
        members = self._radio._zone_members(z)
        if memory.number in members:
            return
        if len(members) >= ZONE_MEMBERS:
            raise errors.RadioError('Zone %s is full (%i channels)' % (
                bank.get_name(), ZONE_MEMBERS))
        self._radio._set_zone_members(bank.index + 1,
                                      members + [memory.number])

    def remove_memory_from_mapping(self, memory, bank):
        members = self._radio._zone_members(bank.index + 1)
        if memory.number not in members:
            raise Exception('Memory %i is not in zone %s' % (
                memory.number, bank.get_name()))
        self._radio._set_zone_members(
            bank.index + 1, [m for m in members if m != memory.number])
        self._radio._drop_empty_last_zone()

    def get_mapping_memories(self, bank):
        return [self._radio.get_memory(n)
                for n in self._radio._zone_members(bank.index + 1)]

    def get_memory_mappings(self, memory):
        zones = []
        for z in self._radio._zone_index().get(memory.number, []):
            zone = DM32UVZone(self, '%i' % z, 'Zone %i' % z)
            zone.index = z - 1
            zones.append(zone)
        return zones


@directory.register
class DM32UV(chirp_common.CloneModeRadio):
    """Baofeng DM-32UV"""
    VENDOR = 'Baofeng'
    MODEL = 'DM-32UV'
    BAUD_RATE = 115200
    _memsize = len(IMAGE_TAGS) * PAGE

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver is experimental. Upload writes channels, zones, '
            'DMR lists, scan lists and radio settings. Passwords, encryption '
            'keys and the factory calibration are left as they are on the '
            'radio. A radio with a password set is refused.')
        rp.pre_download = (
            'Switch the radio on and connect the programming cable.\n\n'
            'The radio returns to normal by itself a few seconds after '
            'the download.')
        rp.pre_upload = (
            'Before the first upload, download from the radio and save the '
            'image as a backup.\n\n'
            'Upload writes only the pages that differ from the radio and '
            'checks each one by reading it back. It takes about a minute '
            'plus a few seconds per changed page.')
        return rp

    @classmethod
    def detect_from_serial(cls, pipe):
        """Check that the connected radio is a DM-32UV."""
        _check_model(_search(_Link(pipe)))
        return cls

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, CH_COUNT)
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_modes = ['FM', 'NFM', 'DMR']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', 'Tone->DTCS',
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(136000000, 174000000), (400000000, 480000000)]
        rf.valid_tuning_steps = STEPS
        # Frequencies are stored to 10 Hz, independent of the step.
        rf.has_nostep_tuning = True
        rf.valid_skips = []
        rf.valid_name_length = 16
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Download failed')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Upload failed')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        self._forget()

    def _forget(self):
        """Drop cached lookups; called whenever the image changes."""
        self._lookups = {}

    def _chan(self, number):
        page, index = channel_offset(number)
        return getattr(self._memobj, 'page%d' % page)[index]

    def get_bank_model(self):
        return DM32UVZoneModel(self)

    def _zone(self, z):
        page, index = zone_offset(z)
        return getattr(self._memobj, 'zpage%d' % page)[index]

    def _zone_count(self):
        count = int(self._memobj.zone_hdr.count)
        return 0 if count > ZONE_COUNT else count

    def _zone_members(self, z):
        if z > self._zone_count():
            return []               # the spare zone, or erased flash
        zone = self._zone(z)
        count = min(int(zone.count), ZONE_MEMBERS)
        return [int(m) for m in zone.members[0:count]
                if 1 <= int(m) <= CH_COUNT]

    @_cached
    def _zone_index(self):
        """{channel: [zones it is in]}"""
        index = collections.defaultdict(list)
        for z in range(1, self._zone_count() + 1):
            for m in self._zone_members(z):
                if z not in index[m]:
                    index[m].append(z)
        return dict(index)

    def _set_zone_members(self, z, members):
        self._forget()
        zone = self._zone(z)
        for i in range(ZONE_MEMBERS):
            zone.members[i] = members[i] if i < len(members) else 0
        zone.count = len(members)

    def _create_zone(self, z):
        """Make zone z (which must be count + 1) an empty, named zone."""
        if z != self._zone_count() + 1 or z > ZONE_COUNT:
            raise errors.RadioError('Zones must be created in order')
        self._forget()
        zone = self._zone(z)
        name = str(zone.name).rstrip('\x00\xFF ')
        if not name or not name.isprintable():
            zone.name = ('Zone %i' % z).ljust(16, '\x00')
        self._set_zone_members(z, [])
        self._memobj.zone_hdr.count = z

    def _zone_list(self):
        """[(name, [members])] for zones 1..count."""
        return [(str(self._zone(z).name).split('\x00')[0].split('\xFF')[0],
                 self._zone_members(z))
                for z in range(1, self._zone_count() + 1)]

    def _set_zone_list(self, zones, remap):
        """Rewrite zones 1..len(zones); remap = {old zone: new zone} for the
        radio's current-zone pointers (a zone not in it was deleted)."""
        self._forget()
        old_count = self._zone_count()
        for z, (name, members) in enumerate(zones, 1):
            zone = self._zone(z)
            if str(zone.name).split('\x00')[0].split('\xFF')[0] != name:
                zone.name.set_raw(_name_bytes(name, 16))
            self._set_zone_members(z, members)
        for z in range(len(zones) + 1, old_count + 1):
            self._zone(z).name.set_raw(b'\xFF' * 16)
            self._set_zone_members(z, [])
        hdr = self._memobj.zone_hdr
        hdr.count = len(zones)
        for zone_f, pos_f in (('a_zone', 'a_pos'), ('b_zone', 'b_pos')):
            new = remap.get(int(getattr(hdr, zone_f)))
            if not new:
                new = 1
                setattr(hdr, pos_f, 1)
            setattr(hdr, zone_f, new)
            members = len(zones[new - 1][1]) if zones else 0
            if not 1 <= int(getattr(hdr, pos_f)) <= max(members, 1):
                setattr(hdr, pos_f, 1)

    def _drop_empty_last_zone(self):
        count = self._zone_count()
        if count > 1 and not self._zone_members(count):
            self._forget()
            self._zone(count).name.set_raw(b'\xFF' * 16)
            self._memobj.zone_hdr.count = count - 1

    def _count(self):
        count = int(self._memobj.ch_count)
        return 0 if count > CH_COUNT else count

    # --- raw page access (DMR lists live outside the bitwise layout) ---------

    def _page(self, tag):
        base = IMAGE_TAGS.index(tag) * PAGE
        return base, self._mmap.get(base, PAGE)

    def _put(self, tag, offset, data):
        base = IMAGE_TAGS.index(tag) * PAGE
        assert offset + len(data) <= PAGE - 1
        self._forget()
        self._mmap.set(base + offset, bytes(data))
        self._mmap.set(base + PAGE - 1, bytes([tag]))   # the page now exists

    @staticmethod
    def _text(raw):
        text = raw.split(b'\xFF')[0].split(b'\x00')[0]
        return text.decode('latin-1')

    # --- radio IDs -----------------------------------------------------------

    @_cached
    def _radio_ids(self):
        """[(dmr_id, name)] for radio IDs 1..count."""
        _base, page = self._page(RADIOID_TAG)
        count = page[0] if page[0] <= RADIOID_MAX else 0
        return [(int.from_bytes(page[16 * n:16 * n + 3], 'little'),
                 self._text(page[16 * n + 3:16 * n + 3 + RADIOID_NAME]))
                for n in range(1, count + 1)]

    def _set_radio_ids(self, entries):
        self._put(RADIOID_TAG, 0, bytes([len(entries)]))
        for n in range(1, RADIOID_MAX + 1):
            if n <= len(entries):
                dmr_id, name = entries[n - 1]
                rec = (dmr_id.to_bytes(3, 'little') +
                       _name_bytes(name, RADIOID_NAME) + b'\x00')
            else:
                rec = b'\x00' * 16
            self._put(RADIOID_TAG, 16 * n, rec)

    # --- contacts ------------------------------------------------------------

    def _contact_loc(self, k):
        return (CONTACT_REC_TAG0 + (k - 1) // CONTACT_PER_PAGE,
                ((k - 1) % CONTACT_PER_PAGE) * CONTACT_REC)

    @_cached
    def _contacts(self):
        """{slot: (name, dmr_id, call_type index)} for used contact slots."""
        _base, index = self._page(CONTACT_INDEX_TAG)
        pages = {}
        contacts = {}
        for k in range(1, CONTACT_MAX + 1):
            if index[0x10 + (k - 1) // 8] >> ((k - 1) % 8) & 1:
                continue                                # free slot
            tag, off = self._contact_loc(k)
            if tag not in pages:
                pages[tag] = self._page(tag)[1]
            rec = pages[tag][off:off + CONTACT_REC]
            ctype = rec[0x16] - 3 if 3 <= rec[0x16] <= 5 else 0
            contacts[k] = (self._text(rec[2:2 + CONTACT_NAME]),
                           int.from_bytes(rec[0x13:0x16], 'little'), ctype)
        return contacts

    def _set_contacts(self, contacts):
        """Write {slot: (name, id, type)} and rebuild the index page the way
        the CPS does (0x474c00): counts, free bitmap, name- and ID-sorted
        lists of (slot | call type code << 12)."""
        _base, index = self._page(CONTACT_INDEX_TAG)
        index = bytearray(index if index[0x10:0x74] != b'\xFF' * 100 or
                          index[0:2] != b'\xFF\xFF' else b'\x00' * PAGE)
        for k, (name, dmr_id, ctype) in contacts.items():
            tag, off = self._contact_loc(k)
            old = self._page(tag)[1][off:off + CONTACT_REC]
            keep = old if old != b'\xFF' * CONTACT_REC else b'\x00' * 24
            name_b = _name_bytes(name, CONTACT_NAME)
            if self._text(keep[2:2 + CONTACT_NAME]) == name:
                name_b = keep[2:2 + CONTACT_NAME]   # keep the radio's padding
            rec = (keep[0:2] + name_b + b'\x00' +
                   dmr_id.to_bytes(3, 'little') + bytes([ctype + 3]) +
                   keep[0x17:0x18])
            self._put(tag, off, rec)
        bitmap = bytearray(b'\xFF' * 100)
        for k in contacts:
            bitmap[(k - 1) // 8] &= ~(1 << ((k - 1) % 8)) & 0xFF
        index[0:2] = len(contacts).to_bytes(2, 'little')
        groups = sum(1 for c in contacts.values() if c[2] == 1)
        index[2:4] = groups.to_bytes(2, 'little')
        index[4] = sum(1 for c in contacts.values() if c[2] == 2)
        index[0x10:0x74] = bitmap
        index[0x100:PAGE - 1] = b'\xFF' * (PAGE - 1 - 0x100)

        def entry(k):
            code = (contacts[k][2] + 3) << 4
            return bytes([k & 0xFF, (k >> 8) & 0xF | code])
        for pos, k in enumerate(sorted(contacts, key=lambda k: (
                contacts[k][0].encode(), k))):
            index[0x100 + 2 * pos:0x102 + 2 * pos] = entry(k)
        for pos, k in enumerate(sorted(contacts, key=lambda k: (
                contacts[k][1], k))):
            index[0x740 + 2 * pos:0x742 + 2 * pos] = entry(k)
        self._put(CONTACT_INDEX_TAG, 0, index[:PAGE - 1])

    def _txc_loc(self, n):
        if n < 0x800:
            return TXC_TAGS[0], 2 * (n - 1)
        if n in (CH_COUNT + 1, CH_COUNT + 2):           # VFO A, B
            return TXC_TAGS[1], 0xFFA + 2 * (n - CH_COUNT - 1)
        return TXC_TAGS[1], 2 * (n & 0x7FF)

    def _tx_contact(self, n):
        tag, off = self._txc_loc(n)
        hi, lo = self._page(tag)[1][off:off + 2]
        value = (hi >> 4) << 8 | lo
        return 0 if value > CONTACT_MAX else value

    def _set_tx_contact(self, n, contact, digital):
        tag, off = self._txc_loc(n)
        hi = self._page(tag)[1][off]
        hi = 0 if hi == 0xFF else hi & 0x0E
        self._put(tag, off, bytes([(contact >> 8) << 4 | hi | int(digital),
                                   contact & 0xFF]))

    # --- RX group lists ------------------------------------------------------

    @_cached
    def _rx_groups(self):
        """{n: (name, [member IDs])} for used groups."""
        _base, page = self._page(RXG_TAG)
        groups = {}
        for n in range(1, RXG_MAX + 1):
            if page[:4] == b'\xFF' * 4 or not page[(n - 1) // 8] >> (
                    (n - 1) % 8) & 1:
                continue
            base = RXG_REC * n - 0x5C
            members = [int.from_bytes(page[base + RXG_NAME + 3 * j:][:3],
                                      'little') for j in range(RXG_MEMBERS)]
            groups[n] = (self._text(page[base:base + RXG_NAME]),
                         [m for m in members if 0 < m <= ALL_CALL_ID])
        return groups

    def _set_rx_groups(self, groups):
        _base, page = self._page(RXG_TAG)
        head = bytearray(page[:0x10] if page[:4] != b'\xFF' * 4
                         else b'\x00' * 0x10)
        head[0:4] = b'\x00' * 4
        for n in groups:
            head[(n - 1) // 8] |= 1 << ((n - 1) % 8)
        self._put(RXG_TAG, 0, head)
        for n in range(1, RXG_MAX + 1):
            base = RXG_REC * n - 0x5C
            name, members = groups.get(n, ('', []))
            data = _name_bytes(name, RXG_NAME)
            for j in range(RXG_MEMBERS):
                m = members[j] if j < len(members) else 0
                data += m.to_bytes(3, 'little')
            self._put(RXG_TAG, base, data)

    # --- scan lists ----------------------------------------------------------

    @_cached
    def _scan_lists(self):
        """[(name, [channels], options bytes +0x0c..+0x17)] for 1..count."""
        _base, page = self._page(SCAN_TAG)
        count = page[0] if page[0] <= SCAN_MAX else 0
        lists = []
        for n in range(1, count + 1):
            rec = page[SCAN_REC * n - 0x38:][:SCAN_REC]
            k = min(rec[0x0B], SCAN_MEMBERS)
            members = [int.from_bytes(rec[0x18 + 2 * i:0x1A + 2 * i],
                                      'little') for i in range(k)]
            lists.append((self._text(rec[:SCAN_NAME]),
                          [m for m in members if 1 <= m <= CH_COUNT],
                          rec[0x0C:0x18]))
        return lists

    def _set_scan_lists(self, lists):
        default = lists[0][2] if lists else SCAN_DEFAULT_OPTS
        old_count = len(self._scan_lists())
        self._put(SCAN_TAG, 0, bytes([len(lists)]))
        for n in range(1, SCAN_MAX + 1):
            base = SCAN_REC * n - 0x38
            if n > len(lists):
                if n <= old_count:          # a list that was removed
                    self._put(SCAN_TAG, base, b'\x00' * SCAN_REC)
                continue
            name, members, opts = lists[n - 1]
            opts = bytearray(opts if len(opts) == 12 else default)
            members = members[:SCAN_MEMBERS]
            designed = int.from_bytes(opts[3:5], 'little')
            if members and designed not in members:
                opts[3:5] = members[0].to_bytes(2, 'little')
            rec = (_name_bytes(name, SCAN_NAME) +
                   bytes([len(members)]) + bytes(opts) +
                   b''.join(m.to_bytes(2, 'little') for m in members) +
                   b'\x00' * (2 * (SCAN_MEMBERS - len(members))))
            self._put(SCAN_TAG, base, rec[:SCAN_REC])

    def _remove_from_scan_lists(self, number):
        lists = self._scan_lists()
        new = []
        for name, members, opts in lists:
            members = [m for m in members if m != number]
            if not members and int.from_bytes(opts[3:5], 'little') == number:
                # the designed channel; the factory lists use channel 1
                opts = opts[:3] + SCAN_DEFAULT_OPTS[3:5] + opts[5:]
            new.append((name, members, opts))
        if new != lists:
            self._set_scan_lists(new)

    # --- Settings tab: DMR lists ---------------------------------------------

    def get_settings(self):
        dmr = RadioSettingGroup('dmr', 'DMR lists')
        ids = RadioSettingGroup('radio_ids', 'Radio IDs')
        entries = self._radio_ids()
        for n in range(1, min(len(entries) + 8, RADIOID_MAX) + 1):
            dmr_id, name = entries[n - 1] if n <= len(entries) else (0, '')
            ids.append(RadioSetting(
                'rid_%d_id' % n, 'Radio ID %d: DMR ID (0 = unused)' % n,
                RadioSettingValueInteger(0, DMR_ID_MAX,
                                         min(dmr_id, DMR_ID_MAX))))
            ids.append(RadioSetting(
                'rid_%d_name' % n, 'Radio ID %d: name' % n,
                RadioSettingValueString(0, RADIOID_NAME, _shown(name),
                                        autopad=False)))
        contacts = RadioSettingGroup('contacts', 'Contacts')
        used = self._contacts()
        free = [k for k in range(1, CONTACT_MAX + 1) if k not in used]
        for k in sorted(used) + free[:10]:
            name, dmr_id, ctype = used.get(k, ('', 1, 1))
            contacts.append(RadioSetting(
                'con_%d_name' % k, 'Contact %d: name (empty = unused)' % k,
                RadioSettingValueString(0, CONTACT_NAME, _shown(name),
                                        autopad=False)))
            contacts.append(RadioSetting(
                'con_%d_id' % k, 'Contact %d: DMR ID' % k,
                RadioSettingValueInteger(1, ALL_CALL_ID, max(dmr_id, 1))))
            contacts.append(RadioSetting(
                'con_%d_type' % k, 'Contact %d: call type' % k,
                RadioSettingValueList(CALL_TYPES, current_index=ctype)))
        groups = RadioSettingGroup('rx_groups', 'RX group lists')
        by_id = {c[1]: _shown(c[0]) for c in used.values()}
        # CHIRP keeps showing this tree after later edits, so remember the
        # names shown here: a member name stays valid after a rename.
        self._shown_contact_ids = {_shown(c[0]): c[1] for c in used.values()}
        existing = self._rx_groups()
        spare = [n for n in range(1, RXG_MAX + 1) if n not in existing][:3]
        for n in sorted(existing) + spare:
            name, members = existing.get(n, ('', []))
            groups.append(RadioSetting(
                'rxg_%d_name' % n, 'RX group %d: name (empty = unused)' % n,
                RadioSettingValueString(0, RXG_NAME, _shown(name),
                                        autopad=False)))
            groups.append(RadioSetting(
                'rxg_%d_members' % n,
                'RX group %d: contacts (names or IDs, comma separated)' % n,
                RadioSettingValueString(
                    0, 600, ', '.join(by_id.get(m, str(m)) for m in members),
                    autopad=False, charset=chirp_common.CHARSET_ASCII)))
        dmr.append(ids)
        dmr.append(contacts)
        dmr.append(groups)
        scan = RadioSettingGroup('scan', 'Scan lists')
        lists = self._scan_lists()
        for n in range(1, min(len(lists) + 1, SCAN_MAX) + 1):
            name, members, opts = lists[n - 1] if n <= len(lists) else (
                '', [], bytes(12))
            scan.append(RadioSetting(
                'scan_%d_name' % n, 'Scan list %d: name (empty = unused)' % n,
                RadioSettingValueString(0, SCAN_NAME, _shown(name),
                                        autopad=False)))
            scan.append(RadioSetting(
                'scan_%d_members' % n,
                'Scan list %d: channels (numbers, comma separated)' % n,
                RadioSettingValueString(0, 100, ', '.join(map(str, members)),
                                        autopad=False)))
            scan.append(RadioSetting(
                'scan_%d_ctc' % n, 'Scan list %d: CTC scan mode' % n,
                RadioSettingValueList(SCAN_CTC_MODES, current_index=min(
                    opts[0] & 0xF, len(SCAN_CTC_MODES) - 1))))
            scan.append(RadioSetting(
                'scan_%d_tx' % n, 'Scan list %d: scan TX mode' % n,
                RadioSettingValueList(SCAN_TX_MODES, current_index=min(
                    opts[0] >> 4, len(SCAN_TX_MODES) - 1))))
        zones = RadioSettingGroup('zones', 'Zones')
        zlist = self._zone_list()
        zones.append(RadioSetting(
            'zone_order', 'Zone order (zone numbers, comma separated; '
            'reopen the image before using the Banks tab again)',
            RadioSettingValueString(0, ZONE_ORDER_MAX, ', '.join(
                str(z) for z in range(1, len(zlist) + 1)), autopad=False)))
        for z, (name, members) in enumerate(zlist, 1):
            zones.append(RadioSetting(
                'zone_%d_name' % z, 'Zone %d: name' % z,
                RadioSettingValueString(0, 16, _shown(name),
                                        autopad=False)))
            zones.append(RadioSetting(
                'zone_%d_members' % z,
                'Zone %d: channels in order (empty = delete zone)' % z,
                RadioSettingValueString(0, 400, ', '.join(map(str, members)),
                                        autopad=False)))
        groups_out = [dmr, scan, zones]
        if self._has_page(DTMF_TAG):
            groups_out.append(self._dtmf_contacts_group())
        if self._has_page(SIGNAL_TAG):
            groups_out.append(self._tt_encode_group())
            groups_out.append(self._ft_special_group())
        radio = self._radio_settings()
        if len(radio):
            groups_out.insert(0, radio)
        return RadioSettings(*groups_out)

    def _tt_encode(self):
        """[(name, single tone, tone 1, tone 2)] of two-tone encode
        entries 1..count (tones in 0.1 Hz)."""
        count = int(self._memobj.tt_encode_count)
        count = count if 1 <= count <= TT_ENCODE else 1    # as the CPS
        out = []
        for e in list(self._memobj.tt_encode)[:count]:
            raw = e.name.get_raw()
            name = raw.decode('utf-16-le', 'replace').split('\x00')[0]
            if raw[:2] == b'\xFF\xFF':
                name = ''
            out.append((name, bool(e.single_tone), int(e.tone1),
                        int(e.tone2)))
        return out

    def _tt_encode_group(self):
        group = RadioSettingGroup('tt_encode', 'Two-tone encode')
        entries = self._tt_encode()
        for n in range(1, min(len(entries) + 4, TT_ENCODE) + 1):
            name, single, t1, t2 = entries[n - 1] if n <= len(entries) \
                else ('', False, 0, 0)
            group.append(RadioSetting(
                'tte_%d_name' % n, 'Encode %d: name (empty = unused)' % n,
                RadioSettingValueString(0, 16, _shown(name), autopad=False)))
            group.append(RadioSetting(
                'tte_%d_single' % n, 'Encode %d: send' % n,
                RadioSettingValueList(['Dual Tone', 'Single Tone'],
                                      current_index=int(single))))
            for k, tone in ((1, t1), (2, t2)):
                group.append(RadioSetting(
                    'tte_%d_tone%d' % (n, k), 'Encode %d: tone %d (Hz)' % (
                        n, k),
                    RadioSettingValueString(
                        0, 7, '%.1f' % (tone / 10)
                        if TT_HZ[0] <= tone <= TT_HZ[1] else '',
                        autopad=False, charset='0123456789.')))
        return group

    def _set_tt_encode(self, values):
        old = self._tt_encode()
        new = list(old)
        for n in range(1, TT_ENCODE + 1):
            if 'tte_%d_name' % n not in values:
                continue
            o = old[n - 1] if n <= len(old) else ('', False, 0, 0)
            name = _edited(values['tte_%d_name' % n], o[0])
            tones = []
            for k in (1, 2):
                text = str(values['tte_%d_tone%d' % (n, k)]).strip()
                shown = '%.1f' % (o[1 + k] / 10) \
                    if TT_HZ[0] <= o[1 + k] <= TT_HZ[1] else ''
                tones.append(o[1 + k] if text == shown else _parse_hz(
                    text, TT_HZ, 'Two-tone encode %d, tone %d' % (n, k)))
            single = str(values['tte_%d_single' % n]) == 'Single Tone'
            while len(new) < n:
                new.append(('', False, 0, 0))
            new[n - 1] = (name, single, tones[0], tones[1])
        while len(new) > 1 and not new[-1][0]:
            new.pop()
        if new == old:
            return
        self._forget()
        for n, (name, single, t1, t2) in enumerate(new, 1):
            e = self._memobj.tt_encode[n - 1]
            if n > len(old) or old[n - 1][0] != name:
                e.name.set_raw(
                    name.encode('utf-16-le')[:32].ljust(32, b'\x00'))
            if n > len(old) and e.get_raw()[0x20:] == b'\xFF' * 8:
                e.set_raw(e.get_raw()[:0x20] + b'\xFE\xFF' + b'\xFF' * 6)
            e.single_tone = int(single)
            e.tone1, e.tone2 = t1, t2
        for n in range(len(new) + 1, len(old) + 1):
            self._memobj.tt_encode[n - 1].set_raw(b'\x00' * 0x20 +
                                                  b'\xFF' * 8)
        self._memobj.tt_encode_count = len(new)

    def _ft_special(self):
        """[{field: shown value}] of the 32 five-tone special calls."""
        out = []
        for e in self._memobj.ft_special:
            types, stored = FT_SPECIAL_TYPES
            t = int(e.type)
            out.append({
                'type': types[stored.index(t)] if t in stored else 'Off',
                'code': _dtmf_text(e.code.get_raw(), CODE_CHARS['hex']),
                'delimiter': FT_DELIMITERS[int(e.delimiter)]
                if int(e.delimiter) < len(FT_DELIMITERS) else
                FT_DELIMITERS[0],
                'standard': FT_STANDARDS[int(e.standard)]
                if int(e.standard) < len(FT_STANDARDS) else FT_STANDARDS[0],
                'tone_long': FT_TONE_LONG[0][int(e.tone_long) - 3]
                if 3 <= int(e.tone_long) < 3 + len(FT_TONE_LONG[0])
                else FT_TONE_LONG[0][0],
                'data': _dtmf_text(e.data.get_raw(), CODE_CHARS['hex']),
                'name': self._text(e.name.get_raw()),
            })
        return out

    def _ft_special_group(self):
        group = RadioSettingGroup('ft_special', 'Five-tone special calls')
        hexchars = CODE_CHARS['hex'] + CODE_CHARS['hex'].lower()
        calls = self._ft_special()
        used = [n for n, c in enumerate(calls, 1) if c['type'] != 'Off']
        spare = [n for n in range(1, FT_SPECIAL + 1) if n not in used][:3]
        for n in used + spare:
            c = calls[n - 1]
            label = 'Special call %d: ' % n
            for key, text, value in (
                    ('type', 'call type (Off = unused)', _pick(
                        FT_SPECIAL_TYPES[0], c['type'])),
                    ('name', 'name', RadioSettingValueString(
                        0, 16, _shown(c['name']), autopad=False)),
                    ('code', 'other side code', RadioSettingValueString(
                        0, 5, c['code'], autopad=False, charset=hexchars)),
                    ('delimiter', 'middle delimiter', _pick(
                        FT_DELIMITERS, c['delimiter'])),
                    ('standard', 'decode standard', _pick(
                        FT_STANDARDS, c['standard'])),
                    ('tone_long', 'tone long', _pick(
                        FT_TONE_LONG[0], c['tone_long'])),
                    ('data', 'data transmission', RadioSettingValueString(
                        0, 16, c['data'], autopad=False, charset=hexchars))):
                group.append(RadioSetting('fts_%d_%s' % (n, key),
                                          label + text, value))
        return group

    def _set_ft_special(self, values):
        calls = self._ft_special()
        for n in range(1, FT_SPECIAL + 1):
            if 'fts_%d_type' % n not in values:
                continue
            c, e = calls[n - 1], self._memobj.ft_special[n - 1]
            new = {k: str(values['fts_%d_%s' % (n, k)]).strip()
                   for k in c}
            if new['name'] == _shown(c['name']).strip():
                new['name'] = c['name']
            for k in ('code', 'data'):
                new[k] = new[k].upper()
            if new == c:
                continue
            self._forget()
            if new['type'] != c['type']:
                types, stored = FT_SPECIAL_TYPES
                e.type = stored[types.index(new['type'])]
            if new['code'] != c['code']:
                e.code.set_raw(_dtmf_bytes(new['code'], 5, CODE_CHARS['hex']))
            if new['data'] != c['data']:
                e.data.set_raw(_dtmf_bytes(new['data'], 16,
                                           CODE_CHARS['hex']))
            if new['name'] != c['name']:
                e.name.set_raw((new['name'].encode('latin-1', 'replace')[:16]
                                + b'\x00')[:16].ljust(16, b'\xFF'))
            if new['delimiter'] != c['delimiter']:
                e.delimiter = FT_DELIMITERS.index(new['delimiter'])
            if new['standard'] != c['standard']:
                e.standard = FT_STANDARDS.index(new['standard'])
            if new['tone_long'] != c['tone_long']:
                e.tone_long = FT_TONE_LONG[0].index(new['tone_long']) + 3

    def _has_page(self, tag):
        return self._page(tag)[1][:PAGE - 1] != b'\xFF' * (PAGE - 1)

    def _dtmf_contacts(self):
        """[(name, number)] of DTMF (analog) contacts 1..count."""
        count = int(self._memobj.dtmf_contact_count)
        count = count if count <= DTMF_CONTACTS else 0
        return [(self._text(c.name.get_raw()),
                 _dtmf_text(c.number.get_raw(), '0123456789'))
                for c in list(self._memobj.dtmf_contacts)[:count]]

    def _dtmf_contacts_group(self):
        group = RadioSettingGroup('dtmf_contacts', 'DTMF contacts')
        contacts = self._dtmf_contacts()
        for n in range(1, min(len(contacts) + 4, DTMF_CONTACTS) + 1):
            name, number = contacts[n - 1] if n <= len(contacts) else ('', '')
            group.append(RadioSetting(
                'dtc_%d_name' % n, 'DTMF contact %d: name' % n,
                RadioSettingValueString(0, 16, _shown(name), autopad=False)))
            group.append(RadioSetting(
                'dtc_%d_number' % n, 'DTMF contact %d: number (up to 5 '
                'digits)' % n,
                RadioSettingValueString(0, 5, number, autopad=False,
                                        charset='0123456789')))
        return group

    def _set_dtmf_contacts(self, values):
        old = self._dtmf_contacts()
        new = list(old)
        for n in range(1, DTMF_CONTACTS + 1):
            if 'dtc_%d_name' % n not in values:
                continue
            old_name = old[n - 1][0] if n <= len(old) else ''
            name = _edited(values['dtc_%d_name' % n], old_name)
            number = str(values['dtc_%d_number' % n]).strip()
            while len(new) < n:
                new.append(('', ''))
            new[n - 1] = (name, number)
        while new and not new[-1][0]:
            new.pop()
        for n, (name, number) in enumerate(new, 1):
            if not name:
                raise errors.InvalidValueError(
                    'DTMF contact %d: a name is needed (only the last '
                    'contacts can be removed)' % n)
        if new == old:
            return
        self._forget()
        for n, (name, number) in enumerate(new, 1):
            c = self._memobj.dtmf_contacts[n - 1]
            if n > len(old) or old[n - 1][0] != name:
                c.name.set_raw(_name_bytes(name, 16))
            if n > len(old) or old[n - 1][1] != number:
                c.number.set_raw(_dtmf_bytes(number, 5, '0123456789'))
            if n > len(old) and c.unknown.get_raw() == b'\xFF' * 11:
                c.unknown.set_raw(b'\x00' * 11)
        for n in range(len(new) + 1, len(old) + 1):
            self._memobj.dtmf_contacts[n - 1].set_raw(b'\xFF' * 0x20)
        self._memobj.dtmf_contact_count = len(new)

    def _radio_settings(self):
        top = RadioSettingGroup('radio', 'Radio settings')
        for title, entries in RADIO_SETTINGS:
            group = RadioSettingGroup('radio_%s' % title.lower().replace(
                ' ', '_'), title)
            for sname, field, label, kind, extra in entries:
                if not self._has_page(STRUCT_TAGS.get(sname, 0x04)):
                    continue
                obj = getattr(self._memobj, sname)
                name = 'set_%s_%s' % (sname, field)
                if kind == 'bool':
                    value = RadioSettingValueBoolean(bool(getattr(obj,
                                                                  field)))
                elif kind == 'text':
                    text = str(getattr(obj, field))
                    text = text.split('\x00')[0].split('\xFF')[0]
                    text = ''.join(c for c in text
                                   if c in chirp_common.CHARSET_ASCII)
                    value = RadioSettingValueString(0, extra, text,
                                                    autopad=False)
                elif kind == 'coord':
                    value = RadioSettingValueString(
                        0, 12, _parse_coord(getattr(obj, field).get_raw()),
                        autopad=False)
                elif kind == 'int':
                    lo, hi = extra
                    number = int(getattr(obj, field))
                    value = RadioSettingValueInteger(
                        lo, hi, number if lo <= number <= hi else lo)
                elif kind == 'channel':
                    name = 'set_%s_%s_%d' % (sname, field, extra + 1)
                    value = self._channel_choice(
                        int(getattr(obj, field)[extra]))
                elif kind == 'hz':
                    tenths = int(getattr(obj, field))
                    value = RadioSettingValueString(
                        0, 7, '%.1f' % (tenths / 10)
                        if extra[0] <= tenths <= extra[1] else '',
                        autopad=False, charset='0123456789.')
                elif kind == 'dtmf':
                    value = RadioSettingValueString(
                        0, extra, _dtmf_text(getattr(obj, field).get_raw()),
                        autopad=False, charset=DTMF_CHARS + 'abcd')
                elif kind in ('digits', 'hex'):
                    chars = CODE_CHARS[kind]
                    value = RadioSettingValueString(
                        0, extra, _dtmf_text(getattr(obj, field).get_raw(),
                                             chars),
                        autopad=False, charset=chars + chars.lower())
                else:
                    options, offset = extra
                    index = _list_index(int(getattr(obj, field)), offset)
                    value = RadioSettingValueList(options, current_index=(
                        index if 0 <= index < len(options) else 0))
                group.append(RadioSetting(name, label, value))
            if len(group):
                top.append(group)
        return top

    def _channel_choice(self, value):
        """Report channel choice: the current channel, or a digital one."""
        options = ['Current Channel'] + self._digital_channels()
        current = 'Current Channel' if not value else '%d: %s' % (
            value, self._channel_names().get(value, '(empty)'))
        if current not in options:
            options.append(current)
        return RadioSettingValueList(options,
                                     current_index=options.index(current))

    @_cached
    def _channel_names(self):
        """{number: name} of the channels in use."""
        names = {}
        for n in range(1, self._count() + 1):
            _mem = self._chan(n)
            if _mem.rxfreq.get_raw() not in (b'\xFF' * 4, b'\x00' * 4):
                names[n] = _shown(str(_mem.name).rstrip('\x00\xFF '))
        return names

    @_cached
    def _digital_channels(self):
        names = self._channel_names()
        return ['%d: %s' % (n, names[n]) for n in names
                if self._chan(n).chtype in (1, 3)]

    @staticmethod
    def _set_coord(field, label, limit, text):
        """Store a coordinate typed on the Settings tab, if it changed."""
        if text == _parse_coord(field.get_raw()):
            return
        if not text:
            field.set_raw(b'\x00' * 9)
            return
        try:
            value = float(text)
        except ValueError:
            value = -1
        if not 0 <= value <= limit:
            raise errors.InvalidValueError(
                '%s must be a number from 0 to %d' % (label, limit))
        field.set_raw(_format_coord(value, limit).encode())

    def set_settings(self, settings):
        values = {}

        def walk(group):
            for element in group:
                if isinstance(element, RadioSetting):
                    values[element.get_name()] = element.value
                else:
                    walk(element)
        walk(settings)

        for title, entries in RADIO_SETTINGS:
            for sname, field, label, kind, extra in entries:
                name = 'set_%s_%s' % (sname, field)
                if kind == 'channel':
                    name = 'set_%s_%s_%d' % (sname, field, extra + 1)
                if name not in values:
                    continue
                obj = getattr(self._memobj, sname)
                if kind == 'coord':
                    self._set_coord(getattr(obj, field), label, extra,
                                    str(values[name]).strip())
                elif kind == 'int':
                    lo, hi = extra
                    number = int(getattr(obj, field))
                    new = int(values[name])
                    if new != (number if lo <= number <= hi else lo):
                        setattr(obj, field, new)
                elif kind == 'channel':
                    choice = str(values[name])
                    new = int(choice.split(':')[0]) if ':' in choice else 0
                    if new != int(getattr(obj, field)[extra]):
                        getattr(obj, field)[extra] = new
                elif kind == 'bool':
                    setattr(obj, field, int(bool(values[name])))
                elif kind == 'text':
                    text = str(values[name]).rstrip()
                    old = str(getattr(obj, field)).split('\x00')[0]
                    if text != old.split('\xFF')[0]:
                        setattr(obj, field, text[:extra].ljust(extra, '\x00'))
                elif kind == 'hz':
                    tenths = int(getattr(obj, field))
                    text = str(values[name]).strip()
                    shown = '%.1f' % (tenths / 10) \
                        if extra[0] <= tenths <= extra[1] else ''
                    if text != shown:
                        setattr(obj, field, _parse_hz(text, extra, label))
                elif kind in CODE_CHARS:
                    chars = CODE_CHARS[kind]
                    raw = getattr(obj, field)
                    text = str(values[name]).strip().upper()
                    if text != _dtmf_text(raw.get_raw(), chars):
                        if kind == 'digits':
                            # the CPS pads with leading zeros (0x47be70)
                            raw.set_raw(bytes(chars.index(c) for c in
                                              text.rjust(extra, '0')))
                        else:
                            raw.set_raw(_dtmf_bytes(text, extra, chars))
                else:
                    options, offset = extra
                    new = options.index(str(values[name]))
                    shown = _list_index(int(getattr(obj, field)), offset)
                    if not 0 <= shown < len(options):
                        shown = 0           # displayed as the first option
                    if new != shown:        # don't rewrite what wasn't changed
                        setattr(obj, field, _list_stored(new, offset))

        self._forget()
        if self._has_page(DTMF_TAG):
            self._set_dtmf_contacts(values)
        if self._has_page(SIGNAL_TAG):
            self._set_tt_encode(values)
            self._set_ft_special(values)

        # Radio IDs: keep the ones with an ID, in order; renumber channels.
        old = self._radio_ids()
        kept, remap = [], {}
        for n in range(1, RADIOID_MAX + 1):
            if 'rid_%d_id' % n not in values:
                if n <= len(old):
                    kept.append(old[n - 1])
                    remap[n] = len(kept)
                continue
            dmr_id = int(values['rid_%d_id' % n])
            old_id, old_name = old[n - 1] if n <= len(old) else (0, '')
            if dmr_id == min(old_id, DMR_ID_MAX):
                dmr_id = old_id             # shown clamped, not changed
            if dmr_id:
                kept.append((dmr_id, _edited(values['rid_%d_name' % n],
                                             old_name)))
                remap[n] = len(kept)
        if [e for e in kept] != old or any(k != v for k, v in remap.items()):
            self._set_radio_ids(kept)
            for number in range(1, self._count() + 1):
                _mem = self._chan(number)
                if int(_mem.radio_id):
                    _mem.radio_id = remap.get(int(_mem.radio_id), 0)

        # Contacts: an empty name frees the slot.
        old_contacts = self._contacts()
        contacts = dict(old_contacts)
        # RX group members are shown by name; accept the names shown when
        # the settings were read and those from before this edit too (a
        # renamed contact keeps its ID).
        by_name = dict(getattr(self, '_shown_contact_ids', {}))
        by_name.update({_shown(c[0]): c[1] for c in contacts.values()})
        for k in range(1, CONTACT_MAX + 1):
            if 'con_%d_name' % k not in values:
                continue
            old_name, old_id, _t = contacts.get(k, ('', 1, 0))
            name = _edited(values['con_%d_name' % k], old_name)
            if name:
                ctype = CALL_TYPES.index(str(values['con_%d_type' % k]))
                dmr_id = int(values['con_%d_id' % k])
                if dmr_id == max(old_id, 1):
                    dmr_id = old_id         # shown clamped, not changed
                contacts[k] = (name, dmr_id, ctype)
            else:
                contacts.pop(k, None)
        if contacts != old_contacts:
            self._set_contacts(contacts)
            for number in range(1, self._count() + 1):
                if self._tx_contact(number) and \
                        self._tx_contact(number) not in contacts:
                    self._set_tx_contact(number, 0,
                                         self._chan(number).chtype in (1, 3))

        # RX groups: members by contact name or number.
        by_name.update({_shown(c[0]): c[1] for c in contacts.values()})
        old_groups = self._rx_groups()
        groups = dict(old_groups)
        for n in range(1, RXG_MAX + 1):
            if 'rxg_%d_name' % n not in values:
                continue
            name = _edited(values['rxg_%d_name' % n],
                           groups.get(n, ('', []))[0])
            if not name:
                groups.pop(n, None)
                continue
            members = []
            for item in str(values['rxg_%d_members' % n]).split(','):
                item = item.strip()
                if not item:
                    continue
                if item in by_name:
                    members.append(by_name[item])
                elif item.isdigit() and 0 < int(item) <= ALL_CALL_ID:
                    members.append(int(item))
                else:
                    raise errors.InvalidValueError(
                        'RX group %s: unknown contact %r' % (name, item))
            if len(members) > RXG_MEMBERS:
                raise errors.InvalidValueError(
                    'RX group %s: at most %d contacts' % (name, RXG_MEMBERS))
            groups[n] = (name, members)
        if groups != old_groups:
            self._set_rx_groups(groups)

        # Zones: names, member order, deletion, zone order.
        if 'zone_order' in values:
            old = self._zone_list()
            edited = {}
            for z, (name, members) in enumerate(old, 1):
                name = _edited(values.get('zone_%d_name' % z, _shown(name)),
                               name)
                text = values.get('zone_%d_members' % z)
                if text is not None:
                    members = []
                    for item in str(text).split(','):
                        item = item.strip()
                        if not item:
                            continue
                        if not item.isdigit() or not \
                                1 <= int(item) <= self._count():
                            raise errors.InvalidValueError(
                                'Zone %s: %r is not a channel in use' % (
                                    name, item))
                        members.append(int(item))
                    if len(members) > ZONE_MEMBERS:
                        raise errors.InvalidValueError(
                            'Zone %s: at most %d channels' % (
                                name, ZONE_MEMBERS))
                if members:
                    edited[z] = (name, members)
            order = []
            for item in str(values['zone_order']).split(','):
                item = item.strip()
                if not item:
                    continue
                if not item.isdigit() or int(item) not in range(
                        1, len(old) + 1) or int(item) in order:
                    raise errors.InvalidValueError(
                        'Zone order: %r is not a zone number' % item)
                order.append(int(item))
            order = [z for z in order if z in edited] + [
                z for z in edited if z not in order]
            if not order:
                raise errors.InvalidValueError('At least one zone must remain')
            new = [edited[z] for z in order]
            if new != old:
                self._set_zone_list(new, {z: i for i, z in enumerate(
                    order, 1)})

        # Scan lists: an empty name removes the list; lists stay numbered
        # 1..count, so channels pointing at a later list are renumbered.
        old = self._scan_lists()
        new, remap = [], {}
        for n in range(1, SCAN_MAX + 1):
            if 'scan_%d_name' % n not in values:
                if n <= len(old):
                    new.append(old[n - 1])
                    remap[n] = len(new)
                continue
            name = _edited(values['scan_%d_name' % n],
                           old[n - 1][0] if n <= len(old) else '')
            if not name:
                continue
            members = []
            for item in str(values['scan_%d_members' % n]).split(','):
                item = item.strip()
                if not item:
                    continue
                if not item.isdigit() or not 1 <= int(item) <= CH_COUNT:
                    raise errors.InvalidValueError(
                        'Scan list %s: %r is not a channel number' % (
                            name, item))
                members.append(int(item))
            if len(members) > SCAN_MEMBERS:
                raise errors.InvalidValueError(
                    'Scan list %s: at most %d channels' % (name, SCAN_MEMBERS))
            opts = bytearray(old[n - 1][2] if n <= len(old) else (
                old[0][2] if old else SCAN_DEFAULT_OPTS))
            tx_mode = SCAN_TX_MODES.index(str(values['scan_%d_tx' % n]))
            ctc_mode = SCAN_CTC_MODES.index(str(values['scan_%d_ctc' % n]))
            opts[0] = tx_mode << 4 | ctc_mode
            new.append((name, members, bytes(opts)))
            remap[n] = len(new)
        if new != old:
            self._set_scan_lists(new)
            for number in range(1, self._count() + 1):
                _mem = self._chan(number)
                if int(_mem.scanlist):
                    _mem.scanlist = remap.get(int(_mem.scanlist), 0)

    def get_raw_memory(self, number):
        return repr(self._chan(number))

    def get_memory(self, number):
        _mem = self._chan(number)
        mem = chirp_common.Memory()
        mem.number = number
        rx = _mem.rxfreq.get_raw()
        if number > self._count() or rx in (b'\xFF' * 4, b'\x00' * 4):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        if _mem.txfreq.get_raw() == b'\xFF' * 4:
            mem.duplex = 'off'
        else:
            chirp_common.split_to_offset(mem, mem.freq,
                                         int(_mem.txfreq) * 10)
        mem.name = str(_mem.name).rstrip('\x00\xFF ')
        digital = _mem.chtype in (1, 3)
        mem.mode = 'DMR' if digital else ('FM' if _mem.wide else 'NFM')
        mem.power = POWER_LEVELS[min(int(_mem.power), 2)]
        if _mem.step < len(STEPS):
            mem.tuning_step = STEPS[_mem.step]
        if not digital:
            chirp_common.split_tone_decode(
                mem, _decode_tone(_mem.txtone), _decode_tone(_mem.rxtone))

        mem.extra = self._get_extra(_mem, number)
        return mem

    @_cached
    def _dmr_names(self, kind):
        """{index: name} of the entries in one of the DMR_LISTS."""
        tag, first, size, length, count = DMR_LISTS[kind]
        _base, page = self._page(tag)
        names = {}
        for n in range(1, count + 1):
            name = self._text(page[first + (n - 1) * size:][:length])
            if name:
                names[n] = name
        return names

    @_cached
    def _choice_names(self, kind):
        """({index: shown name}, name of 0) for _dmr_choice."""
        if kind == 'radio_id':
            names = {n: '%s (%d)' % (name, dmr_id) for n, (dmr_id, name)
                     in enumerate(self._radio_ids(), 1)}
            none = 'Default'
        elif kind == 'tx_contact':
            names = {k: c[0] for k, c in self._contacts().items()}
            none = 'None'
        elif kind == 'rxgroup':
            names = {n: g[0] for n, g in self._rx_groups().items()}
            none = 'None'
        elif kind == 'scanlist':
            names = {n: sl[0] for n, sl in enumerate(self._scan_lists(), 1)}
            none = 'None'
        else:
            names, none = self._dmr_names(kind), 'None'
        return {n: _shown(name) for n, name in names.items()}, none

    def _dmr_choice(self, kind, value):
        """A RadioSettingValueList for a DMR list index (0 = none)."""
        names, none = self._choice_names(kind)
        options = [none] + ['%d: %s' % kv for kv in sorted(names.items())]
        current = none if not value else '%d: %s' % (
            value, names.get(value, '(unnamed)'))
        if current not in options:
            options.append(current)
        return RadioSettingValueList(options,
                                     current_index=options.index(current))

    def _get_extra(self, _mem, number):
        extra = RadioSettingGroup('extra', 'Extra')
        extra.append(RadioSetting(
            'chtype', 'Channel type',
            RadioSettingValueList(CHTYPES, current_index=min(
                int(_mem.chtype), len(CHTYPES) - 1))))
        extra.append(RadioSetting(
            'colorcode', 'Color code (DMR)',
            RadioSettingValueInteger(0, 15, int(_mem.colorcode))))
        extra.append(RadioSetting(
            'timeslot', 'Time slot (DMR)',
            RadioSettingValueList(['1', '2'],
                                  current_index=int(_mem.timeslot))))
        extra.append(RadioSetting(
            'tx_contact', 'TX contact (DMR)',
            self._dmr_choice('tx_contact', self._tx_contact(number))))
        extra.append(RadioSetting(
            'radio_id', 'Radio ID (DMR)',
            self._dmr_choice('radio_id', int(_mem.radio_id))))
        extra.append(RadioSetting(
            'rxgroup', 'RX group list (DMR)',
            self._dmr_choice('rxgroup', int(_mem.rxgroup))))
        extra.append(RadioSetting(
            'encrypt', 'Encryption (DMR)',
            RadioSettingValueBoolean(bool(_mem.encrypt))))
        extra.append(RadioSetting(
            'privacy', 'Encryption key (DMR)',
            self._dmr_choice('privacy', int(_mem.privacy))))
        extra.append(RadioSetting(
            'scanlist', 'Scan list',
            self._dmr_choice('scanlist', int(_mem.scanlist))))
        extra.append(RadioSetting(
            'squelch', 'Squelch level',
            RadioSettingValueInteger(0, 9, min(int(_mem.squelch), 9))))
        extra.append(RadioSetting(
            'forbid_tx', 'Forbid TX',
            RadioSettingValueBoolean(bool(_mem.forbid_tx))))
        extra.append(RadioSetting(
            'forbid_talkaround', 'Forbid talkaround',
            RadioSettingValueBoolean(bool(_mem.forbid_talkaround))))
        admit = TX_ADMIT[_mem.chtype in (1, 3)]
        extra.append(RadioSetting(
            'tx_admit', 'TX admit',
            RadioSettingValueList(admit, current_index=min(
                int(_mem.tx_admit), len(admit) - 1))))
        for name, (label, options) in LIST_EXTRAS.items():
            extra.append(RadioSetting(
                name, label, RadioSettingValueList(options, current_index=min(
                    int(getattr(_mem, name)), len(options) - 1))))
        extra.append(RadioSetting(
            'emerg_system', 'Emergency system (DMR)',
            self._dmr_choice('emergency', int(_mem.emerg_system))))
        for name, label in BOOL_EXTRAS:
            extra.append(RadioSetting(
                name, label,
                RadioSettingValueBoolean(bool(getattr(_mem, name)))))
        return extra

    def set_memory(self, mem):
        _mem = self._chan(mem.number)
        if mem.empty:
            _mem.set_raw(b'\xFF' * CH_SIZE)
            self._update_tx_contact(mem.number, 0, False)
            # Zones must not point at a channel that no longer exists.
            for z in range(1, self._zone_count() + 1):
                members = self._zone_members(z)
                if mem.number in members:
                    self._set_zone_members(
                        z, [m for m in members if m != mem.number])
            self._drop_empty_last_zone()
            self._remove_from_scan_lists(mem.number)
            if mem.number == self._count():
                count = mem.number - 1
                while count and self.get_memory(count).empty:
                    count -= 1
                self._memobj.ch_count = count
            return

        if _mem.get_raw() in (b'\xFF' * CH_SIZE, b'\x00' * CH_SIZE):
            # Defaults as on the channels the radio came with.
            _mem.set_raw(b'\xFF' * 16 + b'\x00' * 8 + bytes.fromhex(
                '0000000030000000' '00ffffffff000000' '0000000000000000'))
        if mem.number > self._count():
            # Channels skipped over become part of 1..count: make sure they
            # are empty, not left-over template data (factory records past
            # the count hold e.g. 400.000 MHz and would show up).
            for gap in range(self._count() + 1, mem.number):
                self._chan(gap).set_raw(b'\xFF' * CH_SIZE)
            self._memobj.ch_count = mem.number

        _mem.name = mem.name.ljust(16, '\x00')[:16]
        _mem.rxfreq = mem.freq // 10
        if mem.duplex == 'off':
            _mem.txfreq.fill_raw(b'\xFF')
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        digital = mem.mode == 'DMR'
        if digital and _mem.chtype not in (1, 3):
            _mem.chtype = 1
        elif not digital and _mem.chtype not in (0, 2):
            _mem.chtype = 0
        _mem.wide = mem.mode == 'FM'
        _mem.power = POWER_LEVELS.index(mem.power) if mem.power else 2
        if mem.tuning_step in STEPS:
            _mem.step = STEPS.index(mem.tuning_step)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _encode_tone(_mem.txtone, *txtone)
        _encode_tone(_mem.rxtone, *rxtone)

        tx_contact = self._tx_contact(mem.number)
        # Values shown clamped (e.g. squelch 12 as 9) stay as they are
        # unless the user changed them.
        shown = {s.get_name(): str(s.value)
                 for s in self._get_extra(_mem, mem.number)}
        for setting in mem.extra:
            name = setting.get_name()
            if shown.get(name) == str(setting.value):
                continue
            if name == 'chtype':
                # Keep the analog/digital choice consistent with the mode.
                value = CHTYPES.index(str(setting.value))
                if (value in (1, 3)) == digital:
                    _mem.chtype = value
            elif name == 'timeslot':
                _mem.timeslot = int(str(setting.value)) - 1
            elif name == 'tx_admit':
                value = str(setting.value)
                options = TX_ADMIT[_mem.chtype in (1, 3)]
                if value not in options:           # mode changed: other list
                    options = TX_ADMIT[_mem.chtype not in (1, 3)]
                _mem.tx_admit = options.index(value)
            elif name in LIST_EXTRAS:
                setattr(_mem, name,
                        LIST_EXTRAS[name][1].index(str(setting.value)))
            elif name in ('tx_contact', 'radio_id', 'rxgroup', 'privacy',
                          'emerg_system', 'scanlist'):
                choice = str(setting.value)
                value = int(choice.split(':')[0]) if ':' in choice else 0
                if name == 'tx_contact':
                    tx_contact = value
                else:
                    setattr(_mem, name, value)
            else:
                setattr(_mem, name, int(setting.value))
        self._update_tx_contact(mem.number, tx_contact, _mem.chtype in (1, 3))

    def _update_tx_contact(self, number, contact, digital):
        """Write the TX contact table only if something changes, so a page
        the radio doesn't have isn't created for nothing."""
        tag, off = self._txc_loc(number)
        hi, lo = self._page(tag)[1][off:off + 2]
        if (hi, lo) == (0xFF, 0xFF) and not contact:
            return
        if self._tx_contact(number) != contact or (hi & 1) != int(digital):
            self._set_tx_contact(number, contact, digital)
