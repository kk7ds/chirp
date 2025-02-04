"""
Icom IC-F621 Land Mobile Radio
"""

# Copyright 2023 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common
from chirp import directory
from chirp import bitwise
from chirp.drivers import icf
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueFloat

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
u8    model_code[4];
u8    unknown100[269];
u8    beep_on:1,
      beep_level_linked:1,
      beep_level:6;
u8    squelch_level;
u8    volume_min_level;
u8    unknown101:5,
      mic_gain:3;
u8    unknown102[9];
u8    unknown103:3,
      ignition_switch_on:1,
      audio_filter:2,
      backlight:2;
u8    horn_off:1,
      unknown104:7;
u8    unknown105[16];
struct {
  u16   user_1:4,
        user_2:4,
        user_3:4,
        user_4:4;
  u24   dealer_1:4,
        dealer_2:4,
        dealer_3:4,
        dealer_4:4,
        dealer_5:4,
        dealer_6:4;
} passwd;
u8    scrambler_syn_capture:2,
      scrambler_tone_start_timing:2,
      scrambler_non_rolling:1,
      unknown106:1,
      scrambler_group_code:2;
u8    unknown107[4];
u16   beep_frequency_low;
u16   beep_frequency_high;
u16   unknown107a;
u8    backlight_set_enable:1,
      beep_set_enable:1,
      beep_level_set_enable:1,
      squelch_level_set_enable:1,
      volume_min_level_set_enable:1,
      audio_filter_set_enable:1,
      mic_gain_set_enable:1,
      horn_set_enable:1;
u8    unknown108[5];
bit   trunk_on[16];
struct {
  u8    emergency;
  u8    priority_a;
  u8    priority_b;
} channel;
struct {
  u8    unk1;
  u8    unk2;
  u8    unk3;
  u8    unk4;
  u8    unk5;
  u8    unk6;
} unknown109;
u8    tx_dtcs_inverse:1,
      rx_dtcs_inverse:1,
      unknown110:6;
u8    unknown111:2,
      emergency_channel_on:1,
      unknown112:1,
      tone_burst_phase_on:1,
      rx_af_filter_low_cut_on:1,
      unknown113:2;
u8    poweron_scan_on:1,
      unknown114:1,
      dtmf_id_out_on:1,
      time_out_timer_beep_on:1,
      unknown115:1,
      data_out_on:1,
      poweron_priority_a:1,
      unknown116:1;
u8    unknown117:2,
      opening_text_on:1,
      poweron_selection_off:1,
      unknown118:4;
u8    unknown119:2,
      password_on:1,
      unknown120:2,
      rf_power_selection:1,
      unknown121:2;
u8    unknown122;
u8    hookoff_monitor_on:1,
      hookoff_priority_a:1,
      hookon_scan_on:1,
      unknown123:1,
      exo_on:1,
      tone_mute_eptt_on:1,
      unknown124:2;
struct {
  u8    scan_fast;
  u8    scan_slow;
  u8    ctcss_reverse_burst;
  u8    unk1;
  u8    unk2;
  u8    unk3;
  u8    unk4;
  u8    two_tone_1_period;
  u8    unk5;
  u8    dtmf;
  u8    dtmf_first;
  u8    dtmf_starpound;
  u8    two_tone_group;
  u8    scan_stop;
  u8    scan_resume;
  u8    unk6;
  u8    unk7;
  u8    emergency_switch_on;
  u8    emergency_switch_off;
  u8    emergency_start_repeat;
  u8    time_out;
  u8    penalty;
  u8    lockout_penalty;
  u8    two_tone_beep_repeat;
  u8    auto_reset_a;
  u8    auto_reset_b;
  u8    unk8;
  u8    two_tone_auto_tx;
  u8    horn;
  u8    exo_delay;
  u8    eptt_delay;
  u8    ignition_switch_delay:4,
        unk9:4;
} timer;
struct {
  u8    lup;
  u8    ldown;
  u8    rup;
  u8    rdown;
  u8    p0;
  u8    p1;
  u8    p2;
  u8    p3;
  u8    p4;
  u8    opf0;
  u8    opf1;
  u8    opf2;
} conv_key;
struct {
  u8    lup;
  u8    ldown;
  u8    rup;
  u8    rdown;
  u8    p0;
  u8    p1;
  u8    p2;
  u8    p3;
  u8    p4;
  u8    opf0;
  u8    opf1;
  u8    opf2;
} trunk_key;
struct {
  u16   capacity;
} bank[16];
struct {
  u16   unk;
} unknown125[16];
char clone_comment[32];
struct {
  u16   map;
} custom_characters[16];
u16   two_tone_1_tone;
u16   two_tone_2_tone;
struct {
  u16   unk;
} unknown126[40];
u8    two_tone_2_period;
struct {
  u8    unk;
} unknown127[14];
u8    two_tone_timer_notone;
struct {
  u8    unk;
} unknown128[22];
u16   user_ctcss_freq;
u32   unknown129;
struct {
  u16   rx;
  u16   tx;
} continuous_tone[9];
struct {
  char  name[10];
  bit   active[256];
  u8    text_on:1,
        unk1:5,
        scan_mode:2;
  u8    unk2;
} scan_list[10];
struct {
  char  name[10];
  u8    code[12];
  u8    count;
} dtmf_autodial[10];
struct {
  char  name[10];
  u32   disp_inhibit:1,
        freq_rx:31;
  u32   tx_inhibit:1,
        freq_tx:31;
  u16   rx_tone_off:1,
        rx_tone_digital:1,
        unk01:5,
        rx_tone:9;
  u16   tx_tone_off:1,
        tx_tone_digital:1,
        unk02:5,
        tx_tone:9;
  u8    unk03:3,
        tot_on:1,
        lockout_repeater:1,
        lockout_busy:1,
        power_rf:2;
  u8    log_in:2,
        log_out:2,
        unk04:1,
        text_on:1,
        unk05:1,
        two_tone_unk1:1;
  u8    unk06:4,
        two_tone_unk2:2,
        auto_reset:1,
        unk07:1;
  u8    narrow:1,
        scrambler_on:1,
        scrambler_inhibit:1,
        compander_on:1,
        unk08:4;
  u8    unk09;
  u8    scrambler_code;
  u16   unk10;
  u16   unk11;
  u8    unk12:6,
        two_tone_index:2;
} memory[256];
struct {
  char  name[10];
  u16   unk1;
  u16   unk2;
  u16   unk3;
} unknown130[32];
u32   unknown131;
struct {
  char name[10];
  u8    unk1;
  u8    ans_on;
  u8    unk2:2,
        scan_start:1,
        scan_cancel:1,
        unk3:1,
        beep:3;
  u8    exo_on:1,
        unk4:1,
        auto_tx_on:1,
        stun_on:1,
        kill_on:1,
        unk5:1,
        bell:2;
  u8    unk6;
  u16   unk7;
  u16   unk8;
} two_tone[9];
u8    unknown132[4];
char  opening_text[10];

