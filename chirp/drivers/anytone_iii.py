# Copyright 2020 Brad Schuler K0BAS <brad@schuler.ws>
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

import struct
import logging
import string

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings


class ATBankModel(chirp_common.BankModel):
    """AnyTone Banks A-J, Each chan in zero or one bank"""

    def __init__(self, radio, name='Banks'):
        super(ATBankModel, self).__init__(radio, name)
        self._banks = []
        self._memBounds = list(range(0, 750))
        for i in range(0, 10):
            self._banks.append(
                chirp_common.Bank(self, i, string.ascii_uppercase[i]))

    def get_num_mappings(self):
        return len(self._banks)

    def get_mappings(self):
        return self._banks

    def add_memory_to_mapping(self, memory, bank):
        self._radio.set_bank(memory.number, bank.get_index())

    def remove_memory_from_mapping(self, memory, mapping):
        # I would argue that removing a memory from a mapping in which it does
        # not exist should not throw an error.  The end result is the
        # requested result.  The memory is not in the mapping.
        index = self._radio.get_bank(memory.number)
        if (index is None or index != mapping.get_index()):
            raise Exception("Memory %d is not in bank %s" %
                            (memory.number, bank.get_name()))
        self._radio.clr_bank(memory.number)

    def get_mapping_memories(self, bank):
        memories = []
        for i in self._memBounds:
            bank_index = self._radio.get_bank(i)
            if (bank_index is not None and bank_index == bank.get_index()):
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        bank_index = self._radio.get_bank(memory.number)
        if bank_index is None:
            return []
        else:
            return [self._banks[bank_index]]


LOG = logging.getLogger(__name__)

# TODO: Reverse engineer scramble codes
#       Examples: 1=x0300 1111=xDA0B 3300=x3323 3400=x4524
# TODO: Reverse engineer derived-value for 2Tone frequencies
#       Below are some samples:
#       freq    tone    derived
#               0000    0000
#       288.0   0b40    0823    208.3
#       321.7   0c91    0749    186.5
#       526.8   1494    2397    911.1
#       526.9   1495    2395    910.9
#       712.3   1bd3    1a52    673.8
#       928.1   2441    0286     64.6
#       1527.3  3ba9    0c46    314.2
#       1934.7  4b93    09b1    248.1
#       3116.0  79b8    000c      1.2


mem_format_thruflags = """
struct flag {                   // Flags about a channel
  u8 left_only:1,    // Channel is 1.25m or AM (meaning left side only)
     unused:1,          // Unused flag
     scan:2,            // chirp_common.SKIP_VALUES
     group:4;           // [A-J, Off]
};

#seekto 0x0020;                 // Read Only
struct {
  u8 unknown1[16];
  u8 unknown2[16];
  char modellike[14];
  u8 unknown3[2];
  char serial[16];
  u8 zeros16[16];
  char date[16];
  u8 zeros128[128];
} oem_info;

struct flag chan_flags[750]; // Channel flags
struct flag limit_flags[10]; // Limit channel flags
//u8 effs8[8];
"""

