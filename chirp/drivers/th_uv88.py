# Version 1.0 for TYT-UV88
# Initial radio protocol decode, channels and memory layout
# by James Berry <james@coppermoth.com>, Summer 2020
# Additional configuration and help, Jim Unroe <rock.unroe@gmail.com>
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
# along with this program.

import struct
import logging
import math
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, RadioSettingSubGroup

LOG = logging.getLogger(__name__)

CHAN_NUM = 200

MEM_FORMAT = """
struct chns {
  ul32 rxfreq;
  ul32 txfreq;
  ul16 scramble:4,
       rxtone:12; //decode:12
  ul16 decodeDSCI:1,
       encodeDSCI:1,
       unk1:1,
       unk2:1,
       txtone:12; //encode:12
  u8   power:2,
       wide:2,
       b_lock:2,
       unk3:2;
  u8   unk4:3,
       signal:2,
       displayName:1,
       unk5:2;
  u8   pttidftones:2,
       pttid:2,
       unk7:1,
       step:3;               // not required
  u8   name[6];
};

struct vfo {
  ul32 rxfreq;
  ul32 txfreq;  // displayed as an offset
  ul16 scramble:4,
       rxtone:12; //decode:12
  ul16 decodeDSCI:1,
       encodeDSCI:1,
       unk1:1,
       unk2:1,
       txtone:12; //encode:12
  u8   power:2,
       wide:2,
       b_lock:2,
       unk3:2;
  u8   unk4:3,
       signal:2,
       displayName:1,
       unk5:2;
  u8   unk6:2,
       pttid:2,
       step:4;
  u8   name[6];
};

struct chname {
  u8  extra_name[10];
};

// #seekto 0x0000;
struct chns chan_mem[200]; // CHAN_NUM

#seekto 0x1140;
struct {
  u8 autoKeylock:1,       // 0x1140 [18] *OFF, On
     unk1:1,              //
     vfomrmodeb:1,        //        *VFO B, MR B
     vfomrmode:1,         //        *VFO, MR
     unk2:4;              //
  u8 mrAch;               // 0x1141 MR A Channel #
  u8 mrBch;               // 0x1142 MR B Channel #
  u8 unk3:5,              //
     ab:1,                //        * A, B
     unk4:2;              //
} workmodesettings;
"""

MEM_FORMAT_PT2 = """
// #seekto 0x1180;
struct {
  u8 bitmap[26];    // one bit for each channel marked in use
} chan_avail;

#seekto 0x11A0;
struct {
  u8 bitmap[26];    // one bit for each channel skipped
} chan_skip;


struct dtmfenc {              // Size=0x0D (13)
  u8   code[12];              // hexa E=* F=#
  u8   unk1:2,
       ani:1,
       codelen:5;
};

struct dtmfsignal {
  struct dtmfenc encode[16];   // 0x11C0
  u8   unk0[16];               // 0x1290
  u8   sidetone:1,             // 0x12A0
       delimiter:3,            //        0=A  .. 5=#
       speed:3,                //        0=50ms 1=100ms 2=200ms 3=300ms 4=500ms
       ani:1;
  u8   unk1:1,                 // 0x12A1
       pttid:2,                //        0=None 1=Begin 2=End 3=Both
       unk1b:2,
       group:3;                //        0=OFF 1=A  .. 6=#
  u8   unk2:4,                 // 0x12A2
       firstdigit:4;           //        *100ms
  u8   unk3;                   // 0x12A3
  u8   unk4:3,                 // 0x12A4
       autoresettime:5;        //        0 to 25
  u8   unk5[2];                // 0x12A5
  u8   encodemask[2];          // 0x12A7
  u8   ownid[4];               // 0x12A9 Hexa E=* F=#
  u8   ownidlen;               // 0x12AD
  u8   unk6[2];                // 0x12AE
  u8   pttidbegin[12];         // 0x12B0 Hexa E=* F=#
  u8   pttidbeginlen;          // 0x12BC
  u8   unk7[3];                // 0x12BD
  u8   pttidend[12];           // 0x12C0 Hexa E=* F=#
  u8   pttidendlen;            // 0x12CC
  u8   unk8[3];                // 0x12CD
  u8   stuncode[7];            // 0x12D0 Hexa E=* F=#
  u8   stuncodelast:4,           // 0x12D7 15th digit
       stuncodelen:4;
  u8   killcode[7];            // 0x12D8 Hexa E=* F=#
  u8   killcodelast:4,           // 0x12DF 15th digit
       killcodelen:4;
                               // 0x12E0
};

struct ttonesenc {             // Size=0xB (11)
  u16  tone1;                  // Freq *10
  u16  tone2;                  // Freq *10
  char name[6];
  u8   namelen;
};

struct ttonessignal {
  struct ttonesenc encode[16]; // 0x1300
  u8   unk1[16];               // 0x13B0
  u16  tone1;                  // 0x13C0 Freq *10
  u16  tone2;                  // 0x13C2 Freq *10
  u16  tone3;                  // 0x13C4 Freq *10
  u16  tone4;                  // 0x13C6 Freq *10
  u8   unk2:1,                 // 0x13C8
       sidetone:1,
       unk3:2,
       format:4;               //        0=A-B -> 14=LONG C
  u8   firsttone;              // 0x13C9 0=500ms 95=10000ms 100ms steps
  u8   secondtone;             // 0x13CA 0=500ms 95=10000ms 100ms steps
  u8   longtone;               // 0x13CB 0=500ms 95=10000ms 100ms steps
  u8   intervaltime;           // 0x13CC 0 to 20 * 100ms
  u8   autoresettime;          // 0x13CD 0 to 25s
  u8   encodemask[2];          // 0x13CE
};

struct ftonesenc {             // Size=0x20 (32)
  u8   callid[4];              // Hexa
  u8   callidlen;
  u8   unk1[16];
  u8   type:3,                 // 0=OFF/1=ANI
       unk2:5;
  char name[6];
  u8   namelen;
  u8   unk3[3];
};

struct ftonesdec {             // Size=0x10 (16)
  u8   unk1:4,
       active:1,
       function:3;	           // select=0/stun=1/kill=2/wake=3
  u8   code[6];                // Hexa
  u8   codelen;
  char chname[6];
  u8   chnamelen;
  u8   unk2;
};

struct ftonessignal {          // Size=0x2A0 (672)
  struct ftonesenc encode[16]; // 0x13E0
  u8   ownid[4];               // 0x15E0 Hexa
  u8   ownidlen;               // 0x15E4
  u8   unk1;                   // 0x15E5
  u8   unk2:3,                 // 0x15E6
       autoresettime:5;        //        0 to 25s
  u8   unk3:4,                 // 0x15E7
       firstdigit:4;           //        0 to 10 *100ms
  u8   unk4;                   // 0x15E8
  u8   unk5:2,                 // 0x15E9
       repeater:3,             //        A=0/B=1/C=2/D=3/*=44/#=5
       group:3;                //        A=0/B=1/C=2/D=3/*=44/#=5
  u8   sidetone:1,             // 0x15EA
       delimiter:3,            //        A=0/B=1/C=2/D=3/*=44/#=5
       mode:4;                 //        ZVEI1=0/PZVEI1/ZVEI2/.../CCITT=13
  u8   unk6:3,                 // 0x15EB
       pttid:2,                //        0=None 1=Begin 2=End 3=Both
       unk7:3;
  u8   pttidbegin[4];          // 0x15EC Hexa
  u8   pttidbeginlen;          // 0x15F0
  u8   pttidend[4];            // 0x15F1
  u8   pttidendlen;            // 0x15F5
  u8   encodemask[2];          // 0x15F6
  u8   decodemask;             // 0x15F8
  u8   digitlen;               // 0x15F9 ms
  u8   unk9[6];                // 0x15FA
  struct ftonesdec decode[8];  // 0x1600
                               // 0x1680
};

#seekto 0x11C0;
struct {
  struct dtmfsignal dtmf;       // 0x11C0
  u8 unk1[32];                 // 0x12E0
  struct ttonessignal ttones;  // 0x1300
  u8 unk2[16];                 // 0x13D0
  struct ftonessignal ftones;  // 0x13E0
} optsignal;

#seekto 0x191E;
struct {
  u8 unk1:4,              //
     region:4;            // 0x191E Radio Region (read only)
                          // 0 = Unlocked  TX: 136-174 MHz / 400-480 MHz
                          // 2-3 = Unknown
                          // 3 = EU        TX: 144-146 MHz / 430-440 MHz
                          // 4 = US        TX: 144-148 MHz / 420-450 MHz
                          // 5-15 = Unknown
} settings2;

#seekto 0x1940;
struct {
  char name1[15];         // Intro Screen Line 1 (16 alpha text characters)
  u8 unk1;
  char name2[15];         // Intro Screen Line 2 (16 alpha text characters)
  u8 unk2;
} openradioname;

struct fm_chn {
  ul32 rxfreq;
};

// #seekto 0x1960;
struct chname chan_name[200]; // CHAN_NUM

#seekto 0x2180;
struct fm_chn fm_stations[24];

// #seekto 0x021E0;
struct {
  u8  fmset[4];
} fmmap;

// #seekto 0x21E4;
struct {
  ul32 fmcur;
} fmfrqs;

"""