"""

APPEAR_CHOICE = ["Appear", "Inhibit"]
ENABLE_CHOICE = ["Disable", "Enable"]
INVERSE_CHOICE = ["Normal", "Inverse"]
NO_YES_CHOICE = ["No", "Yes"]
ON_CHOICE = ["", "On"]          # ["OFF", "ON"]
ON_OFF_CHOICE = ["Off", "On"]
YES_CHOICE = ["", "Yes"]

MODES = ["FM", "NFM"]           # Supported emission (or receive) modes

TMODES = ["", "Tone", "TSQL", "DTCS", "Cross", ]
CROSS_MODES = [
    "Tone->Tone",
    "Tone->DTCS",
    "DTCS->Tone",
    "DTCS->",
    "->Tone",
    "->DTCS",
    "DTCS->DTCS",
    ]

TONES = [
    67.0, 69.3, 71.0, 71.9, 74.4, 77.0, 79.7, 82.5,
    85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
    107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
    159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
    196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
    225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
    ]

DUPLEX = ["", "+", "-", "split", "off"]

# Valid values for programable keys.
# Hex numbers are used for unkown functions.
KEY_FUNC = [
    "Null",
    "CH Up",
    "CH Down",
    "Bank",
    "Scan A Start/Stop",
    "Scan B Start/Stop",
    "Scan Add/Del(Tag)",
    "Prio A",
    "Prio A(Rewrite)",
    "Prio B",
    "MR-CH 1",
    "MR-CH 2",
    "MR-CH 3",
    "MR-CH 4",
    "Moni",
    "Lock",
    "High/Low",
    "Wide/Narrow",
    "Compander",
    "C.Tone CH Ent",
    "Talk Around",
    "Scrambler",
    "Re-dial",
    "DTMF Autodial",
    "Call",
    "0x19",
    "0x1A",
    "Emergency Single",
    "Emergency Repeat",
    "0x1D",
    "0x1E",
    "0x1F",
    "0x20",
    "User Set Mode",
    "Public Address",
    "RX Speaker",
    "0x24",
    "0x25",
    "0x26",
    "0x27",
    "Turbo SpeeDial A",
    "Turbo SpeeDial B",
    "Turbo SpeeDial C",
    "Turbo SpeeDial D",
    "Trunking Group Switch",
    "Sp. Func 1",
    "Sp. Func 2",
    "Hook Scan",
    "OPT1 Out",
    "OPT2 Out",
    "OPT3 Out",
    "OPT1 Momentary",
    "OPT2 Momentary",
    "OPT3 Momentary",
    ]

# List of valid conventional keys
# in the order they should be presented to the user.
KEY_CONV = [
    "Null",
    "CH Up",
    "CH Down",
    "Bank",
    "Scan A Start/Stop",
    "Scan B Start/Stop",
    "Scan Add/Del(Tag)",
    "Prio A",
    "Prio A(Rewrite)",
    "Prio B",
    "MR-CH 1",
    "MR-CH 2",
    "MR-CH 3",
    "MR-CH 4",
    "Moni",
    "Public Address",
    "RX Speaker",
    "Lock",
    "High/Low",
    "C.Tone CH Ent",
    "Talk Around",
    "Wide/Narrow",
    "DTMF Autodial",
    "Re-dial",
    "Call",
    "Emergency Single",
    "Emergency Repeat",
    "Scrambler",
    "Compander",
    "Hook Scan",
    "User Set Mode",
    "OPT1 Out",
    "OPT2 Out",
    "OPT3 Out",
    "OPT1 Momentary",
    "OPT2 Momentary",
    "OPT3 Momentary",
    "Sp. Func 1",
    "Sp. Func 2",
    ]

# List of valid trunk keys
# in the order they should be presented to the user.
KEY_TRUNK = [
    "Null",
    "Bank",
    "Lock",
    "High/Low",
    "Trunking Group Switch",
    "Turbo SpeeDial A",
    "Turbo SpeeDial B",
    "Turbo SpeeDial C",
    "Turbo SpeeDial D",
    "CH Up",
    "CH Down",
    "Compander",
    "Sp. Func 1",
    "Sp. Func 2",
    ]

AUDIO_FILTER_RX_OPTIONS = [
    "Normal",
    "Low Cut",
    ]

RF_POWER_SELECTION_OPTIONS = [
    "MR CH Individual",
    "Override",
    ]

BACKLIGHT_VALUES = [
    "Off",
    "Dim",
    "Auto",
    "On",
    ]

BEEP_LEVEL_VALUES = [
    "",
    "1",
    "2",
    "3",
    "4",
    "5",
    ]

AUDIO_FILTER_VALUES = [
    "300-3000 Hz",
    "0-3000 Hz",
    "300-3400 Hz",
    "0-3400 Hz",
    ]

# Valid values for Mic Gain.
# Hex numbers are used for unkown functions.
MIC_GAIN_FUNC = [
    "0x00",
    "1 Min",
    "2",
    "3",
    "4",
    "5 Max",
    ]

# List of valid Mic Gain choices
# in the order they should be presented to the user.
MIC_GAIN_CHOICE = [
    "1 Min",
    "2",
    "3",
    "4",
    "5 Max",
    ]

LOCKOUT_VALUES = [              # CS-F500 equivalent
    "",                         # OFF
    "Repeater",                 # Repeater Lockout
    "Busy",                     # Busy Lockout
    ]

LOG_IN_OUT_VALUES = [           # CS-F500 equivalent
    "",                         # OFF
    "L-IN",                     # Log IN
    "L-OFF",                    # Log OFF
    "Both",                     # Log IN/OFF
    ]

RESET_TIMERS_VALUES = [
    "Timer B",
    "Timer A",
    ]

SCRAMBLER_TYPE_VALUES = [
    "Rolling",
    "Non-rolling",
    ]

SCRAMBLER_GCODE_VALUES = [
    "1",
    "2",
    "3",
    "4",
    ]

# Valid values for Scrambler Synchronous Capture.
# Hex numbers are used for unkown functions.
SYN_CAPTURE_FUNC = [
    "Standard",
    "0x01",
    "0x02",
    "Continuous",
    ]

# List of valid Scrambler Synchronous Capture choices
# in the order they should be presented to the user.
SYN_CAPTURE_CHOICE = [
    "Standard",
    "Continuous",
    ]

TONE_BURST_VALUES = [
    "Notone",
    "Phase",
    ]

TONE_STIMING_VALUES = [
    "Off",
    "300 ms",
    "600 ms",
    "1100 ms",
    ]


def kf_kc(i):
    """
    Given the index of the conventional key choice
    return the index of the corresponding function
    """
    return int(KEY_FUNC.index(KEY_CONV[int(i)]))


def kc_kf(i):
    """
    Given the index of the key function
    return the index of the corresponding conventional key choice
    """
    return int(KEY_CONV.index(KEY_FUNC[int(i)]))


def kf_kt(i):
    """
    Given the index of the trunk key choice
    return the index of the corresponding function
    """
    return int(KEY_FUNC.index(KEY_TRUNK[int(i)]))


def kt_kf(i):
    """
    Given the index of the key function
    return the index of the corresponding trunk key choice
    """
    return int(KEY_TRUNK.index(KEY_FUNC[int(i)]))


def mf_mc(i):
    """
    Given the index of the mic gain choice
    return the index of the corresponding function
    """
    return int(MIC_GAIN_FUNC.index(MIC_GAIN_CHOICE[int(i)]))


def mc_mf(i):
    """
    Given the index of the mic gain function
    return the index of the corresponding choice
    """
    return int(MIC_GAIN_CHOICE.index(MIC_GAIN_FUNC[int(i)]))


def sf_sc(i):
    """
    Given the index of the sync capture choice
    return the index of the corresponding function
    """
    return int(SYN_CAPTURE_FUNC.index(SYN_CAPTURE_CHOICE[int(i)]))


def sc_sf(i):
    """
    Given the index of the sync capture function
    return the index of the corresponding choice
    """
    return int(SYN_CAPTURE_CHOICE.index(SYN_CAPTURE_FUNC[int(i)]))


@directory.register
class ICF621_2Radio(icf.IcomCloneModeRadio):
    """
    Icom IC-F621-2 UHF Land Mobile Radio
    """
    VENDOR = "Icom"
    MODEL = "IC-F621-2"

    # _power_high watts is taken from the brochure.
    # FIXME: The others are guesses
    _power_low1 = chirp_common.PowerLevel("Low1", watts=5)
    _power_low2 = chirp_common.PowerLevel("Low2", watts=20)
    _power_high = chirp_common.PowerLevel("High", watts=45)

    _model = "\x25\x26\x02\x00"     # 4 byte model (don't use Byte String)
    _memsize = 0x3000
    _endframe = "Icom Inc."         # \x49\x63\x6F\x6D\x20\x49\x6E\x63\x2E

    # Ranges of the mmap to send to the radio
    _ranges = [(0x0100, 0x3000, 16)]

    _num_banks = 16
    _can_hispeed = False

    # Different models and versions support subsets of the valid bands.
    # Frequency values out of range for a radio will not cause a
    # transfer error.  The radio display will flash when that channel
    # is selected.
    # IC-F521 _valid_bands = [(136000000, 174000000)]
    _valid_bands = [(440000000, 490000000)]

    _memories = {}

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True

        # Channels
        rf.has_bank = False
        rf.has_bank_names = False
        rf.memory_bounds = (1, 256)

        # Channel Name
        rf.has_name = True
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 10

        # Frequency
        rf.valid_modes = list(MODES)
        rf.has_offset = True
        rf.has_tuning_step = False
        rf.valid_tuning_steps = chirp_common.TUNING_STEPS
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_bands = list(self._valid_bands)
        rf.can_odd_split = True
        rf.has_mode = True

        # Tone
        rf.has_ctone = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_cross = True
        rf.valid_cross_modes = list(CROSS_MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_tones = list(TONES)

        # RF Power
        rf.has_variable_power = False
        rf.valid_power_levels = [
            self._power_high, self._power_low2, self._power_low1]

        # Scanning
        rf.valid_skips = []

        return rf

    def process_mmap(self):
        """Convert the raw byte array into a memory object structure"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

        # FIXME: BEGIN Ugly Hack
        # Force driver to use one bank that contains all memories.
        # This allows us to work on other parts of the driver before
        # the bank model is complete.
        self._memobj.bank[0].capacity = 256
        for i in range(1, self._num_banks):
            self._memobj.bank[i].capacity = 0
        # When deleting this ugly hack, remember to change:
        #    rf.has_bank = True
        # below.
        # FIXME: END Ugly Hack

    def get_memory(self, number):
        """Create a high-level memory object to return to the UI"""

        _mem = self._memobj.memory[number - 1]
        memory = chirp_common.Memory()
        memory.number = number
        memory.immutable = []

        # Frequency: Low level format is frequency in Hz
        memory.freq = int(_mem.freq_rx)

        if _mem.tx_inhibit:
            memory.duplex = "off"
            memory.offset = 0
        elif int(_mem.freq_rx) == int(_mem.freq_tx):
            memory.duplex = ""
            memory.offset = 0
        else:
            chirp_common.split_to_offset(
                memory, int(_mem.freq_rx), int(_mem.freq_tx))

        # Modes
        if _mem.narrow:
            memory.mode = "NFM"
        else:
            memory.mode = "FM"

        # Name
        memory.name = str(_mem.name).rstrip()

        # Tone
        txpol = None
        if _mem.tx_tone_off:
            txmode = None
            txval = None
        elif _mem.tx_tone_digital:
            txmode = "DTCS"
            txval = chirp_common.ALL_DTCS_CODES[int(_mem.tx_tone)]
        else:
            txmode = "Tone"
            txval = TONES[_mem.tx_tone]

        rxpol = None
        if _mem.rx_tone_off:
            rxmode = None
            rxval = None
        elif _mem.rx_tone_digital:
            rxmode = "DTCS"
            rxval = chirp_common.ALL_DTCS_CODES[int(_mem.rx_tone)]
        else:
            rxmode = "Tone"
            rxval = TONES[_mem.rx_tone]

        txspec = (txmode, txval, txpol)
        rxspec = (rxmode, rxval, rxpol)
        chirp_common.split_tone_decode(memory, txspec, rxspec)

        # RF Power
        if _mem.power_rf == 3:
            memory.power = self._power_high
        elif _mem.power_rf == 2:
            memory.power = self._power_low2
        else:
            memory.power = self._power_low1

        memory.extra = RadioSettingGroup('extra', 'Extra')

        # Mask (Don't display) channel on radio.
        # This is refered as Inhibit in the CS-F500 software.
        _disp_inhibit = RadioSetting(
            "disp_inhibit", "Mask",
            RadioSettingValueList(
                YES_CHOICE, current_index=int(_mem.disp_inhibit)))
        _disp_inhibit.set_doc(
            "Prevent the radio from displaying the channel.  This "
            "prevents use of the channel but CHIRP will still download "
            "the channel information.")
        memory.extra.append(_disp_inhibit)

        _compander_on = RadioSetting(
            "compander_on", "Compander",
            RadioSettingValueList(
                ON_CHOICE, current_index=int(
                    _mem.compander_on)))
        _compander_on.set_doc("Compander On")
        memory.extra.append(_compander_on)

        _tot_on = RadioSetting(
            "tot_on", "TOT",
            RadioSettingValueList(
                ON_CHOICE, current_index=int(_mem.tot_on)))
        _tot_on.set_doc("Time Out Timer On")
        memory.extra.append(_tot_on)

        _auto_reset_timer = RadioSetting(
            "auto_reset_timer", "Auto Reset Timer",
            RadioSettingValueList(
                RESET_TIMERS_VALUES, current_index=int(
                    _mem.auto_reset)))
        _auto_reset_timer.set_doc("Auto Reset Timer Selection")
        memory.extra.append(_auto_reset_timer)

        _lockout_bits = (_mem.lockout_busy << 1) | _mem.lockout_repeater
        _lockout = RadioSetting(
            "lockout", "Lockout",
            RadioSettingValueList(
                LOCKOUT_VALUES, current_index=int(_lockout_bits)))
        _lockout.set_doc("Transmit Lockout")
        memory.extra.append(_lockout)

        _log_in_out_bits = (_mem.log_in << 2) + _mem.log_out
        _log_in_out_index = 0
        if _log_in_out_bits == 0x03:
            _log_in_out_index = 2
        elif _log_in_out_bits == 0x0C:
            _log_in_out_index = 1
        elif _log_in_out_bits == 0x0F:
            _log_in_out_index = 3
        _log_in_out = RadioSetting(
            "log_in_out", "Log",
            RadioSettingValueList(
                LOG_IN_OUT_VALUES, current_index=int(_log_in_out_index)))
        _log_in_out.set_doc("Log in and Log out")
        memory.extra.append(_log_in_out)

        # Any memory with a frequency of 0 MHz is treated as empty.
        #
        # When CS-F500 inserts a blank memory, it sets Tx and Rx frequency
        # to 0 MHz and leaves the disp_inhibit bit unset.  When the
        # disp_inhibit bit is set, the memory is displayed in CS-F500
        # with an "i" in the inhibit column.
        #
        # The radio does not display inhibited (masked) memory
        # channels.
        if memory.freq == 0:
            memory.empty = True

        return memory

    def set_memory(self, memory):
        """Set the memory object @memory"""
        # Store details about a high-level memory to the memory map
        # This is called when a user edits a memory in the UI

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[memory.number - 1]

        rf = self.get_features()

        # Frequency: Low level format is frequency in Hz
        _mem.freq_rx = memory.freq
        _mem.tx_inhibit = 0
        if memory.duplex == "off":
            _mem.freq_tx = memory.freq
            _mem.tx_inhibit = 1
        elif memory.duplex == "split":
            _mem.freq_tx = memory.offset
        elif memory.duplex == "-":
            _mem.freq_tx = _mem.freq_rx - memory.offset
        elif memory.duplex == "+":
            _mem.freq_tx = _mem.freq_rx + memory.offset
        else:
            _mem.freq_tx = memory.freq

        # Modes
        if memory.mode == "NFM":
            _mem.narrow = 1
        else:
            _mem.narrow = 0

        # Name (alpha tag)
        _mem.name = str(memory.name).ljust(rf.valid_name_length)[
            :rf.valid_name_length]
        _mem.text_on = 1

        # Tone
        txspec, rxspec = chirp_common.split_tone_encode(memory)
        txmode, txval, txpol = txspec
        rxmode, rxval, rxpol = rxspec

        _mem.tx_tone_off = 1
        _mem.tx_tone_digital = 0
        _mem.tx_tone = 0
        if txmode == "Tone":
            _mem.tx_tone_off = 0
            _mem.tx_tone = TONES.index(txval)
        elif txmode == "DTCS":
            _mem.tx_tone_off = 0
            _mem.tx_tone_digital = 1
            _mem.tx_tone = chirp_common.ALL_DTCS_CODES.index(txval)

        _mem.rx_tone_off = 1
        _mem.rx_tone_digital = 0
        _mem.rx_tone = 0
        if rxmode == "Tone":
            _mem.rx_tone_off = 0
            _mem.rx_tone = TONES.index(rxval)
        elif rxmode == "DTCS":
            _mem.rx_tone_off = 0
            _mem.rx_tone_digital = 1
            _mem.rx_tone = chirp_common.ALL_DTCS_CODES.index(rxval)

        # RF Power
        if memory.power == self._power_high:
            _mem.power_rf = 3
        elif memory.power == self._power_low2:
            _mem.power_rf = 2
        else:
            _mem.power_rf = 1

        _mem.disp_inhibit = 0
        _mem.compander_on = 0
        _mem.tot_on = 0
        _mem.auto_reset = 0
        _mem.lockout_busy = 0
        _mem.lockout_repeater = 0
        _mem.log_in = 0
        _mem.log_out = 0

        if memory.extra:
            _mem.disp_inhibit = memory.extra['disp_inhibit'].value
            _mem.compander_on = memory.extra['compander_on'].value
            _mem.tot_on = memory.extra['tot_on'].value
            _mem.auto_reset = memory.extra['auto_reset_timer'].value

            _lockout = int(memory.extra['lockout'].value)
            _mem.lockout_repeater = _lockout & 1
            _mem.lockout_busy = (_lockout >> 1) & 1

            # There are two bits each for log in and log out/off.
            # 0 is off and 3 is on.  1 and 2 remain a mystery
            _log_in_out = int(memory.extra['log_in_out'].value)
            _mem.log_in = 0
            _mem.log_out = 0
            if _log_in_out == 1:
                _mem.log_in = 3
            elif _log_in_out == 2:
                _mem.log_out = 3
            elif _log_in_out == 3:
                _mem.log_in = 3
                _mem.log_out = 3

        if memory.empty:
            _mem.freq_rx = 0
            _mem.freq_tx = 0
            _mem.narrow = 0
            _mem.name = "          "
            _mem.text_on = 0
            _mem.tx_tone_off = 1
            _mem.tx_tone_digital = 0
            _mem.tx_tone = 0
            _mem.rx_tone_off = 1
            _mem.rx_tone_digital = 0
            _mem.rx_tone = 0