mem_format = mem_format_thruflags + """
struct memory {
    bbcd freq[5];           // rx freq
    bbcd offset[3];         // tx offset from rx / 100
    u8 unknown1:4,
       tune_step:4;         // [2.5k, 5k, 6.25k, 8.33k, 10k,
                            //  12.5k, 15k, 20k, 25k, 30k]
    u8 rxdcsextra:1,        // use with rxcode for index of rx DCS to use
       txdcsextra:1,        // use with txcode for index of tx DCS to use
       rxdcsinv:1,          // inverse DCS rx polarity
       txdcsinv:1,          // inverse DCS tx polarity
       channel_width:2,     // [25 kHz, 20 kHz, 12.5 kHz]
       rev:1,               // reverse the tx and rx frequencies & tones
       txoff:1;             // prevent tx
    u8 talkaround:1,        // Use the rx freq & tone when transmitting
       compander:1,
       unknown2:1,
       is_am:1,             // modulation is AM
       power:2,             // [High, Mid1, Mid2, Low]
       duplex:2;            // ['', -, +, off]
    u8 dtmf_enc_num:4,      // zero-based DTMF slot to use for optional
                            // signalling (when optsig = DTMF)
       rxtmode:2,           // ['', Tone, DTCS]
       txtmode:2;           // ['', Tone, DTCS]
    u8 unknown3:2,
       txtone:6;            // TONES[0..50] & 51=custom
    u8 unknown4:2,
       rxtone:6;            // TONES[0..50] & 51=custom
    u8 txcode;              // use with txdcsextra for index of tx DCS to use
    u8 rxcode;              // use with rxdcsextra for index of rx DCS to use
    u8 unknown5:2,
       pttid:2,             // [Off, Begin, End, Begin&End]
       unknown6:2,
       bclo:2;              // [Off, Repeater, Busy]
    u8 unknown7:6,
       band:2;              // [2m, 1-1/4m, 350+ MHz, 70cm]
    u8 unknown8:5,
       sql_mode:3;          // [Carrier, CTCSS/DCS Tones, Opt Sig Only,
                            //  Tones & Opt Sig, Tones or Opt Sig]
                            // Implemented in GUI as a combination of rxmode
                            // and opt sig squelch list OPT_SIG_SQL
    u8 unknown9:6,
       optsig:2;            // [Off, DTMF, 2Tone, 5Tone]
    u8 unknown10:3,
       twotone:5;           // zero-based 2-tone slot to use for optional
                            // signalling (when optsig = 2Tone)
    u8 unknown11:1,
       fivetone:7;          // zero-based 5-tone slot to use for optional
                            // signalling (when optsig = 5Tone)
    u8 unknown12:4,
       scramble:4;          // [Off, 1 ... 9, Define 1, Define 2]
    char name[7];
    ul16 custtone;          // custom ctcss tone (%5.1f) * 10
};

struct DTMF12p3 {
  u8 dtmf[12];              // Each nibble is a DTMF code [0-9A-D*#]
  u8 num_tones;             // Quantity of nibbles/digits in above
  u8 unknown3[3];
};

struct DTMF7 {
  u8 dtmf[7];               // Each nibble is a DTMF code [0-9A-D*#]
  u8 num_tones;             // Quantity of nibbles/digits in above
};

#seekto 0x0400;                 // DTMF slots
struct DTMF12p3 dtmf_encodings[16];

//#seekto 0x0500;
//u8 unknown[64];

#seekto 0x0540;                 // Hyper channels (12 x 2)
struct memory hyper_channels[24];

struct {
  u8 unknown1:6,
     display:2;             // Display Mode: [freq, chan, name]
  u8 unknown2:3,
     sql_left:5;            // Left Squelch Level: 1..20
  u8 unknown3:3,
     sql_right:5;           // Right Squelch Level: 1..20
  u8 unknown4;
  u8 unknown5:6,
     scan_tot:2;            // Scan Pause Time: [TO, CO, SE]
  u8 unknown6:7,
     scan_mode:1;           // Scan Mode: [MEM, MSM(Pri Scan)]
  u8 bg_red;                // Background color red intensity
                            // 0-x1f displayed as 1-32d
  u8 bg_green;              // Background color green intensity
  u8 bg_blue;               // Background color blue intensity
  u8 unknown7:5,
     tbst_freq:3;           // TBST Freq [Off, 1750, 2100, 1000, 1450] Hz
  u8 unknown8:3,
     ptt_tot:5;             // Talk Timeout Timer: [Off, 1..30] minutes
  u8 unknown9:6,
     ptt_lockout:2;         // PTT Key Lock: [Off, Right, Left, Both]
  u8 unknown10:3,
     apo:5;                 // Auto Power Off: [Off, 1..18] * 30 minutes
  u8 unknown11:3,
     key_bright:5;          // Key Light Level: [00-1e] := [1-32]
  u8 long_key_time;         // Long Key Time: # seconds * 100,
                            // so 100 := 1.0 sec, 250 := 2.5 sec
  u8 unknown12:6,
     deputy_mute:2;         // Mute the Deputy channel (sub band) when
                            // primary is doing this: [Off, Tx, Rx, Tx & Rx]
  //#seekto 0x0850;
  u8 disp_chan_lock:1,      // Display Channel Lock when display=1(Chan)
     unknown13:1,
     keypad_lock:1,         // Lock the keypad
     beep_hi:1,             // 0=low 1=high volume
     no_init:1,             // Prohibit initialization: 0=no 1=yes
     unknown14:3;
  u8 unknown15:2,
     clk_shift:1,           // CLK Shift: 0=off 1=on
     ext_spk_on:1,          // Enable the external speaker
     alt_key_mode:1,        // Use Alt Keypad Mode: 0=off 1=on
     beep_on:1,             // Enable beep
     no_tone_elim_tail:1,   // Elim squelch tail when no CTCSS/DCS signaling
     sql_key_mode:1;        // SQL Key Function: [Momentary, Toggle]
  u8 unknown16:5,
     dtmf_preload_time:3;   // DTMF encode preload time:
                            // [100, 300, 500, 800, 1000] ms
  u8 unknown17:5,
     dtmf_speed:3;          // DTMF transmit time/speed:
                            // [30, 50, 80, 100, 150, 200, 250] ms
  u8 unknown19:6,
     tail_elim_type:2;      // Tail Eliminator Type: [Off, 120, 180] degrees
  u8 unknown20:3,
     key_a_func:5;          // Programmable key A function [0-19]:
                            // [Off, DUP, ... Bandwidth, Talk Around]
  u8 unknown21:3,
     key_b_func:5;          // Programmable key B function
  u8 unknown22:3,
     key_c_func:5;          // Programmable key C function
  u8 unknown23:3,
     key_d_func:5;          // Programmable key D function
  u8 unknown24:7,
     boot_pw_on:1;          // Use boot password (verify password is set!)
  u8 unknown25:5,
     rfsql_left:3;          // Left RF Squelch Level:
                            // [Off, S-2, S-5, S-9, FULL]
  u8 unknown26:5,
     rfsql_right:3;         // Right RF Squelch Level
  u8 scramble1[2];          // Scramble code #1 (unknown encoding)
  u8 scramble2[2];          // Scramble code #2 (unknown encoding)

  //#seekto 0x0860 & 0x0880
  struct {
    u8 unknown1;
    u8 unknown2:6,
       left_mode:2;         // [VFO, Channel, Home]
    u8 unknown3:6,
       right_mode:2;        // [VFO, Channel, Home]
    u8 unknown4:6,
       sub_display:2;       // [Freq, DC IN, Off]
    ul16 left_channel;      // Zero-based chan number
    ul16 right_channel;     // Zero-based chan number
    u8 unknown5;
    u8 unknown6:6,
       spkr_mode:2;         // Hand/Main [Off/On, On/On, On/Off]
    u8 unknown7:6,
       left_vfo_band:2;     // [108, 220, 350, 400] MHz
    u8 unknown8:7,
       right_vfo_band:1;    // [136, 400] MHz
    u8 unknown9;
    u8 unknown10:1,
       vfo_tracked:1,
       auto_hyper_save:1,
       auto_rpt_shift:1,
       auto_am:1,
       main:1,              // [Left, Right]
       vfo_band_edge:1,
       unknown11:1;
    u8 unknown12;
    u8 unknown13;
    //#seekto 0x0870 & 0x0890
    u8 unknown14:4,
       left_work_bank:4;    // [A - J, Off]
    u8 unknown15:7,
       left_bank_mode:1;    // [CH, Bank]
    u8 unknown16:7,
       left_bank_sw:1;      // [Off, On]
    u8 unknown17:4,
       right_work_bank:4;   // [A - J, Off]
    u8 unknown18:7,
       right_bank_mode:1;   // [CH, Bank]
    u8 unknown19:7,
       right_bank_sw:1;     // [Off, On]
    // This would be better than below:
    //   struct { u8 unknown:7, linked:1; } linkedBanks[10];
    // They would need to be in a sub-group of settings in the extras.
    // A-J (one byte each) 00 or 01
    u8 unknown20:7,
        link_bank_A:1;
    u8 unknown21:7,
        link_bank_B:1;
    u8 unknown22:7,
        link_bank_C:1;
    u8 unknown23:7,
        link_bank_D:1;
    u8 unknown24:7,
        link_bank_E:1;
    u8 unknown25:7,
        link_bank_F:1;
    u8 unknown26:7,
        link_bank_G:1;
    u8 unknown27:7,
        link_bank_H:1;
    u8 unknown28:7,
        link_bank_I:1;
    u8 unknown29:7,
        link_bank_J:1;
  } hyper_settings[2];

  //#seekto 0x08a0;
  char boot_password[7];    // Boot password
  u8 unknown30[9];

  //#seekto 0x08b0;
  u8 unknown31[16];

  //#seekto 0x08c0;
  u8 unknown32:4,
     dtmf_interval_char:4;  // DTMF interval character
  u8 dtmf_group_code;       // DTMF Group Code: 0a-0f,ff displayed as A-#,Off
  u8 unknown33:6,
     dtmf_dec_resp:2;       // DTMF Decoding Response:
                            // [None, Beep, Beep & Respond]
  u8 unknown34;
  u8 dtmf_first_dig_time;   // DTMF First digit time: 0..250 * 10 ms
  u8 dtmf_auto_rst_time;    // DTMF auto reset time: 0..250
                            // displayed as 0.0-25.0 in 0.1 increments sec
  u8 unknown35;
  u8 dtmf_self_id[3];       // DTMF Self ID: low nibble of each byte is a
                            // DTMF char, exactly 3 chars
  u8 unknown36;
  u8 unknown37;
  u8 unknown38;
  u8 unknown39:7,
     dtmf_sidetone_on:1;    // DTMF side tone enabled
  u8 dtmf_enc_delay;        // DTMF encode delay: 1..250 * 10 ms
  u8 dtmf_pttid_delay;      // DTMF PTT ID delay: 0,5-75
                            // shown as [Off,5-75] sec

  //#seekto 0x08d0;
  struct DTMF7 dtmf_kill;    // DTMF to remotely kill
  struct DTMF7 dtmf_stun;    // DTMF to remotely stun
} settings;

//#seekto 0x08e0;                   // 2 Tone settings - for future work
//struct {
//  ul16 calltone1;           // Call format 1st tone freq * 10
//  ul16 calltone2;           // Call format 2nd tone freq * 10
//                            // (or 00 00 for long tone version of 1st tone)
//  ul16 calltone1derived;    // some derived freq? calculated from 1st tone
//  ul16 calltone2derived;    // some derived freq? calculated from 2nd tone
//  u8 unknown1:6,
//     decode_resp:2;         // Decode response [None, Beep, Beep & Respond]
//  u8 tone1_dur;             // 1st tone duration * 10
//                            // shown as range(0.5, 10, 0.1) seconds
//  u8 tone2_dur;             // 2nd tone duration * 10
//                            // shown as range(0.5, 10, 0.1) seconds
//  u8 longtone_dur;          // Long tone duration * 10
//                            // shown as range(0.5, 10, 0.1) seconds
//  u8 gap_time;              // Gap time / 100
//                            // shown as range(0, 2000, 100) msec
//  u8 auto_rst_time;         // Auto reset time * 10
//                            // shown as range(0, 25, 0.1) sec
//  u8 unknown:7,
//     enc_sidetone;          // Encode side-tone 0=off 1=on
//  u8 unknown2:4,
//     call_format:4;         // Call format [A-B, A-C, A-D, B-A, B-C, B-D,
//                            //              C-A, C-B, C-D, D-A, D-B, D-C,
//                            //              Long A, Long B, Long C]
//                            // Be sure to change callTone1/2 and
//                            // callTone1/2derived when callFormat is changed
//  //#seekto 0x08f0;
//  u16 a_tone;               // A tone freq * 10
//  u16 b_tone;               // B tone freq * 10
//  u16 c_tone;               // C tone freq * 10
//  u16 d_tone;               // D tone freq * 10
//  u8 zeros[8];
//} twotone_settings;

//#seekto 0x0900;                 // Unknown all 0x00
//u8 zeros[512];

//#seekto 0x0b00;                 // 2 Tone memories (24 slots of 16 bytes)
//struct {
//  ul16 tone1derived;        // some derived freq? calculated from 1st tone
//  ul16 tone2derived;        // some derived freq? calculated from 2nd tone
//  ul16 tone1;               // 1st tone freq * 10
//  ul16 tone2;               // 2nd tone freq * 10
//  char name[7];             // Tone name (padded)
//  u8 zero;
//} twotone_slots[24];

//#seekto 0x0c80;                 // Unknown all 0x24
//u8 twentyfours[128];

//#seekto 0x0d00;                 // 5 Tone configs (100 slots of 32 bytes)
//u8 fivetones[3200];

#seekto 0x1980;                 // Communication  notes
struct {
    char call_id[5];         // Call ID (numeric, max 5 digits (x30-x39)
    u8 zeros[3];            // 0x00 * 3
} note_call_ids[100];
struct {
    char name[7];           // Names (ALPHAnumeric max 7 chars)
    char space;             // 0x20
} note_names[100];

//#seekto 0x1fc0;                 // Unknown all 0x00
//u8 zeros[64];

#seekto 0x2000;
struct memory channels[750];        // Normal channels (750 * 32 bytes)

//#seekto 0x7dc0;
struct memory limit_channels[10];   // Limit channels
                                    // (10 * 32 bytes: Five pair of lo/hi)

//#seekto 0x7f00;                 // Unknown
//u8 unknown[32];

#seekto 0x7f20;
struct DTMF12p3 dtmf_pttid_bot;   // DTMF PTT ID Start (BOT)
struct DTMF12p3 dtmf_pttid_eot;   // DTMF PTT ID End (EOT)

//#seekto 0x7f40;
//u8 unknown[64]

#seekto 0x7f80;                 // Emergency Information
struct {
  u8 unknown:6,
     mode:2;                // [Alarm, Transpond+Background,
                            //  Transpond+Alarm, Both]
  u8 unknown2:6,
     eni_type:2;            // [None, DTMF, 5Tone]
  u8 id;                    // When DTMF: [M1-M16], When 5Tone: 0-99
  u8 alarm_time;            // [1-255] seconds
  u8 tx_time;               // [0-255] seconds
  u8 rx_time;               // [0-255] seconds
  u8 unknown3:7,
     chan_select:1;         // [Assigned, Selected]
  ul16 channel;             // [0-749]
  u8 cycle;                 // [Continuous, 1-255]
} emergency;
u8 unknown9[6];

//#seekto 0x7f90;                 // Unknown
//u8 unknown[48]

#seekto 0x7fc0;                 // Welcome message
char welcome[7];
//u8 zeros[9];

//#seekto 0x7fd0;
//u8 unknown[48];
"""


