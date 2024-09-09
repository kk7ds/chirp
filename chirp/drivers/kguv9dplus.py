# Copyright 2022 Mel Terechenok <melvin.terechenok@gmail.com>
# Updated Driver to support Wouxun KG-UV9PX
# based on prior driver for KG-UV9D Plus by
# Jim Lieb <lieb@sea-troll.net>
#
# Borrowed from other chirp drivers, especially the KG-UV8D Plus
# by Krystian Struzik <toner_82@tlen.pl>
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

"""Wouxun KG-UV9D Plus radio management module"""

import time
import logging
import struct
from chirp import chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
     RadioSettingValueBoolean, \
     RadioSettingValueList, RadioSettingValueInteger, \
     RadioSettingValueString, RadioSettings, \
     InvalidValueError

LOG = logging.getLogger(__name__)

CMD_IDENT = 0x80
CMD_HANGUP = 0x81
CMD_RCONF = 0x82
CMD_WCONF = 0x83
CMD_RCHAN = 0x84
CMD_WCHAN = 0x85

cmd_name = {
    CMD_IDENT:  "ident",
    CMD_HANGUP: "hangup",
    CMD_RCONF:  "read config",
    CMD_WCONF:  "write config",
    CMD_RCHAN:  "read channel memory",  # Unused
    CMD_WCHAN:  "write channel memory"  # Unused because it is a hack.
    }

# This is used to write the configuration of the radio base on info
# gleaned from the downloaded app. There are empty spaces and we honor
# them because we don't know what they are (yet) although we read the
# whole of memory.
#
# Channel memory is separate. There are 1000 (1-999) channels.
# These are read/written to the radio in 4 channel (96 byte)
# records starting at address 0xa00 and ending at
# 0x4800 (presuming the end of channel 1000 is 0x4860-1

config_map = (          # map address, write size, write count
    (0x40,   16, 1),    # Passwords
    (0x60,   20, 1),    # RX frequency limits
    (0x74,    8, 1),    # TX frequency limits
    (0x740,  40, 1),    # FM chan 1-20
    (0x780,  16, 1),    # vfo-b-150
    (0x790,  16, 1),    # vfo-b-450
    (0x800,  16, 1),    # vfo-a-150
    (0x810,  16, 1),    # vfo-a-450
    (0x820,  16, 1),    # vfo-a-300
    (0x830,  16, 1),    # vfo-a-700
    (0x840,  16, 1),    # vfo-a-200
    (0x860,  16, 1),    # area-a-conf
    (0x870,  16, 1),    # area-b-conf
    (0x880,  16, 1),    # radio conf 0
    (0x890,  16, 1),    # radio conf 1
    (0x8a0,  16, 1),    # radio conf 2
    (0x8b0,  16, 1),    # radio conf 3
    (0x8c0,  16, 1),    # PTT-ANI
    (0x8d0,  16, 1),    # SCC
    (0x8e0,  16, 1),    # power save
    (0x8f0,  16, 1),    # Display banner
    (0x940,  64, 2),    # Scan groups and names
    (0xa00,  64, 249),  # Memory Channels 1-996
    (0x4840, 48, 1),    # Memory Channels 997-999
    (0x4900, 32, 249),  # Memory Names    1-996
    (0x6820, 24, 1),    # Memory Names    997-999
    (0x7000, 8, 124),   # Valid Channel bytes 1-992
    (0x73E0, 1, 7),     # Valid Channel Bytes 993-999
    (0x7400, 64, 5),    # CALL-ID 1-20, names 1-20
    )

config_map2 = (          # map address, write size, write count
    (0x40,   16, 1),    # Passwords
    (0x50,   10, 1),    # OEM Display Name
    (0x60,   20, 1),    # Rx Freq Limits Area A
    (0x74,   8,  1),    # TX Frequency Limits 150M and 450M
    (0x7c,   4,  1),    # Rx 150M Freq Limits Area B
    #   (0x80,   8,  1),    # unknown Freq limits
    (0x740,  40, 1),    # FM chan 1-20
    (0x780,  16, 1),    # vfo-b-150
    (0x790,  16, 1),    # vfo-b-450
    (0x800,  16, 1),    # vfo-a-150
    (0x810,  16, 1),    # vfo-a-450
    (0x820,  16, 1),    # vfo-a-300
    (0x830,  16, 1),    # vfo-a-700
    (0x840,  16, 1),    # vfo-a-200
    (0x860,  16, 1),    # area-a-conf
    (0x870,  16, 1),    # area-b-conf
    (0x880,  16, 1),    # radio conf 0
    (0x890,  16, 1),    # radio conf 1
    (0x8a0,  16, 1),    # radio conf 2
    (0x8b0,  16, 1),    # radio conf 3
    (0x8c0,  16, 1),    # PTT-ANI
    (0x8d0,  16, 1),    # SCC
    (0x8e0,  16, 1),    # power save
    (0x8f0,  16, 1),    # Display banner
    (0x940,  64, 2),    # Scan groups and names
    (0xa00,  64, 249),  # Memory Channels 1-996
    (0x4840, 48, 1),    # Memory Channels 997-999
    (0x4900, 32, 249),  # Memory Names    1-996
    (0x6820, 24, 1),    # Memory Names    997-999
    (0x7000, 8, 124),   # Valid Channel bytes 1-992
    (0x73E0, 1, 7),     # Valid Channel Bytes 993-999
    (0x7400, 64, 5),    # CALL-ID 1-20, names 1-20
    (0x7600,  1, 1)     # Screen Mode
    )

MEM_VALID = 0xfc
MEM_INVALID = 0xff
VALID_MEM_VALUES = [MEM_VALID, 0x00, 0x02, 0x40, 0x3D]
INVALID_MEM_VALUES = [MEM_INVALID]
# new CHAN_VALID/INVALID mem values to address some radios not showing
# new channels
CHAN_VALID = 0x41
CHAN_INVALID = 0xFC
# Radio memory map. This matches the reads/writes above.
# structure elements whose name starts with x are currently unidentified

_MEM_FORMAT02 = """
#seekto 0x40;

struct {
    char reset[6];
    char x46[2];
    char mode_sw[6];
    char x4e;
}  passwords;

#seekto 0x60;

struct freq_limit {
    u16 start;
    u16 stop;
};

struct {
    struct freq_limit band_150;
    struct freq_limit band_450;
    struct freq_limit band_300;
    struct freq_limit band_700;
    struct freq_limit band_200;
} rx_freq_limits;

struct {
    struct freq_limit band_150;
    struct freq_limit band_450;
} tx_freq_limits;

#seekto 0x740;

struct {
    u16 fm_freq;
} fm_chans[20];

// each band has its own configuration, essentially its default params

struct vfo {
    u32 freq;
    u32 offset;
    u16 encqt;
    u16 decqt;
    u8  bit7_4:3,
        qt:3,
        bit1_0:2;
    u8  bit7:1,
        scan:1,
        bit5:1,
        pwr:2,
        mod:1,
        fm_dev:2;
    u8  pad2:6,
        shift:2;
    u8  zeros;
};

#seekto 0x780;

struct {
    struct vfo band_150;
    struct vfo band_450;
} vfo_b;

#seekto 0x800;

struct {
    struct vfo band_150;
    struct vfo band_450;
    struct vfo band_300;
    struct vfo band_700;
    struct vfo band_200;
} vfo_a;

// There are two independent radios, aka areas (as described
// in the manual as the upper and lower portions of the display...

struct area_conf {
    u8 w_mode;
    u16 w_chan;
    u8 scan_grp;
    u8 bcl;
    u8 sql;
    u8 cset;
    u8 step;
    u8 scan_mode;
    u8 x869;
    u8 scan_range;
    u8 x86b;
    u8 x86c;
    u8 x86d;
    u8 x86e;
    u8 x86f;
};

#seekto 0x860;

struct area_conf a_conf;

#seekto 0x870;

struct area_conf b_conf;

#seekto 0x880;

struct {
    u8 menu_avail;
    u8 reset_avail;
    u8 x882;
    u8 x883;
    u8 lang;
    u8 x885;
    u8 beep;
    u8 auto_am;
    u8 qt_sw;
    u8 lock;
    u8 x88a;
    u8 pf1;
    u8 pf2;
    u8 pf3;
    u8 s_mute;
    u8 type_set;
    u8 tot;
    u8 toa;
    u8 ptt_id;
    u8 x893;
    u8 id_dly;
    u8 x895;
    u8 voice_sw;
    u8 s_tone;
    u8 abr_lvl;
    u8 ring_time;
    u8 roger;
    u8 x89b;
    u8 abr;
    u8 save_m;
    u8 lock_m;
    u8 auto_lk;
    u8 rpt_ptt;
    u8 rpt_spk;
    u8 rpt_rct;
    u8 prich_sw;
    u16 pri_ch;
    u8 x8a6;
    u8 x8a7;
    u8 dtmf_st;
    u8 dtmf_tx;
    u8 x8aa;
    u8 sc_qt;
    u8 apo_tmr;
    u8 vox_grd;
    u8 vox_dly;
    u8 rpt_kpt;
    struct {
        u16 scan_st;
        u16 scan_end;
    } a;
    struct {
        u16 scan_st;
        u16 scan_end;
    } b;
    u8 x8b8;
    u8 x8b9;
    u8 x8ba;
    u8 ponmsg;
    u8 blcdsw;
    u8 bledsw;
    u8 x8be;
    u8 x8bf;
} settings;


#seekto 0x8c0;
struct {
    u8 code[6];
    char x8c6[10];
} my_callid;

#seekto 0x8d0;
struct {
    u8 scc[6];
    char x8d6[10];
} stun;

#seekto 0x8e0;
struct {
    u16 wake;
    u16 sleep;
} save[4];

#seekto 0x8f0;
struct {
    char banner[16];
} display;

#seekto 0x940;
struct {
    struct {
        i16 scan_st;
        i16 scan_end;
    } addrs[10];
    u8 x0968[8];
    struct {
        char name[8];
    } names[10];
} scn_grps;

// this array of structs is marshalled via the R/WCHAN commands
#seekto 0xa00;
struct {
    u32 rxfreq;
    u32 txfreq;
    u16 encQT;
    u16 decQT;
    u8  bit7_5:3,  // all ones
        qt:3,
        bit1_0:2;
    u8  bit7:1,
        scan:1,
        bit5:1,
        pwr:2,
        mod:1,
        fm_dev:2;
    u8  state;
    u8  c3;
} chan_blk[999];

// nobody really sees this. It is marshalled with chan_blk
// in 4 entry chunks
#seekto 0x4900;

// Tracks with the index of  chan_blk[]
struct {
    char name[8];
} chan_name[999];

#seekto 0x7000;
struct {
    u8 ch_valid;
} chan_valid[999];

#seekto 0x7400;
struct {
    u8 cid[6];
    u8 pad[2];
}call_ids[20];

// This array tracks with the index of call_ids[]
struct {
    char name[6];
    char pad[2];
} cid_names[20];
    """