THUV88_SETTINGS = """
#seekto 0x1160;
struct {
  u8 introScreen1[12];    // 0x1160 *Intro Screen Line 1(truncated to 12 alpha
                          //         text characters)
  u8 offFreqVoltage:3,    // 0x116C unknown referred to in code but not on
                          //        screen
     unk1:1,              //
     sqlLevel:4;          //        [05] *OFF, 1-9
  u8 beep:1,              // 0x116D [09] *OFF, On
     callKind:2,          //        code says 1750,2100,1000,1450 as options
                          //        not on screen
     introScreen:2,       //        [20] *OFF, Voltage, Char String
     unk2:2,              //
     txChSelect:1;        //        [02] *Last CH, Main CH
  u8 autoPowOff:3,        // 0x116E not on screen? OFF, 30Min, 1HR, 2HR
     unk3:1,              //
     tot:4;               //        [11] *OFF, 30 Second, 60 Second, 90 Second,
                          //              ... , 270 Second
  u8 unk4:1,              // 0x116F
     roger:1,             //        [14] *OFF, On
     dailDef:1,           //        Unknown - 'Volume, Frequency'
     language:1,          //        ?Chinese, English (English only FW BQ1.38+)
     unk5:1,              //
     endToneElim:1,       //        *OFF, Frequency
     unk6:1,              //
     unk7:1;              //
  u8 scanResumeTime:2,    // 0x1170 2S, 5S, 10S, 15S (not on screen)
     disMode:2,           //        [33] *Frequency, Channel, Name
     scanType:2,          //        [17] *To, Co, Se
     ledMode:2;           //        [07] *Off, On, Auto
  u8 unk8;                // 0x1171
  u8 unk9:4,              // 0x1172 Has flags to do with logging - factory
                          //        enabled (bits 16,64,128)
     ftonesch:4;          //        active five tones channel
  u8 dtmfch:4,            // 0x1173 active dtmf channel
     ttonesch:4;          //        active two tones channel
  u8 swAudio:1,           // 0x1174 [19] *OFF, On
     radioMoni:1,         //        [34] *OFF, On
     keylock:1,           //        [18] *OFF, On
     dualWait:1,          //        [06] *OFF, On
     unk11:1,             //
     light:3;             //        [08] *1, 2, 3, 4, 5, 6, 7
  u8 voxSw:1,             // 0x1175 [13] *OFF, On
     voxDelay:4,          //        *0.5S, 1.0S, 1.5S, 2.0S, 2.5S, 3.0S, 3.5S,
                          //         4.0S, 4.5S, 5.0S
     voxLevel:3;          //        [03] *1, 2, 3, 4, 5, 6, 7
  u8 unk12:4,             // 0x1176
     saveMode:2,          //        [16] *OFF, 1:1, 1:2, 1:4
     keyMode:2;           //        [32] *ALL, PTT, KEY, Key & Side Key
  u8 unk13;               // 0x1177
  u8 unk14;               // 0x1178
  u8 unk15;               // 0x1179
  u8 name2[6];            // 0x117A unused
} basicsettings;
"""

RA89_SETTINGS = """
#seekto 0x1160;
struct {
  u8 sideKey2:4,          // 0x1160 side key 2
     sideKey1:4;          //        side key 1
  u8 sideKey2_long:4,     // 0x1161 side key 2 Long
     sideKey1_long:4;     //        side key 1 Long
  u8 unknownBytes[10];    // 0x1162 - 0x116B
  u8 offFreqVoltage:3,    // 0x116C unknown referred to in code but not on
                          //        screen
     unk1:1,              //
     sqlLevel:4;          //        [05] *OFF, 1-9
  u8 beep:1,              // 0x116D [09] *OFF, On
     callKind:2,          //        code says 1750,2100,1000,1450 as options
                          //        not on screen
     introScreen:2,       //        [20] *OFF, Voltage, Char String
     unk2:2,              //
     txChSelect:1;        //        [02] *Last CH, Main CH
  u8 autoPowOff:3,        // 0x116E not on screen? OFF, 30Min, 1HR, 2HR
     unk3:1,              //
     tot:4;               //        [11] *OFF, 30 Second, 60 Second, 90 Second,
                          //              ... , 270 Second
  u8 unk4:1,              // 0x116F
     roger:1,             //        [14] *OFF, On
     dailDef:1,           //        Unknown - 'Volume, Frequency'
     language:1,          //        English only
     endToneElim:2,       //        *Frequency, 120, 180, 240 (RA89)
     unk5:1,              //
     unk6:1;              //
  u8 scanType:2,          // 0x1170 [17] *Off, On, 5s, 10s, 15s, 20s, 25s, 30s
     disMode:2,           //        [33] *Frequency, Channel, Name
     ledMode:4;           //        [07] *Off, On, 5s, 10s, 15s, 20s, 25s, 30s
  u8 unk7;                // 0x1171
  u8 unk8:4,              // 0x1172 Has flags to do with logging - factory
                          //        enabled (bits 16,64,128)
     ftonesch:4;          //        five tones channel
  u8 dtmfch:4,            // 0x1173 dtmf channel
     ttonesch:4;          //        two tones channel
  u8 swAudio:1,           // 0x1174 [19] *OFF, On
     radioMoni:1,         //        [34] *OFF, On
     keylock:1,           //        [18] *OFF, On
     dualWait:1,          //        [06] *OFF, On
     unk10:1,             //
     light:3;             //        [08] *1, 2, 3, 4, 5, 6, 7
  u8 voxSw:1,             // 0x1175 [13] *OFF, On
     voxDelay:4,          //        *0.5S, 1.0S, 1.5S, 2.0S, 2.5S, 3.0S, 3.5S,
                          //         4.0S, 4.5S, 5.0S
     voxLevel:3;          //        [03] *1, 2, 3, 4, 5, 6, 7
  u8 unk11:4,             // 0x1176
     saveMode:2,          //        [16] *OFF, 1:1, 1:2, 1:4
     keyMode:2;           //        [32] *ALL, PTT, KEY, Key & Side Key
  u8 unk12;               // 0x1177
  u8 unk13;               // 0x1178
  u8 unk14;               // 0x1179
  u8 name2[6];            // 0x117A unused
} basicsettings;
"""