# Radio Settings

    # Build the "DTMF" menu.
    # TODO: This menu is not even started.

    # Build the "Continuous Tone" menu.
    # TODO: This menu is not complete.
    def _get_continuous_tone_group(self):
        _group = RadioSettingGroup(
            "group_continuous_tone", "Continuous Tone")
        # 9 custom CTCSS pairs
        _group.append(RadioSetting(
            "tone_burst_phase_on", "Tone Burst",
            RadioSettingValueList(
                TONE_BURST_VALUES, current_index=int(
                    self._memobj.tone_burst_phase_on))))
        # "CTCSS Reverse Burst Timer"
        #  "User CTCSS Freq (Hz)"
        _group.append(RadioSetting(
            "tx_dtcs_inverse", "TX DTCS Inverse",
            RadioSettingValueList(
                INVERSE_CHOICE, current_index=int(
                    self._memobj.tx_dtcs_inverse))))
        _group.append(RadioSetting(
            "rx_dtcs_inverse", "RX DTCS Inverse",
            RadioSettingValueList(
                INVERSE_CHOICE, current_index=int(
                    self._memobj.rx_dtcs_inverse))))
        _group.append(RadioSetting(
            "rx_af_filter_low_cut_on", "RX AF Filter",
            RadioSettingValueList(
                AUDIO_FILTER_RX_OPTIONS, current_index=int(
                    self._memobj.rx_af_filter_low_cut_on))))
        return _group

    # Build the "Scan" menu.
    # TODO: This menu is barely started
    def _get_scan_group(self):
        _group = RadioSettingGroup("group_scan", "Scan")
        # 10 scan lists
        # timer.scan_stop   "Stop"
        # timer.scan_resume "Resume"
        # timer.scan_fast   "Fast Scan
        # timer.scan_slow   "Slow Scan"
        _group.append(RadioSetting(
            "poweron_scan_on", "Power on Scan",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.poweron_scan_on))))
        return _group

    # Build the "2TONE" menu
    # TODO: This menu is not even started.

    # Build the "Conventional Key" menu.
    def _get_conv_key_group(self):
        _group = RadioSettingGroup("conv_keys", "Conventional Keys")
        _group.append(RadioSetting(
            "conv_key_lup", "L-Up",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.lup))))
        _group.append(RadioSetting(
            "conv_key_ldown", "L-Down",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.ldown))))
        _group.append(RadioSetting(
            "conv_key_rup", "R-Up",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.rup))))
        _group.append(RadioSetting(
            "conv_key_rdown", "R-Down",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.rdown))))
        _group.append(RadioSetting(
            "conv_key_p0", "P0",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.p0))))
        _group.append(RadioSetting(
            "conv_key_p1", "P1",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.p1))))
        _group.append(RadioSetting(
            "conv_key_p2", "P2",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.p2))))
        _group.append(RadioSetting(
            "conv_key_p3", "P3",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.p3))))
        _group.append(RadioSetting(
            "conv_key_p4", "P4",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.p4))))
        _group.append(RadioSetting(
            "conv_key_opf0", "OPF0",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.opf0))))
        _group.append(RadioSetting(
            "conv_key_opf1", "OPF1",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.opf1))))
        _group.append(RadioSetting(
            "conv_key_opf2", "OPF2",
            RadioSettingValueList(
                KEY_CONV, current_index=kc_kf(
                    self._memobj.conv_key.opf2))))
        return _group

    # Build the "SmarTrunk Key" menu.
    def _get_trunk_key_group(self):
        _group = RadioSettingGroup("trunk_keys", "SmarTrunk Keys")
        _group.append(RadioSetting(
            "trunk_key_lup", "L-Up",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.lup))))
        _group.append(RadioSetting(
            "trunk_key_ldown", "L-Down",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.ldown))))
        _group.append(RadioSetting(
            "trunk_key_rup", "R-Up",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.rup))))
        _group.append(RadioSetting(
            "trunk_key_rdown", "R-Down",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.rdown))))
        _group.append(RadioSetting(
            "trunk_key_p0", "P0",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.p0))))
        _group.append(RadioSetting(
            "trunk_key_p1", "P1",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.p1))))
        _group.append(RadioSetting(
            "trunk_key_p2", "P2",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.p2))))
        _group.append(RadioSetting(
            "trunk_key_p3", "P3",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.p3))))
        _group.append(RadioSetting(
            "trunk_key_p4", "P4",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.p4))))
        _group.append(RadioSetting(
            "trunk_key_opf0", "OPF0",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.opf0))))
        _group.append(RadioSetting(
            "trunk_key_opf1", "OPF1",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.opf1))))
        _group.append(RadioSetting(
            "trunk_key_opf2", "OPF2",
            RadioSettingValueList(
                KEY_TRUNK, current_index=kt_kf(
                    self._memobj.trunk_key.opf2))))
        return _group

    # Build the "Display" menu.
    def _get_display_group(self):
        _freq_lo = self._memobj.beep_frequency_low / 10.0
        _freq_hi = self._memobj.beep_frequency_high / 10.0
        _psw = int(not self._memobj.poweron_selection_off)
        _isw = int(self._memobj.ignition_switch_on)
        _pria = int(self._memobj.poweron_priority_a)

        _group = RadioSettingGroup("group_display", "Display")
        _group.append(RadioSetting(
            "beep_frequency_low", "Beep Low Freq",
            RadioSettingValueFloat(
                400.0, 3000.0, _freq_lo, precision=0)))
        _group.append(RadioSetting(
            "beep_frequency_high", "Beep High Freq",
            RadioSettingValueFloat(
                400.0, 3000.0, _freq_hi, precision=0)))
        _group.append(RadioSetting(
            "opening_text", "Opening Text",
            RadioSettingValueString(
                0, 10, str(self._memobj.opening_text).rstrip(), False)))
        _group.append(RadioSetting(
            "rf_power_selection", "RF Power",
            RadioSettingValueList(
                RF_POWER_SELECTION_OPTIONS, current_index=int(
                    self._memobj.rf_power_selection))))
        _group.append(RadioSetting(
            "poweron_selection_off", "Power Switch Selection",
            RadioSettingValueList(APPEAR_CHOICE, current_index=_psw)))
        _group.append(RadioSetting(
            "ignition_switch_on", "Ignition Switch",
            RadioSettingValueList(APPEAR_CHOICE, current_index=_isw)))
        _group.append(RadioSetting(
            "ignition_switch_delay", "Ignition Switch Delay Timer",
            RadioSettingValueInteger(
                0, 240, self._memobj.timer.ignition_switch_delay)))
        _group.append(RadioSetting(
            "poweron_priority_a", "Power On Priority A Channel",
            RadioSettingValueList(ENABLE_CHOICE, current_index=_pria)))
        _group.append(RadioSetting(
            "hookoff_priority_a", "Hook Off Priority A Channel",
            RadioSettingValueList(
                ENABLE_CHOICE, current_index=int(
                    self._memobj.hookoff_priority_a))))
        _group.append(RadioSetting(
            "hookoff_monitor_on", "Hook Off Monitor",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.hookoff_monitor_on))))
        _group.append(RadioSetting(
            "hookon_scan_on", "Hook on Scan",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.hookon_scan_on))))
        return _group

    # Build the "Set Mode" menu.
    def _get_set_mode_group(self):
        _hrn = int(not self._memobj.horn_off)

        _group = RadioSettingGroup("set_mode_group", "Set Mode")
        _group.append(RadioSetting(
            "backlight", "Backlight",
            RadioSettingValueList(
                BACKLIGHT_VALUES, current_index=int(
                    self._memobj.backlight))))
        _group.append(RadioSetting(
            "backlight_set_enable", "Enable Backlight",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.backlight_set_enable))))
        _group.append(RadioSetting(
            "beep_on", "Beep",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.beep_on))))
        _group.append(RadioSetting(
            "beep_set_enable", "Enable Beep",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.beep_set_enable))))
        _group.append(RadioSetting(
            "beep_level", "Beep Level",
            RadioSettingValueList(
                BEEP_LEVEL_VALUES, current_index=int(
                    self._memobj.beep_level))))
        _group.append(RadioSetting(
            "beep_level_set_enable", "Enable Beep Level",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.beep_level_set_enable))))
        _group.append(RadioSetting(
            "squelch_level", "Squelch Level",
            RadioSettingValueInteger(
                0, 255, self._memobj.squelch_level)))
        _group.append(RadioSetting(
            "squelch_level_set_enable", "Enable Squelch Level",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.squelch_level_set_enable))))
        _group.append(RadioSetting(
            "volume_min_level", "Volume Minimum Level",
            RadioSettingValueInteger(
                0, 255, self._memobj.volume_min_level)))
        _group.append(RadioSetting(
            "volume_min_level_set_enable", "Enable Volume Minimum Level",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.volume_min_level_set_enable))))
        _group.append(RadioSetting(
            "audio_filter", "Audio Filter",
            RadioSettingValueList(
                AUDIO_FILTER_VALUES, current_index=int(
                    self._memobj.audio_filter))))
        _group.append(RadioSetting(
            "audio_filter_set_enable", "Enable Audio Filter",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.audio_filter_set_enable))))
        _group.append(RadioSetting(
            "mic_gain", "Mic Gain",
            RadioSettingValueList(
                MIC_GAIN_CHOICE, current_index=mc_mf(
                    self._memobj.mic_gain))))
        _group.append(RadioSetting(
            "mic_gain_set_enable", "Enable Mic Gain",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.mic_gain_set_enable))))
        _group.append(RadioSetting(
            "horn_off", "Horn",
            RadioSettingValueList(
                ON_CHOICE, current_index=_hrn)))
        _group.append(RadioSetting(
            "horn_set_enable", "Enable Horn",
            RadioSettingValueList(
                NO_YES_CHOICE, current_index=int(
                    self._memobj.horn_set_enable))))
        return _group

    # Build the "Common" menu.
    def _get_common_group(self):
        _timer_eptt = self._memobj.timer.eptt_delay / 10.0
        _timer_exo = self._memobj.timer.exo_delay / 10.0
        _timer_es_on = self._memobj.timer.emergency_switch_on / 10.0
        _timer_es_off = self._memobj.timer.emergency_switch_off / 10.0

        _group = RadioSettingGroup("common_group", "Common")
        _group.append(RadioSetting(
            "clone_comment", "Clone Comment",
            RadioSettingValueString(
                0, 32, str(self._memobj.clone_comment).rstrip(), False)))
        _group.append(RadioSetting(
            "password_on", "Power-on Password",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.password_on))))
        _group.append(RadioSetting(
            "data_out_on", "Transceiver Data Out",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.data_out_on))))
        _group.append(RadioSetting(
            "timer_auto_reset_a", "Auto Reset Timer A",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.auto_reset_a)))
        _group.append(RadioSetting(
            "timer_auto_reset_b", "Auto Reset Timer B",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.auto_reset_b)))
        _group.append(RadioSetting(
            "timer_time_out", "Time Out Timer",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.time_out)))
        _group.append(RadioSetting(
            "timer_penalty", "Penalty Timer",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.penalty)))
        _group.append(RadioSetting(
            "dtmf_id_out_on", "DTMF ID Out",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.dtmf_id_out_on))))
        _group.append(RadioSetting(
            "time_out_timer_beep_on", "Time Out Timer Beep",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.time_out_timer_beep_on))))
        _group.append(RadioSetting(
            "timer_lockout_penalty", "Lockout Penalty Timer",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.lockout_penalty)))
        _group.append(RadioSetting(
            "timer_eptt_delay", "EPTT Delay Timer",
            RadioSettingValueFloat(0, 25.5, _timer_eptt, precision=1)))
        _group.append(RadioSetting(
            "tone_mute_eptt_on", "Tone Mute EPTT",
            RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(
                    self._memobj.tone_mute_eptt_on))))
        _group.append(RadioSetting(
            "exo_on", "EXO", RadioSettingValueList(
                ON_OFF_CHOICE, current_index=int(self._memobj.exo_on))))
        _group.append(RadioSetting(
            "timer_exo_delay", "EXO Delay Timer",
            RadioSettingValueFloat(0, 25.5, _timer_exo, precision=1)))
        _group.append(RadioSetting(
            "timer_horn", "EXO/Horn Timer",
            RadioSettingValueInteger(0, 255, self._memobj.timer.horn)))
        _group.append(RadioSetting(
            "scrambler_non_rolling", "Scrambler Type",
            RadioSettingValueList(
                SCRAMBLER_TYPE_VALUES, current_index=int(
                    self._memobj.scrambler_non_rolling))))
        _group.append(RadioSetting(
            "scrambler_group_code", "Scrambler Group Code",
            RadioSettingValueList(
                SCRAMBLER_GCODE_VALUES, current_index=int(
                    self._memobj.scrambler_group_code))))
        _group.append(RadioSetting(
            "scrambler_syn_capture", "Scrambler Synchronous Capture",
            RadioSettingValueList(
                SYN_CAPTURE_CHOICE, current_index=sc_sf(
                    self._memobj.scrambler_syn_capture))))
        _group.append(RadioSetting(
            "scrambler_tone_start_timing", "Scrambler Tone Start Timing",
            RadioSettingValueList(
                TONE_STIMING_VALUES, current_index=int(
                    self._memobj.scrambler_tone_start_timing))))
        _group.append(RadioSetting(
            "timer_emergency_switch_on", "Emergency Switch On Timer",
            RadioSettingValueFloat(0, 25.5, _timer_es_on, precision=1)))
        _group.append(RadioSetting(
            "timer_emergency_switch_off", "Emergency Switch Off Timer",
            RadioSettingValueFloat(0, 25.5, _timer_es_off, precision=1)))
        _group.append(RadioSetting(
            "emergency_start_repeat", "Emergency Start/Repeat",
            RadioSettingValueInteger(
                0, 255, self._memobj.timer.emergency_start_repeat)))
        return _group

    # Build the top menu.
    def get_settings(self):
        """Returns a RadioSettingGroup containing one or more
        RadioSettingGroup or RadioSetting objects. These represent general
        setting knobs and dials that can be adjusted on the radio."""
        return list(
            RadioSettingGroup(
                "top", "LMR",
                self._get_continuous_tone_group(),
                self._get_scan_group(),
                self._get_conv_key_group(),
                self._get_trunk_key_group(),
                self._get_display_group(),
                self._get_set_mode_group(),
                self._get_common_group()))

    def set_settings(self, settings):
        """Accepts the top-level RadioSettingGroup returned from get_settings()
        and adjusts the values in the radio accordingly. This function expects
        the entire RadioSettingGroup hierarchy returned from get_settings()."""
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)

            # "Continuous Tone" items
            elif element.get_name() == "tone_burst_phase_on":
                self._memobj.tone_burst_phase_on = element.value
            elif element.get_name() == "tx_dtcs_inverse":
                self._memobj.tx_dtcs_inverse = element.value
            elif element.get_name() == "rx_dtcs_inverse":
                self._memobj.rx_dtcs_inverse = element.value
            elif element.get_name() == "rx_af_filter_low_cut_on":
                self._memobj.rx_af_filter_low_cut_on = element.value

            # "Scan" items
            elif element.get_name() == "poweron_scan_on":
                self._memobj.poweron_scan_on = element.value

            # "Conventional Key" items
            elif element.get_name() == "conv_key_lup":
                self._memobj.conv_key.lup = kf_kc(element.value)
            elif element.get_name() == "conv_key_ldown":
                self._memobj.conv_key.ldown = kf_kc(element.value)
            elif element.get_name() == "conv_key_rup":
                self._memobj.conv_key.rup = kf_kc(element.value)
            elif element.get_name() == "conv_key_rdown":
                self._memobj.conv_key.rdown = kf_kc(element.value)
            elif element.get_name() == "conv_key_p0":
                self._memobj.conv_key.p0 = kf_kc(element.value)
            elif element.get_name() == "conv_key_p1":
                self._memobj.conv_key.p1 = kf_kc(element.value)
            elif element.get_name() == "conv_key_p2":
                self._memobj.conv_key.p2 = kf_kc(element.value)
            elif element.get_name() == "conv_key_p3":
                self._memobj.conv_key.p3 = kf_kc(element.value)
            elif element.get_name() == "conv_key_p4":
                self._memobj.conv_key.p4 = kf_kc(element.value)
            elif element.get_name() == "conv_key_opf0":
                self._memobj.conv_key.opf0 = kf_kc(element.value)
            elif element.get_name() == "conv_key_opf1":
                self._memobj.conv_key.opf1 = kf_kc(element.value)
            elif element.get_name() == "conv_key_opf2":
                self._memobj.conv_key.opf2 = kf_kc(element.value)
            elif element.get_name() == "trunk_key_lup":
                self._memobj.trunk_key.lup = kf_kt(element.value)

            # "SmarTrunk Key" items
            elif element.get_name() == "trunk_key_ldown":
                self._memobj.trunk_key.ldown = kf_kt(element.value)
            elif element.get_name() == "trunk_key_rup":
                self._memobj.trunk_key.rup = kf_kt(element.value)
            elif element.get_name() == "trunk_key_rdown":
                self._memobj.trunk_key.rdown = kf_kt(element.value)
            elif element.get_name() == "trunk_key_p0":
                self._memobj.trunk_key.p0 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_p1":
                self._memobj.trunk_key.p1 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_p2":
                self._memobj.trunk_key.p2 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_p3":
                self._memobj.trunk_key.p3 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_p4":
                self._memobj.trunk_key.p4 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_opf0":
                self._memobj.trunk_key.opf0 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_opf1":
                self._memobj.trunk_key.opf1 = kf_kt(element.value)
            elif element.get_name() == "trunk_key_opf2":
                self._memobj.trunk_key.opf2 = kf_kt(element.value)

            # "Display Mode" items
            elif element.get_name() == "beep_frequency_low":
                self._memobj.beep_frequency_low = element.value * 10.0
            elif element.get_name() == "beep_frequency_high":
                self._memobj.beep_frequency_high = element.value * 10.0
            elif element.get_name() == "opening_text":
                self._memobj.opening_text = str(
                    element.value).ljust(10)[:10]
            elif element.get_name() == "rf_power_selection":
                self._memobj.rf_power_selection = element.value
            elif element.get_name() == "poweron_selection_off":
                self._memobj.poweron_selection_off = not element.value
            elif element.get_name() == "ignition_switch_on":
                self._memobj.ignition_switch_on = element.value
            elif element.get_name() == "ignition_switch_delay":
                self._memobj.timer.ignition_switch_delay = element.value
            elif element.get_name() == "poweron_priority_a":
                self._memobj.poweron_priority_a = element.value
            elif element.get_name() == "hookoff_priority_a":
                self._memobj.hookoff_priority_a = element.value
            elif element.get_name() == "hookoff_monitor_on":
                self._memobj.hookoff_monitor_on = element.value
            elif element.get_name() == "hookon_scan_on":
                self._memobj.hookon_scan_on = element.value

            # "Set Mode" items
            elif element.get_name() == "backlight":
                self._memobj.backlight = element.value
            elif element.get_name() == "backlight_set_enable":
                self._memobj.backlight_set_enable = element.value
            elif element.get_name() == "beep_on":
                self._memobj.beep_on = element.value
            elif element.get_name() == "beep_set_enable":
                self._memobj.beep_set_enable = element.value
            elif element.get_name() == "beep_level":
                self._memobj.beep_level = element.value
            elif element.get_name() == "beep_level_set_enable":
                self._memobj.beep_level_set_enable = element.value
            elif element.get_name() == "squelch_level":
                self._memobj.squelch_level = element.value
            elif element.get_name() == "squelch_level_set_enable":
                self._memobj.squelch_level_set_enable = element.value
            elif element.get_name() == "volume_min_level":
                self._memobj.volume_min_level = element.value
            elif element.get_name() == "volume_min_level_set_enable":
                self._memobj.volume_min_level_set_enable = element.value
            elif element.get_name() == "audio_filter":
                self._memobj.audio_filter = element.value
            elif element.get_name() == "audio_filter_set_enable":
                self._memobj.audio_filter_set_enable = element.value
            elif element.get_name() == "mic_gain":
                self._memobj.mic_gain = mf_mc(element.value)
            elif element.get_name() == "mic_gain_set_enable":
                self._memobj.mic_gain_set_enable = element.value
            elif element.get_name() == "horn_off":
                self._memobj.horn_off = not element.value
            elif element.get_name() == "horn_set_enable":
                self._memobj.horn_set_enable = element.value

            # "Common" items
            elif element.get_name() == "clone_comment":
                self._memobj.clone_comment = str(
                    element.value).ljust(32)[:32]
            elif element.get_name() == "password_on":
                self._memobj.password_on = element.value
            elif element.get_name() == "data_out_on":
                self._memobj.data_out_on = element.value
            elif element.get_name() == "timer_auto_reset_a":
                self._memobj.timer.auto_reset_a = element.value
            elif element.get_name() == "timer_auto_reset_b":
                self._memobj.timer.auto_reset_b = element.value
            elif element.get_name() == "timer_time_out":
                self._memobj.timer.time_out = element.value
            elif element.get_name() == "timer_penalty":
                self._memobj.timer.penalty = element.value
            elif element.get_name() == "dtmf_id_out_on":
                self._memobj.dtmf_id_out_on = element.value
            elif element.get_name() == "time_out_timer_beep_on":
                self._memobj.time_out_timer_beep_on = element.value
            elif element.get_name() == "timer_lockout_penalty":
                self._memobj.timer.lockout_penalty = element.value
            elif element.get_name() == "timer_eptt_delay":
                self._memobj.timer.eptt_delay = element.value * 10.0
            elif element.get_name() == "tone_mute_eptt_on":
                self._memobj.tone_mute_eptt_on = element.value
            elif element.get_name() == "exo_on":
                self._memobj.tone_mute_eptt_on = element.value
            elif element.get_name() == "timer_exo_delay":
                self._memobj.timer.exo_delay = element.value * 10.0
            elif element.get_name() == "timer_horn":
                self._memobj.timer.horn = element.value
            elif element.get_name() == "scrambler_non_rolling":
                self._memobj.scrambler_non_rolling = element.value
            elif element.get_name() == "scrambler_group_code":
                self._memobj.scrambler_group_code = element.value
            elif element.get_name() == "scrambler_syn_capture":
                self._memobj.scrambler_syn_capture = sf_sc(element.value)
            elif element.get_name() == "scrambler_tone_start_timing":
                self._memobj.scrambler_tone_start_timing = element.value
            elif element.get_name() == "timer_emergency_switch_on":
                self._memobj.timer.emergency_switch_on = element.value * 10.0
            elif element.get_name() == "timer_emergency_switch_off":
                self._memobj.timer.emergency_switch_off = element.value * 10.0
            elif element.get_name() == "emergency_start_repeat":
                self._memobj.timer.emergency_start_repeat = element.value
            else:
                LOG.warning(
                    'Attempt to set _memobj.%s to "%s"'
                    % (element.get_name(), element.value))