_MEM_FORMAT_9PX = """
#seekto 0x40;

struct {
    char reset[6];
    char x46[2];
    char mode_sw[6];
    char x4e;
}  passwords;

#seekto 0x50;
struct {
    char model[10];
} oemmodel;

#seekto 0x60;
struct {
    u16 lim_150M_area_a_rxlower_limit; // 0x60
    u16 lim_150M_area_a_rxupper_limit;
    u16 lim_450M_rxlower_limit;
    u16 lim_450M_rxupper_limit;
    u16 lim_300M_rxlower_limit;
    u16 lim_300M_rxupper_limit;
    u16 lim_800M_rxlower_limit;
    u16 lim_800M_rxupper_limit;
    u16 lim_210M_rxlower_limit;
    u16 lim_210M_rxupper_limit;
    u16 lim_150M_Txlower_limit;
    u16 lim_150M_Txupper_limit;
    u16 lim_450M_Txlower_limit;
    u16 lim_450M_Txupper_limit;
    u16 lim_150M_area_b_rxlower_limit;
    u16 lim_150M_area_b_rxupper_limit;
    u16 unknown_lower_limit;
    u16 unknown_upper_limit;
    u16 unknown2_lower_limit;
    u16 unknown2_upper_limit;
}  limits;

#seekto 0x740;

struct {
    u16 fm_freq;
} fm_chans[20];

// each band has its own configuration, essentially its default params

struct vfo {
    u32 freq;
    u32 offset;
    u16 encqt;
    u16 decqt;
    u8  bit7_4:3,
        qt:3,
        bit1_0:2;
    u8  bit7:1,
        scan:1,
        bit5:1,
        pwr:2,
        mod:1,
        fm_dev:2;
    u8  pad2:6,
        shift:2;
    u8  zeros;
};

#seekto 0x780;

struct {
    struct vfo band_150;
    struct vfo band_450;
} vfo_b;

#seekto 0x800;

struct {
    struct vfo band_150;
    struct vfo band_450;
    struct vfo band_300;
    struct vfo band_700;
    struct vfo band_200;
} vfo_a;

// There are two independent radios, aka areas (as described
// in the manual as the upper and lower portions of the display...

struct area_conf {
    u8 w_mode;
    u16 w_chan; // fix issue in 9D Plus -  w_chan is 2bytes
    u8 scan_grp;
    u8 bcl;
    u8 sql;
    u8 cset;
    u8 step;
    u8 scan_mode;
    u8 x869;
    u8 scan_range;
    u8 x86b;
    u8 x86c;
    u8 x86d;
    u8 x86e;
    u8 x86f;
};

#seekto 0x860;

struct area_conf a_conf;

#seekto 0x870;

struct area_conf b_conf;

#seekto 0x880;

struct {
    u8 menu_avail;
    u8 reset_avail;
    u8 act_area;
    u8 tdr;
    u8 lang;
    u8 x885;
    u8 beep;
    u8 auto_am;
    u8 qt_sw;
    u8 lock;
    u8 x88a;
    u8 pf1;
    u8 pf2;
    u8 pf3;
    u8 s_mute;
    u8 type_set;
    u8 tot;
    u8 toa;
    u8 ptt_id;
    u8 x893;
    u8 id_dly;
    u8 x895;
    u8 voice_sw;
    u8 s_tone;
    u8 abr_lvl;
    u8 ring_time;
    u8 roger;
    u8 x89b;
    u8 abr;
    u8 save_m;
    u8 lock_m;
    u8 auto_lk;
    u8 rpt_ptt;
    u8 rpt_spk;
    u8 rpt_rct;
    u8 prich_sw;
    u16 pri_ch;
    u8 x8a6;
    u8 x8a7;
    u8 dtmf_st;
    u8 dtmf_tx;
    u8 x8aa;
    u8 sc_qt;
    u8 apo_tmr;
    u8 vox_grd;
    u8 vox_dly;
    u8 rpt_kpt;
    struct {
        u16 scan_st;
        u16 scan_end;
    } a;
    struct {
        u16 scan_st;
        u16 scan_end;
    } b;
    u8 x8b8;
    u8 x8b9;
    u8 x8ba;
    u8 ponmsg;
    u8 blcdsw;
    u8 bledsw;
    u8 x8be;
    u8 x8bf;

} settings;


#seekto 0x8c0;
struct {
    u8 code[6];
    char x8c6[10];
} my_callid;

#seekto 0x8d0;
struct {
    u8 scc[6];
    char x8d6[10];
} stun;

#seekto 0x8e0;
struct {
    u16 wake;
    u16 sleep;
} save[4];

#seekto 0x8f0;
struct {
    char banner[16];
} display;

#seekto 0x940;
struct {
    struct {
        i16 scan_st;
        i16 scan_end;
    } addrs[10];
    u8 x0968[8];
    struct {
        char name[8];
    } names[10];
} scn_grps;

// this array of structs is marshalled via the R/WCHAN commands
#seekto 0xa00;
struct {
    u32 rxfreq;
    u32 txfreq;
    u16 encQT;
    u16 decQT;
    u8  bit7_5:3,  // all ones
        qt:3,
        bit1_0:2;
    u8  bit7:1,
        scan:1,
        bit5:1,
        pwr:2,
        mod:1,
        fm_dev:2;
    u8  state;
    u8  c3;
} chan_blk[999];

// nobody really sees this. It is marshalled with chan_blk
// in 4 entry chunks
#seekto 0x4900;

// Tracks with the index of  chan_blk[]
struct {
    char name[8];
} chan_name[999];

#seekto 0x7400;
struct {
    u8 cid[6];
    u8 pad[2];
}call_ids[20];

// This array tracks with the index of call_ids[]
struct {
    char name[6];
    char pad[2];
} cid_names[20];

#seekto 0x7000;
struct {
    u8 ch_valid;
} chan_valid[999];

#seekto 0x7600;
struct {
    u8 screen_mode;
} screen;
"""


# Support for the Wouxun KG-UV9D Plus and KG-UV9PX radio
# Serial coms are at 19200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7d)
#    1      Command (6 commands, see above)
#    2      direction (\xff PC-> Radio, \x00 Radio -> PC)
#    3      length of payload (excluding header/checksum) (n)
#    4      payload (n bytes)
#    4+n+1  checksum - byte sum (% 256) of bytes 1 -> 4+n
#
# Memory Read Records:
# the payload is 3 bytes, first 2 are offset (big endian),
# 3rd is number of bytes to read
# Memory Write Records:
# the maximum payload size (from the Wouxun software)
# seems to be 66 bytes (2 bytes location + 64 bytes data).

def _pkt_encode(op, payload):
    """Assemble a packet for the radio and encode it for transmission.
    Yes indeed, the checksum we store is only 4 bits. Why?
    I suspect it's a bug in the radio firmware guys didn't want to fix,
    i.e. a typo 0xff -> 0xf..."""

    data = bytearray()
    data.append(0x7d)  # tag that marks the beginning of the packet
    data.append(op)
    data.append(0xff)  # 0xff is from app to radio
    # calc checksum from op to end
    cksum = op + 0xff
    if (payload):
        data.append(len(payload))
        cksum += len(payload)
        for byte in payload:
            cksum += byte
            data.append(byte)
    else:
        data.append(0x00)
        # Yea, this is a 4 bit cksum (also known as a bug)
    data.append(cksum & 0xf)

    # now obfuscate by an xor starting with first payload byte ^ 0x52
    # including the trailing cksum.
    xorbits = 0x52
    for i, byte in enumerate(data[4:]):
        xord = xorbits ^ byte
        data[i + 4] = xord
        xorbits = xord
    return (data)


def _pkt_decode(data):
    """Take a packet hot off the wire and decode it into clear text
    and return the fields. We say <<cleartext>> here because all it
    turns out to be is annoying obfuscation.
    This is the inverse of pkt_decode"""

    # we don't care about data[0].
    # It is always 0x7d and not included in checksum
    op = data[1]
    direction = data[2]
    bytecount = data[3]

    # First un-obfuscate the payload and cksum
    payload = bytearray()
    xorbits = 0x52
    for i, byte in enumerate(data[4:]):
        payload.append(xorbits ^ byte)
        xorbits = byte

    # Calculate the checksum starting with the 3 bytes of the header
    cksum = op + direction + bytecount
    for byte in payload[:-1]:
        cksum += byte
    # yes, a 4 bit cksum to match the encode
    cksum_match = (cksum & 0xf) == payload[-1]
    if (not cksum_match):
        LOG.debug(
            "Checksum mismatch: %x != %x; " % (cksum, payload[-1]))
    return (cksum_match, op, payload[:-1])

# UI callbacks to process input for mapping UI fields to memory cells


def freq2int(val, min, max):
    """Convert a frequency as a string to a u32. Units is Hz
    """
    _freq = chirp_common.parse_freq(str(val))
    if _freq > max or _freq < min:
        raise InvalidValueError("Frequency %s is not with in %s-%s" %
                                (chirp_common.format_freq(_freq),
                                 chirp_common.format_freq(min),
                                 chirp_common.format_freq(max)))
    return _freq


def int2freq(freq):
    """
    Convert a u32 frequency to a string for UI data entry/display
    This is stored in the radio as units of 10 Hz which we compensate to Hz.
    A value of -1 indicates <no frequency>, i.e. unused channel.
    """
    if (int(freq) > 0):
        f = chirp_common.format_freq(freq)
        return f
    else:
        return ""


def freq2short(val, min, max):
    """Convert a frequency as a string to a u16 which is units of 10 kHz
    """
    _freq = chirp_common.parse_freq(str(val))
    if _freq > max or _freq < min:
        raise InvalidValueError("Frequency %s is not with in %s-%s" %
                                (chirp_common.format_freq(_freq),
                                 chirp_common.format_freq(min),
                                 chirp_common.format_freq(max)))
    return _freq // 100000 & 0xFFFF


def short2freq(freq):
    """
       Convert a short frequency to a string for UI data entry/display
       This is stored in the radio as units of 10 kHz which we
       compensate to Hz.
       A value of -1 indicates <no frequency>, i.e. unused channel.
    """
    if (int(freq) > 0):
        f = chirp_common.format_freq(freq * 100000)
        return f
    else:
        return ""


def tone2short(t):
    """Convert a string tone or DCS to an encoded u16
    """
    tone = str(t)
    if tone == "----":
        u16tone = 0x0000
    elif tone[0] == 'D':  # This is a DCS code
        c = tone[1: -1]
        code = int(c, 8)
        if tone[-1] == 'I':
            code |= 0x4000
        u16tone = code | 0x8000
    else:              # This is an analog CTCSS
        u16tone = int(tone[0:-2]+tone[-1]) & 0xffff  # strip the '.'
    return u16tone


def short2tone(tone):
    """ Map a binary CTCSS/DCS to a string name for the tone
    """
    if tone == 0 or tone == 0xffff:
        ret = "----"
    else:
        code = tone & 0x3fff
        if tone & 0x8000:      # This is a DCS
            if tone & 0x4000:  # This is an inverse code
                ret = "D%0.3oI" % code
            else:
                ret = "D%0.3oN" % code
        else:   # Just plain old analog CTCSS
            ret = "%4.1f" % (code / 10.0)
    return ret


def str2callid(val):
    """ Convert caller id strings from callid2str.
    """
    ascii2bin = "0123456789"
    s = str(val).strip()
    if len(s) < 3 or len(s) > 6:
        raise InvalidValueError(
            "Caller ID must be at least 3 and no more than 6 digits")
    if s[0] == '0':
        raise InvalidValueError(
            "First digit of a Caller ID cannot be a zero '0'")
    blk = bytearray()
    for c in s:
        if c not in ascii2bin:
            raise InvalidValueError(
                "Caller ID must be all digits 0x%x" % c)
        b = (0xa, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9)[int(c)]
        blk.append(b)
    if len(blk) < 6:
        blk.append(0xc)  # EOL a short ID
    if len(blk) < 6:
        for i in range(0, (6 - len(blk))):
            blk.append(0xf0)
    return blk