MEM_SIZE = 0x22A0
BLOCK_SIZE = 0x20
STIMEOUT = 2
BAUDRATE = 57600

# Channel power: 3 levels
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                chirp_common.PowerLevel("Mid", watts=2.50),
                chirp_common.PowerLevel("Low", watts=0.50)]

SCRAMBLE_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8"]
B_LOCK_LIST = ["OFF", "Sub", "Carrier"]
OPTSIG_LIST = ["OFF", "DTMF", "2TONE", "5TONE"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
LIST_STEPS = [str(x) for x in STEPS]
OPTSIGENCTYPE_LIST = ["OFF", "ANI"]
OPTSIGDECFUNC_LIST = ["Select", "Stun", "Kill", "Wake"]
OPTSIGEXTDIGIT_LIST = ["A", "B", "C", "D", "*", "#"]
OPTSIGTELDIGIT_LIST = ["0", "1", "2", "3", "4", "5", "6", "7",
                       "8", "9", "A", "B", "C", "D", "*", "#"]
CHARSET_TEL = "0123456789ABCD*#"


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except Exception:
        _exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        _exit_program_mode(radio)
        msg = "Error reading from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except Exception:
        raise errors.RadioError("Error sending data to radio")


def _make_read_frame(addr, length):
    frame = b"\xFE\xFE\xEE\xEF\xEB"
    """Pack the info in the header format"""
    frame += struct.pack(">ih", addr, length)

    frame += b"\xFD"
    # Return the data
    return frame


def _make_write_frame(addr, length, data=""):
    frame = b"\xFE\xFE\xEE\xEF\xE4"

    """Pack the info in the header format"""
    output = struct.pack(">ih", addr, length)
    # Add the data if set
    if len(data) != 0:
        output += data

    frame += output
    frame += _calculate_checksum(output)

    frame += b"\xFD"
    # Return the data
    return frame


def _calculate_checksum(data):
    num = 0
    for x in range(0, len(data)):
        num = (num + data[x]) % 256

    if num == 0:
        return bytes([0])

    return bytes([256 - num])


def _recv(radio, addr, length):
    """Get data from the radio """

    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(data))

    return data


def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    radio.pipe.baudrate = BAUDRATE
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # Ident radio
    magic = radio._magic0
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 36)

    if not ack.startswith(radio._fingerprint) or not ack.endswith(b"\xFD"):
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond as expected (A)")

    return True


def _exit_program_mode(radio):
    # This may be the last part of a read
    magic = radio._magic5
    _rawsend(radio, magic)
    _clean_buffer(radio)


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)

    # Enter read mode
    magic = radio._magic2
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 7)
    if ack != b"\xFE\xFE\xEF\xEE\xE6\x00\xFD":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter read mode")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = b""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_read_frame(addr, BLOCK_SIZE)
        # DEBUG
        LOG.debug("Frame=" + util.hexprint(frame))

        # Sending the read request
        _rawsend(radio, frame)

        # Now we read data
        d = _recv(radio, addr, BLOCK_SIZE + 13)

        LOG.debug("Response Data= " + util.hexprint(d))

        if not d.startswith(b"\xFE\xFE\xEF\xEE\xE4"):
            LOG.warning("Incorrect start")
        if not d.endswith(b"\xFD"):
            LOG.warning("Incorrect end")
        # could validate the block data

        # Aggregate the data
        data += d[11:-2]

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)

    return data


def _upload(radio):
    """Upload procedure"""
    # Put radio in program mode and identify it
    _do_ident(radio)

    magic = radio._magic3
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 7)
    if ack != b"\xFE\xFE\xEF\xEE\xE6\x00\xFD":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter write mode")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # The fun starts here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # Official programmer skips writing these memory locations
        if addr >= 0x1680 and addr < 0x1940:
            continue

        # Sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_write_frame(addr, BLOCK_SIZE, data)
        LOG.warning("Frame:%s:" % util.hexprint(frame))
        _rawsend(radio, frame)

        ack = _rawrecv(radio, 7)
        LOG.debug("Response Data= " + util.hexprint(ack))

        if not ack.startswith(b"\xFE\xFE\xEF\xEE\xE6\x00\xFD"):
            LOG.warning("Unexpected response")
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def _do_map(chn, sclr, mary):
    """Set or Clear the chn (1-128) bit in mary[] word array map"""
    # chn is 1-based channel, sclr:1 = set, 0= = clear, 2= return state
    # mary[] is u8 array, but the map is by nibbles
    ndx = int(math.floor((chn - 1) / 8))
    bv = (chn - 1) % 8
    msk = 1 << bv
    mapbit = sclr
    if sclr == 1:    # Set the bit
        mary[ndx] = mary[ndx] | msk
    elif sclr == 0:  # clear
        mary[ndx] = mary[ndx] & (~ msk)     # ~ is complement
    else:       # return current bit state
        mapbit = 0
        if (mary[ndx] & msk) > 0:
            mapbit = 1
    return mapbit


def _do_map_int(chn, sclr, mary):
    """Set or Clear the chn (1-128) bit in mary[] word array map"""
    # chn is 1-based channel, sclr:1 = set, 0= = clear, 2= return state
    # mary is u8/u16/u32
    bv = (chn - 1)
    msk = 1 << bv
    mapbit = sclr
    if sclr == 1:    # Set the bit
        mary = mary | msk
    elif sclr == 0:  # clear
        mary = mary & (~ msk)     # ~ is complement
    else:       # return current bit state
        mapbit = 0
        if (mary & msk) > 0:
            mapbit = 1
    return mapbit