def _is_chan_used(memobj, num):
    return not memobj.chan_flags[num].unused


def _is_limit_chan_used(memobj, num):
    return not memobj.limit_flags[num].unused


def _should_send_addr(memobj, addr):
    # Skip read-only & out of bounds
    if addr < 0x0100 or addr >= 0x8000:
        return False
    # Skip regions of unknown or uncontrolled by this software
    if ((addr >= 0x0500 and addr < 0x0540) or
            (addr >= 0x08e0 and addr < 0x1980) or
            (addr >= 0x1fc0 and addr < 0x2000) or
            (addr >= 0x7f00 and addr < 0x7f20) or
            (addr >= 0x7f40 and addr < 0x7f80) or
            (addr >= 0x7f90 and addr < 0x7fc0) or
            addr >= 0x7fd0):
        return False
    # Skip unused memories
    if addr >= 0x2000 and addr < 0x7dc0:
        return _is_chan_used(memobj, int((addr - 0x2000) / 0x20))
    if addr >= 0x7dc0 and addr < 0x7f00:
        return _is_limit_chan_used(memobj, int((addr - 0x7dc0) / 0x20))
    return True


def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
        radio.pipe.read(len(data))
    except Exception as e:
        LOG.error("Error writing to radio: %s" % e)
        raise errors.RadioError("Unable to write to radio")


def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception as e:
        LOG.error("Error reading from radio: %s" % e)
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        LOG.error("Short read from radio (%i, expected %i)" %
                  (len(data), length))
        LOG.debug(util.hexprint(data))
        raise errors.RadioError("Short read from radio")
    return data


valid_model = [b'I588UVP']


def _ident(radio):
    radio.pipe.timeout = 1
    _echo_write(radio, b"PROGRAM")
    response = radio.pipe.read(3)
    if response != b"QX\x06":
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")
    _echo_write(radio, b"\x02")
    response = radio.pipe.read(16)
    LOG.debug(util.hexprint(response))
    if response[-1:] != b"\x06":
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Missing ack")
    if response[0:7] not in valid_model:
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")
    # Manufacturer software does this also: _send(radio, b'R', 0x0080, 0x10)


def _finish(radio):
    endframe = b"\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    if result != b"\x06":
        LOG.debug("Got:\n%s" % util.hexprint(result))
        raise errors.RadioError("Radio did not finish cleanly")


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += bytes([_checksum(frame[1:])])
        frame += b"\x06"
    _echo_write(radio, frame)
    LOG.debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != b"\x06":
            LOG.debug("Ack was: %s" % util.hexprint(result))
            raise errors.RadioError(
                "Radio did not accept block at %04x" % addr)
        return
    result = _read(radio, length + 6)
    LOG.debug("Got:\n%s" % util.hexprint(result))
    header = result[0:4]
    data = result[4:-2]
    ack = result[-1:]
    if ack != b"\x06":
        LOG.debug("Ack was: %s" % repr(ack))
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        LOG.debug("Expected/Received:")
        LOG.debug(" Length: %02x/%02x" % (length, _length))
        LOG.debug(" Addr: %04x/%04x" % (addr, _addr))
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != result[-2]:
        LOG.debug("Calculated: %02x" % cs)
        LOG.debug("Actual:     %02x" % result[-2])
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data


def _download(radio):
    _ident(radio)

    memobj = None

    data = b""
    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            if memobj is not None and not _should_send_addr(memobj, addr):
                block = b"\x00" * 0x10
            else:
                block = _send(radio, b'R', addr, 0x10)
            data += block

            status = chirp_common.Status()
            status.cur = len(data)
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)

            if addr == 0x0400 - 0x10:
                memobj = bitwise.parse(mem_format_thruflags, data)

    _finish(radio)

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    _ident(radio)

    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            if not _should_send_addr(radio._memobj, addr):
                continue
            block = radio._mmap[addr:addr + 0x10]
            _send(radio, b'W', addr, len(block), block)

            status = chirp_common.Status()
            status.cur = addr
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    _finish(radio)


def _filter(s, charset):
    rc = ""
    for i in range(0, len(s)):
        c = str(s[i])
        rc += (c if c in charset else "")
    return rc


SEVEN_SPACES = "       "
APO = ['Off'] + ['%.1f hour(s)' % (0.5 * x) for x in range(1, 25)]
ONEANDQTRBAND = (220000000, 260000000)
LEFT_BANDS = [
    (108000000, 180000000),  # L-108
    ONEANDQTRBAND,           # L-220
    (350000000, 399995000),  # L-350
    (400000000, 523000000)   # L/R-400
]
RIGHT_BANDS = [
    (136000000, 174000000),  # R-136
    (400000000, 523000000)   # L/R-400
]
BCLO = ['Off', 'Repeater', 'Busy']
BEEP_VOL = ['Low', 'High']
CROSS_MODES = list(chirp_common.CROSS_MODES)
CROSS_MODES.remove("Tone->")
DISPLAY = ['Freq', 'Chan#', 'Name']
DTMF_SLOTS = ['M%d' % x for x in range(1, 17)]
DUPLEXES = ['', '-', '+', 'off']
KEY_FUNCS = ['Off', 'DUP', 'PRI On', 'Power', 'Set DCS/CTCSS Code', 'MHz',
             'Reverse', 'HM Chan', 'Main L/R Switch', 'VFO/MR', 'Scan',
             'Squelch Off', 'Call TBST', 'Call', 'Tone Compande',
             'Scramble', 'Add Opt Signal', 'Bandwidth', 'Talk Around']
MODES = ["WFM", "FM", "NFM"]
OPT_SIGS = ['Off', 'DTMF', '2Tone', '5Tone']
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=50),
                chirp_common.PowerLevel("Mid1", watts=25),
                chirp_common.PowerLevel("Mid2", watts=10),
                chirp_common.PowerLevel("Low", watts=5)]
PTT_IDS = ['Off', 'Begin', 'End', 'Begin & End']
RF_SQUELCHES = ['Off', 'S-2', 'S-5', 'S-9', 'FULL']
SCAN_PAUSES = ['TO', 'CO', 'SE']
SCAN_MODES = ['MEM', 'MSM (Pri Scan)']

SCRAMBLE_CODES = ['Off']
for x in range(1, 10):
    SCRAMBLE_CODES.append('%d' % x)
SCRAMBLE_CODES += ['Define 1', 'Define 2']