def digits2str(digits, padding=' ', width=6):
    """Convert a password or SCC digit string to a string
    Passwords are expanded to and must be 6 chars. Fill them with '0'
    """

    bin2ascii = "0123456789"
    digitsstr = ""
    for i in range(0, 6):
        b = digits[i].get_value()
        if b == 0xc:  # the digits EOL
            break
        if b >= 0xa:
            raise InvalidValueError(
                "Value has illegal byte 0x%x" % ord(b))
        digitsstr += bin2ascii[b]
    digitsstr = digitsstr.ljust(width, padding)
    return digitsstr


def str2digits(val):
    """ Callback for edited strings from digits2str.
    """
    ascii2bin = " 0123456789"
    s = str(val).strip()
    if len(s) < 3 or len(s) > 6:
        raise InvalidValueError(
            "Value must be at least 3 and no more than 6 digits")
    blk = bytearray()
    for c in s:
        if c not in ascii2bin:
            raise InvalidValueError("Value must be all digits 0x%x" % c)
        blk.append(int(c))
    for i in range(len(blk), 6):
        blk.append(0xc)  # EOL a short ID
    return blk


def name2str(name):
    """ Convert a callid or scan group name to a string
    Deal with fixed field padding (\0 or \0xff)
    """

    namestr = ""
    for i in range(0, len(name)):
        b = ord(name[i].get_value())
        if b != 0 and b != 0xff:
            namestr += chr(b)
    return namestr


def str2name(val, size=6, fillchar='\0', emptyfill='\0'):
    """ Convert a string to a name. A name is a 6 element bytearray
    with ascii chars.
    """
    val = str(val).rstrip(' \t\r\n\0\xff')
    if len(val) == 0:
        name = "".ljust(size, emptyfill)
    else:
        name = val.ljust(size, fillchar)
    return name


def pw2str(pw):
    """Convert a password string (6 digits) to a string
    Passwords must be 6 digits. If it is shorter, pad right with '0'
    """
    pwstr = ""
    ascii2bin = "0123456789"
    for i in range(0, len(pw)):
        b = pw[i].get_value()
        if b not in ascii2bin:
            raise InvalidValueError("Value must be digits 0-9")
        pwstr += b
    pwstr = pwstr.ljust(6, '0')
    return pwstr


def str2pw(val):
    """Store a password from UI to memory obj
    If we clear the password (make it go away), change the
    empty string to '000000' since the radio must have *something*
    Also, fill a < 6 digit pw with 0's
    """
    ascii2bin = "0123456789"
    val = str(val).rstrip(' \t\r\n\0\0xff')
    if len(val) == 0:  # a null password
        val = "000000"
    for i in range(0, len(val)):
        b = val[i]
        if b not in ascii2bin:
            raise InvalidValueError("Value must be digits 0-9")
    if len(val) == 0:
        pw = "".ljust(6, '\0')
    else:
        pw = val.ljust(6, '0')
    return pw


# Helpers to replace python2 things like confused str/byte