@directory.register
class THUV88Radio(chirp_common.CloneModeRadio):
    """TYT UV88 Radio"""
    VENDOR = "TYT"
    MODEL = "TH-UV88"
    NEEDS_COMPAT_SERIAL = False
    MODES = ['WFM', 'FM', 'NFM']
    # 62.5 is a non standard tone listed in the official programming software
    # 169.9 is a non standard tone listed in the official programming software
    # probably by mistake instead of 167.9
    TONES = (62.5,) + chirp_common.TONES + (169.9,)
    DTCS_CODES = chirp_common.DTCS_CODES
    NAME_LENGTH = 10
    DTMF_CHARS = list("0123456789ABCD*#")
    # 136-174, 400-480
    VALID_BANDS = [(136000000, 174000000), (400000000, 480000000)]

    # Valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`!\"#$%&'()*+,-./:;<=>?@[]^_"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0" + b"UV88" + b"\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2" + b"UV88" + b"\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3" + b"UV88" + b"\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + b"UV88" + b"\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + b"UV88"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = \
            (cls.VENDOR + ' ' + cls.MODEL + '\n')

        rp.pre_download = _(
            "This is an early stage beta driver\n")
        rp.pre_upload = _(
            "This is an early stage beta driver - upload at your own risk\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_comment = False
        rf.has_tuning_step = False      # Not as chan feature
        rf.valid_tuning_steps = STEPS
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_sub_devices = False
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS",
                                "Tone->DTCS", "DTCS->Tone", "->Tone",
                                "DTCS->DTCS"]
        rf.valid_skips = []
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tones = self.TONES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, CHAN_NUM)
        rf.valid_skips = ["", "S"]
        return rf

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""

        try:
            _upload(self)
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def process_mmap(self):
        """Process the mem map into the mem object"""
        mem_format = MEM_FORMAT + THUV88_SETTINGS + MEM_FORMAT_PT2
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def set_memory(self, memory):
        """A value in a UI column for chan 'number' has been modified."""
        # update all raw channel memory values (_mem) from UI (mem)
        _mem = self._memobj.chan_mem[memory.number - 1]
        _name = self._memobj.chan_name[memory.number - 1]

        if memory.empty:
            _do_map(memory.number, 0, self._memobj.chan_avail.bitmap)
            return

        _do_map(memory.number, 1, self._memobj.chan_avail.bitmap)

        if memory.skip == "":
            _do_map(memory.number, 1, self._memobj.chan_skip.bitmap)
        else:
            _do_map(memory.number, 0, self._memobj.chan_skip.bitmap)

        return self._set_memory(memory, _mem, _name)

    def get_memory(self, number):
        # radio first channel is 1, mem map is base 0
        _mem = self._memobj.chan_mem[number - 1]
        _name = self._memobj.chan_name[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        # Determine if channel is empty

        if _do_map(number, 2, self._memobj.chan_avail.bitmap) == 0:
            mem.empty = True
            return mem

        if _do_map(mem.number, 2, self._memobj.chan_skip.bitmap) > 0:
            mem.skip = ""
        else:
            mem.skip = "S"

        return self._get_memory(mem, _mem, _name)

    def _add_pttid(self, setting, name, display, value):
        rs = RadioSetting(name, display,
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[value]))
        setting.append(rs)

    def _get_memory(self, mem, _mem, _name):
        """Convert raw channel memory data into UI columns"""
        mem.extra = RadioSettingGroup("extra", "Extra")

        mem.empty = False
        # This function process both 'normal' and Freq up/down' entries
        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 25000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) \
                and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.name = ""
        for i in range(6):   # 0 - 6
            mem.name += chr(_mem.name[i])
        for i in range(10):
            mem.name += chr(_name.extra_name[i])

        mem.name = mem.name.rstrip()    # remove trailing spaces

        # ########## TONE ##########

        if _mem.txtone > 2600:
            # All off
            txmode = ""
        elif _mem.txtone > 511:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # DTSC
            txmode = "DTCS"
            mem.dtcs = int(format(int(_mem.txtone), 'o'))

        if _mem.rxtone > 2600:
            rxmode = ""
        elif _mem.rxtone > 511:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            rxmode = "DTCS"
            mem.rx_dtcs = int(format(int(_mem.rxtone), 'o'))

        mem.dtcs_polarity = ("N", "R")[_mem.encodeDSCI] + (
                             "N", "R")[_mem.decodeDSCI]

        mem.tmode = ""
        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        # ########## TONE ##########

        mem.mode = self.MODES[_mem.wide]
        mem.power = POWER_LEVELS[int(_mem.power)]

        rs = RadioSettingValueList(B_LOCK_LIST,
                                   B_LOCK_LIST[min(_mem.b_lock, 0x02)])
        b_lock = RadioSetting("b_lock", "B_Lock", rs)
        mem.extra.append(b_lock)

        step = RadioSetting("step", "Step",
                            RadioSettingValueList(LIST_STEPS,
                                                  LIST_STEPS[_mem.step]))
        mem.extra.append(step)

        scramble_value = _mem.scramble
        if self.MODEL == "RA89":
            if scramble_value >= 2:
                scramble_value = 0
            rs = RadioSetting("scramble", "Scramble",
                              RadioSettingValueBoolean(_mem.scramble))
            mem.extra.append(rs)
        else:
            if scramble_value >= 8:     # Looks like OFF is 0x0f ** CONFIRM
                scramble_value = 0
            scramble = RadioSetting("scramble", "Scramble",
                                    RadioSettingValueList(SCRAMBLE_LIST,
                                                          SCRAMBLE_LIST[
                                                              scramble_value]))
            mem.extra.append(scramble)

        optsig = RadioSetting("signal", "Optional signaling",
                              RadioSettingValueList(
                                  OPTSIG_LIST,
                                  OPTSIG_LIST[_mem.signal]))
        mem.extra.append(optsig)

        self._add_pttid(mem.extra, "pttid", "DTMF PTT ID",
                        _mem.pttid)
        self._add_pttid(mem.extra, "pttidftones", "5 TONES PTT ID",
                        _mem.pttidftones)

        return mem

    def _set_memory(self, mem, _mem, _name):
        # """Convert UI column data (mem) into MEM_FORMAT memory (_mem)."""

        _mem.rxfreq = mem.freq / 10
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = _mem.rxfreq

        out_name = mem.name.ljust(16)

        for i in range(6):   # 0 - 6
            _mem.name[i] = ord(out_name[i])
        for i in range(10):
            _name.extra_name[i] = ord(out_name[i+6])

        if mem.name != "":
            _mem.displayName = 1    # Name only displayed if this is set on
        else:
            _mem.displayName = 0

        rxmode = ""
        txmode = ""

        if mem.tmode == "Tone":
            txmode = "Tone"
        elif mem.tmode == "TSQL":
            rxmode = "Tone"
            txmode = "TSQL"
        elif mem.tmode == "DTCS":
            rxmode = "DTCSSQL"
            txmode = "DTCS"
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

        if mem.dtcs_polarity[1] == "N":
            _mem.decodeDSCI = 0
        else:
            _mem.decodeDSCI = 1

        if rxmode == "":
            _mem.rxtone = 0xFFF
        elif rxmode == "Tone":
            _mem.rxtone = int(float(mem.ctone) * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxtone = int(str(mem.dtcs), 8)
        elif rxmode == "DTCS":
            _mem.rxtone = int(str(mem.rx_dtcs), 8)

        if mem.dtcs_polarity[0] == "N":
            _mem.encodeDSCI = 0
        else:
            _mem.encodeDSCI = 1

        if txmode == "":
            _mem.txtone = 0xFFF
        elif txmode == "Tone":
            _mem.txtone = int(float(mem.rtone) * 10)
        elif txmode == "TSQL":
            _mem.txtone = int(float(mem.ctone) * 10)
        elif txmode == "DTCS":
            _mem.txtone = int(str(mem.dtcs), 8)

        _mem.wide = self.MODES.index(mem.mode)
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)

        return

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        _settings = self._memobj.basicsettings
        _settings2 = self._memobj.settings2
        _workmode = self._memobj.workmodesettings
        _optsignal = self._memobj.optsignal

        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 02 - TX Channel Select
        options = ["Last Channel", "Main Channel"]
        rx = RadioSettingValueList(options, options[_settings.txChSelect])
        rset = RadioSetting("basicsettings.txChSelect",
                            "Priority Transmit", rx)
        basic.append(rset)

        # Menu 03 - VOX Level
        rx = RadioSettingValueInteger(1, 7, _settings.voxLevel + 1)
        rset = RadioSetting("basicsettings.voxLevel", "Vox Level", rx)
        basic.append(rset)

        # Menu 05 - Squelch Level
        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rx = RadioSettingValueList(options, options[_settings.sqlLevel])
        rset = RadioSetting("basicsettings.sqlLevel", "Squelch Level", rx)
        basic.append(rset)

        # Menu 06 - Dual Wait
        rx = RadioSettingValueBoolean(_settings.dualWait)
        rset = RadioSetting("basicsettings.dualWait", "Dual Wait/Standby", rx)
        basic.append(rset)

        # Menu 07 - LED Mode
        if self.MODEL == "RA89":
            options = ["Off", "On", "5s", "10s", "15s", "20s", "25s", "30s"]
        else:
            options = ["Off", "On", "Auto"]
        rx = RadioSettingValueList(options, options[_settings.ledMode])
        rset = RadioSetting("basicsettings.ledMode", "LED Display Mode", rx)
        basic.append(rset)

        # Menu 08 - Light
        options = ["%s" % x for x in range(1, 8)]
        rx = RadioSettingValueList(options, options[_settings.light])
        rset = RadioSetting("basicsettings.light",
                            "Background Light Color", rx)
        basic.append(rset)

        # Menu 09 - Beep
        rx = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("basicsettings.beep", "Keypad Beep", rx)
        basic.append(rset)

        # Menu 11 - TOT
        options = ["Off"] + ["%s seconds" % x for x in range(30, 300, 30)]
        rx = RadioSettingValueList(options, options[_settings.tot])
        rset = RadioSetting("basicsettings.tot",
                            "Transmission Time-out Timer", rx)
        basic.append(rset)

        # Menu 13 - VOX Switch
        rx = RadioSettingValueBoolean(_settings.voxSw)
        rset = RadioSetting("basicsettings.voxSw", "Vox Switch", rx)
        basic.append(rset)

        # Menu 14 - Roger
        rx = RadioSettingValueBoolean(_settings.roger)
        rset = RadioSetting("basicsettings.roger", "Roger Beep", rx)
        basic.append(rset)

        # Menu 16 - Save Mode
        options = ["Off", "1:1", "1:2", "1:4"]
        rx = RadioSettingValueList(options, options[_settings.saveMode])
        rset = RadioSetting("basicsettings.saveMode", "Battery Save Mode", rx)
        basic.append(rset)

        # Menu 17 - Scan Type
        if self.MODEL == "QRZ-1":
            options = ["Time", "Carrier", "Stop"]
        else:
            options = ["TO", "CO", "SE"]
        rx = RadioSettingValueList(options, options[_settings.scanType])
        rset = RadioSetting("basicsettings.scanType", "Scan Type", rx)
        basic.append(rset)

        # Menu 18 - Key Lock
        rx = RadioSettingValueBoolean(_settings.keylock)
        rset = RadioSetting("basicsettings.keylock", "Auto Key Lock", rx)
        basic.append(rset)

        if self.MODEL != "QRZ-1":
            # Menu 19 - SW Audio
            rx = RadioSettingValueBoolean(_settings.swAudio)
            rset = RadioSetting("basicsettings.swAudio", "Voice Prompts", rx)
            basic.append(rset)

        # Menu 20 - Intro Screen
        if self.MODEL == "RA89":
            options = ["Off", "Voltage", "Character String", "Startup Logo"]
        else:
            options = ["Off", "Voltage", "Character String"]
        rx = RadioSettingValueList(options, options[_settings.introScreen])
        rset = RadioSetting("basicsettings.introScreen", "Intro Screen", rx)
        basic.append(rset)

        # Menu 32 - Key Mode
        options = ["ALL", "PTT", "KEY", "Key & Side Key"]
        rx = RadioSettingValueList(options, options[_settings.keyMode])
        rset = RadioSetting("basicsettings.keyMode", "Key Lock Mode", rx)
        basic.append(rset)

        # Menu 33 - Display Mode
        options = ['Frequency', 'Channel #', 'Name']
        rx = RadioSettingValueList(options, options[_settings.disMode])
        rset = RadioSetting("basicsettings.disMode", "Display Mode", rx)
        basic.append(rset)

        # Menu 34 - FM Dual Wait
        rx = RadioSettingValueBoolean(_settings.radioMoni)
        rset = RadioSetting("basicsettings.radioMoni", "Radio Monitor", rx)
        basic.append(rset)

        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group.append(advanced)

        # software only
        if self.MODEL == "RA89":
            options = ['Frequency', '120', '180', '240']
        else:
            options = ['Off', 'Frequency']
        rx = RadioSettingValueList(options, options[_settings.endToneElim])
        rset = RadioSetting("basicsettings.endToneElim", "End Tone Elim", rx)
        advanced.append(rset)

        # software only
        name = ""
        for i in range(15):  # 0 - 15
            char = chr(int(self._memobj.openradioname.name1[i]))
            if char == "\x00":
                char = " "  # Other software may have 0x00 mid-name
            name += char
        name = name.rstrip()  # remove trailing spaces

        rx = RadioSettingValueString(0, 15, name)
        rset = RadioSetting("openradioname.name1", "Intro Line 1", rx)
        advanced.append(rset)

        # software only
        name = ""
        for i in range(15):  # 0 - 15
            char = chr(int(self._memobj.openradioname.name2[i]))
            if char == "\x00":
                char = " "  # Other software may have 0x00 mid-name
            name += char
        name = name.rstrip()  # remove trailing spaces

        rx = RadioSettingValueString(0, 15, name)
        rset = RadioSetting("openradioname.name2", "Intro Line 2", rx)
        advanced.append(rset)

        # software only
        options = ['0.5S', '1.0S', '1.5S', '2.0S', '2.5S', '3.0S', '3.5S',
                   '4.0S', '4.5S', '5.0S']
        rx = RadioSettingValueList(options, options[_settings.voxDelay])
        rset = RadioSetting("basicsettings.voxDelay", "VOX Delay", rx)
        advanced.append(rset)

        options = ['Unlocked', 'Unknown 1', 'Unknown 2', 'EU', 'US']
        # extend option list with unknown description for values 5 - 15.
        for ix in range(len(options), _settings2.region + 1):
            item_to_add = 'Unknown {region_code}'.format(region_code=ix)
            options.append(item_to_add)
        # log unknown region codes greater than 4
        if _settings2.region > 4:
            LOG.debug("Unknown region code: {value}".
                      format(value=_settings2.region))
        rx = RadioSettingValueList(options, options[_settings2.region])
        rx.set_mutable(False)
        rset = RadioSetting("settings2.region", "Region", rx)
        advanced.append(rset)

        if self.MODEL == "RA89":
            options = ["None", "VOX", "Dual Wait", "Scan", "Moni", "1750 Tone",
                       "Flashlight", "Power Level", "Alarm",
                       "Noise Cancelaton", "Temp Monitor", "FM Radio",
                       "Talk Around", "Frequency Reverse"]
            rx = RadioSettingValueList(options, options[_settings.sideKey1])
            rset = RadioSetting("basicsettings.sideKey1", "Side Key 1", rx)
            advanced.append(rset)

            rx = RadioSettingValueList(options,
                                       options[_settings.sideKey1_long])
            rset = RadioSetting("basicsettings.sideKey1_long",
                                "Side Key 1 Long", rx)
            advanced.append(rset)

            rx = RadioSettingValueList(options,
                                       options[_settings.sideKey2])
            rset = RadioSetting("basicsettings.sideKey2",
                                "Side Key 2", rx)
            advanced.append(rset)

            rx = RadioSettingValueList(options,
                                       options[_settings.sideKey2_long])
            rset = RadioSetting("basicsettings.sideKey2_long",
                                "Side Key 2 Long", rx)
            advanced.append(rset)

        workmode = RadioSettingGroup("workmode", "Work Mode Settings")
        group.append(workmode)

        # Toggle with [#] key
        options = ["Frequency", "Channel"]
        rx = RadioSettingValueList(options, options[_workmode.vfomrmode])
        rset = RadioSetting("workmodesettings.vfomrmode", "VFO/MR Mode", rx)
        workmode.append(rset)

        # Toggle with [#] key
        options = ["Frequency", "Channel"]
        rx = RadioSettingValueList(options, options[_workmode.vfomrmodeb])
        rset = RadioSetting("workmodesettings.vfomrmodeb",
                            "VFO/MR Mode B", rx)
        workmode.append(rset)

        # Toggle with [A/B] key
        options = ["B", "A"]
        rx = RadioSettingValueList(options, options[_workmode.ab])
        rset = RadioSetting("workmodesettings.ab", "A/B Select", rx)
        workmode.append(rset)

        rx = RadioSettingValueInteger(1, CHAN_NUM, _workmode.mrAch + 1)
        rset = RadioSetting("workmodesettings.mrAch", "MR A Channel #", rx)
        workmode.append(rset)

        rx = RadioSettingValueInteger(1, CHAN_NUM, _workmode.mrBch + 1)
        rset = RadioSetting("workmodesettings.mrBch", "MR B Channel #", rx)
        workmode.append(rset)

        # Optional signaling
        def _set_namelen(setting, obj, atrb):
            vx = str(setting.value)
            vx = vx.rstrip()
            setattr(obj, atrb, vx.ljust(6, " "))
            setattr(obj, atrb+"len", len(vx))
            return

        def _add_namelen(setting, name, display, obj, atrb, maxlen,
                         value, valuelen):
            valname = ""
            for i in range(valuelen):
                char = chr(int(value[i]))
                if char == "\x00":
                    char = " "  # Other software may have 0x00 mid-name
                valname += char

            rx = RadioSettingValueString(0, maxlen, valname, False,
                                         self.VALID_CHARS)
            rset = RadioSetting(name, display, rx)
            rset.set_apply_callback(_set_namelen, obj, atrb)
            setting.append(rset)

        def _tel_encode(char):
            for i in range(len(OPTSIGTELDIGIT_LIST)):
                if OPTSIGTELDIGIT_LIST[i] == char:
                    return i
            return 0

        def _set_hexlen(setting, obj, atrb, maxlen):
            vx = str(setting.value)
            vx = vx.rstrip()
            vxlen = len(vx)
            vx = vx.ljust(maxlen, "0")
            hval = []
            LOG.debug(("HEXALEN %d:" % maxlen)+vx)
            for i in range(maxlen // 2):
                hval.append(_tel_encode(vx[2 * i]) * 16 + _tel_encode(vx[ 2 * i + 1]))

            if (maxlen % 2) == 1:
                setattr(obj, atrb + "last", _tel_encode(vx[maxlen - 1]))

            setattr(obj, atrb, hval)
            setattr(obj, atrb+"len", vxlen)
            return

        def _add_hexlen(setting, name, display, obj, atrb, maxlen,
                        value, valuelen):
            valname = ""
            for i in range(valuelen):
                if (i // 2) < len(value):
                    if (i % 2) == 0:
                        digit = int(value[i // 2]) // 16
                    else:
                        digit = int(value[i // 2]) % 16
                else:
                    digit = int(getattr(obj, atrb+"last"))

                # Convert
                valname += OPTSIGTELDIGIT_LIST[digit]

            rx = RadioSettingValueString(0, maxlen, valname, False,
                                         CHARSET_TEL)
            rset = RadioSetting(name, display, rx)
            rset.set_apply_callback(_set_hexlen, obj, atrb, maxlen)
            setting.append(rset)

        def _add_extdigit(setting, name, display, value, addoff):
            digits = OPTSIGEXTDIGIT_LIST.copy()
            if addoff:
                digits.insert(0, "OFF")
            digit = digits[value]
            rx = RadioSettingValueList(digits, digit)
            rset = RadioSetting(name, display, rx)
            setting.append(rset)

        def _add_ani(setting, name, display, value):
            ani = OPTSIGENCTYPE_LIST[value]
            rx = RadioSettingValueList(OPTSIGENCTYPE_LIST, ani)
            rset = RadioSetting(name, display, rx)
            setting.append(rset)

        def _add_time(setting, name, display, start, step, count,
                      format, value):
            options = []
            for i in range(count):
                options.append(format % (start + i * step))
            rx = RadioSettingValueList(options, options[value])
            rset = RadioSetting(name, display, rx)
            setting.append(rset)

        def _set_int10(setting, obj, atrb):
            setattr(obj, atrb, setting.value * 10)
            return

        def _add_int10(setting, name, display, obj, atrb, mini, maxi, value):
            rx = RadioSettingValueFloat(mini, maxi, value / 10, 0.1, 1)
            rset = RadioSetting(name, display, rx)
            # This callback uses the array index
            rset.set_apply_callback(_set_int10, obj, atrb)
            setting.append(rset)

        def _add_ttones_tone(setting, name, display, obj, atrb, value):
            _add_int10(setting, name, display, obj, atrb, 300.0, 3116.0, value)

        def _add_intname(setting, name, display, src, atrb, value):
            options = []
            for i in range(len(src)):
                asname = str(getattr(src[i], atrb))
                options.append("%02d - " % (i + 1) + asname)

            rx = RadioSettingValueList(options, options[value])
            rset = RadioSetting(name, display, rx)
            setting.append(rset)

        def _set_mask_array(setting, src, idx):
            _do_map(idx, bool(setting.value), src)
            return

        def _set_mask_int(setting, src, idx):
            _do_map_int(idx, bool(setting.value), src)
            return

        def _add_active(setting, name, display, src, idx, value, array):
            rx = RadioSettingValueBoolean(value)
            rset = RadioSetting(name, display, rx)
            if array:
                rset.set_apply_callback(_set_mask_array, src, idx)
            else:
                rset.set_apply_callback(_set_mask_int, src, idx)
            setting.append(rset)

        optsignal = RadioSettingGroup("optsignal", "Optional signaling")
        group.append(optsignal)

        dtmf = RadioSettingGroup("dtmf", "DTMF")
        optsignal.append(dtmf)

        # Delimiter
        _add_extdigit(dtmf, "optsignal.dtmf.delimiter", "Delimiter",
                      _optsignal.dtmf.delimiter, False)

        # Group
        _add_extdigit(dtmf, "optsignal.dtmf.group", "Group",
                      _optsignal.dtmf.group, True)

        # Speed
        options = ['50 ms', '100 ms', '200 ms', '300 ms', '500 ms']
        rx = RadioSettingValueList(options, options[_optsignal.dtmf.speed])
        rset = RadioSetting("optsignal.dtmf.speed", "Speed", rx)
        dtmf.append(rset)

        # First digit
        _add_time(dtmf, "optsignal.dtmf.firstdigit",
                  "First digit", 0, 0.1, 11, "%.1f s",
                  _optsignal.dtmf.firstdigit)

        # Autoreset time
        _add_time(dtmf, "optsignal.dtmf.autoresettime",
                  "Autoreset time", 0, 1, 26, "%d s",
                  _optsignal.dtmf.autoresettime)

        # ANI
        rv = RadioSettingValueBoolean(_optsignal.dtmf.ani)
        rx = RadioSetting("optsignal.dtmf.ani", "ANI", rv)
        dtmf.append(rx)

        # Stun
        _add_hexlen(dtmf, "optsignal.dtmf.stuncode", "Stun",
                    _optsignal.dtmf, "stuncode", 15,
                    _optsignal.dtmf.stuncode,
                    _optsignal.dtmf.stuncodelen)

        # Kill
        _add_hexlen(dtmf, "optsignal.dtmf.killcode", "Kill",
                    _optsignal.dtmf, "killcode", 15,
                    _optsignal.dtmf.killcode,
                    _optsignal.dtmf.killcodelen)

        dtmfenc = RadioSettingGroup("dtmfenc", "Encode")
        dtmf.append(dtmfenc)

        # Own ID
        _add_hexlen(dtmfenc, "optsignal.dtmf.ownid", "Own ID",
                    _optsignal.dtmf, "ownid", 8,
                    _optsignal.dtmf.ownid,
                    _optsignal.dtmf.ownidlen)

        # PTT ID
        self._add_pttid(dtmfenc, "optsignal.dtmf.pttid", "PTT ID",
                        _optsignal.dtmf.pttid)

        # PTT ID BEGIN
        _add_hexlen(dtmfenc, "optsignal.dtmf.pttidbegin", "PTT ID Begin",
                    _optsignal.dtmf, "pttidbegin", 24,
                    _optsignal.dtmf.pttidbegin,
                    _optsignal.dtmf.pttidbeginlen)

        # PTT ID END
        _add_hexlen(dtmfenc, "optsignal.dtmf.pttidend", "PTT ID End",
                    _optsignal.dtmf, "pttidend", 24,
                    _optsignal.dtmf.pttidend,
                    _optsignal.dtmf.pttidendlen)

        # Sidetone
        rv = RadioSettingValueBoolean(_optsignal.dtmf.sidetone)
        rx = RadioSetting("optsignal.dtmf.sidetone", "Sidetone", rv)
        dtmfenc.append(rx)

        # Select channel
        options = ['1', '2', '3', '4', '5', '6', '7', '8',
                   '9', '10', '11', '12', '13', '14', '15', '16']
        rx = RadioSettingValueList(options, options[_settings.dtmfch])
        rset = RadioSetting("basicsettings.dtmfch", "Select channel", rx)
        dtmfenc.append(rset)

        # Encode channels
        for i in range(16):  # 0 - 15
            sigchan = RadioSettingSubGroup("dtmfencchan%d" % i,
                                           "Channel %02d" % (i + 1))
            dtmfenc.append(sigchan)

            # Active
            _add_active(sigchan, "active_%d" % i, "Active",
                        _optsignal.dtmf.encodemask, i + 1,
                        _do_map(i + 1, 2, _optsignal.dtmf.encodemask), True)

            # ANI
            _add_ani(sigchan, "optsignal.dtmf.encode/%d.ani" % i, "Type",
                     _optsignal.dtmf.encode[i].ani)

            # Code
            _add_hexlen(sigchan, "optsignal.dtmf.encode/%d.code" % i, "Code",
                        _optsignal.dtmf.encode[i], "code", 24,
                        _optsignal.dtmf.encode[i].code,
                        _optsignal.dtmf.encode[i].codelen)

        ttones = RadioSettingGroup("ttones", "2 Tones")
        optsignal.append(ttones)

        # First tone
        _add_time(ttones, "optsignal.ttones.firsttone",
                  "First tone", 0.5, 0.1, 96, "%.1f s",
                  _optsignal.ttones.firsttone)

        # Second tone
        _add_time(ttones, "optsignal.ttones.secondtone",
                  "Second tone", 0.5, 0.1, 96, "%.1f s",
                  _optsignal.ttones.secondtone)

        # Long tone
        _add_time(ttones, "optsignal.ttones.longtone",
                  "Long tone", 0.5, 0.1, 96, "%.1f s",
                  _optsignal.ttones.longtone)

        # Interval
        _add_time(ttones, "optsignal.ttones.intervaltime",
                  "Interval", 0, 0.1, 21, "%.1f s",
                  _optsignal.ttones.intervaltime)

        # Auto reset time
        _add_time(ttones, "optsignal.ttones.autoresettime",
                  "Auto reset time", 0, 1, 26, "%d s",
                  _optsignal.ttones.autoresettime)

        # Encode settings
        ttonesenc = RadioSettingGroup("ttonesenc", "Encode")
        ttones.append(ttonesenc)

        # Sidetone
        rv = RadioSettingValueBoolean(_optsignal.ttones.sidetone)
        rx = RadioSetting("optsignal.ttones.sidetone", "Sidetone", rv)
        ttonesenc.append(rx)

        # Select channel
        _add_intname(ttonesenc, "basicsettings.ttonesch", "Select channel",
                     _optsignal.ttones.encode, "name",
                     _settings.ttonesch)

        # 16 encode channels
        for i in range(16):  # 0 - 15
            sigchan = RadioSettingSubGroup("ttonesencchan%d" % i,
                                           "Channel %02d" % (i + 1))
            ttonesenc.append(sigchan)

            # Active
            _add_active(sigchan, "active_%d" % i, "Active",
                        _optsignal.ttones.encodemask, i + 1,
                        _do_map(i + 1, 2, _optsignal.ttones.encodemask), True)

            # Name
            _add_namelen(sigchan, "name_%d" % i, "Name",
                         _optsignal.ttones.encode[i],
                         "name", 6,
                         _optsignal.ttones.encode[i].name,
                         _optsignal.ttones.encode[i].namelen)

            # First Tone
            _add_ttones_tone(sigchan, "tone1_%d" % i, "First Tone",
                             _optsignal.ttones.encode[i],
                             "tone1", _optsignal.ttones.encode[i].tone1)

            # Second Tone
            _add_ttones_tone(sigchan, "tone2_%d" % i, "Second Tone",
                             _optsignal.ttones.encode[i],
                             "tone2", _optsignal.ttones.encode[i].tone2)

        # Decode settings
        ttonesdec = RadioSettingGroup("ttonesdec", "Decode")
        ttones.append(ttonesdec)

        # Format
        options = ['A-B', 'A-C', 'A-D', 'B-A', 'B-C', 'B-D',
                   'C-A', 'C-B', 'C-D', 'D-A', 'D-B', 'D-C',
                   'Long A', 'Long B', 'Long C', 'Long D']
        rx = RadioSettingValueList(options, options[_optsignal.ttones.format])
        rset = RadioSetting("optsignal.ttones.format", "Format", rx)
        ttonesdec.append(rset)

        # A tone
        _add_ttones_tone(ttonesdec, "tone1", "A Tone",
                         _optsignal.ttones,
                         "tone1", _optsignal.ttones.tone1)

        # B tone
        _add_ttones_tone(ttonesdec, "tone2", "B Tone",
                         _optsignal.ttones,
                         "tone2", _optsignal.ttones.tone2)

        # C tone
        _add_ttones_tone(ttonesdec, "tone3", "C Tone",
                         _optsignal.ttones,
                         "tone3", _optsignal.ttones.tone3)

        # D tone
        _add_ttones_tone(ttonesdec, "tone4", "D Tone",
                         _optsignal.ttones,
                         "tone4", _optsignal.ttones.tone4)

        # Five tones settings
        ftones = RadioSettingGroup("ftones", "5 Tones")
        optsignal.append(ftones)

        # Standard
        options = ['ZVEI 1', 'PZVEI 1', 'ZVEI 2', 'ZVEI 3', 'DZVEI',
                   'PDZVEI', 'CCIR 1', 'CCIR 2', 'PCCIR', 'EEA',
                   'Euro Signal', 'Natel', 'Modat', 'CCITT']
        rx = RadioSettingValueList(options, options[_optsignal.ftones.mode])
        rset = RadioSetting("optsignal.ftones.mode", "Standard", rx)
        ftones.append(rset)

        # Digit Length
        rx = RadioSettingValueInteger(70, 255, _optsignal.ftones.digitlen)
        rset = RadioSetting("optsignal.ftones.digitlen", "Digit Length (ms)",
                            rx)
        ftones.append(rset)

        # Delimiter
        _add_extdigit(ftones, "optsignal.ftones.delimiter", "Delimiter",
                      _optsignal.ftones.delimiter, False)

        # Group
        _add_extdigit(ftones, "optsignal.ftones.group", "Groupe",
                      _optsignal.ftones.group, False)

        # Repeater
        _add_extdigit(ftones, "optsignal.ftones.repeater", "Repeater",
                      _optsignal.ftones.repeater, False)

        # Auto reset time
        _add_time(ftones, "optsignal.ftones.autoresettime",
                  "Auto reset time", 0, 1, 26, "%d s",
                  _optsignal.ftones.autoresettime)

        # Encode settings
        ftonesenc = RadioSettingGroup("ftonesenc", "Encode")
        ftones.append(ftonesenc)

        # Own ID
        _add_hexlen(ftonesenc, "optsignal.ftones.ownid", "Own ID",
                    _optsignal.ftones, "ownid", 8,
                    _optsignal.ftones.ownid,
                    _optsignal.ftones.ownidlen)

        # First Digit
        _add_time(ftones, "optsignal.ftones.firstdigit",
                  "First Digit", 0, 100, 11, "%d ms",
                  _optsignal.ftones.firstdigit)

        # PTT ID
        self._add_pttid(ftonesenc, "optsignal.ftones.pttid", "PTT ID",
                        _optsignal.ftones.pttid)

        # PTT ID Begin
        _add_hexlen(ftonesenc, "optsignal.ftones.pttidbegin", "PTT ID Begin",
                    _optsignal.ftones, "pttidbegin", 8,
                    _optsignal.ftones.pttidbegin,
                    _optsignal.ftones.pttidbeginlen)

        # PTT ID End
        _add_hexlen(ftonesenc, "optsignal.ftones.pttidend", "PTT ID End",
                    _optsignal.ftones, "pttidend", 8,
                    _optsignal.ftones.pttidend,
                    _optsignal.ftones.pttidendlen)

        # Sidetone
        rv = RadioSettingValueBoolean(_optsignal.ftones.sidetone)
        rx = RadioSetting("optsignal.ftones.sidetone", "Sidetone", rv)
        ftonesenc.append(rx)

        # Select channel
        _add_intname(ftonesenc, "basicsettings.ftonesch", "Select channel",
                     _optsignal.ftones.encode, "name",
                     _settings.ftonesch)

        # 16 Encode channels
        for i in range(16):  # 0 - 15
            sigchan = RadioSettingSubGroup("ftonesencchan%d" % i,
                                           "Channel %02d" % (i + 1))
            ftonesenc.append(sigchan)

            # Active
            _add_active(sigchan, "active_%d" % i, "Active",
                        _optsignal.ftones.encodemask, i + 1,
                        _do_map(i + 1, 2, _optsignal.ftones.encodemask), True)

            # Name
            _add_namelen(sigchan, "name_%d" % i, "Name",
                         _optsignal.ftones.encode[i],
                         "name", 6,
                         _optsignal.ftones.encode[i].name,
                         _optsignal.ftones.encode[i].namelen)

            # Type
            _add_ani(sigchan, "optsignal.ftones.encode/%d.type" % i, "Type",
                     _optsignal.ftones.encode[i].type)

            # Call ID
            _add_hexlen(sigchan, "optsignal.ftones.encode/%d.callid" % i,
                        "Call ID",
                        _optsignal.ftones.encode[i], "callid", 8,
                        _optsignal.ftones.encode[i].callid,
                        _optsignal.ftones.encode[i].callidlen)

        ftonesdec = RadioSettingGroup("ftonesdec", "Decode")
        ftones.append(ftonesdec)

        # 8 Decode channels
        for i in range(8):  # 0 - 7
            sigchan = RadioSettingSubGroup("ftonesencchan%d" % i,
                                           "Channel %02d" % (i + 1))
            ftonesdec.append(sigchan)

            # Active
            _add_active(sigchan, "active_%d" % i, "Active",
                        _optsignal.ftones.decodemask, i + 1,
                        _do_map_int(i + 1, 2, _optsignal.ftones.decodemask),
                        False)

            # Name
            _add_namelen(sigchan, "chname_%d" % i, "Name",
                         _optsignal.ftones.decode[i],
                         "chname", 6,
                         _optsignal.ftones.decode[i].chname,
                         _optsignal.ftones.decode[i].chnamelen)

            # Function
            options = ['Select', 'Stun', 'Kill', 'Wake']
            value = options[_optsignal.ftones.decode[i].function]
            rx = RadioSettingValueList(options, value)
            rset = RadioSetting("optsignal.ftones.decode/%d.function" % i,
                                "Function", rx)
            sigchan.append(rset)

            # Code
            _add_hexlen(sigchan, "optsignal.ftones.decode/%d.code" % i, "Code",
                        _optsignal.ftones.decode[i], "code", 12,
                        _optsignal.ftones.decode[i].code,
                        _optsignal.ftones.decode[i].codelen)

        fmb = RadioSettingGroup("fmradioc", "FM Radio Settings")
        group.append(fmb)

        def myset_mask(setting, obj, atrb, nx):
            _do_map(nx + 1, bool(setting.value), self._memobj.fmmap.fmset)
            return

        def myset_fmfrq(setting, obj, atrb, nx):
            """ Callback to set xx.x FM freq in memory as xx.x * 100000"""
            # in-valid even kHz freqs are allowed; to satisfy run_tests
            vx = float(str(setting.value))
            vx = int(vx * 100000)
            setattr(obj[nx], atrb, vx)
            return

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        _fmx = self._memobj.fmfrqs

        # FM Broadcast Manual Settings
        val = _fmx.fmcur
        val = val / 100000.0
        if val < 64.0 or val > 108.0:
            val = 100.7
        rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
        rset = RadioSetting("fmfrqs.fmcur", "Manual FM Freq (MHz)", rx)
        rset.set_apply_callback(myset_freq, _fmx, "fmcur", 100000)
        fmb.append(rset)

        _fmfrq = self._memobj.fm_stations
        _fmap = self._memobj.fmmap

        # FM Broadcast Presets Settings
        for j in range(0, 24):
            val = _fmfrq[j].rxfreq
            if val < 6400000 or val > 10800000:
                val = 88.0
                fmset = False
            else:
                val = (float(int(val)) / 100000)
                # get fmmap bit value: 1 = enabled
                ndx = int(math.floor((j) / 8))
                bv = j % 8
                msk = 1 << bv
                vx = _fmap.fmset[ndx]
                fmset = bool(vx & msk)
            rx = RadioSettingValueBoolean(fmset)
            rset = RadioSetting("fmmap.fmset/%d" % j,
                                "FM Preset %02d" % (j + 1), rx)
            rset.set_apply_callback(myset_mask, _fmap, "fmset", j)
            fmb.append(rset)

            rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
            rset = RadioSetting("fm_stations/%d.rxfreq" % j,
                                "    Preset %02d Freq" % (j + 1), rx)
            # This callback uses the array index
            rset.set_apply_callback(myset_fmfrq, _fmfrq, "rxfreq", j)
            fmb.append(rset)

        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.basicsettings
        _mem = self._memobj
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
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "mrAch" or setting == "mrBch":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "voxLevel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise


@directory.register
class RT85(THUV88Radio):
    VENDOR = "Retevis"
    MODEL = "RT85"


@directory.register
class RA89(THUV88Radio):
    VENDOR = "Retevis"
    MODEL = "RA89"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0" + b"UV99" + b"\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2" + b"UV99" + b"\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3" + b"UV99" + b"\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + b"UV99" + b"\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + b"UV99"

    def process_mmap(self):
        """Process the mem map into the mem object"""
        mem_format = MEM_FORMAT + RA89_SETTINGS + MEM_FORMAT_PT2
        self._memobj = bitwise.parse(mem_format, self._mmap)


@directory.register
class QRZ1(THUV88Radio):
    VENDOR = "Explorer"
    MODEL = "QRZ-1"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0" + b"UV78" + b"\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2" + b"UV78" + b"\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3" + b"UV78" + b"\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + b"UV78" + b"\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + b"UV78"