T_MODES = ['', 'Tone', 'DTCS', '']
TONE2_SLOTS = ['%d' % x for x in range(0, 24)]
TONE5_SLOTS = ['%d' % x for x in range(0, 100)]
# Future: chirp_common should present TONES instead of hard-coded list
TONES = (62.5,) + chirp_common.TONES
TOT = ['Off'] + ['%s Minutes' % x for x in range(1, 31)]
TUNING_STEPS = [2.5, 5, 6.25, 8.33, 10, 12.5, 15, 20, 25, 30]
PTT_KEY_LOCKS = ["Off", "Right", "Left", "Both"]
TBST_FREQS = ["Off", "1750 Hz", "2100 Hz", "1000 Hz", "1450 Hz"]
LONG_KEY_TIMES = ["1 second", "1.5 seconds", "2 seconds", "2.5 seconds"]
DEPUTY_CHAN_MUTES = ["Off", "Tx", "Rx", "Both"]
SQL_BTN_MODES = ["Momentary", "Toggle"]
SQL_MODES = ["Carrier", "CTCSS/DCS", "Opt Sig Only", "Tones AND Sig",
             "Tones OR Sig"]
OPT_SIG_SQL = ["Off"] + SQL_MODES[2:]
TAIL_ELIM_TYPES = ["Off", "120 degrees", "180 degrees"]
LIMIT_NAMES = ["Limit %s %d" % (c, i + 1)
               for i in range(0, 5) for c in ('Lo', 'Hi')]
HYPER_NAMES = ["Hyper-%s %s%s" % (h, x, y)
               for h in ('1', '2')
               for x in ('', 'H')
               for y in ('L-108', 'L-220', 'L-350', 'L-400', 'R-136', 'R-400')]
HYPER_MODES = ['VFO', 'Channel', 'Home']
HYPER_SUB_DISPLAYS = ['Freq', 'DC IN', 'Off']
HYPER_SPKR_MODES = ['Mic off', 'Mic on', 'Main off']
HYPER_L_VFOS = ['108 MHz', '220 MHz', '350 MHz', '400 MHz']
HYPER_R_VFOS = ['136 MHz', '400 MHz']
HYPER_MAINS = ['Left', 'Right']
HYPER_BANK_MODES = ['CH', 'Bank']
EMER_MODES = ['Alarm', 'Transpond+Background', 'Transpond+Alarm', 'Both']
EMER_ENI_TYPES = ['None', 'DTMF', '5Tone']
EMER_CHAN_SEL = ['Assigned', 'Selected']
EMER_CYCLES = ['Continuous'] + ["%d seconds" % x for x in range(1, 256)]
BANK_CHOICES = ["%s" % chr(x) for x in range(ord("A"), ord("J") + 1)] + ['Off']
DTMF_CHARS = "0123456789ABCD*#"
DTMF_INTCHARS = "ABCD*#"
DTMF_PRELOADS = ['100 ms', '300 ms', '500 ms', '800 ms', '1000 ms']
DTMF_SPEEDS = ['30 ms', '50 ms', '80 ms', '100 ms',
               '150 ms', '200 ms', '250 ms']
DTMF_GROUPS = list("ABCDEF") + ['Off']
DTMF_RESPONSES = ['None', 'Beep', 'Beep & Respond']
DTMF_PTTDELAYS = ['Off'] + ["%d seconds" % x for x in range(5, 76)]


def _dtmf_encode(dtmf_str, numBytes):
    dtmf_bytes = []
    if len(dtmf_str) != 0:
        _byte = 0x00
        for i in range(1, len(dtmf_str)+1):
            if i % 2 == 0:
                _byte |= DTMF_CHARS.index(dtmf_str[i-1])
                dtmf_bytes.append(_byte)
                _byte = 0x00
            else:
                _byte = DTMF_CHARS.index(dtmf_str[i-1]) << 4
        if len(dtmf_str) % 2 == 1:
            dtmf_bytes.append(_byte)
    while (len(dtmf_bytes) < numBytes):
        dtmf_bytes.append(0)
    return dtmf_bytes


def _dtmf_decode(dtmf_bytes, num_tones):
    dtmf_str = ""
    x = 1
    while (x <= num_tones):
        _byte = dtmf_bytes[(x-1)/2]
        dtmf_str += DTMF_CHARS[_byte >> 4]
        x += 1
        if (x <= num_tones):
            dtmf_str += DTMF_CHARS[_byte & 0x0F]
            x += 1
    return dtmf_str


class _RadioSettingValueOffsetInt(RadioSettingValueInteger):
    """An integer setting whose real value is offset from displayed value"""

    def __init__(self, minval, maxval, current, step=1, offset=0):
        RadioSettingValueInteger.__init__(self, minval, maxval, current, step)
        self.offset = offset