def _hex_print(data, addrfmt=None):
    """Return a hexdump-like encoding of @data
    We expect data to be a bytearray, not a string.
    Expanded from borrowed code to use the first 2 bytes as the address
    per comm packet format.
    """
    if addrfmt is None:
        addrfmt = '%(addr)03i'
        addr = 0
    else:  # assume first 2 bytes are address
        a = struct.unpack(">H", data[0:2])
        addr = a[0]
        data = data[2:]

    block_size = 16

    lines = (len(data) // block_size)
    if (len(data) % block_size > 0):
        lines += 1

    out = ""
    left = len(data)
    for block in range(0, lines):
        addr += block * block_size
        try:
            out += addrfmt % locals()
        except (OverflowError, ValueError, TypeError, KeyError):
            out += "%03i" % addr
        out += ': '

        if left < block_size:
            limit = left
        else:
            limit = block_size

        for j in range(0, block_size):
            if (j < limit):
                out += "%02x " % data[(block * block_size) + j]
            else:
                out += "   "

        out += "  "

        for j in range(0, block_size):

            if (j < limit):
                _byte = data[(block * block_size) + j]
                if _byte >= 0x20 and _byte < 0x7F:
                    out += "%s" % chr(_byte)
                else:
                    out += "."
            else:
                out += " "
        out += "\n"
        if (left > block_size):
            left -= block_size

    return out


# Useful UI lists
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
STEPS_9K = [2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 25.0, 50.0, 100.0]
S_TONES = [str(x) for x in [1000, 1450, 1750, 2100]]
STEP_LIST = [str(x)+"kHz" for x in STEPS]
STEP_LIST_9K = [str(x)+"kHz" for x in STEPS_9K]
ROGER_LIST = ["Off", "Begin", "End", "Both"]
TIMEOUT_LIST = [str(x) + "s" for x in range(15, 601, 15)]
TOA_LIST = ["Off"] + ["%ds" % t for t in range(1, 11)]
BANDWIDTH_LIST = ["Wide", "Narrow"]
LANGUAGE_LIST = ["English", "Chinese"]
LANGUAGE_LIST2 = ["English", "Chinese-DISABLED"]
PF1KEY_LIST = ["OFF", "call id", "r-alarm", "SOS", "SF-TX"]
PF1KEY_LIST9GX = ["OFF", "call id", "r-alarm", "SOS", "SF-TX", "Scan",
                  "Second", "Lamp"]
PF2KEY_LIST = ["OFF", "Scan", "Second", "Lamp", "SDF-DIR", "K-lamp"]
PF2KEY_LIST9GX = ["OFF", "Scan", "Second", "Lamp", "K-lamp"]
PF3KEY_LIST2 = ["OFF", "Call ID", "R-ALARM", "SOS", "SF-TX", "Scan",
                "Second", "Lamp"]
PF3KEY_LIST9GX = ["OFF", "call id", "r-alarm", "SOS", "SF-TX", "Scan",
                  "Second", "Lamp"]
PF3KEY_LIST = ["OFF", "Call ID", "R-ALARM", "SOS", "SF-TX"]
WORKMODE_LIST = ["VFO freq", "Channel No.", "Ch. No.+Freq.",
                 "Ch. No.+Name"]
BACKLIGHT_LIST = ["Off"] + ["%sS" % t for t in range(1, 31)] + \
                 ["Always On"]
BACKLIGHT_BRIGHT_MIN = 1
BACKLIGHT_BRIGHT_MAX = 5
SAVE_MODES = ["Off", "1", "2", "3", "4"]
LOCK_MODES = ["key-lk", "key+pg", "key+ptt", "all"]
APO_TIMES = ["Off"] + ["%dm" % t for t in range(15, 151, 15)]
OFFSET_LIST = ["none", "+", "-"]
PONMSG_LIST = ["Battery Volts", "Bitmap"]
PONMSG_LIST2 = ["Battery Volts", "Bitmap-DISABLED"]
SPMUTE_LIST = ["QT", "QT*T", "QT&T"]
DTMFST_LIST = ["Off", "DT-ST", "ANI-ST", "DT-ANI"]
DTMF_TIMES = ["%d" % x for x in range(80, 501, 20)]
PTTID_LIST = ["Off", "Begin", "End", "Both"]
ID_DLY_LIST = ["%dms" % t for t in range(100, 3001, 100)]
VOX_GRDS = ["Off"] + ["%dlevel" % l for l in range(1, 11)]
VOX_DLYS = ["Off"] + ["%ds" % t for t in range(1, 5)]
RPT_KPTS = ["Off"] + ["%dms" % t for t in range(100, 5001, 100)]
ABR_LVL_MAP = [("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5)]
LIST_1_5 = ["%s" % x for x in range(1, 6)]
LIST_0_9 = ["%s" % x for x in range(0, 10)]
LIST_1_20 = ["%s" % x for x in range(1, 21)]
LIST_OFF_10 = ["Off"] + ["%s" % x for x in range(1, 11)]
SCANGRP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
SCANMODE_LIST = ["TO", "CO", "SE"]
SCANRANGE_LIST = ["Current band", "freq range", "ALL"]
SCQT_LIST = ["Decoder", "Encoder", "Both"]
S_MUTE_LIST = ["off", "rx mute", "tx mute", "r/t mute"]
POWER_LIST = ["Low", "Med", "High"]
RPTMODE_LIST = ["Radio/Talkie", "One direction Repeater",
                "Two direction repeater"]
TONE_LIST = ["----"] + ["%s" % str(t) for t in chirp_common.TONES] + \
            ["D%0.3dN" % dts for dts in chirp_common.DTCS_CODES] + \
            ["D%0.3dI" % dts for dts in chirp_common.DTCS_CODES]
SCREEN_MODE_LIST = ["Classic", "Covert", "Day_1", "Day_2"]
ACTIVE_AREA_LIST = ["Receiver A - Top", "Receiver B - Bottom"]
TDR_LIST = ["TDR ON", "TDR OFF"]


@directory.register
class KGUV9DPlusRadio(chirp_common.CloneModeRadio,
                      chirp_common.ExperimentalRadio):

    """Wouxun KG-UV9D Plus"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV9D Plus"
    _model = b"KG-UV9D"
    _rev = b"00"  # default rev for the radio I know about...
    _file_ident = b"kg-uv9d"
    BAUD_RATE = 19200
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=1),
                    chirp_common.PowerLevel("M", watts=2),
                    chirp_common.PowerLevel("H", watts=5)]
    _step_list = STEP_LIST
    _valid_steps = STEPS
    _mmap = ""

    def _read_record(self):
        """ Read and validate the header of a radio reply.
        A record is a formatted byte stream as follows:
            0x7D   All records start with this
            opcode This is in the set of legal commands.
                   The radio reply matches the request
            dir    This is the direction, 0xFF to the radio,
                   0x00 from the radio.
            cnt    Count of bytes in payload
                   (not including the trailing checksum byte)
            <cnt bytes>
            <checksum byte>
        """

        # first get the header and validate it
        data = bytearray(self.pipe.read(4))
        if (len(data) < 4):
            raise errors.RadioError('Radio did not respond')
        if (data[0] != 0x7D):
            raise errors.RadioError(
                'Radio reply garbled (%02x)' % data[0])
        if (data[1] not in cmd_name):
            raise errors.RadioError(
                "Unrecognized opcode (%02x)" % data[1])
        if (data[2] != 0x00):
            raise errors.RadioError(
                "Direction incorrect. Got (%02x)" % data[2])
        payload_len = data[3]
        # don't forget to read the checksum byte
        data.extend(self.pipe.read(payload_len + 1))
        if (len(data) != (payload_len + 5)):  # we got a short read
            raise errors.RadioError(
                "Radio reply wrong size. Wanted %d, got %d" %
                ((payload_len + 1), (len(data) - 4)))
        return _pkt_decode(data)

    def _write_record(self, cmd, payload=None):
        """ Write a request packet to the radio.
        """

        packet = _pkt_encode(cmd, payload)
        self.pipe.write(packet)

    @classmethod
    def match_model(cls, filedata, filename):
        """Look for bits in the file image and see if it looks
        like ours...
        TODO: there is a bunch of rubbish between 0x50 and 0x160
        that is still a known unknown
        """
        return cls._file_ident in filedata[0x51:0x59].lower()

    def _identify(self):
        """ Identify the radio
        The ident block identifies the radio and its capabilities.
        This block is always 78 bytes. The rev == '01' is the base
        radio and '02' seems to be the '-Plus' version.
        I don't really trust the content after the model and revision.
        One would assume this is pretty much constant data but I have
        seen differences between my radio and the dump named
        KG-UV9D-Plus-OutOfBox-Read.txt from bug #3509. The first
        five bands match the OEM windows
        app except the 350-400 band. The OOB trace has the 700 MHz
        band different. This is speculation at this point.

        TODO: This could be smarter and reject a radio not actually
        a UV9D...
        """

        for _i in range(0, 10):  # retry 10 times if we get junk
            self._write_record(CMD_IDENT)
            chksum_match, op, _resp = self._read_record()
            if len(_resp) == 0:
                raise Exception("Radio not responding")
            if len(_resp) != 74:
                LOG.error(
                    "Expected and IDENT reply of 78 bytes. Got (%d)" %
                    len(_resp))
                continue
            if not chksum_match:
                LOG.error("Checksum error: retrying ident...")
                time.sleep(0.100)
                continue
            if op != CMD_IDENT:
                LOG.error("Expected IDENT reply. Got (%02x)" % op)
                continue
            LOG.debug("Got:\n%s" % _hex_print(_resp))
            (mod, rev) = struct.unpack(">7s2s", _resp[0:9])
            LOG.debug("Model %s, rev %s" % (mod, rev))
            if mod == self._model:
                self._rev = rev
                return
            else:
                raise Exception("Unable to identify radio")
        raise Exception("All retries to identify failed")

    def process_mmap(self):
        if self._rev != b"02" and self._rev != b"00":
            # new revision found - log it and assume same map and proceed
            LOG.debug("Unrecognized model variation (%s) Using default Map" %
                      self._rev)
        self._memobj = bitwise.parse(_MEM_FORMAT02, self._mmap)

    def sync_in(self):
        """ Public sync_in
            Download contents of the radio. Throw errors back
            to the core if the radio does not respond.
            """
        try:
            self._identify()
            self._mmap = self._do_download()
            self._write_record(CMD_HANGUP)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        """ Public sync_out
            Upload the modified memory image into the radio.
            """

        try:
            self._identify()
            self._do_upload()
            self._write_record(CMD_HANGUP)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)
        return

    def _do_download(self):
        """ Read the whole of radio memory in 64 byte chunks.
        We load the config space followed by loading memory channels.
        The radio seems to be a "clone" type and the memory channels
        are actually within the config space. There are separate
        commands (CMD_RCHAN, CMD_WCHAN) for reading channel memory but
        these seem to be a hack that can only do 4 channels at a time.
        Since the radio only supports 999, (can only support 3 chars
        in the display UI?) although the vendors app reads 1000
        channels, it hacks back to config writes (CMD_WCONF) for the
        last 3 channels and names. We keep it simple and just read
        the whole thing even though the vendor app doesn't. Channels
        are separate in their app simply because the radio protocol
        has read/write commands to access it. What they do is simply
        marshal the frequency+mode bits in 4 channel chunks followed
        by a separate chunk of for names. In config space, they are two
        separate arrays 1..999. Given that this space is not a
        multiple of 4, there is hackery on upload to do the writes to
        config space. See upload for this.
        """

        mem = bytearray(0x8000)  # The radio's memory map is 32k
        for addr in range(0, 0x8000, 64):
            req = bytearray(struct.pack(">HB", addr, 64))
            self._write_record(CMD_RCONF, req)
            chksum_match, op, resp = self._read_record()
            if not chksum_match:
                LOG.debug(_hex_print(resp))
                raise Exception(
                    "Checksum error while reading configuration (0x%x)" %
                    addr)
            pa = struct.unpack(">H", resp[0:2])
            pkt_addr = pa[0]
            payload = resp[2:]
            if op != CMD_RCONF or addr != pkt_addr:
                raise Exception(
                    "Expected CMD_RCONF (%x) reply. Got (%02x: %x)" %
                    (addr, op, pkt_addr))
            LOG.debug("Config read (0x%x):\n%s" %
                      (addr, _hex_print(resp, '0x%(addr)04x')))
            # Orig Code from 9D Plus driver was len(Payload)-1:
            # This Caused every 64th byte to = 00
            for i in range(0, len(payload)):
                mem[addr + i] = payload[i]
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr
                status.max = 0x8000
                status.msg = "Cloning from radio"
                self.status_fn(status)
        return memmap.MemoryMapBytes(bytes(mem))

    def _do_upload(self):
        """Walk through the config map and write updated records to
        the radio. The config map contains only the regions we know
        about. We don't use the channel memory commands to avoid the
        hackery of using config write commands to fill in the last
        3 channel memory and names slots. As we discover other useful
        goodies in the map, we can add more slots...
        """
        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):
            cfgmap = config_map2
        else:
            cfgmap = config_map

        for start, blocksize, count in cfgmap:
            end = start + (blocksize * count)
            for addr in range(start, end, blocksize):
                req = bytearray(struct.pack(">H", addr))
                req.extend(self.get_mmap()[addr:addr + blocksize])
                self._write_record(CMD_WCONF, req)
                LOG.debug("Config write (0x%x):\n%s" %
                          (addr, _hex_print(req)))
                chksum_match, op, ack = self._read_record()
                LOG.debug("Config write ack [%x]\n%s" %
                          (addr, _hex_print(ack)))
                a = struct.unpack(">H", ack)  # big endian short...
                ack = a[0]
                if not chksum_match or op != CMD_WCONF or addr != ack:
                    msg = ""
                    if not chksum_match:
                        msg += "Checksum err, "
                    if op != CMD_WCONF:
                        msg += "cmd mismatch %x != %x, " % \
                               (op, CMD_WCONF)
                    if addr != ack:
                        msg += "ack error %x != %x, " % (addr, ack)
                    raise Exception("Radio did not ack block: %s error" % msg)
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = addr
                    status.max = 0x8000
                    status.msg = "Cloning to radio"
                    self.status_fn(status)

    def get_features(self):
        """ Public get_features
            Return the features of this radio once we have identified
            it and gotten its bits
            """
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_bands = [(108000000, 136000000),  # Aircraft  AM
                          (136000000, 180000000),  # supports 2m
                          (230000000, 250000000),
                          (350000000, 400000000),
                          (400000000, 520000000),  # supports 70cm
                          (700000000, 985000000)]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_tuning_steps = self._valid_steps
        rf.memory_bounds = (1, 999)  # 999 memories
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.chan_blk[number - 1])

    def _get_tone(self, _mem, mem):
        """Decode both the encode and decode CTSS/DCS codes from
        the memory channel and stuff them into the UI
        memory channel row.
        """
        txtone = short2tone(_mem.encQT)
        rxtone = short2tone(_mem.decQT)
        pt = "N"
        pr = "N"

        if txtone == "----":
            txmode = ""
        elif txtone[0] == "D":
            mem.dtcs = int(txtone[1:4])
            if txtone[4] == "I":
                pt = "R"
            txmode = "DTCS"
        else:
            mem.rtone = float(txtone)
            txmode = "Tone"

        if rxtone == "----":
            rxmode = ""
        elif rxtone[0] == "D":
            mem.rx_dtcs = int(rxtone[1:4])
            if rxtone[4] == "I":
                pr = "R"
            rxmode = "DTCS"
        else:
            mem.ctone = float(rxtone)
            rxmode = "Tone"

        if txmode == "Tone" and len(rxmode) == 0:
            mem.tmode = "Tone"
        elif (txmode == rxmode and txmode == "Tone" and
              mem.rtone == mem.ctone):
            mem.tmode = "TSQL"
        elif (txmode == rxmode and txmode == "DTCS" and
              mem.dtcs == mem.rx_dtcs):
            mem.tmode = "DTCS"
        elif (len(rxmode) + len(txmode)) > 0:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = pt + pr

        LOG.debug("_get_tone: Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.encQT, rxmode, _mem.decQT))

    def get_memory(self, number):
        """ Public get_memory
            Return the channel memory referenced by number to the UI.
        """
        _mem = self._memobj.chan_blk[number - 1]
        _nam = self._memobj.chan_name[number - 1]
        _val = self._memobj.chan_valid[number - 1]

        mem = chirp_common.Memory()
        mem.number = number
        _valid = _mem.state

        # This code attempts to robustly decipher what Wouxun considers valid
        # memory locations on the 9 series radios and the factory CPS.
        # It appears they use a combination of State and Rx Freq to determine
        # validity rather than just the State value.
        # It is possible the State value is not even used at all.
        # Rather than continuously adding new Mem Valid values as they are
        # found, assume any value other than 0xFF is likely valid and use
        # Rx Freq to further assess validity

        if _mem.rxfreq == 0xFFFFFFFF:
            # Rx freq indicates empty channel memory
            # assume empty regardless of _valid and proceed to next channel
            if _valid not in INVALID_MEM_VALUES:
                # only log if _valid indicates the channel is not invalid
                LOG.debug("CH %s Rx Freq = 0xFFFFFFFF - "
                          "Treating chan as empty", mem.number)
            mem.empty = True
            _val.ch_valid = CHAN_INVALID
            return mem
        elif _valid in INVALID_MEM_VALUES:
            # Check for 9PX case where CPS creates a valid channel with
            # 0xFF for State -  accept it as valid as long as Rx Freq is
            # <= max value
            if _mem.rxfreq > 99999999:  # Max poss Value = 999.99999 MHz
                LOG.debug("CH %s State invalid - Rx Frq > 999.99999 MHz: "
                          "Treating chan as empty", mem.number)
                mem.empty = True
                _val.ch_valid = CHAN_INVALID
                return mem
            else:
                LOG.debug("CH %s State invalid - Rx Freq valid: "
                          "Assume chan valid", mem.number)
                mem.empty = False
                _val.ch_valid = CHAN_VALID
        else:  # State not Invalid and Rx Freq not 0xFFFFFFFF
            if _mem.rxfreq > 99999999:  # Max poss Value = 999.99999 MHz
                LOG.debug("CH %s Invalid Rx Frq: %s MHz - "
                          "Treating chan as empty", mem.number,
                          int(_mem.rxfreq) / 100000)
                mem.empty = True
                _val.ch_valid = CHAN_INVALID
                return mem
            else:
                _val.ch_valid = CHAN_VALID
                mem.empty = False

        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
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

        mem.name = name2str(_nam.name)

        self._get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan) else "S"

        mem.power = self.POWER_LEVELS[_mem.pwr]
        if _mem.mod == 1:
            mem.mode = "AM"
        elif _mem.fm_dev == 0:
            mem.mode = "FM"
        else:
            mem.mode = "NFM"
        #  qt has no home in the UI
        return mem

    def _set_tone(self, mem, _mem):
        """Update the memory channel block CTCC/DCS tones
        from the UI fields
        """
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) | 0x8000
            if pol == "R":
                val |= 0x4000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0x0000

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            txtone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10)

        _mem.decQT = rxtone
        _mem.encQT = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.encQT, rx_mode, _mem.decQT))

    def set_memory(self, mem):
        """ Public set_memory
            Inverse of get_memory. Update the radio memory image
            from the mem object
            """
        number = mem.number

        _mem = self._memobj.chan_blk[number - 1]
        _nam = self._memobj.chan_name[number - 1]
        _val = self._memobj.chan_valid[number - 1]

        if mem.empty:
            # consider putting in a check for chan # that is empty but
            # listed as one of the 2 working channels and change them
            # to channel 1 to be consistent with CPS and allow
            # complete deletion from radio.  Otherwise,
            # a deleted channel will still show on radio with no name.
            # MRT implement the above working channel check
            if self._memobj.a_conf.w_chan == number:
                self._memobj.a_conf.w_chan = 1
            if self._memobj.b_conf.w_chan == number:
                self._memobj.b_conf.w_chan = 1

            _mem.set_raw("\xFF" * (_mem.size() // 8))
            _nam.name = str2name("", 8, '\0', '\0')
            _mem.state = MEM_INVALID
            _val.ch_valid = CHAN_INVALID
            return

        _mem.rxfreq = int(mem.freq / 10)
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = int(mem.offset / 10)
        elif mem.duplex == "+":
            _mem.txfreq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.txfreq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.txfreq = int(mem.freq / 10)
        _mem.scan = int(mem.skip != "S")
        if mem.mode == "FM":
            _mem.mod = 0    # make sure forced AM is off
            _mem.fm_dev = 0
        elif mem.mode == "NFM":
            _mem.mod = 0
            _mem.fm_dev = 1
        elif mem.mode == "AM":
            _mem.mod = 1     # AM on
            _mem.fm_dev = 1  # set NFM bandwidth
        else:
            _mem.mod = 0
            _mem.fm_dev = 0  # Catchall default is FM
        # set the tone
        self._set_tone(mem, _mem)
        # set the power
        if mem.power:
            _mem.pwr = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.pwr = True

        # Set fields we can't access via the UI table to safe defaults
        _mem.qt = 0   # mute mode to QT
        _mem.bit5 = 0   # clear this bit to ensure accurate CPS power level
        _nam.name = str2name(mem.name, 8, '\0', '\0')
        _mem.state = MEM_VALID
        _val.ch_valid = CHAN_VALID

# Build the UI configuration tabs
# the channel memory tab is built by the core.
# We have no control over it

    def _core_tab(self):
        """ Build Core Configuration tab
        Radio settings common to all modes and areas go here.
        """
        s = self._memobj.settings
        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):

            sm = self._memobj.screen

        cf = RadioSettingGroup("cfg_grp", "Configuration")

        cf.append(RadioSetting("auto_am",
                               "Auto detect AM (Menu 53)",
                               RadioSettingValueBoolean(s.auto_am)))
        cf.append(RadioSetting("qt_sw",
                               "Scan tone detect (Menu 59)",
                               RadioSettingValueBoolean(s.qt_sw)))
        cf.append(
            RadioSetting("s_mute",
                         "SubFreq Mute (Menu 60)",
                         RadioSettingValueList(S_MUTE_LIST,
                                               current_index=s.s_mute)))
        cf.append(
            RadioSetting("tot",
                         "Transmit timeout Timer (Menu 10)",
                         RadioSettingValueList(TIMEOUT_LIST,
                                               current_index=s.tot)))
        cf.append(
            RadioSetting("toa",
                         "Transmit Timeout Alarm (Menu 11)",
                         RadioSettingValueList(TOA_LIST,
                                               current_index=s.toa)))
        cf.append(
            RadioSetting("ptt_id",
                         "PTT Caller ID mode (Menu 23)",
                         RadioSettingValueList(PTTID_LIST,
                                               current_index=s.ptt_id)))
        cf.append(
            RadioSetting("id_dly",
                         "Caller ID Delay time (Menu 25)",
                         RadioSettingValueList(ID_DLY_LIST,
                                               current_index=s.id_dly)))
        cf.append(RadioSetting("voice_sw",
                               "Voice Guide (Menu 12)",
                               RadioSettingValueBoolean(s.voice_sw)))
        cf.append(RadioSetting("beep",
                               "Keypad Beep (Menu 13)",
                               RadioSettingValueBoolean(s.beep)))
        cf.append(
            RadioSetting("s_tone",
                         "Side Tone (Menu 36)",
                         RadioSettingValueList(S_TONES,
                                               current_index=s.s_tone)))
        cf.append(
            RadioSetting("ring_time",
                         "Ring Time (Menu 26)",
                         RadioSettingValueList(
                             LIST_OFF_10,
                             current_index=s.ring_time)))
        cf.append(
            RadioSetting("roger",
                         "Roger Beep (Menu 9)",
                         RadioSettingValueList(ROGER_LIST,
                                               current_index=s.roger)))
        cf.append(RadioSetting("blcdsw",
                               "Backlight (Menu 41)",
                               RadioSettingValueBoolean(s.blcdsw)))
        cf.append(
            RadioSetting("abr",
                         "Auto Backlight Time (Menu 1)",
                         RadioSettingValueList(BACKLIGHT_LIST,
                                               current_index=s.abr)))
        cf.append(
            RadioSetting("abr_lvl",
                         "Backlight Brightness (Menu 27)",
                         RadioSettingValueInteger(BACKLIGHT_BRIGHT_MIN,
                                                  BACKLIGHT_BRIGHT_MAX,
                                                  s.abr_lvl)))
        cf.append(RadioSetting("lock",
                               "Keypad Lock",
                               RadioSettingValueBoolean(s.lock)))
        cf.append(
            RadioSetting("lock_m",
                         "Keypad Lock Mode (Menu 35)",
                         RadioSettingValueList(LOCK_MODES,
                                               current_index=s.lock_m)))
        cf.append(RadioSetting("auto_lk",
                               "Keypad Autolock (Menu 34)",
                               RadioSettingValueBoolean(s.auto_lk)))
        cf.append(RadioSetting("prich_sw",
                               "Priority Channel Scan (Menu 33)",
                               RadioSettingValueBoolean(s.prich_sw)))
        cf.append(RadioSetting("pri_ch",
                               "Priority Channel (Menu 32)",
                               RadioSettingValueInteger(1, 999,
                                                        s.pri_ch)))
        cf.append(
            RadioSetting("dtmf_st",
                         "DTMF Sidetone (Menu 22)",
                         RadioSettingValueList(DTMFST_LIST,
                                               current_index=s.dtmf_st)))
        cf.append(RadioSetting("sc_qt",
                               "Scan QT Save Mode (Menu 38)",
                               RadioSettingValueList(
                                   SCQT_LIST,
                                   current_index=s.sc_qt)))
        cf.append(
            RadioSetting("apo_tmr",
                         "Automatic Power-off (Menu 39)",
                         RadioSettingValueList(APO_TIMES,
                                               current_index=s.apo_tmr)))
        cf.append(  # VOX "guard" is really VOX trigger audio level
            RadioSetting("vox_grd",
                         "VOX level (Menu 7)",
                         RadioSettingValueList(VOX_GRDS,
                                               current_index=s.vox_grd)))
        cf.append(
            RadioSetting("vox_dly",
                         "VOX Delay (Menu 37)",
                         RadioSettingValueList(VOX_DLYS,
                                               current_index=s.vox_dly)))
        cf.append(RadioSetting("bledsw",
                               "Receive LED (Menu 42)",
                               RadioSettingValueBoolean(s.bledsw)))

        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):
            cf.append(RadioSetting("screen.screen_mode",
                                   "Screen Mode (Menu 62)",
                                   RadioSettingValueList(
                                         SCREEN_MODE_LIST,
                                         current_index=sm.screen_mode)))
        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):
            langlst = LANGUAGE_LIST2
        else:
            langlst = LANGUAGE_LIST
        cf.append(
            RadioSetting("lang",
                         "Menu Language (Menu 14)",
                         RadioSettingValueList(langlst,
                                               current_index=s.lang)))

        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):
            ponmsglst = PONMSG_LIST2
        else:
            ponmsglst = PONMSG_LIST
        cf.append(RadioSetting("ponmsg",
                               "Poweron message (Menu 40)",
                               RadioSettingValueList(
                                   ponmsglst, current_index=s.ponmsg)))
        return cf

    def _repeater_tab(self):
        """Repeater mode functions
        """
        s = self._memobj.settings
        cf = RadioSettingGroup("repeater", "Repeater Functions")

        cf.append(
            RadioSetting("type_set",
                         "Radio Mode (Menu 43)",
                         RadioSettingValueList(
                             RPTMODE_LIST,
                             current_index=s.type_set)))
        cf.append(RadioSetting("rpt_ptt",
                               "Repeater PTT (Menu 45)",
                               RadioSettingValueBoolean(s.rpt_ptt)))
        cf.append(RadioSetting("rpt_spk",
                               "Repeater Mode Speaker (Menu 44)",
                               RadioSettingValueBoolean(s.rpt_spk)))
        cf.append(
            RadioSetting("rpt_kpt",
                         "Repeater Hold Time (Menu 46)",
                         RadioSettingValueList(RPT_KPTS,
                                               current_index=s.rpt_kpt)))
        cf.append(RadioSetting("rpt_rct",
                               "Repeater Receipt Tone (Menu 47)",
                               RadioSettingValueBoolean(s.rpt_rct)))
        return cf

    def _admin_tab(self):
        """Admin functions not present in radio menu...
        These are admin functions not radio operation configuration
        """

        def apply_cid(setting, obj):
            c = str2callid(setting.value)
            obj.code = c

        def apply_scc(setting, obj):
            c = str2digits(setting.value)
            obj.scc = c

        def apply_mode_sw(setting, obj):
            pw = str2pw(setting.value)
            obj.mode_sw = pw
            setting.value = pw2str(obj.mode_sw)

        def apply_reset(setting, obj):
            pw = str2pw(setting.value)
            obj.reset = pw
            setting.value = pw2str(obj.reset)

        def apply_wake(setting, obj):
            obj.wake = int(setting.value)/10

        def apply_sleep(setting, obj):
            obj.sleep = int(setting.value)/10

        pw = self._memobj.passwords  # admin passwords
        s = self._memobj.settings

        cf = RadioSettingGroup("admin", "Admin Functions")

        cf.append(RadioSetting("menu_avail",
                               "Menu available in channel mode",
                               RadioSettingValueBoolean(s.menu_avail)))
        mode_sw = RadioSettingValueString(0, 6,
                                          pw2str(pw.mode_sw), False)
        rs = RadioSetting("passwords.mode_sw",
                          "Mode Switch Password", mode_sw)
        rs.set_apply_callback(apply_mode_sw, pw)
        cf.append(rs)

        cf.append(RadioSetting("reset_avail",
                               "Radio Reset Available",
                               RadioSettingValueBoolean(s.reset_avail)))
        reset = RadioSettingValueString(0, 6, pw2str(pw.reset), False)
        rs = RadioSetting("passwords.reset",
                          "Radio Reset Password", reset)
        rs.set_apply_callback(apply_reset, pw)
        cf.append(rs)

        cf.append(
            RadioSetting("dtmf_tx",
                         "DTMF Tx Duration",
                         RadioSettingValueList(DTMF_TIMES,
                                               current_index=s.dtmf_tx)))
        cid = self._memobj.my_callid
        my_callid = RadioSettingValueString(3, 6,
                                            self.callid2str(cid.code), False)
        rs = RadioSetting("my_callid.code",
                          "PTT Caller ID code (Menu 24)", my_callid)
        rs.set_apply_callback(apply_cid, cid)
        cf.append(rs)

        stun = self._memobj.stun
        st = RadioSettingValueString(0, 6, digits2str(stun.scc), False)
        rs = RadioSetting("stun.scc", "Security code", st)
        rs.set_apply_callback(apply_scc, stun)
        cf.append(rs)

        cf.append(
            RadioSetting("settings.save_m",
                         "Save Mode  (Menu 2)",
                         RadioSettingValueList(SAVE_MODES,
                                               current_index=s.save_m)))
        for i in range(0, 4):
            sm = self._memobj.save[i]
            wake = RadioSettingValueInteger(0, 18000, sm.wake * 10, 1)
            wf = RadioSetting("save[%i].wake" % i,
                              "Save Mode %d Wake Time" % (i+1), wake)
            wf.set_apply_callback(apply_wake, sm)
            cf.append(wf)

            slp = RadioSettingValueInteger(0, 18000, sm.sleep * 10, 1)
            wf = RadioSetting("save[%i].sleep" % i,
                              "Save Mode %d Sleep Time" % (i+1), slp)
            wf.set_apply_callback(apply_sleep, sm)
            cf.append(wf)

        _msg = str(self._memobj.display.banner).split("\0")[0]
        val = RadioSettingValueString(0, 16, _msg)
        val.set_mutable(True)
        cf.append(RadioSetting("display.banner",
                               "Display Message", val))

        if (self.MODEL == "KG-UV9PX" or self.MODEL == "KG-UV9GX"):
            _str = str(self._memobj.oemmodel.model).split("\0")[0]
            val = RadioSettingValueString(0, 10, _str)
            val.set_mutable(True)
            cf.append(RadioSetting("oemmodel.model",
                                   "Custom Sub-Receiver Message", val))

            val = RadioSettingValueList(
                                TDR_LIST,
                                current_index=s.tdr)
            val.set_mutable(True)
            cf.append(RadioSetting("tdr", "TDR", val))

            val = RadioSettingValueList(
                                ACTIVE_AREA_LIST,
                                current_index=s.act_area)
            val.set_mutable(True)
            cf.append(RadioSetting("act_area", "Active Receiver(BAND)", val))

        return cf

    def _fm_tab(self):
        """FM Broadcast channels
        """
        def apply_fm(setting, obj):
            f = freq2short(setting.value, 76000000, 108000000)
            obj.fm_freq = f

        fm = RadioSettingGroup("fm_chans", "FM Broadcast")
        for ch in range(0, 20):
            chan = self._memobj.fm_chans[ch]
            freq = RadioSettingValueString(0, 20,
                                           short2freq(chan.fm_freq))
            rs = RadioSetting("fm_%d" % (ch + 1),
                              "FM Channel %d" % (ch + 1), freq)
            rs.set_apply_callback(apply_fm, chan)
            fm.append(rs)
        return fm

    def _scan_grp(self):
        """Scan groups
        """
        def apply_name(setting, obj):
            name = str2name(setting.value, 8, '\0', '\0')
            obj.name = name

        def apply_start(setting, obj):
            """Do a callback to deal with RadioSettingInteger limitation
            on memory address resolution
            """
            obj.scan_st = int(setting.value)

        def apply_end(setting, obj):
            """Do a callback to deal with RadioSettingInteger limitation
            on memory address resolution
            """
            obj.scan_end = int(setting.value)

        sgrp = self._memobj.scn_grps
        scan = RadioSettingGroup("scn_grps", "Channel Scanner Groups")
        for i in range(0, 10):
            s_grp = sgrp.addrs[i]
            s_name = sgrp.names[i]
            rs_name = RadioSettingValueString(0, 8,
                                              name2str(s_name.name))
            rs = RadioSetting("scn_grps.names[%i].name" % i,
                              "Group %i Name" % (i + 1), rs_name)
            rs.set_apply_callback(apply_name, s_name)
            scan.append(rs)
            rs_st = RadioSettingValueInteger(1, 999, s_grp.scan_st)
            rs = RadioSetting("scn_grps.addrs[%i].scan_st" % i,
                              "Starting Channel", rs_st)
            rs.set_apply_callback(apply_start, s_grp)
            scan.append(rs)
            rs_end = RadioSettingValueInteger(1, 999, s_grp.scan_end)
            rs = RadioSetting("scn_grps.addrs[%i].scan_end" % i,
                              "Last Channel", rs_end)
            rs.set_apply_callback(apply_end, s_grp)
            scan.append(rs)
        return scan

    def _callid_grp(self):
        """Caller IDs to be recognized by radio
        This really should be a table in the UI
        """
        def apply_callid(setting, obj):
            c = str2callid(setting.value)
            obj.cid = c

        def apply_name(setting, obj):
            name = str2name(setting.value, 6, '\0', '\xff')
            obj.name = name

        cid = RadioSettingGroup("callids", "Caller IDs")
        for i in range(0, 20):
            callid = self._memobj.call_ids[i]
            name = self._memobj.cid_names[i]
            c_name = RadioSettingValueString(0, 6, name2str(name.name))
            rs = RadioSetting("cid_names[%i].name" % i,
                              "Caller ID %i Name" % (i + 1), c_name)
            rs.set_apply_callback(apply_name, name)
            cid.append(rs)
            c_id = RadioSettingValueString(0, 6,
                                           self.callid2str(callid.cid),
                                           False)
            rs = RadioSetting("call_ids[%i].cid" % i,
                              "Caller ID Code", c_id)
            rs.set_apply_callback(apply_callid, callid)
            cid.append(rs)
        return cid

    def _band_tab(self, area, band):
        """ Build a band tab inside a VFO/Area
        """
        def apply_freq(setting, lo, hi, obj):
            f = freq2int(setting.value, lo, hi)
            obj.freq = f/10

        def apply_offset(setting, obj):
            f = freq2int(setting.value, 0, 5000000)
            obj.offset = f/10

        def apply_enc(setting, obj):
            t = tone2short(setting.value)
            obj.encqt = t

        def apply_dec(setting, obj):
            t = tone2short(setting.value)
            obj.decqt = t

        if area == "a":
            if band == 150:
                c = self._memobj.vfo_a.band_150
                lo = 108000000
                hi = 180000000
            elif band == 200:
                c = self._memobj.vfo_a.band_200
                lo = 230000000
                hi = 250000000
            elif band == 300:
                c = self._memobj.vfo_a.band_300
                lo = 350000000
                hi = 400000000
            elif band == 450:
                c = self._memobj.vfo_a.band_450
                lo = 400000000
                hi = 512000000
            else:   # 700
                c = self._memobj.vfo_a.band_700
                lo = 700000000
                hi = 985000000
        else:  # area 'b'
            if band == 150:
                c = self._memobj.vfo_b.band_150
                lo = 136000000
                hi = 180000000
            else:  # 450
                c = self._memobj.vfo_b.band_450
                lo = 400000000
                hi = 512000000

        prefix = "vfo_%s.band_%d" % (area, band)
        bf = RadioSettingGroup(prefix, "%d MHz Band" % band)
        freq = RadioSettingValueString(0, 15, int2freq(c.freq * 10))
        rs = RadioSetting(prefix + ".freq", "Rx Frequency", freq)
        rs.set_apply_callback(apply_freq, lo, hi, c)
        bf.append(rs)

        off = RadioSettingValueString(0, 15, int2freq(c.offset * 10))
        rs = RadioSetting(prefix + ".offset", "Tx Offset (Menu 28)", off)
        rs.set_apply_callback(apply_offset, c)
        bf.append(rs)

        rs = RadioSetting(prefix + ".encqt",
                          "Encode QT (Menu 17,19)",
                          RadioSettingValueList(TONE_LIST,
                                                short2tone(c.encqt)))
        rs.set_apply_callback(apply_enc, c)
        bf.append(rs)

        rs = RadioSetting(prefix + ".decqt",
                          "Decode QT (Menu 16,18)",
                          RadioSettingValueList(TONE_LIST,
                                                short2tone(c.decqt)))
        rs.set_apply_callback(apply_dec, c)
        bf.append(rs)

        bf.append(RadioSetting(prefix + ".qt",
                               "Mute Mode (Menu 21)",
                               RadioSettingValueList(SPMUTE_LIST,
                                                     current_index=c.qt)))
        bf.append(RadioSetting(prefix + ".scan",
                               "Scan this (Menu 48)",
                               RadioSettingValueBoolean(c.scan)))
        bf.append(RadioSetting(prefix + ".pwr",
                               "Power (Menu 5)",
                               RadioSettingValueList(
                                   POWER_LIST, current_index=c.pwr)))
        bf.append(RadioSetting(prefix + ".mod",
                               "AM Modulation (Menu 54)",
                               RadioSettingValueBoolean(c.mod)))
        bf.append(RadioSetting(prefix + ".fm_dev",
                               "FM Deviation (Menu 4)",
                               RadioSettingValueList(
                                   BANDWIDTH_LIST,
                                   current_index=c.fm_dev)))
        bf.append(
            RadioSetting(prefix + ".shift",
                         "Frequency Shift (Menu 6)",
                         RadioSettingValueList(OFFSET_LIST,
                                               current_index=c.shift)))
        return bf

    def _area_tab(self, area):
        """Build a VFO tab
        """
        def apply_scan_st(setting, scan_lo, scan_hi, obj):
            f = freq2short(setting.value, scan_lo, scan_hi)
            obj.scan_st = f

        def apply_scan_end(setting, scan_lo, scan_hi, obj):
            f = freq2short(setting.value, scan_lo, scan_hi)
            obj.scan_end = f

        if area == "a":
            desc = "Area A Settings"
            c = self._memobj.a_conf
            scan_lo = 108000000
            scan_hi = 985000000
            scan_rng = self._memobj.settings.a
            band_list = (150, 200, 300, 450, 700)
        else:
            desc = "Area B Settings"
            c = self._memobj.b_conf
            scan_lo = 136000000
            scan_hi = 512000000
            scan_rng = self._memobj.settings.b
            band_list = (150, 450)

        prefix = "%s_conf" % area
        af = RadioSettingGroup(prefix, desc)
        af.append(
            RadioSetting(prefix + ".w_mode",
                         "Workmode",
                         RadioSettingValueList(
                             WORKMODE_LIST,
                             current_index=c.w_mode)))
        af.append(RadioSetting(prefix + ".w_chan",
                               "Channel",
                               RadioSettingValueInteger(1, 999,
                                                        c.w_chan)))
        af.append(
            RadioSetting(prefix + ".scan_grp",
                         "Scan Group (Menu 49)",
                         RadioSettingValueList(
                             SCANGRP_LIST,
                             current_index=c.scan_grp)))
        af.append(RadioSetting(prefix + ".bcl",
                               "Busy Channel Lock-out (Menu 15)",
                               RadioSettingValueBoolean(c.bcl)))
        af.append(
            RadioSetting(prefix + ".sql",
                         "Squelch Level (Menu 8)",
                         RadioSettingValueList(LIST_0_9,
                                               current_index=c.sql)))
        af.append(
            RadioSetting(prefix + ".cset",
                         "Call ID Group (Menu 52)",
                         RadioSettingValueList(LIST_1_20,
                                               current_index=c.cset)))
        af.append(
            RadioSetting(prefix + ".step",
                         "Frequency Step (Menu 3)",
                         RadioSettingValueList(
                             self._step_list, current_index=c.step)))
        af.append(
            RadioSetting(prefix + ".scan_mode",
                         "Scan Mode (Menu 20)",
                         RadioSettingValueList(
                             SCANMODE_LIST,
                             current_index=c.scan_mode)))
        af.append(
            RadioSetting(prefix + ".scan_range",
                         "Scan Range (Menu 50)",
                         RadioSettingValueList(
                             SCANRANGE_LIST,
                             current_index=c.scan_range)))
        st = RadioSettingValueString(0, 15,
                                     short2freq(scan_rng.scan_st))
        rs = RadioSetting("settings.%s.scan_st" % area,
                          "Frequency Scan Start", st)
        rs.set_apply_callback(apply_scan_st, scan_lo, scan_hi, scan_rng)
        af.append(rs)

        end = RadioSettingValueString(0, 15,
                                      short2freq(scan_rng.scan_end))
        rs = RadioSetting("settings.%s.scan_end" % area,
                          "Frequency Scan End", end)
        rs.set_apply_callback(apply_scan_end, scan_lo, scan_hi,
                              scan_rng)
        af.append(rs)
        # Each area has its own set of bands
        for band in (band_list):
            af.append(self._band_tab(area, band))
        return af

    def _key_tab(self):
        """Build radio key/button menu
        """
        s = self._memobj.settings
        if self.MODEL == "KG-UV9PX":
            pfkey1 = PF1KEY_LIST
            pfkey2 = PF2KEY_LIST
            pfkey3 = PF3KEY_LIST2
        elif (self.MODEL == "KG-UV9GX" or
              self.MODEL == "KG-UV9G Pro"):
            pfkey1 = PF1KEY_LIST9GX
            pfkey2 = PF2KEY_LIST9GX
            pfkey3 = PF3KEY_LIST9GX
        else:
            pfkey1 = PF1KEY_LIST
            pfkey2 = PF2KEY_LIST
            pfkey3 = PF3KEY_LIST

        kf = RadioSettingGroup("key_grp", "Key Settings")

        kf.append(RadioSetting("settings.pf1",
                               "PF1 Key function (Menu 55)",
                               RadioSettingValueList(
                                   pfkey1,
                                   current_index=s.pf1)))
        kf.append(RadioSetting("settings.pf2",
                               "PF2 Key function (Menu 56)",
                               RadioSettingValueList(
                                   pfkey2,
                                   current_index=s.pf2)))

        kf.append(RadioSetting("settings.pf3",
                               "PF3 Key function (Menu 57)",
                               RadioSettingValueList(
                                   pfkey3,
                                   current_index=s.pf3)))
        return kf

    def _fl_tab(self):
        """Build the frequency limits tab
        """

        # The stop limits in the factory KG-UV9D Mate memory image are 1 MHz
        # higher than the published specs. The settings panel will crash if
        # it encounters a value outside of these ranges.
        hard_limits = {
            "band_150": (108000000, 181000000),
            "band_450": (400000000, 513000000),
            "band_300": (350000000, 401000000),
            "band_700": (700000000, 987000000),
            "band_200": (230000000, 251000000)
        }

        def apply_freq_start(setting, low, high, obj):
            f = freq2short(setting.value, low, high)
            obj.start = f

        def apply_freq_stop(setting, low, high, obj):
            """Sets the stop limit to 1 MHz below the input value"""

            # The firmware has an off-by-1MHz error with stop limits.
            # If you set the stop limit to 1480 (148 MHz), you can still tune
            # up to 148.99 MHz. To compensate for this,
            # we subtract 10 increments of 100 MHz before storing the value.
            f = freq2short(setting.value, low, high) - 10
            obj.stop = f

        fl = RadioSettingGroup("freq_limit_grp", "Frequency Limits")

        rx = self._memobj.rx_freq_limits
        tx = self._memobj.tx_freq_limits

        for rx_band in rx.items():
            name, limits = rx_band

            start_freq = RadioSettingValueString(1,
                                                 20,
                                                 short2freq(limits.start))
            start_rs = RadioSetting("rx_start_" + name,
                                    name + " Receive Start",
                                    start_freq)
            start_rs.set_apply_callback(apply_freq_start,
                                        hard_limits[name][0],
                                        hard_limits[name][1],
                                        limits)
            fl.append(start_rs)

            # Add 10 increments of 100 MHz before displaying to compensate for
            # the firmware off-by-1MHz problem.
            stop_freq = RadioSettingValueString(1,
                                                20,
                                                short2freq(limits.stop + 10))
            stop_rs = RadioSetting("rx_stop_" + name,
                                   name + " Receive Stop",
                                   stop_freq)
            stop_rs.set_apply_callback(apply_freq_stop,
                                       hard_limits[name][0],
                                       hard_limits[name][1],
                                       limits)
            fl.append(stop_rs)

        for tx_band in tx.items():
            name, limits = tx_band

            start_freq = RadioSettingValueString(1,
                                                 20,
                                                 short2freq(limits.start))
            start_rs = RadioSetting("tx_start_" + name,
                                    name + " Transmit Start",
                                    start_freq)
            start_rs.set_apply_callback(apply_freq_start,
                                        hard_limits[name][0],
                                        hard_limits[name][1], limits)
            fl.append(start_rs)

            # Add 10 increments of 100 MHz before displaying to compensate for
            # the firmware off-by-1MHz problem.
            stop_freq = RadioSettingValueString(1,
                                                20,
                                                short2freq(limits.stop + 10))
            stop_rs = RadioSetting("tx_stop_" + name,
                                   name + " Transmit Stop",
                                   stop_freq)
            stop_rs.set_apply_callback(apply_freq_stop,
                                       hard_limits[name][0],
                                       hard_limits[name][1],
                                       limits)
            fl.append(stop_rs)

        return fl

    def _get_settings(self):
        """Build the radio configuration settings menus
        """

        core_grp = self._core_tab()
        fm_grp = self._fm_tab()
        area_a_grp = self._area_tab("a")
        area_b_grp = self._area_tab("b")
        key_grp = self._key_tab()
        scan_grp = self._scan_grp()
        callid_grp = self._callid_grp()
        admin_grp = self._admin_tab()
        rpt_grp = self._repeater_tab()
        freq_limit_grp = self._fl_tab()

        core_grp.append(key_grp)
        core_grp.append(admin_grp)
        core_grp.append(rpt_grp)
        core_grp.append(freq_limit_grp)
        group = RadioSettings(core_grp,
                              area_a_grp,
                              area_b_grp,
                              fm_grp,
                              scan_grp,
                              callid_grp
                              )
        return group

    def get_settings(self):
        """ Public build out linkage between radio settings and UI
        """
        try:
            return self._get_settings()
        except Exception:
            import traceback
            LOG.error("Failed to parse settings: %s",
                      traceback.format_exc())
            return None

    def _is_freq(self, element):
        """This is a hack to smoke out whether we need to do
        frequency translations for otherwise innocent u16s and u32s
        """
        return "rxfreq" in element.get_name() or \
               "txfreq" in element.get_name() or \
               "scan_st" in element.get_name() or \
               "scan_end" in element.get_name() or \
               "offset" in element.get_name() or \
               "fm_stop" in element.get_name()

    def _is_limit(self, element):
        return "lower_limit" in element.get_name() or\
               "upper_limit" in element.get_name()

    def set_settings(self, settings):
        """ Public update radio settings via UI callback
        A lot of this should be in common code....
        """

        for element in settings:
            if not isinstance(element, RadioSetting):
                LOG.debug("set_settings: not instance %s" %
                          element.get_name())
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            # decode an array index
                            if "[" in bit and "]" in bit:
                                bit, index = bit.split("[", 1)
                                index, junk = index.split("]", 1)
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
                    else:
                        LOG.debug("Setting %s = %s" %
                                  (setting, element.value))
                        if self._is_freq(element):
                            setattr(obj, setting, int(element.value)/10)
                        elif self._is_limit(element):
                            setattr(obj, setting, int(element.value)*10)
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug("set_settings: Exception with %s" %
                              element.get_name())
                    raise

    def callid2str(self, cid):
        """Caller ID per MDC-1200 spec? Must be 3-6 digits (100 - 999999).
        One digit (binary) per byte, terminated with '0xc'
        """

        bin2ascii = " 1234567890"
        cidstr = ""
        for i in range(0, 6):
            b = cid[i].get_value()
            if b == 0xc:  # the cid EOL
                break
            if b == 0 or b > 0xa:
                raise InvalidValueError(
                    "Caller ID code has illegal byte 0x%x" % b)
            cidstr += bin2ascii[b]
        return cidstr


@directory.register
class KGUV9PXRadio(KGUV9DPlusRadio):

    """Wouxun KG-UV9PX"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV9PX"
    _model = b"KG-UV9D"
    _rev = b"02"  # default rev for the radio I know about...
    _file_ident = b"kg-uv9px"
    _valid_steps = STEPS
    _step_list = STEP_LIST

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False

    def process_mmap(self):
        if self._rev != b"02" and self._rev != b"00":
            # new revision found - log it and assume same map and proceed
            LOG.debug("Unrecognized model variation (%s) Using default Map" %
                      self._rev)
        self._memobj = bitwise.parse(_MEM_FORMAT_9PX, self._mmap)

    def get_features(self):
        """ Public get_features
            Return the features of this radio once we have identified
            it and gotten its bits
            """
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_bands = [(108000000, 135997500),  # Aircraft  AM
                          (136000000, 180997500),  # supports 2m
                          (219000000, 250997500),
                          (350000000, 399997500),
                          (400000000, 512997500),  # supports 70cm
                          (700000000, 986997500)]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_tuning_steps = STEPS
        rf.memory_bounds = (1, 999)  # 999 memories
        return rf

    def callid2str(self, cid):
        """Caller ID per MDC-1200 spec? Must be 3-6 digits (100 - 999999).
        One digit (binary) per byte, terminated with '0xc'
        """

        bin2ascii = " 1234567890"
        cidstr = ""
        for i in range(0, 6):
            b = cid[i].get_value()
            # 9PX factory reset CID use 0x00 for 0 digit - instead of 0x0a
            # remap 0x00 to 0x0a
            if b == 0x00:
                b = 0x0a
            if b == 0xc or b == 0xf0:  # the cid EOL
                break
            if b > 0xa:
                raise InvalidValueError(
                    "Caller ID code has illegal byte 0x%x" % b)
            cidstr += bin2ascii[b]
        return cidstr

    def _get_settings(self):
        """Build the radio configuration settings menus
        """

        core_grp = self._core_tab()
        fm_grp = self._fm_tab()
        area_a_grp = self._area_tab("a")
        area_b_grp = self._area_tab("b")
        key_grp = self._key_tab()
        scan_grp = self._scan_grp()
        callid_grp = self._callid_grp()
        admin_grp = self._admin_tab()
        rpt_grp = self._repeater_tab()
        freq_limit_grp = self._fl_tab()
        core_grp.append(key_grp)
        core_grp.append(admin_grp)
        core_grp.append(rpt_grp)
        group = RadioSettings(core_grp,
                              area_a_grp,
                              area_b_grp,
                              fm_grp,
                              scan_grp,
                              callid_grp,
                              freq_limit_grp,)
        return group

    def _area_tab(self, area):
        """Build a VFO tab
        """
        def apply_scan_st(setting, scan_lo, scan_hi, obj):
            f = freq2short(setting.value, scan_lo, scan_hi)
            obj.scan_st = f

        def apply_scan_end(setting, scan_lo, scan_hi, obj):
            f = freq2short(setting.value, scan_lo, scan_hi)
            obj.scan_end = f

        if area == "a":
            desc = "Receiver A Settings"
            c = self._memobj.a_conf
            scan_lo = 108000000
            scan_hi = 985997500
            scan_rng = self._memobj.settings.a
            band_list = (150, 200, 300, 450, 700)
        else:
            desc = "Receiver B Settings"
            c = self._memobj.b_conf
            scan_lo = 136000000
            scan_hi = 512997500
            scan_rng = self._memobj.settings.b
            band_list = (150, 450)

        prefix = "%s_conf" % area
        af = RadioSettingGroup(prefix, desc)
        af.append(
            RadioSetting(prefix + ".w_mode",
                         "Workmode",
                         RadioSettingValueList(
                             WORKMODE_LIST,
                             current_index=c.w_mode)))
        af.append(RadioSetting(prefix + ".w_chan",
                               "Channel",
                               RadioSettingValueInteger(1, 999,
                                                        c.w_chan)))
        af.append(
            RadioSetting(prefix + ".scan_grp",
                         "Scan Group (Menu 49)",
                         RadioSettingValueList(
                             SCANGRP_LIST,
                             current_index=c.scan_grp)))
        af.append(RadioSetting(prefix + ".bcl",
                               "Busy Channel Lock-out (Menu 15)",
                               RadioSettingValueBoolean(c.bcl)))
        af.append(
            RadioSetting(prefix + ".sql",
                         "Squelch Level (Menu 8)",
                         RadioSettingValueList(LIST_0_9,
                                               current_index=c.sql)))
        af.append(
            RadioSetting(prefix + ".cset",
                         "Call ID Group (Menu 52)",
                         RadioSettingValueList(LIST_1_20,
                                               current_index=c.cset)))
        af.append(
            RadioSetting(prefix + ".step",
                         "Frequency Step (Menu 3)",
                         RadioSettingValueList(
                             self._step_list, current_index=c.step)))
        af.append(
            RadioSetting(prefix + ".scan_mode",
                         "Scan Mode (Menu 20)",
                         RadioSettingValueList(
                             SCANMODE_LIST,
                             current_index=c.scan_mode)))
        af.append(
            RadioSetting(prefix + ".scan_range",
                         "Scan Range (Menu 50)",
                         RadioSettingValueList(
                             SCANRANGE_LIST,
                             current_index=c.scan_range)))
        st = RadioSettingValueString(0, 15,
                                     short2freq(scan_rng.scan_st))
        rs = RadioSetting("settings.%s.scan_st" % area,
                          "Frequency Scan Start", st)
        rs.set_apply_callback(apply_scan_st, scan_lo, scan_hi, scan_rng)
        af.append(rs)

        end = RadioSettingValueString(0, 15,
                                      short2freq(scan_rng.scan_end))
        rs = RadioSetting("settings.%s.scan_end" % area,
                          "Frequency Scan End", end)
        rs.set_apply_callback(apply_scan_end, scan_lo, scan_hi,
                              scan_rng)
        af.append(rs)
        # Each area has its own set of bands
        for band in (band_list):
            af.append(self._band_tab(area, band))
        return af

    def _band_tab(self, area, band):
        """ Build a band tab inside a VFO/Area
        """
        def apply_freq(setting, lo, hi, obj):
            f = freq2int(setting.value, lo, hi)
            obj.freq = f/10

        def apply_offset(setting, obj):
            f = freq2int(setting.value, 0, 5000000)
            obj.offset = f/10

        def apply_enc(setting, obj):
            t = tone2short(setting.value)
            obj.encqt = t

        def apply_dec(setting, obj):
            t = tone2short(setting.value)
            obj.decqt = t

        if area == "a":
            if band == 150:
                c = self._memobj.vfo_a.band_150
                lo = 108000000
                hi = 180997500
            elif band == 200:
                c = self._memobj.vfo_a.band_200
                lo = 219000000
                hi = 250997500
            elif band == 300:
                c = self._memobj.vfo_a.band_300
                lo = 350000000
                hi = 399997500
            elif band == 450:
                c = self._memobj.vfo_a.band_450
                lo = 400000000
                hi = 512997500
            else:   # 700
                c = self._memobj.vfo_a.band_700
                lo = 700000000
                hi = 986997500
        else:  # area 'b'
            if band == 150:
                c = self._memobj.vfo_b.band_150
                lo = 136000000
                hi = 180997500
            else:  # 450
                c = self._memobj.vfo_b.band_450
                lo = 400000000
                hi = 512997500

        prefix = "vfo_%s.band_%d" % (area, band)
        bf = RadioSettingGroup(prefix, "%d MHz Band" % band)
        freq = RadioSettingValueString(0, 15, int2freq(c.freq * 10))
        rs = RadioSetting(prefix + ".freq", "Rx Frequency", freq)
        rs.set_apply_callback(apply_freq, lo, hi, c)
        bf.append(rs)

        off = RadioSettingValueString(0, 15, int2freq(c.offset * 10))
        rs = RadioSetting(prefix + ".offset", "Tx Offset (Menu 28)", off)
        rs.set_apply_callback(apply_offset, c)
        bf.append(rs)

        rs = RadioSetting(prefix + ".encqt",
                          "Encode QT (Menu 17,19)",
                          RadioSettingValueList(TONE_LIST,
                                                short2tone(c.encqt)))
        rs.set_apply_callback(apply_enc, c)
        bf.append(rs)

        rs = RadioSetting(prefix + ".decqt",
                          "Decode QT (Menu 16,18)",
                          RadioSettingValueList(TONE_LIST,
                                                short2tone(c.decqt)))
        rs.set_apply_callback(apply_dec, c)
        bf.append(rs)

        bf.append(RadioSetting(prefix + ".qt",
                               "Mute Mode (Menu 21)",
                               RadioSettingValueList(SPMUTE_LIST,
                                                     current_index=c.qt)))
        bf.append(RadioSetting(prefix + ".scan",
                               "Scan this (Menu 48)",
                               RadioSettingValueBoolean(c.scan)))
        bf.append(RadioSetting(prefix + ".pwr",
                               "Power (Menu 5)",
                               RadioSettingValueList(
                                   POWER_LIST, current_index=c.pwr)))
        bf.append(RadioSetting(prefix + ".mod",
                               "AM Modulation (Menu 54)",
                               RadioSettingValueBoolean(c.mod)))
        bf.append(RadioSetting(prefix + ".fm_dev",
                               "FM Deviation (Menu 4)",
                               RadioSettingValueList(
                                   BANDWIDTH_LIST,
                                   current_index=c.fm_dev)))
        bf.append(
            RadioSetting(prefix + ".shift",
                         "Frequency Shift (Menu 6)",
                         RadioSettingValueList(OFFSET_LIST,
                                               current_index=c.shift)))
        return bf

    def _fl_tab(self):

        freq_limit_grp = RadioSettingGroup("limits",
                                           "Freq Limits")
        limgrp = freq_limit_grp

        l = self._memobj.limits

        if self.MODEL == "KG-UV9PX":
            val = RadioSettingValueInteger(136, 180,
                                           (l.lim_150M_Txlower_limit) / 10.0)
            rs = RadioSetting("limits.lim_150M_Txlower_limit",
                              "150M Tx Lower Limit (MHz)",
                              val)
            limgrp.append(rs)

            val = RadioSettingValueInteger(136, 180,
                                           (l.lim_150M_Txupper_limit) / 10.0)
            rs = RadioSetting("limits.lim_150M_Txupper_limit",
                              "150M Tx Upper Limit (MHz + 0.9975)",
                              val)
            limgrp.append(rs)

            val = RadioSettingValueInteger(400, 512,
                                           (l.lim_450M_Txlower_limit) / 10.0)
            rs = RadioSetting("limits.lim_450M_Txlower_limit",
                              "450M Tx Lower Limit (MHz)",
                              val)
            limgrp.append(rs)

            val = RadioSettingValueInteger(400, 512,
                                           (l.lim_450M_Txupper_limit) / 10.0)
            rs = RadioSetting("limits.lim_450M_Txupper_limit",
                              "450M Tx Upper Limit (MHz + 0.9975)",
                              val)
            limgrp.append(rs)

        val = RadioSettingValueInteger(108, 180,
                                       (l.lim_150M_area_a_rxlower_limit) /
                                       10.0)
        rs = RadioSetting("limits.lim_150M_area_a_rxlower_limit",
                          "Rcvr A 150M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(108, 180,
                                       (l.lim_150M_area_a_rxupper_limit) /
                                       10.0)
        rs = RadioSetting("limits.lim_150M_area_a_rxupper_limit",
                          "Rcvr A 150M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(136, 180,
                                       (l.lim_150M_area_b_rxlower_limit) /
                                       10.0)
        rs = RadioSetting("limits.lim_150M_area_b_rxlower_limit",
                          "Rcvr B 150M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(136, 180,
                                       (l.lim_150M_area_b_rxupper_limit) /
                                       10.0)
        rs = RadioSetting("limits.lim_150M_area_b_rxupper_limit",
                          "Rcvr B 150M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(400, 512,
                                       (l.lim_450M_rxlower_limit) / 10.0)
        rs = RadioSetting("limits.lim_450M_rxlower_limit",
                          "450M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(400, 512,
                                       (l.lim_450M_rxupper_limit) / 10.0)
        rs = RadioSetting("limits.lim_450M_rxupper_limit",
                          "450M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(350, 399,
                                       (l.lim_300M_rxlower_limit) / 10.0)
        rs = RadioSetting("limits.lim_300M_rxlower_limit",
                          "300M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(350, 399,
                                       (l.lim_300M_rxupper_limit) / 10.0)
        rs = RadioSetting("limits.lim_300M_rxupper_limit",
                          "300M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)
        val = RadioSettingValueInteger(700, 986,
                                       (l.lim_800M_rxlower_limit) / 10.0)
        rs = RadioSetting("limits.lim_800M_rxlower_limit",
                          "800M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(700, 986,
                                       (l.lim_800M_rxupper_limit) / 10.0)
        rs = RadioSetting("limits.lim_800M_rxupper_limit",
                          "800M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(219, 250,
                                       (l.lim_210M_rxlower_limit) / 10.0)
        rs = RadioSetting("limits.lim_210M_rxlower_limit",
                          "210M Rx Lower Limit (MHz)",
                          val)
        limgrp.append(rs)

        val = RadioSettingValueInteger(219, 250,
                                       (l.lim_210M_rxupper_limit) / 10.0)
        rs = RadioSetting("limits.lim_210M_rxupper_limit",
                          "210M Rx Upper Limit (MHz + 0.9975)",
                          val)
        limgrp.append(rs)

        return limgrp


@directory.register
class KGUV9GXRadio(KGUV9PXRadio):

    """Wouxun KG-UV9GX"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV9GX"
    _model = b"KG-UV9D"
    _rev = b"02"  # default rev for the radio I know about...
    _valid_steps = STEPS
    _step_list = STEP_LIST

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class KGUV9KRadio(KGUV9DPlusRadio):

    """Wouxun KG-UV9K"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV9K"
    _model = b"KG-UV9D"
    _file_ident = b"kg-uv9k"
    _rev = b"02"  # default rev for the radio I know about...
    _step_list = STEP_LIST_9K
    _valid_steps = STEPS_9K

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class KGUV9GProRadio(KGUV9DPlusRadio):

    """Wouxun KG-UV9G Pro"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV9G Pro"
    _model = b"KG-UV9D"
    _file_ident = b"kg-uv9gpro"
    _rev = b"02"  # default rev for the radio I know about...
    _step_list = STEP_LIST
    _valid_steps = STEPS

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False