@directory.register
class AnyTone5888UVIIIRadio(chirp_common.CloneModeRadio,
                            chirp_common.ExperimentalRadio):
    """AnyTone 5888UVIII"""
    VENDOR = "AnyTone"
    MODEL = "5888UVIII"
    BAUD_RATE = 9600
    _file_ident = b"588UVP"

    _ranges = [
            (0x0000, 0x8000)
        ]

    def get_bank_model(self):
        return ATBankModel(self)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The Anytone 5888UVIII driver is currently "
                           "experimental. There are no known issues with it, "
                           "but you should proceed with caution. 2-tone, "
                           "5-tone, and scramble settings are limited. ")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_rx_dtcs = True
        rf.has_bank = True
        rf.has_cross = True
        rf.has_settings = True
        rf.valid_modes = MODES + ['AM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = CROSS_MODES
        rf.valid_duplexes = DUPLEXES
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_bands = LEFT_BANDS + RIGHT_BANDS
        rf.valid_skips = chirp_common.SKIP_VALUES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_name_length = 7
        # Future: rf.valid_tones = TONES
        # Future: update memdetail.py to use rf.valid_dtcs_codes
        # Future: update memdetail.py to use rf.dtcs_polarity
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.memory_bounds = (1, 750)
        rf.valid_special_chans = LIMIT_NAMES + HYPER_NAMES
        return rf

    def sync_in(self):
        self._mmap = _download(self)
        self.process_mmap()

    def sync_out(self):
        _upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_memobjs(self, number):
        if number <= len(self._memobj.channels):
            _mem = self._memobj.channels[number - 1]
            _flg = self._memobj.chan_flags[number - 1]
        elif (number <= len(self._memobj.channels) +
              len(self._memobj.limit_channels)):
            _mem = self._memobj.limit_channels[number -
                                               len(self._memobj.channels) -
                                               1]
            _flg = self._memobj.limit_flags[number -
                                            len(self._memobj.channels) -
                                            1]
        else:
            _mem = self._memobj.hyper_channels[
                number -
                len(self._memobj.channels) -
                len(self._memobj.limit_channels) -
                1]
            _flg = None
        return _mem, _flg

    def _get_dcs_index(self, _mem, which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)

    def get_raw_memory(self, number):
        _mem, _flg = self._get_memobjs(number)
        return repr(_mem) + repr(_flg)

    def set_bank(self, number, bank_index):
        _mem, _flg = self._get_memobjs(number)
        _flg.group = bank_index

    def clr_bank(self, number):
        _mem, _flg = self._get_memobjs(number)
        _flg.group = BANK_CHOICES.index('Off')

    def get_bank(self, number):
        _mem, _flg = self._get_memobjs(number)
        if (_flg.group < 0xa):
            return _flg.group
        return None

    def get_memory(self, number):
        mem = chirp_common.Memory()
        is_limit_chan = is_hyper_chan = False
        if isinstance(number, str):
            if number in LIMIT_NAMES:
                is_limit_chan = True
                mem.number = (len(self._memobj.channels) +
                              LIMIT_NAMES.index(number) +
                              1)
            elif number in HYPER_NAMES:
                is_hyper_chan = True
                mem.number = (len(self._memobj.channels) +
                              len(LIMIT_NAMES) +
                              HYPER_NAMES.index(number) +
                              1)
            mem.extd_number = number
        elif number > (len(self._memobj.channels) +
                       len(self._memobj.limit_channels)):
            is_hyper_chan = True
            mem.number = number
            mem.extd_number = HYPER_NAMES[number -
                                          len(self._memobj.channels) -
                                          len(self._memobj.limit_channels) -
                                          1]
        elif number > len(self._memobj.channels):
            is_limit_chan = True
            mem.number = number
            mem.extd_number = LIMIT_NAMES[number -
                                          len(self._memobj.channels) -
                                          1]
        else:
            mem.number = number

        _mem, _flg = self._get_memobjs(mem.number)

        if not is_hyper_chan and _flg.unused:
            mem.empty = True
            _mem.fill_raw(b"\x00")
            _mem.name = SEVEN_SPACES
            _flg.scan = 0

        mem.freq = int(_mem.freq)

        mem.offset = int(_mem.offset) * 100
        mem.name = (str(_mem.name).rstrip()
                    if not is_limit_chan and not is_hyper_chan
                    else SEVEN_SPACES)
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.mode = _mem.is_am and "AM" or MODES[_mem.channel_width]
        mem.tuning_step = TUNING_STEPS[_mem.tune_step]

        if _mem.txoff:
            mem.duplex = DUPLEXES[3]

        rxtone = txtone = None
        rxmode = T_MODES[_mem.rxtmode]
        if _mem.sql_mode == 0 or _mem.sql_mode == 2:
            rxmode = T_MODES.index('')
        txmode = T_MODES[_mem.txtmode]
        if txmode == "Tone":
            # If custom tone is being used, show as 88.5 and set checkbox in
            # extras.
            # Future: Improve chirp_common, so I can add "CUSTOM" into TONES
            if _mem.txtone == len(TONES):
                txtone = 88.5
            else:
                txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'tx')]
        if rxmode == "Tone":
            # If custom tone is being used, show as 88.5 and set checkbox in
            # extras.
            # Future: Improve chirp_common, so I can add "CUSTOM" into TONES
            if _mem.rxtone == len(TONES):
                rxtone = 88.5
            else:
                rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'rx')]

        rxpol = _mem.rxdcsinv and "R" or "N"
        txpol = _mem.txdcsinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        mem.skip = chirp_common.SKIP_VALUES[_flg.scan
                                            if not is_hyper_chan
                                            else 0]
        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("rev", "Reverse",
                          RadioSettingValueBoolean(_mem.rev))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting("talkaround", "Talkaround",
                          RadioSettingValueBoolean(_mem.talkaround))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTT_IDS,
                                                current_index=_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("bclo", "Busy Channel Lockout",
                          RadioSettingValueList(BCLO,
                                                current_index=_mem.bclo))
        mem.extra.append(rs)

        rs = RadioSetting("optsig", "Optional Signaling",
                          RadioSettingValueList(OPT_SIGS,
                                                current_index=_mem.optsig))
        mem.extra.append(rs)

        rs = RadioSetting("OPTSIGSQL", "Squelch w/Opt Signaling",
                          RadioSettingValueList(
                              OPT_SIG_SQL,
                              SQL_MODES[_mem.sql_mode]
                              if SQL_MODES[_mem.sql_mode] in OPT_SIG_SQL
                              else "Off"))
        mem.extra.append(rs)

        rs = RadioSetting(
            "dtmf_enc_num", "DTMF",
            RadioSettingValueList(
                DTMF_SLOTS, current_index=_mem.dtmf_enc_num))
        mem.extra.append(rs)

        rs = RadioSetting("twotone", "2-Tone",
                          RadioSettingValueList(TONE2_SLOTS,
                                                current_index=_mem.twotone))
        mem.extra.append(rs)

        rs = RadioSetting("fivetone", "5-Tone",
                          RadioSettingValueList(TONE5_SLOTS,
                                                current_index=_mem.fivetone))
        mem.extra.append(rs)

        rs = RadioSetting("scramble", "Scrambler Switch",
                          RadioSettingValueList(SCRAMBLE_CODES,
                                                current_index=_mem.scramble))
        mem.extra.append(rs)

        # Memory properties dialog is only capable of Boolean and List
        # RadioSettingValue classes, so cannot configure custtone.
        # rs = RadioSetting("custtone", "Custom CTCSS",
        #                   RadioSettingValueFloat(
        #                       min(TONES),
        #                       max(TONES),
        #                       _mem.custtone and _mem.custtone / 10 or 151.1,
        #                       0.1,
        #                       1))
        # mem.extra.append(rs)
        custtone_str = chirp_common.format_freq(_mem.custtone)

        rs = RadioSetting("CUSTTONETX",
                          "Use Custom CTCSS (%s) for Tx" % custtone_str,
                          RadioSettingValueBoolean(_mem.txtone == len(TONES)))
        mem.extra.append(rs)

        rs = RadioSetting("CUSTTONERX",
                          "Use Custom CTCSS (%s) for Rx" % custtone_str,
                          RadioSettingValueBoolean(_mem.rxtone == len(TONES)))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        is_limit_chan = is_hyper_chan = False
        if mem.number > (len(self._memobj.channels) +
                         len(self._memobj.limit_channels)):
            is_hyper_chan = True
        elif mem.number > len(self._memobj.channels):
            is_limit_chan = True

        _mem, _flg = self._get_memobjs(mem.number)

        if mem.empty:
            if is_hyper_chan:
                raise errors.InvalidValueError("Hyper memories may not be "
                                               "empty.")
            _mem.set_raw("\x00" * 32)
            _flg.unused = 1
            _flg.group = BANK_CHOICES.index('Off')
            return

        if mem.mode == "AM" and (mem.freq < LEFT_BANDS[0][0] or
                                 mem.freq > LEFT_BANDS[0][1]):
            raise errors.InvalidValueError("AM modulation only allowed in 2m "
                                           "band.")

        _mem.set_raw("\x00" * 32)
        if _flg:
            # Only non-special memories track this
            _flg.unused = 0

        _mem.freq = mem.freq

        for band_idx in range(0, len(LEFT_BANDS)):
            if (mem.freq >= LEFT_BANDS[band_idx][0] and
                    mem.freq <= LEFT_BANDS[band_idx][1]):
                _mem.band = band_idx
                break

        if _flg:
            # Only non-special memories have this
            _flg.left_only = 0
        if (not is_hyper_chan):
            if mem.mode == "AM":
                _flg.left_only = 1
            else:
                _flg.left_only = 1
                for low, high in RIGHT_BANDS:
                    if mem.freq >= low and mem.freq <= high:
                        _flg.left_only = 0
                        break

        _mem.offset = mem.offset / 100

        if is_hyper_chan:
            mem.name = SEVEN_SPACES
        else:
            _mem.name = mem.name.ljust(7)

        if mem.duplex == "off":
            _mem.duplex = DUPLEXES.index("")
            _mem.txoff = 1
        else:
            _mem.duplex = DUPLEXES.index(mem.duplex)
            _mem.txoff = 0

        _mem.is_am = mem.mode == "AM"

        _mem.tune_step = TUNING_STEPS.index(mem.tuning_step)

        try:
            _mem.channel_width = MODES.index(mem.mode)
        except ValueError:
            _mem.channel_width = 0

        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = T_MODES.index(txmode)
        _mem.rxtmode = T_MODES.index(rxmode)
        if rxmode != '':
            _mem.sql_mode = SQL_MODES.index("CTCSS/DCS")
        else:
            _mem.sql_mode = SQL_MODES.index("Carrier")
        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem, 'tx',
                                chirp_common.ALL_DTCS_CODES.index(txtone))
        if rxmode == "Tone":
            _mem.rxtone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            self._set_dcs_index(_mem, 'rx',
                                chirp_common.ALL_DTCS_CODES.index(rxtone))

        _mem.txdcsinv = txpol == "R"
        _mem.rxdcsinv = rxpol == "R"

        if not is_hyper_chan:
            _flg.scan = chirp_common.SKIP_VALUES.index(mem.skip)

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        for setting in mem.extra:
            if setting.get_name() == "ignore":
                LOG.debug("*** ignore: %s" % str(setting.value))
            # Future: elif setting.get_name() == "custtone":
            # Future: setattr(_mem, "custtone", setting.value.get_value() * 10)
            elif setting.get_name() == "OPTSIGSQL":
                if str(setting.value) != "Off":
                    _mem.sql_mode = SQL_MODES.index(str(setting.value))
            elif setting.get_name() == "CUSTTONETX":
                if setting.value:
                    _mem.txtone = len(TONES)
            elif setting.get_name() == "CUSTTONERX":
                if setting.value:
                    _mem.rxtone = len(TONES)
            else:
                setattr(_mem, setting.get_name(), setting.value)

        return mem

    def get_settings(self):
        allGroups = RadioSettings()

        _settings = self._memobj.settings

        basic = RadioSettingGroup("basic", "Basic")
        basic.append(
            RadioSetting(
                "welcome",
                "Welcome Message",
                RadioSettingValueString(
                    0,
                    7,
                    _filter(self._memobj.welcome,
                            chirp_common.CHARSET_ASCII))))
        basic.append(
            RadioSetting(
                "display", "Display",
                RadioSettingValueList(
                    DISPLAY, current_index=_settings.display)))
        basic.append(
            RadioSetting(
                "disp_chan_lock",
                "Lock Chan# Disp",
                RadioSettingValueBoolean(_settings.disp_chan_lock)))
        basic.append(
            RadioSetting(
                "scan_tot",
                "Scan Pause Time",
                RadioSettingValueList(
                    SCAN_PAUSES,
                    current_index=_settings.scan_tot)))
        basic.append(
            RadioSetting(
                "scan_mode",
                "Scan Mode",
                RadioSettingValueList(
                    SCAN_MODES,
                    current_index=_settings.scan_mode)))
        basic.append(
            RadioSetting(
                "ptt_tot",
                "Talk Timeout",
                RadioSettingValueList(TOT, current_index=_settings.ptt_tot)))
        basic.append(
            RadioSetting(
                "apo",
                "Auto Power Off",
                RadioSettingValueList(APO, current_index=_settings.apo)))
        basic.append(
            RadioSetting(
                "beep_on",
                "Beep",
                RadioSettingValueBoolean(_settings.beep_on)))
        basic.append(
            RadioSetting(
                "beep_hi", "Beep Volume",
                RadioSettingValueList(
                    BEEP_VOL, current_index=_settings.beep_hi)))
        basic.append(
            RadioSetting(
                "ext_spk_on",
                "External Speaker",
                RadioSettingValueBoolean(_settings.ext_spk_on)))
        basic.append(
            RadioSetting(
                "deputy_mute",
                "Deputy Chan Mute",
                RadioSettingValueList(
                    DEPUTY_CHAN_MUTES,
                    current_index=_settings.deputy_mute)))
        basic.append(
            RadioSetting(
                "tail_elim_type",
                "Tail Eliminator",
                RadioSettingValueList(
                    TAIL_ELIM_TYPES,
                    current_index=_settings.tail_elim_type)))
        basic.append(
            RadioSetting(
                "no_tone_elim_tail",
                "Eliminate SQL Tail When\nNo Tone Signaling",
                RadioSettingValueBoolean(_settings.no_tone_elim_tail)))
        allGroups.append(basic)

        sqls = RadioSettingGroup("sql", "Squelch Levels")
        sqls.append(
            RadioSetting(
                "sql_left",
                "Left Squelch",
                RadioSettingValueInteger(0, 20, _settings.sql_left)))
        sqls.append(
            RadioSetting(
                "sql_right",
                "Right Squelch",
                RadioSettingValueInteger(0, 20, _settings.sql_right)))
        sqls.append(
            RadioSetting(
                "rfsql_left",
                "Left RF Squelch",
                RadioSettingValueList(
                    RF_SQUELCHES,
                    current_index=_settings.rfsql_left)))
        sqls.append(
            RadioSetting(
                "rfsql_right",
                "Right RF Squelch",
                RadioSettingValueList(
                    RF_SQUELCHES,
                    current_index=_settings.rfsql_right)))
        allGroups.append(sqls)

        keys = RadioSettingGroup("keys", "Keys / Buttons")
        keys.append(
            RadioSetting(
                "sql_key_mode",
                "SQL Key Mode",
                RadioSettingValueList(
                    SQL_BTN_MODES,
                    current_index=_settings.sql_key_mode)))
        keys.append(
            RadioSetting(
                "key_a_func",
                "PA Key Function",
                RadioSettingValueList(
                    KEY_FUNCS,
                    current_index=_settings.key_a_func)))
        keys.append(
            RadioSetting(
                "key_b_func",
                "PB Key Function",
                RadioSettingValueList(
                    KEY_FUNCS,
                    current_index=_settings.key_b_func)))
        keys.append(
            RadioSetting(
                "key_c_func",
                "PC Key Function",
                RadioSettingValueList(
                    KEY_FUNCS,
                    current_index=_settings.key_c_func)))
        keys.append(
            RadioSetting(
                "key_d_func",
                "PD Key Function",
                RadioSettingValueList(
                    KEY_FUNCS,
                    current_index=_settings.key_d_func)))
        keys.append(
            RadioSetting(
                "key_bright",
                "Key Light Level",
                _RadioSettingValueOffsetInt(
                    1,
                    32,
                    _settings.key_bright + 1,
                    1,
                    -1)))
        keys.append(
            RadioSetting(
                "ptt_lockout",
                "PTT Key Lock",
                RadioSettingValueList(
                    PTT_KEY_LOCKS,
                    current_index=_settings.ptt_lockout)))
        keys.append(
            RadioSetting(
                "keypad_lock",
                "Keypad Lockout",
                RadioSettingValueBoolean(_settings.keypad_lock)))
        allGroups.append(keys)

        bgColor = RadioSettingGroup("bgColor", "Background Color")
        bgColor.append(
            RadioSetting(
                "bg_red",
                "Red",
                _RadioSettingValueOffsetInt(
                    1,
                    32,
                    _settings.bg_red + 1,
                    1,
                    -1)))
        bgColor.append(
            RadioSetting(
                "bg_green",
                "Green",
                _RadioSettingValueOffsetInt(
                    1,
                    32,
                    _settings.bg_green + 1,
                    1,
                    -1)))
        bgColor.append(
            RadioSetting(
                "bg_blue",
                "Blue",
                _RadioSettingValueOffsetInt(
                    1,
                    32,
                    _settings.bg_blue + 1,
                    1,
                    -1)))
        allGroups.append(bgColor)

        pwdGroup = RadioSettingGroup("pwdGroup", "Boot Password")
        pwdGroup.append(
            RadioSetting(
                "boot_pw_on",
                "Enable",
                RadioSettingValueBoolean(_settings.boot_pw_on)))
        pwdGroup.append(
            RadioSetting(
                "boot_password",
                "Password (digits)",
                RadioSettingValueString(
                    0,
                    7,
                    _filter(_settings.boot_password, string.digits),
                    False,
                    string.digits)))
        allGroups.append(pwdGroup)

        advanced = RadioSettingGroup("advanced", "Advanced")
        advanced.append(
            RadioSetting(
                "tbst_freq",
                "TBST Freq",
                RadioSettingValueList(
                    TBST_FREQS,
                    current_index=_settings.tbst_freq)))
        advanced.append(
            RadioSetting(
                "long_key_time",
                "Long Key Time",
                RadioSettingValueList(
                    LONG_KEY_TIMES,
                    current_index=int((_settings.long_key_time-100) / 50))))
        advanced.append(
            RadioSetting(
                "clk_shift",
                "CLK Shift",
                RadioSettingValueBoolean(_settings.clk_shift)))
        advanced.append(
            RadioSetting(
                "alt_key_mode",
                "Keypad Alt Mode",
                RadioSettingValueBoolean(_settings.alt_key_mode)))
        advanced.append(
            RadioSetting(
                "no_init",
                "Prohibit Initialization",
                RadioSettingValueBoolean(_settings.no_init)))
        allGroups.append(advanced)

        hyperGroups = [
            RadioSettingGroup("hyper1", "Hyper 1"),
            RadioSettingGroup("hyper2", "Hyper 2")
        ]
        for idx in range(0, len(hyperGroups)):
            _hyperSettings = _settings.hyper_settings[idx]
            hyperGroup = hyperGroups[idx]
            hyperGroup.append(
                RadioSetting(
                    "main",
                    "Main Band",
                    RadioSettingValueList(
                        HYPER_MAINS,
                        current_index=_hyperSettings.main)))
            hyperGroup.append(
                RadioSetting(
                    "sub_display",
                    "Sub Display",
                    RadioSettingValueList(
                        HYPER_SUB_DISPLAYS,
                        current_index=_hyperSettings.sub_display)))
            hyperGroup.append(
                RadioSetting(
                    "spkr_mode",
                    "Speakers",
                    RadioSettingValueList(
                        HYPER_SPKR_MODES,
                        current_index=_hyperSettings.spkr_mode)))
            hyperGroup.append(
                RadioSetting(
                    "vfo_band_edge",
                    "VFO Band Lock",
                    RadioSettingValueBoolean(_hyperSettings.vfo_band_edge)))
            hyperGroup.append(
                RadioSetting(
                    "auto_am",
                    "Auto AM",
                    RadioSettingValueBoolean(_hyperSettings.auto_am)))
            hyperGroup.append(
                RadioSetting(
                    "auto_rpt_shift",
                    "Auto Repeater Shift",
                    RadioSettingValueBoolean(_hyperSettings.auto_rpt_shift)))
            hyperGroup.append(
                RadioSetting(
                    "auto_hyper_save",
                    "Auto Hyper Save",
                    RadioSettingValueBoolean(_hyperSettings.auto_hyper_save)))
            hyperGroup.append(
                RadioSetting(
                    "vfo_tracked",
                    "VFO Tracking",
                    RadioSettingValueBoolean(_hyperSettings.vfo_tracked)))
            hyperGroup.append(
                RadioSetting(
                    "left_mode",
                    "Left Mode",
                    RadioSettingValueList(
                        HYPER_MODES,
                        current_index=_hyperSettings.left_mode)))
            hyperGroup.append(
                RadioSetting(
                    "right_mode",
                    "Right Mode",
                    RadioSettingValueList(
                        HYPER_MODES,
                        current_index=_hyperSettings.right_mode)))
            hyperGroup.append(
                RadioSetting(
                    "left_channel",
                    "Left Channel",
                    _RadioSettingValueOffsetInt(
                        1,
                        750,
                        _hyperSettings.left_channel + 1,
                        1,
                        -1)))
            hyperGroup.append(
                RadioSetting(
                    "right_channel",
                    "Right Channel",
                    _RadioSettingValueOffsetInt(
                        1,
                        750,
                        _hyperSettings.right_channel + 1,
                        1,
                        -1)))
            hyperGroup.append(
                RadioSetting(
                    "left_vfo_band",
                    "Left VFO Band",
                    RadioSettingValueList(
                        HYPER_L_VFOS,
                        current_index=_hyperSettings.left_vfo_band)))
            hyperGroup.append(
                RadioSetting(
                    "right_vfo_band",
                    "Right VFO Band",
                    RadioSettingValueList(
                        HYPER_R_VFOS,
                        current_index=_hyperSettings.right_vfo_band)))
            hyperGroup.append(
                RadioSetting(
                    "left_work_bank",
                    "Left Work Bank",
                    RadioSettingValueList(
                        BANK_CHOICES,
                        current_index=_hyperSettings.left_work_bank)))
            hyperGroup.append(
                RadioSetting(
                    "right_work_bank",
                    "Right Work Bank",
                    RadioSettingValueList(
                        BANK_CHOICES,
                        current_index=_hyperSettings.right_work_bank)))
            hyperGroup.append(
                RadioSetting(
                    "left_bank_mode",
                    "Left Bank Mode",
                    RadioSettingValueList(
                        HYPER_BANK_MODES,
                        current_index=_hyperSettings.left_bank_mode)))
            hyperGroup.append(
                RadioSetting(
                    "right_bank_mode",
                    "Right Bank Mode",
                    RadioSettingValueList(
                        HYPER_BANK_MODES,
                        current_index=_hyperSettings.right_bank_mode)))
            hyperGroup.append(
                RadioSetting(
                    "left_bank_sw",
                    "Left Bank Switch",
                    RadioSettingValueBoolean(_hyperSettings.left_bank_sw)))
            hyperGroup.append(
                RadioSetting(
                    "right_bank_sw",
                    "Right Bank Switch",
                    RadioSettingValueBoolean(_hyperSettings.right_bank_sw)))
            for bank in BANK_CHOICES[0:-1]:
                hyperGroup.append(
                    RadioSetting(
                        "link_bank_%s" % bank,
                        "Bank %s" % bank,
                        RadioSettingValueBoolean(
                            getattr(_hyperSettings, "link_bank_%s" % bank))))
            allGroups.append(hyperGroup)

        notes = RadioSettingGroup("notes", "Comm Notes")
        for idx in range(0, 100):
            notes.append(
                RadioSetting(
                    "note_call_ids.%d" % idx,
                    "Call ID %d (5 digits)" % idx,
                    RadioSettingValueString(
                        0,
                        5,
                        _filter(self._memobj.note_call_ids[idx].call_id,
                                string.digits)[idx*8:idx*8+5],
                        False,
                        string.digits)))
            notes.append(
                RadioSetting(
                    "note_names.%d" % idx,
                    "Name %d (7 ALPHAnumeric)" % idx,
                    RadioSettingValueString(
                        0,
                        7,
                        _filter(self._memobj.note_names[idx].name,
                                chirp_common.CHARSET_UPPER_NUMERIC)
                        [idx*8:idx*8+7],
                        True,
                        chirp_common.CHARSET_UPPER_NUMERIC)))
        allGroups.append(notes)

        _emergency = self._memobj.emergency
        emer = RadioSettingGroup("emergency", "Emergency Info")
        emer.append(
            RadioSetting(
                "mode",
                "Alarm Mode",
                RadioSettingValueList(
                    EMER_MODES,
                    current_index=_emergency.mode)))
        emer.append(
            RadioSetting(
                "eni_type",
                "ENI Type",
                RadioSettingValueList(
                    EMER_ENI_TYPES,
                    current_index=_emergency.eni_type)))
        emer.append(
            RadioSetting(
                "emergency.id",
                "DTMF ID",
                RadioSettingValueList(
                    DTMF_SLOTS,
                    DTMF_SLOTS[_emergency.id]
                    if EMER_ENI_TYPES[_emergency.eni_type] == 'DTMF'
                    else DTMF_SLOTS[0])))
        emer.append(
            RadioSetting(
                "5ToneId",
                "5Tone ID",
                RadioSettingValueInteger(
                    0,
                    99,
                    _emergency.id
                    if EMER_ENI_TYPES[_emergency.eni_type] == '5Tone'
                    else 0)))
        emer.append(
            RadioSetting(
                "alarm_time",
                "Alarm Time (sec)",
                RadioSettingValueInteger(1, 255, _emergency.alarm_time)))
        emer.append(
            RadioSetting(
                "tx_time",
                "TX Duration (sec)",
                RadioSettingValueInteger(1 if _emergency.tx_time > 0 else 0,
                                         255,
                                         _emergency.tx_time)))
        emer.append(
            RadioSetting(
                "rx_time",
                "RX Duration (sec)",
                RadioSettingValueInteger(1 if _emergency.rx_time > 0 else 0,
                                         255,
                                         _emergency.rx_time)))
        emer.append(
            RadioSetting(
                "chan_select",
                "ENI Channel",
                RadioSettingValueList(
                    EMER_CHAN_SEL,
                    current_index=_emergency.chan_select)))
        emer.append(
            RadioSetting(
                "channel",
                "Assigned Channel",
                _RadioSettingValueOffsetInt(
                    1,
                    750,
                    _emergency.channel + 1,
                    1,
                    -1)))
        emer.append(
            RadioSetting(
                "cycle",
                "Cycle",
                RadioSettingValueList(
                    EMER_CYCLES,
                    current_index=_emergency.cycle)))
        allGroups.append(emer)

        dtmfGroup = RadioSettingGroup("dtmf", "DTMF")
        for idx in range(0, 16):
            dtmfGroup.append(
                RadioSetting(
                    "dtmf_encodings.%d" % idx,
                    "Encode Tone %s" % DTMF_SLOTS[idx],
                    RadioSettingValueString(
                        0,
                        12,
                        _dtmf_decode(
                            self._memobj.dtmf_encodings[idx].dtmf,
                            self._memobj.dtmf_encodings[idx].num_tones),
                        False,
                        DTMF_CHARS)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_preload_time",
                "Encode Preload Time",
                RadioSettingValueList(
                    DTMF_PRELOADS,
                    current_index=_settings.dtmf_preload_time)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_speed",
                "Speed",
                RadioSettingValueList(
                    DTMF_SPEEDS,
                    current_index=_settings.dtmf_speed)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_interval_char",
                "Interval Character",
                RadioSettingValueList(
                    list(DTMF_INTCHARS),
                    DTMF_CHARS[_settings.dtmf_interval_char])))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_group_code",
                "Group Code",
                RadioSettingValueList(
                    DTMF_GROUPS,
                    DTMF_GROUPS[_settings.dtmf_group_code-0x0a]
                    if _settings.dtmf_group_code < 0xff
                    else DTMF_GROUPS[6])))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_dec_resp",
                "Decode Response",
                RadioSettingValueList(
                    DTMF_RESPONSES,
                    current_index=_settings.dtmf_dec_resp)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_first_dig_time",
                "1st Digit Time (ms)",
                RadioSettingValueInteger(
                    0,
                    2500,
                    _settings.dtmf_first_dig_time * 10,
                    10)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_auto_rst_time",
                "Auto Reset Time (0-25 sec by 0.1)",
                RadioSettingValueFloat(
                    0,
                    25,
                    _settings.dtmf_auto_rst_time / 10,
                    0.1,
                    1)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_self_id",
                "Self ID",
                RadioSettingValueString(
                    3,
                    3,
                    (DTMF_CHARS[_settings.dtmf_self_id[0] & 0x0F] +
                     DTMF_CHARS[_settings.dtmf_self_id[1] & 0x0F] +
                     DTMF_CHARS[_settings.dtmf_self_id[2] & 0x0F]),
                    True,
                    DTMF_CHARS)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_sidetone_on",
                "Use Side Tone",
                RadioSettingValueBoolean(_settings.dtmf_sidetone_on)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_enc_delay",
                "Encode Delay (ms)",
                RadioSettingValueInteger(
                    10,
                    2500,
                    _settings.dtmf_enc_delay * 10,
                    10)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_pttid_delay",
                "PTT ID Delay",
                RadioSettingValueList(
                    DTMF_PTTDELAYS,
                    DTMF_PTTDELAYS[_settings.dtmf_pttid_delay-4]
                    if _settings.dtmf_pttid_delay >= 5
                    else DTMF_PTTDELAYS[0])))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_kill",
                "Remote Kill",
                RadioSettingValueString(
                    0,
                    7,
                    _dtmf_decode(_settings.dtmf_kill.dtmf,
                                 _settings.dtmf_kill.num_tones),
                    False,
                    DTMF_CHARS)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_stun",
                "Remote Stun",
                RadioSettingValueString(
                    0,
                    7,
                    _dtmf_decode(_settings.dtmf_stun.dtmf,
                                 _settings.dtmf_stun.num_tones),
                    False,
                    DTMF_CHARS)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_pttid_bot",
                "PTT ID Start (BOT)",
                RadioSettingValueString(
                    0,
                    12,
                    _dtmf_decode(self._memobj.dtmf_pttid_bot.dtmf,
                                 self._memobj.dtmf_pttid_bot.num_tones),
                    False,
                    DTMF_CHARS)))
        dtmfGroup.append(
            RadioSetting(
                "dtmf_pttid_eot",
                "PTT ID Start (EOT)",
                RadioSettingValueString(
                    0,
                    12,
                    _dtmf_decode(self._memobj.dtmf_pttid_eot.dtmf,
                                 self._memobj.dtmf_pttid_eot.num_tones),
                    False,
                    DTMF_CHARS)))
        allGroups.append(dtmfGroup)

        # TODO: 2-Tone settings
        # TODO: 5-Tone settings

        return allGroups

    def _set_hyper_settings(self, settings, _hyperSettings):
        for element in settings:
            name = element.get_name()
            if not isinstance(element, RadioSetting):
                self._set_hyper_settings(element, _hyperSettings)
                continue
            elif isinstance(element.value, _RadioSettingValueOffsetInt):
                setattr(_hyperSettings,
                        name,
                        int(element.value) + element.value.offset)
            else:
                setattr(_hyperSettings, name, element.value)

    def _set_pwd_settings(self, settings):
        _settings = self._memobj.settings
        use_pw = pwd = None
        for element in settings:
            name = element.get_name()
            if not isinstance(element, RadioSetting):
                self._set_pwd_settings(element)
                continue
            elif name == "boot_pw_on":
                use_pw = bool(element.value)
            elif name == "boot_password":
                pwd = _filter(str(element.value), string.digits)
        if (pwd is not None and (len(pwd) or use_pw is False)):
            setattr(_settings, "boot_pw_on", use_pw and 1 or 0)
            pwd = pwd + "\x00"*(7-len(pwd))
            setattr(_settings, "boot_password", pwd)
        elif (use_pw is not None and use_pw is True):
            raise errors.InvalidValueError("Password may not be enabled "
                                           "without being set.")

    def _set_notes_settings(self, settings):
        _noteCalls = self._memobj.note_call_ids
        _noteNames = self._memobj.note_names
        for element in settings:
            name = str(element.get_name())
            if not isinstance(element, RadioSetting):
                self._set_notes_settings(element)
                continue
            elif name.startswith("note_call_ids."):
                idx = int(name[len("note_call_ids."):])
                setattr(self._memobj.note_call_ids[idx],
                        "call_id",
                        str(element.value).ljust(5, "\x00"))
            elif name.startswith("note_names."):
                idx = int(name[len("note_names."):])
                setattr(self._memobj.note_names[idx],
                        "name",
                        str(element.value).ljust(7))

    def _set_emer_settings(self, settings):
        _emergency = self._memobj.emergency
        dtmf_id = fivetone_id = None
        for element in settings:
            name = str(element.get_name())
            if not isinstance(element, RadioSetting):
                self._set_emer_settings(element)
                continue
            elif name == "emergency.id":
                dtmf_id = element.value
            elif name == "5ToneId":
                fivetone_id = element.value
            elif name == "channel":
                zb_mem_num = int(element.value) + element.value.offset
                _mem, _flg = self._get_memobjs(zb_mem_num + 1)
                if _flg.unused:
                    raise errors.InvalidValueError("Assigned emergency ENI "
                                                   "channel is empty.")
                else:
                    setattr(_emergency, name, zb_mem_num)
            elif isinstance(element.value, _RadioSettingValueOffsetInt):
                setattr(_emergency,
                        name,
                        int(element.value) + element.value.offset)
            else:
                setattr(_emergency, name, element.value)
        if EMER_ENI_TYPES[_emergency.eni_type] == 'DTMF':
            setattr(_emergency, "id", dtmf_id)
        elif EMER_ENI_TYPES[_emergency.eni_type] == '5Tone':
            setattr(_emergency, "id", fivetone_id)

    def _set_dtmf_settings(self, settings):
        def _setDtmf(dtmfStruct, newVal):
            dtmfStruct.num_tones.set_value(len(newVal))
            dtmfStruct.dtmf.set_value(_dtmf_encode(newVal,
                                                   len(dtmfStruct.dtmf)))

        for element in settings:
            name = str(element.get_name())
            if not isinstance(element, RadioSetting):
                self._set_dtmf_settings(element)
                continue
            if name.startswith("dtmf_encodings."):
                idx = int(name[len("dtmf_encodings."):])
                _setDtmf(self._memobj.dtmf_encodings[idx], str(element.value))
            elif name == "dtmf_interval_char":
                setattr(self._memobj.settings.dtmf_interval_char,
                        name,
                        DTMF_CHARS.index(str(element.value)))
            elif name == "dtmf_group_code":
                setattr(self._memobj.settings,
                        name,
                        int(element.value)+0x0a
                        if int(element.value) != 6
                        else 0xff)
            elif name == "dtmf_first_dig_time" or name == "dtmf_enc_delay":
                setattr(self._memobj.settings, name, int(element.value) / 10)
            elif name == "dtmf_auto_rst_time":
                setattr(self._memobj.settings, name, int(element.value) * 10)
            elif name == "dtmf_self_id":
                newStr = str(element.value)
                newVal = []
                for charIdx in range(0, 3):
                    newVal.append(DTMF_CHARS.index(newStr[charIdx]))
                setattr(self._memobj.settings, name, newVal)
            elif name == "dtmf_pttid_delay":
                setattr(self._memobj.settings,
                        name,
                        DTMF_PTTDELAYS.index(str(element.value))+4
                        if element.value != DTMF_PTTDELAYS[0]
                        else 0)
            elif name == "dtmf_kill" or name == "dtmf_stun":
                _setDtmf(getattr(self._memobj.settings, name),
                         str(element.value))
            elif name == "dtmf_pttid_bot" or name == "dtmf_pttid_eot":
                _setDtmf(getattr(self._memobj, name), str(element.value))
            else:
                setattr(self._memobj.settings, name, element.value)

    def set_settings(self, settings):
        _root = self._memobj
        _settings = self._memobj.settings
        for element in settings:
            name = element.get_name()
            if isinstance(element, RadioSettingGroup):
                if name == "hyper1":
                    self._set_hyper_settings(
                        element,
                        _settings.hyper_settings[0])
                    continue
                elif name == "hyper2":
                    self._set_hyper_settings(
                        element,
                        _settings.hyper_settings[1])
                    continue
                elif name == "pwdGroup":
                    self._set_pwd_settings(element)
                    continue
                elif name == "notes":
                    self._set_notes_settings(element)
                    continue
                elif name == "emergency":
                    self._set_emer_settings(element)
                    continue
                elif name == "dtmf":
                    self._set_dtmf_settings(element)
                    continue
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if name == "ignore":
                LOG.debug("*** ignore: %s" % str(element.value))
            elif name == "welcome":
                setattr(_root, "welcome", element.value)
            elif name == "long_key_time":
                setattr(_settings, name, 100 + 50 * int(element.value))
            elif isinstance(element.value, _RadioSettingValueOffsetInt):
                setattr(_settings, name, (int(element.value) +
                                          element.value.offset))
            else:
                setattr(_settings, name, element.value)

    @classmethod
    def match_model(cls, filedata, filename):
        return cls._file_ident in filedata[0x40:0x4D]
