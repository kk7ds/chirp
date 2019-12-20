# Copyright 2019 Rick DeWitt <aa0rd@yahoo.com>
# Version 1.0: CatClone- Implementing fake memory image
# Version 2.0: No Live Mode library links. Implementing mem as Clone Mode
#              Having fun with Dictionaries
# Version 2.1: Adding match_model function to fix File>New issue #7409
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

import time
import struct
import logging
import re
import math
import threading
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
struct {            // 20 bytes per chan
  u32  rxfreq;
  u32  txfreq;
  u8   xmode:4,     // param stored as CAT value
       data:2,
       tmode:2;
  u8   rtone;
  u8   ctone;
  u8   filter:1,
       fmnrw:1,
       skip:1,
       nu:5;
  char name[8];
} ch_mem[120];   // 100 normal + 10 P-type + 10 EXT

struct {        // 5 bytes each
  u32 asfreq;
  u8  asmode:4,     // param stored as CAT value
      asdata:2,
      asnu:2;
} asf[32];

struct {        // 10 x 5 4-byte frequencies
  u32  ssfreq;
} ssf[50];

struct {        // 16 bytes
  u8  txeq;
  u8  rxeq;
} eqx[8];

struct {        // Common to S and SG models
  u8   ag;
  u8   an1:2,
       an2:2,
       an3:2,
       anu:2;
  u32  fa;
  u32  fb;
  char fv[4];
  u8   mf;
  u8   mg;
  u8   pc;
  u8   rg;
  u8   tp;
} settings;

struct {            // Menu A/B settings by TS-590SG names
  char ex001[8];    // 590S values get put in SG equiv
  u8   ex002;       // These params stored as nibbles
  u8   ex003;
  u8   ex005;
  u8   ex006;
  u8   ex007;
  u8   ex008;
  u8   ex009;
  u8   ex010;
  u8   ex011;
  u8   ex012;
  u8   ex013;
  u8   ex016;
  u8   ex017;
  u8   ex018;
  u8   ex019;
  u8   ex021;
  u8   ex022;
  u8   ex023;
  u8   ex024;
  u8   ex025;
  u8   ex026;
  u8   ex054;
  u8   ex055;
  u8   ex076;
  u8   ex077;
  u8   ex087;
  u8   ex088;
  u8   ex089;
  u8   ex090;
  u8   ex091;
  u8   ex092;
  u8   ex093;
  u8   ex094;
  u8   ex095;
  u8   ex096;
  u8   ex097;
  u8   ex098;
  u8   ex099;
} exset[2];

  char mdl_name[9];     // appended model name, first 9 chars

"""

STIMEOUT = 2
LOCK = threading.Lock()
BAUD = 0    # Initial baud rate
MEMSEL = 0  # Default Menu A
BEEPVOL = 4     # Default beep volume
W8S = 0.01      # short wait, secs
W8L = 0.05      # long wait

TS590_DUPLEX = ["", "-", "+"]
TS590_SKIP = ["", "S"]

# start at 0:LSB
TS590_MODES = ["LSB", "USB", "CW", "FM", "AM", "FSK", "CW-R",
               "FSK-R", "Data+LSB", "Data+USB", "Data+FM"]
EX_MODES = ["FSK-R", "CW-R", "Data+LSB", "Data+USB", "Data+FM"]
for ix in EX_MODES:
    if ix not in chirp_common.MODES:
        chirp_common.MODES.append(ix)

TS590_TONES = list(chirp_common.TONES)
TS590_TONES.append(1750.0)

RADIO_IDS = {   # From kenwood_live.py; used to report wrong radio
    "ID019;": "TS-2000",
    "ID009;": "TS-850",
    "ID020;": "TS-480",
    "ID021;": "TS-590S",
    "ID023;": "TS-590SG"
}


def command(ser, cmd, rsplen, w8t=0.01, exts=""):
    """Send @cmd to radio via @ser"""
    # cmd is output string without ; terminator
    # rsplen is expected response char count, including terminator
    #       If rsplen = 0 then do not read after write

    start = time.time()
    #   LOCK.acquire()
    stx = cmd       # preserve cmd for response check
    stx = stx + exts + ";"    # append arguments
    ser.write(stx)
    LOG.debug("PC->RADIO [%s]" % stx)
    ts = time.time()        # implement the wait after command
    while (time.time() - ts) < w8t:
        ix = 0      # NOP
    result = ""
    if rsplen > 0:  # read response
        result = ser.read(rsplen)
        LOG.debug("RADIO->PC [%s]" % result)
        result = result[:-1]        # remove terminator
    #   LOCK.release()
    return result.strip()


def _connect_radio(radio):
    """Determine baud rate and verify radio on-line"""
    global BAUD        # Allows modification
    bauds = [115200, 57600, 38400, 19200, 9600, 4800]
    if BAUD > 0:
        bauds.insert(0, BAUD)       # Make the detected one first
    # Flush the input buffer
    radio.pipe.timeout = 0.005
    radio.pipe.baudrate = 9600
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT

    for bd in bauds:
        radio.pipe.baudrate = bd
        BAUD = bd
        radio.pipe.write(";")
        radio.pipe.write(";")
        resp = radio.pipe.read(4)
        radio.pipe.write("ID;")
        resp = radio.pipe.read(6)

        if resp == radio.ID:           # Good comms
            resp = command(radio.pipe, "AI0", 0, W8L)
            return
        elif resp in RADIO_IDS.keys():
            msg = "Radio reported as model %s, not %s!" % \
                (RADIO_IDS[resp], radio.MODEL)
            raise errors.RadioError(msg)
    raise errors.RadioError("No response from radio")
    return


def read_str(radio, trm=";"):
    """ Read chars until terminator """
    stq = ""
    ctq = ""
    while ctq != trm:
        ctq = radio.pipe.read(1)
        stq += ctq
    LOG.debug("   + [%s]" % stq)
    return stq[:-1]     # Return without trm


def _read_mem(radio):
    """Get the memory map"""
    global BEEPVOL
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._upper + 20  # 10 P chans and 10 EXT
    status.msg = "Reading Channel Memory..."
    radio.status_fn(status)

    result0 = command(radio.pipe, "EX0050000", 9, W8S)
    result0 += read_str(radio)
    BEEPVOL = int(result0[6:])
    result0 = command(radio.pipe, "EX005000000", 0, W8L)   # Silence beeps

    data = ""
    mrlen = 41      # Expected fixed return string length
    for chn in range(0, (radio._upper + 21)):   # Loop stops at +20
        # Request this mem chn
        r0ch = 999
        r1ch = r0ch
        # return results can come back out of order
        while (r0ch != chn):
            # simplex
            if chn < 100:
                result0 = command(radio.pipe, "MR0 %02i" % chn,
                                  mrlen, W8S)
                result0 += read_str(radio)
            else:
                result0 = command(radio.pipe, "MR0%03i" % chn,
                                  mrlen, W8S)
                result0 += read_str(radio)
            r0ch = int(result0[3:6])
        while (r1ch != chn):
            # split
            if chn < 100:
                result1 = command(radio.pipe, "MR1 %02i" % chn,
                                  mrlen, W8S)
                result1 += read_str(radio)
            else:
                result1 = command(radio.pipe, "MR1%03i" % chn,
                                  mrlen, W8S)
                result1 += read_str(radio)
            r1ch = int(result1[3:6])
        data += radio._parse_mem_spec(result0, result1)
        # UI Update
        status.cur = chn
        status.msg = "Reading Channel Memory..."
        radio.status_fn(status)

    if len(data) == 0:       # To satisfy run_tests
        raise errors.RadioError('No data received.')
    return data


def _make_dat(sx, nb):
    """ Split the string sx into nb binary bytes """
    vx = int(sx)
    dx = ""
    if nb > 3:
        dx += chr((vx >> 24) & 0xFF)
    if nb > 2:
        dx += chr((vx >> 16) & 0xFF)
    if nb > 1:
        dx += chr((vx >> 8) & 0xFF)
    dx += chr(vx & 0xFF)
    return dx


def _sets_val(stx, nv=3, nb=2):
    """ Split string stx into nv nb-bit values in 1 byte """
    # Right now: hardcoded for nv:3 values of nb:2 bits each
    v1 = int(stx[0]) << 6
    v1 = v1 | (int(stx[1]) << 4)
    v1 = v1 | (int(stx[2]) << 2)
    return chr(v1)


def _sets_asf(stx):
    """ Process AS0 auto-mode setting """
    asm = _make_dat(stx[0:11], 4)   # 11-bit freq
    a1 = int(stx[11])               # 4-bit mode
    a2 = int(stx[12])               # 2-bit data
    asm += chr((a1 << 4) | (a2 << 2))
    return asm


def my_val_list(setting, opts, obj, atrb, fix=0, ndx=-1):
    """Callback:from ValueList. Set the integer index."""
    # This function is here to be available to get_mem and get_set
    # fix is optional additive offset to the list index
    # ndx is optional obj[ndx] array index
    value = opts.index(str(setting.value))
    value += fix
    if ndx >= 0:    # indexed obj
        setattr(obj[ndx], atrb, value)
    else:
        setattr(obj, atrb, value)
    return


def _read_settings(radio):
    """ Continue filling memory map"""
    global MEMSEL
    # setc: the list of CAT commands for downloaded settings
    # Block paramters first. In the exact order of MEM_FORMAT
    setc = radio.SETC
    setc.extend(radio.EX)  # Menu A EX params
    setc.extend(radio.EX)  # Menu B
    status = chirp_common.Status()
    status.cur = 0
    status.max = 32 + 50 + 8 + 11 + 39 + 39
    status.msg = "Reading Settings..."
    radio.status_fn(status)

    setts = ""
    nc = 0
    for cmc in setc:
        skipme = False
        argx = ""           # Extended arguments
        if cmc == "AS0":
            skipme = True   # flag to disable further processing
            for ix in range(32):        # 32 AS params
                result0 = command(radio.pipe, cmc, 19, W8S,
                                  "%02i" % ix)
                xc = len(cmc) + 2
                result0 = result0[xc:]
                setts += _sets_asf(result0)
                nc += 1
                status.cur = nc
                radio.status_fn(status)
        elif cmc == "SS":
            skipme = True
            for ix in range(10):     # 10 chans
                for nx in range(5):     # 5 spots
                    result0 = command(radio.pipe, cmc, 16, W8S,
                                      "%1i%1i" % (ix, nx))
                    setts += _make_dat(result0[4:], 4)
                    nc += 1
                    status.cur = nc
                    radio.status_fn(status)
        elif cmc == "EQ":
            skipme = True
            for ix in range(8):
                result0 = command(radio.pipe, cmc, 6, W8S, "0%1i"
                                  % ix)   # Tx eq
                setts += chr(int(result0[4:]))    # 'EQ13x", want the x
                result0 = command(radio.pipe, cmc, 6, W8S, "1%1i"
                                  % ix)   # Rx eq
                setts += chr(int(result0[4:]))
                nc += 1
                status.cur = nc
                radio.status_fn(status)
        elif ((not radio.SG) and (cmc == "EX087")) \
                or (radio.SG and (cmc == "EX001")):
            result0 = command(radio.pipe, cmc, 9, W8S, "0000")
            result0 += read_str(radio)    # Read pwron message
            result0 = result0[8:]
            nx = len(result0)
            for ix in range(8):
                if ix < nx:
                    sx = result0[ix]    # may need to test valid char
                    setts += sx
                else:
                    setts += chr(0)
            skipme = True
            nc += 1
            status.cur = nc
            radio.status_fn(status)
        elif (cmc == "MF0") or (cmc == "MF1"):
            result0 = command(radio.pipe, cmc, 0, W8S)
            skipme = True   # cmd only, no response
        else:   # issue the cmc cmd as-is with argx
            if str(cmc).startswith("EX"):
                argx = "0000"
            result0 = command(radio.pipe, cmc, 0, W8S, argx)
            result0 = read_str(radio)    # various length responses
            # strip the cmd echo
            xc = len(cmc)
            result0 = result0[xc:]
        # Cmd has been sent, process the result
        if cmc == "FV":      # all chars
            skipme = True
            setts += result0
        elif cmc == "AN":    # Antenna selection has 3 values
            skipme = True
            setts += _sets_val(result0, 3, 2)   # store as 2-bits each
        elif (cmc == "FA") or (cmc == "FB"):    # Response is 11-bit frq
            skipme = True
            setts += _make_dat(result0, 4)   # 11-bit freq
        elif (cmc == "MF0") or (cmc == "MF1"):  # No stored response
            skipme = True
        # Generic single byte processing
        if not skipme:
            setts += chr(int(result0))
        if cmc == "MF":     # Save the initial Menu selection
            MEMSEL = int(result0)
        nc += 1
        status.cur = nc
        radio.status_fn(status)
    setts += radio.MODEL.ljust(9)
    # Now set the inidial menu selection back
    result0 = command(radio.pipe, "MF", 0, W8L, "%1i" % MEMSEL)
    # And the original Beep Volume
    result0 = command(radio.pipe, "EX0050000%2i" % BEEPVOL, 0, W8L)
    return setts


def _write_mem(radio):
    """ Send MW commands for each channel """
    global BEEPVOL
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._upper + 20  # 10 P chans and 10 EXT
    status.msg = "Writing Channel Memory"
    radio.status_fn(status)

    result0 = command(radio.pipe, "EX0050000", 9, W8S)
    result0 += read_str(radio)
    BEEPVOL = int(result0[6:])
    result0 = command(radio.pipe, "EX005000000", 0, W8L)   # Silence beeps

    for chn in range(0, (radio._upper + 21)):   # Loop stops at +20
        _mem = radio._memobj.ch_mem[chn]
        cmx = "MW0 %02i" % chn
        if chn > 99:
            cmx = "MW0%03i" % chn
        stm = cmx + radio._make_base_spec(_mem, _mem.rxfreq)
        result0 = command(radio.pipe, stm, 0, W8L)     # No response
        cmx = "MW1 %02i" % chn
        if chn > 99:
            cmx = "MW1%03i" % chn
        stm = cmx + radio._make_base_spec(_mem, _mem.txfreq)
        if _mem.rxfreq > 0:         # Dont write MW1 if empty
            result0 = command(radio.pipe, stm, 0, W8L)
        # UI Update
        status.cur = chn
        radio.status_fn(status)
    return


def _write_sets(radio):
    """ Send settings and Menu a/b """
    status = chirp_common.Status()
    status.cur = 0
    status.max = 187   # Total to send
    status.msg = "Writing Settings"
    radio.status_fn(status)
    # Define mem struct shortcuts
    _sets = radio._memobj.settings
    _asf = radio._memobj.asf
    _ssf = radio._memobj.ssf
    _eqx = radio._memobj.eqx
    _mex = radio._memobj.exset
    snx = 0     # Settings status counter
    stlen = 0   # No response count
    # Send 32 AS
    for ix in range(32):
        scm = "AS0%02i%011i%1i%1i" % (ix, _asf[ix].asfreq,
                                      _asf[ix].asmode, _asf[ix].asdata)
        result0 = command(radio.pipe, scm, stlen, W8S)
        snx += 1
        status.cur = snx
        radio.status_fn(status)
    # Send 50 SS
    for ix in range(10):
        for kx in range(5):
            nx = ix * 5 + kx
            scm = "SS%1i%1i%011i" % (ix, kx, _ssf[nx].ssfreq)
            result0 = command(radio.pipe, scm, stlen, W8S)
            snx += 1
            status.cur = snx
            radio.status_fn(status)
    # Send 16 EQ
    for ix in range(8):
        scm = "EQ0%1i%1i" % (ix, _eqx[ix].txeq)
        result0 = command(radio.pipe, scm, stlen, W8S)
        scm = "EQ1%1i%1i" % (ix, _eqx[ix].rxeq)
        result0 = command(radio.pipe, scm, stlen, W8S)
        snx += 2
        status.cur = snx
        radio.status_fn(status)
    # Send 11 thingies
    scm = "AG0%03i" % _sets.ag
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "AN%1i%1i%1i" % (_sets.an1, _sets.an2, _sets.an3)
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "FA%011i" % _sets.fa
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "FB%011i" % _sets.fb
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "MG%03i" % _sets.mg
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "PC%03i" % _sets.pc
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "RG%03i" % _sets.rg
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "TP%03i" % _sets.tp
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "MF0"   # Select menu A/B
    result0 = command(radio.pipe, scm, stlen, W8S)
    snx += 11
    status.cur = snx
    radio.status_fn(status)
    # Send 38 Menu A EX
    setc = radio.EX     # list of EX cmds
    for ix in range(2):
        for cmx in setc:
            if str(cmx)[0:2] == "MF":
                scm = cmx
            else:       # The EX cmds
                # Test for the power-on string
                if (radio.SG and cmx == "EX001") or \
                        ((not radio.SG) and cmx == "EX087"):
                    scm = cmx + "0000"
                    for chx in _mex[ix].ex001:  # Both get string here
                        scm += chr(chx)
                    scm = scm.strip()
                    scm = scm.strip(chr(0))     # in case any got thru
                # Now for the other EX cmds
                else:
                    if radio.SG:
                        scm = "%s0000%i" % (cmx, getattr(_mex[ix],
                                            cmx.lower()))
                    else:   # Gotta use the cross reference dict for cmd
                        scm = "%s0000%i" % (cmx, getattr(_mex[ix],
                                            radio.EX_X[cmx].lower()))
            result0 = command(radio.pipe, scm, stlen, W8S)
            snx += 1
            status.cur = snx
            radio.status_fn(status)
    # Now set the inidial menu selection back
    result0 = command(radio.pipe, "MF", 0, W8L, "%1i" % _sets.mf)
    # And the original Beep Volume
    result0 = command(radio.pipe, "EX0050000%2i" % BEEPVOL, 0, W8L)
    return


@directory.register
class TS590Radio(chirp_common.CloneModeRadio):
    """Kenwood TS-590"""
    VENDOR = "Kenwood"
    MODEL = "TS-590SG_CloneMode"
    ID = "ID023;"
    SG = True
    # Settings read/write cmd sequence list
    SETC = ["AS0", "SS", "EQ", "AG0", "AN", "FA", "FB",
            "FV", "MF", "MG", "PC", "RG", "TP", "MF0"]
    # This is the TS-590SG MENU A/B read_settings paramter tuple list
    # The order is mandatory; to match the Mem_Format sequence
    EX = ["EX001", "EX002", "EX003", "EX005", "EX006", "EX007",
          "EX008", "EX009", "EX010", "EX011", "EX012", "EX013", "EX016",
          "EX017", "EX018", "EX019", "EX021", "EX022", "EX023", "EX024",
          "EX025", "EX026", "EX054", "EX055", "EX076", "EX077", "EX087",
          "EX088", "EX089", "EX090", "EX091", "EX092", "EX093", "EX094",
          "EX095", "EX096", "EX097", "EX098", "EX099", "MF1"]
    # EX menu settings label dictionary. Key is the EX number
    EX_LBL = {2: " Display brightness",
              1: " Power-On message",
              3: " Backlight color",
              5: " Beep volume",
              6: " Sidetone volume",
              7: " Message playback volume",
              8: " Voice guide volume",
              9: " Voice guide speed",
              10: " Voice guide language",
              11: " Auto Announcement",
              12: " MHz step",
              13: " Tuning control adj rate (Hz)",
              16: " SSB tune step (KHz)",
              17: " CW/FSK tune step (KHz)",
              18: " AM tune step (KHz)",
              19: " FM tune step (KHz)",
              21: " Max number of Quick Mem chans",
              22: " Temporary MR Chan freq allowed",
              23: " Program Scan slowdown",
              24: " Program Scan slowdown range (Hz)",
              25: " Program Scan hold",
              26: " Scan Resume method",
              54: " TX Power fine adjust",
              55: " Timeout timer (Secs)",
              76: " Data VOX",
              77: " Data VOX delay (x30 mSecs)",
              87: " Panel PF-A function",
              88: " Panel PF-B function",
              89: " RIT key function",
              90: " XIT key function",
              91: " CL key function",
              92: " Front panel MULTI/CH key (non-CW mode)",
              93: " Front panel MULTI/CH key (CW mode)",
              94: " MIC PF1 function",
              95: " MIC PF2 function",
              96: " MIC PF3 function",
              97: " MIC PF4 function",
              98: " MIC PF (DWN) function",
              99: " MIC PF (UP) function"}

    BAUD_RATE = 115200
    _upper = 99

    # Special Channels Declaration
    # WARNING Indecis are hard wired in get/set_memory code !!!
    # Channels print in + increasing index order
    SPECIAL_MEMORIES = {"EXT 0": 110,
                        "EXT 1": 111,
                        "EXT 2": 112,
                        "EXT 3": 113,
                        "EXT 4": 114,
                        "EXT 5": 115,
                        "EXT 6": 116,
                        "EXT 7": 117,
                        "EXT 8": 118,
                        "EXT 9": 119}

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.can_odd_split = False
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = True
        rf.has_settings = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_tuning_step = False  # Not in mem chan
        rf.has_nostep_tuning = True     # Radio accepts any entered freq
        rf.has_cross = True
        rf.has_comment = False
        rf.memory_bounds = (0, self._upper)
        rf.valid_bands = [(30000, 24999999), (25000000, 59999999)]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "*+-/"
        rf.valid_duplexes = TS590_DUPLEX
        rf.valid_modes = TS590_MODES
        rf.valid_skips = TS590_SKIP
        rf.valid_tuning_steps = [0.5, 1.0, 2.5, 5.0, 6.25, 10.0, 12.5,
                                 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone"]
        rf.valid_name_length = 8    # 8 character channel names
        rf.valid_special_chans = sorted(self.SPECIAL_MEMORIES.keys())

        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = _(dedent("""\
            Click on the "Special Channels" toggle-button of the memory
            editor to see/set the EXT channels. P-VFO channels 100-109
            are considered Settings.\n
            Only a subset of the over 200 available radio settings
            are supported in this release.\n
            Ignore the beeps from the radio on upload and download.
            """))
        rp.pre_download = _(dedent("""\
            Follow these instructions to download the radio memory:
            1 - Connect your interface cable
            2 - Radio > Download from radio: DO NOT mess with the radio
            during download!
            3 - Disconnect your interface cable
            """))
        rp.pre_upload = _(dedent("""\
            Follow these instructions to upload the radio memory:
            1 - Connect your interface cable
            2 - Radio > Upload to radio: DO NOT mess with the radio
            during upload!
            3 - Disconnect your interface cable
            """))
        return rp

    def sync_in(self):
        """Download from radio"""
        try:
            _connect_radio(self)
            data = _read_mem(self)
            data += _read_settings(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()
        return

    def sync_out(self):
        """Upload to radio"""
        try:
            _connect_radio(self)
            _write_mem(self)
            _write_sets(self)
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        return

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        return

    def get_memory(self, number):
        """Convert raw channel data (_mem) into UI columns (mem)"""
        mem = chirp_common.Memory()
        mem.extra = RadioSettingGroup("extra", "Extra")
        if isinstance(number, str):
            mem.name = number   # Spcl chns 1st var
            mem.number = self.SPECIAL_MEMORIES[number]
            _mem = self._memobj.ch_mem[mem.number]
        else:       # Normal mem chans and VFO edges
            if number > 99 and number < 110:
                return          # Don't show VFO edges as mem chans
            _mem = self._memobj.ch_mem[number]
            mem.number = number
            mnx = ""
            for char in _mem.name:
                mnx += chr(char)
            mem.name = mnx.strip()
            mem.name = mem.name.upper()
        # From here on is common to both types
        if _mem.rxfreq == 0:
            _mem.txfreq = 0
            mem.empty = True
            mem.freq = 0
            mem.mode = "LSB"
            mem.offset = 0
            return mem
        mem.empty = False
        mem.freq = int(_mem.rxfreq)
        mem.duplex = TS590_DUPLEX[0]    # None by default
        mem.offset = 0
        if _mem.rxfreq < _mem.txfreq:   # + shift
            mem.duplex = TS590_DUPLEX[2]
            mem.offset = _mem.txfreq - _mem.rxfreq
        if _mem.rxfreq > _mem.txfreq:   # - shift
            mem.duplex = TS590_DUPLEX[1]
            mem.offset = _mem.rxfreq - _mem.txfreq
        if _mem.txfreq == 0:
            # leave offset alone, or run_tests will bomb
            mem.duplex = TS590_DUPLEX[0]
        mx = _mem.xmode - 1     # CAT modes start at 1
        if _mem.xmode == 9:     # except CAT FSK-R is 9, there is no 8
            mx = 7
        if _mem.data:       # LSB+Data= 8, USB+Data= 9, FM+Data= 10
            if _mem.xmode == 1:     # CAT LSB
                mx = 8
            elif _mem.xmode == 2:   # CAT USB
                mx = 9
            elif _mem.xmode == 4:   # CAT FM
                mx = 10
        mem.mode = TS590_MODES[mx]
        mem.tmode = ""
        mem.cross_mode = "Tone->Tone"
        mem.ctone = TS590_TONES[_mem.ctone]
        mem.rtone = TS590_TONES[_mem.rtone]
        if _mem.tmode == 1:
            mem.tmode = "Tone"
        elif _mem.tmode == 2:
            mem.tmode = "TSQL"
        elif _mem.tmode == 3:
            mem.tmode = "Cross"
        mem.skip = TS590_SKIP[_mem.skip]

        # Channel Extra settings: Only Boolean & List methods, no call-backs
        options = ["Wide", "Narrow"]
        rx = RadioSettingValueList(options, options[_mem.fmnrw])
        # NOTE: first param of RadioSetting is the object attribute name
        rset = RadioSetting("fmnrw", "FM mode", rx)
        rset.set_apply_callback(my_val_list, options, _mem, "fmnrw")
        mem.extra.append(rset)

        options = ["Filter A", "Filter B"]
        rx = RadioSettingValueList(options, options[_mem.filter])
        rset = RadioSetting("filter", "Filter A/B", rx)
        rset.set_apply_callback(my_val_list, options, _mem, "filter")
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        """Convert UI column data (mem) into MEM_FORMAT memory (_mem)"""
        _mem = self._memobj.ch_mem[mem.number]
        if mem.empty:
            _mem.rxfreq = 0
            _mem.txfreq = 0
            _mem.xmode = 0
            _mem.data = 0
            _mem.tmode = 0
            _mem.rtone = 0
            _mem.ctone = 0
            _mem.filter = 0
            _mem.skip = 0
            _mem.fmnrw = 0
            _mem.name = "        "
            return

        if mem.number > self._upper:    # Specials: No Name changes
            ix = 0
            # LOG.warning("Special Chan set_mem @ %i" % mem.number)
        else:
            nx = len(mem.name)
            for ix in range(8):
                if ix < nx:
                    _mem.name[ix] = mem.name[ix].upper()
                else:
                    _mem.name[ix] = " "    # assignment needs 8 chrs
        _mem.rxfreq = mem.freq
        _mem.txfreq = 0
        if mem.duplex == "+":
            _mem.txfreq = mem.freq + mem.offset
        if mem.duplex == "-":
            _mem.txfreq = mem.freq - mem.offset
        ix = TS590_MODES.index(mem.mode)
        _mem.data = 0
        _mem.xmode = ix + 1     # stored as CAT values, LSB= 1
        if ix == 7:     # FSK-R
            _mem.xmode = 9      # There is no CAT 8
        if ix > 7:      # a Data mode
            _mem.data = 1
            if ix == 8:
                _mem.xmode = 1      # LSB
            elif ix == 9:
                _mem.xmode = 2      # USB
            elif ix == 10:
                _mem.xmode = 4      # FM
        _mem.tmode = 0
        _mem.rtone = TS590_TONES.index(mem.rtone)
        _mem.ctone = TS590_TONES.index(mem.ctone)
        if mem.tmode == "Tone":
            _mem.tmode = 1
        if mem.tmode == "TSQL":
            _mem.tmode = 2
        if mem.tmode == "Cross" or mem.tmode == "Tone->Tone":
            _mem.tmode = 3
        _mem.skip = 0
        if mem.skip == "S":
            _mem.skip = 1
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)
        return

    def _parse_mem_spec(self, spec0, spec1):
        """ Extract ascii memory paramters; build data string """
        # spec0 is simplex result, spec1 is split
        # pad string so indexes match Kenwood docs
        spec0 = "x" + spec0  # match CAT document 1-based description
        ix = len(spec0)
        # _pxx variables are STRINGS
        _p1 = spec0[3]       # P1    Split Specification
        _p3 = spec0[4:7]     # P3    Memory Channel
        _p4 = spec0[7:18]    # P4    Frequency
        _p5 = spec0[18]      # P5    Mode
        _p6 = spec0[19]      # P6    Data Mode
        _p7 = spec0[20]      # P7    Tone Mode
        _p8 = spec0[21:23]   # P8    Tone Frequency Index
        if _p8 == "00":      # Can't be 0 at upload
            _p8 = "08"
        _p9 = spec0[23:25]   # P9    CTCSS Frequency Index
        if _p9 == "00":
            _p9 = "08"
        _p10 = spec0[25:28]  # P10   Always 0
        _p11 = spec0[28]     # P11   Filter A/B
        _p12 = spec0[29]     # P12   Always 0
        _p13 = spec0[30:38]  # P13   Always 0
        _p14 = spec0[38:40]  # P14   FM Mode
        _p15 = spec0[40]     # P15   Chan Lockout (Skip)
        _p16 = spec0[41:49]  # P16   Max 8-Char Name if assigned

        spec1 = "x" + spec1
        _p4s = int(spec1[7:18])  # P4: Offset freq

        datm = ""   # Fill in MEM_FORMAT sequence
        datm += _make_dat(_p4, 4)   # rxreq: u32, 4 bytes/chars
        datm += _make_dat(_p4s, 4)  # tx freq
        v1 = int(_p5) << 4          # xMode: 0-9, upper 4 bits
        v1 = v1 | (int(_p6) << 2)   # Data: 0/1
        v1 = v1 | int(_p7)          # Tmode: 0-3
        datm += chr(v1)
        datm += chr(int(_p8))       # rtone: 00-42
        datm += chr(int(_p9))       # ctone
        v1 = int(_p11) << 7         # Filter A/B 1 bit msb
        v1 = v1 | (int(_p14) << 6)  # fmwide: 1 bit
        v1 = v1 | (int(_p15) << 5)  # skip: 1 bit
        datm += chr(v1)
        v1 = len(_p16)
        for ix in range(8):
            if ix < v1:
                datm += _p16[ix]
            else:
                datm += " "

        return datm

    def _make_base_spec(self, mem, freq):
        """ Generate memory channel parameter string """
        spec = "%011i%1i%1i%1i%02i%02i000%1i0000000000%02i%1i%s" \
            % (freq, mem.xmode, mem.data, mem.tmode, mem.rtone,
                mem.ctone, mem.filter, mem.fmnrw, mem.skip, mem.name)

        return spec.strip()

    def get_settings(self):
        """Translate the MEM_FORMAT structs into settings in the UI"""
        # Define mem struct write-back shortcuts
        _sets = self._memobj.settings
        _asf = self._memobj.asf
        _ssf = self._memobj.ssf
        _eqx = self._memobj.eqx
        _mex = self._memobj.exset
        _chm = self._memobj.ch_mem
        basic = RadioSettingGroup("basic", "Basic Settings")
        pvfo = RadioSettingGroup("pvfo", "VFO Band Edges")
        mena = RadioSettingGroup("mena", "Menu A")
        menb = RadioSettingGroup("menb", "Menu B")
        equ = RadioSettingGroup("equ", "Equalizers")
        amode = RadioSettingGroup("amode", "Auto Mode")
        ssc = RadioSettingGroup("ssc", "Slow Scan")
        group = RadioSettings(basic, pvfo, mena, menb, equ, amode, ssc)

        mhz1 = 1000000.
        nsg = not self.SG
        if nsg:     # Make reverse EX_X dictionary
            x_ex = dict(zip(self.EX_X.values(), self.EX_X.keys()))

        # Callback functions
        def _my_readonly(setting, obj, atrb):
            """NOP callback, prevents writing the setting"""
            vx = 0
            return

        def my_adjraw(setting, obj, atrb, fix=0, ndx=-1):
            """Callback for Integer add or subtract fix from value."""
            vx = int(str(setting.value))
            value = vx + int(fix)
            if value < 0:
                value = 0
            if ndx < 0:
                setattr(obj, atrb, value)
            else:
                setattr(obj[ndx], atrb, value)
            return

        def my_mhz_val(setting, obj, atrb, ndx=-1):
            """ Callback to set freq back to Htz"""
            vx = float(str(setting.value))
            vx = int(vx * mhz1)
            if ndx < 0:
                setattr(obj, atrb, vx)
            else:
                setattr(obj[ndx], atrb, vx)
            return

        def my_bool(setting, obj, atrb, ndx=-1):
            """ Callback to properly set boolean """
            # set_settings is not setting [indexed] booleans???
            vx = 0
            if str(setting.value) == "True":
                vx = 1
            if ndx < 0:
                setattr(obj, atrb, vx)
            else:
                setattr(obj[ndx], atrb, vx)
            return

        def my_asf_mode(setting, obj, nx=0):
            """ Callback to extract mode and create asmode, asdata """
            v1 = TS590_MODES.index(str(setting.value))
            v2 = 0      # asdata
            vx = v1 + 1     # stored as CAT values, same as xmode
            if v1 == 7:
                vx = 9
            if v1 > 7:      # a Data mode
                v2 = 1
                if v1 == 8:
                    vx = 1      # LSB
                elif v1 == 9:
                    vx = 2      # USB
                elif v1 == 10:
                    vx = 4      # FM
            setattr(obj[nx], "asdata", v2)
            setattr(obj[nx], "asmode", vx)
            return

        def my_fnctns(setting, obj, ndx, atrb):
            """ Filter only valid key function assignments """
            vx = int(str(setting.value))
            if self.SG:
                vmx = 210
                if (vx > 99 and vx < 120) or (vx > 170 and vx < 200):
                    raise errors.RadioError(" %i Change Ignored for %s."
                                            % (vx, atrb))
                    return  # not valid, ignored
            else:
                vmx = 208
                if (vx > 87 and vx < 100) or (vx > 134 and vx < 200):
                    raise errors.RadioError(" %i Change Ignored for %s."
                                            % (vx, atrb))
                    return
            if vx > vmx:
                vx = 255       # Off
            setattr(obj[ndx], atrb, vx)
            return

        def my_labels(kx):      # nsg and x_ex defined above
            lbl = "%03i:" % kx      # SG EX number
            if nsg:
                lbl = x_ex["EX%03i" % kx][2:] + ":"    # S-model EX num
            lbl += self.EX_LBL[kx]      # and the label to match
            return lbl

        # ===== BASIC GROUP =====
        sx = ""
        for i in range(4):
            sx += chr(_sets.fv[i])
        rx = RadioSettingValueString(0, 4, sx)
        rset = RadioSetting("settings.fv", "FirmwareVersion", rx)
        rset.set_apply_callback(_my_readonly, _sets, "fv")
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 255, _sets.ag + 1)
        rset = RadioSetting("settings.ag", "AF Gain", rx)
        rset.set_apply_callback(my_adjraw, _sets, "ag", -1)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 255, _sets.rg + 1)
        rset = RadioSetting("settings.rg", "RF Gain", rx)
        rset.set_apply_callback(my_adjraw, _sets, "rg", -1)
        basic.append(rset)

        options = ["ANT1", "ANT2"]
        # CAUTION: an1 has value of 1 or 2
        rx = RadioSettingValueList(options, options[_sets.an1 - 1])
        rset = RadioSetting("settings.an1", "Antenna Selected", rx)
        # Add 1 to the changed value. S/b 1/2
        rset.set_apply_callback(my_val_list, options, _sets, "an1", 1)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.an2))
        rset = RadioSetting("settings.an2", "Recv Antenna is used", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.an3))
        rset = RadioSetting("settings.an3", "Drive Out On", rx)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 100, _sets.mg)
        rset = RadioSetting("settings.mg", "Microphone gain", rx)
        basic.append(rset)

        nx = 5      # Coarse step
        if bool(_mex[0].ex054):   # Power Fine enabled in menu A
            nx = 1
        vx = _sets.pc       # Trap invalid values from run_tests.py
        if vx < 5:
            vx = 5
        rx = RadioSettingValueInteger(5, 100, vx, nx)
        sx = "TX Output power (Watts)"
        rset = RadioSetting("settings.pc", sx, rx)
        basic.append(rset)

        vx = _sets.tp
        rx = RadioSettingValueInteger(5, 100, vx, nx)
        sx = "TX Tuning power (Watts)"
        rset = RadioSetting("settings.tp", sx, rx)
        basic.append(rset)

        val = _sets.fa / mhz1       # Allow Rx freq range
        rx = RadioSettingValueFloat(0.3, 60.0, val, 0.001, 3)
        sx = "VFO-A Frequency (MHz)"
        rset = RadioSetting("settings.fa", sx, rx)
        rset.set_apply_callback(my_mhz_val, _sets, "fa")
        basic.append(rset)

        val = _sets.fb / mhz1
        rx = RadioSettingValueFloat(0.3, 60.0, val, 0.001, 3)
        sx = "VFO-B Frequency (MHz)"
        rset = RadioSetting("settings.fb", sx, rx)
        rset.set_apply_callback(my_mhz_val, _sets, "fb")
        basic.append(rset)

        options = ["Menu A", "Menu B"]
        rx = RadioSettingValueList(options, options[_sets.mf])
        sx = "Menu Selected"
        rset = RadioSetting("settings.mf", sx, rx)
        rset.set_apply_callback(my_val_list, options, _sets, "mf")
        basic.append(rset)

        # ==== VFO Edges Group ================

        for mx in range(100, 110):
            val = _chm[mx].rxfreq / mhz1
            if val < 1.8:       # Many operators never use this
                val = 1.8       # So default is 0.0
            rx = RadioSettingValueFloat(1.8, 54.0, val, 0.001, 3)
            sx = "VFO-Band %i lower limit (MHz)" % (mx - 100)
            rset = RadioSetting("ch_mem.rxfreq/%d" % mx, sx, rx)
            rset.set_apply_callback(my_mhz_val, _chm, "rxfreq", mx)
            pvfo.append(rset)

            val = _chm[mx].txfreq / mhz1
            if val < 1.8:
                val = 54.0
            rx = RadioSettingValueFloat(1.8, 54.0, val, 0.001, 3)
            sx = "    VFO-Band %i upper limit (MHz)" % (mx - 100)
            rset = RadioSetting("ch_mem.txfreq/%d" % mx, sx, rx)
            rset.set_apply_callback(my_mhz_val, _chm, "txfreq", mx)
            pvfo.append(rset)

            kx = _chm[mx].xmode
            options = ["None", "LSB", "USB", "CW", "FM", "AM", "FSK",
                       "CW-R", "N/A", "FSK-R"]
            rx = RadioSettingValueList(options, options[kx])
            sx = "    VFO-Band %i Tx/Rx Mode" % (mx - 100)
            rset = RadioSetting("ch_mem.xmode/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _chm,
                                    "xmode", 0, mx)
            pvfo.append(rset)

        # ==== Menu A/B Group =================

        for mx in range(2):      # A/B index
            sx = ""
            for i in range(8):
                if int(_mex[mx].ex001[i]) != 0:
                    sx += chr(_mex[mx].ex001[i])
            sx = sx.strip()
            rx = RadioSettingValueString(0, 8, sx)
            sx = my_labels(1)     # Proper label for EX001
            rset = RadioSetting("exset.ex001/%d" % mx, sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(2)
            rx = RadioSettingValueInteger(0, 6, _mex[mx].ex002)
            rset = RadioSetting("exset.ex002", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            nx = 2
            if self.SG:
                nx = 10
            vx = _mex[mx].ex003 + 1     # radio rtns 0-9
            rx = RadioSettingValueInteger(1, nx, vx)
            sx = my_labels(3)
            rset = RadioSetting("exset.ex003", sx, rx)
            rset.set_apply_callback(my_adjraw, _mex, "ex003", -1, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            nx = 9
            if self.SG:
                nx = 20
            rx = RadioSettingValueInteger(0, nx, _mex[mx].ex005)
            sx = my_labels(5)
            rset = RadioSetting("exset.ex005", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(6)
            rx = RadioSettingValueInteger(0, nx, _mex[mx].ex006)
            rset = RadioSetting("exset.ex006", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(7)
            rx = RadioSettingValueInteger(0, nx, _mex[mx].ex007)
            rset = RadioSetting("exset.ex007", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            nx = 7
            if self.SG:
                nx = 20
            sx = my_labels(8)
            rx = RadioSettingValueInteger(0, nx, _mex[mx].ex008)
            rset = RadioSetting("exset.ex008", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(9)
            rx = RadioSettingValueInteger(0, 4, _mex[mx].ex009)
            rset = RadioSetting("exset.ex009", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["English", "Japanese"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex010])
            sx = my_labels(10)
            rset = RadioSetting("exset.ex010/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex010", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["Off", "1", "2"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex011])
            sx = my_labels(11)
            rset = RadioSetting("exset.ex011/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex011", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["0.1", "0.5", "1.0"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex012])
            sx = my_labels(12)
            rset = RadioSetting("exset.ex012", sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex012", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["250", "500", "1000"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex013])
            sx = my_labels(13)
            rset = RadioSetting("exset.ex013/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex013", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            # S and SG have different ranges for control steps
            options = ["0.5", "1.0", "2.5", "5.0", "10.0"]
            if self.SG:
                options = ["Off", "0.5", "0.5", "1.0", "2.5",
                           "5.0", "10.0"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex016])
            sx = my_labels(16)
            if nsg:
                sx = "014: Tuning step for SSB/CW/FSK (KHz)"
            rset = RadioSetting("exset.ex016/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex016", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            if self.SG:       # this setting only for SG
                rx = RadioSettingValueList(options,
                                           options[_mex[mx].ex017])

                sx = my_labels(17)
                rset = RadioSetting("exset.ex017/%d" % mx, sx, rx)
                rset.set_apply_callback(my_val_list, options, _mex,
                                        "ex017", 0, mx)
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

            options = ["Off", "5.0", "6.25", "10.0", "12.5", "15.0",
                       "20.0", "25.0", "30.0", "50.0", "100.0"]
            if self.SG:
                options.remove("Off")
            rx = RadioSettingValueList(options, options[_mex[mx].ex018])
            sx = my_labels(18)
            rset = RadioSetting("exset.ex018/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex018", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueList(options, options[_mex[mx].ex019])
            sx = my_labels(19)
            rset = RadioSetting("exset.ex019/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex019", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["3", "5", "10"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex021])
            sx = my_labels(21)
            rset = RadioSetting("exset.ex021/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex021", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex022))
            sx = my_labels(22)
            rset = RadioSetting("exset.ex022/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex022", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex023))
            sx = my_labels(23)
            rset = RadioSetting("exset.ex023/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex023", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["100", "200", "300", "400", "500"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex024])
            sx = my_labels(24)
            rset = RadioSetting("exset.ex024/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex024", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex025))
            sx = my_labels(25)
            rset = RadioSetting("exset.ex025/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex025", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["TO", "CO"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex026])
            sx = my_labels(26)
            rset = RadioSetting("exset.ex026/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex026", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex054))
            sx = my_labels(54)
            rset = RadioSetting("exset.ex054/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex054", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["Off", "3", "5", "10", "20", "30"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex055])
            sx = my_labels(55)
            rset = RadioSetting("exset.ex055/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex055", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex076))
            sx = my_labels(76)
            rset = RadioSetting("exset.ex076/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex076", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 100, _mex[mx].ex077, 5)
            sx = my_labels(77)
            rset = RadioSetting("exset.ex077/%d" % mx, sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex087)
            sx = my_labels(87)
            rset = RadioSetting("exset.ex087/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex087")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex088)
            sx = my_labels(88)
            rset = RadioSetting("exset.ex088/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex088")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            if self.SG:       # Next 5 settings not supported in 590S
                rx = RadioSettingValueInteger(0, 256, _mex[mx].ex089)
                sx = my_labels(89)
                rset = RadioSetting("exset.ex089/%d" % mx, sx, rx)
                rset.set_apply_callback(my_fnctns, _mex, mx, "ex089")
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

                rx = RadioSettingValueInteger(0, 256, _mex[mx].ex090)
                sx = my_labels(90)
                rset = RadioSetting("exset.ex090/%d" % mx, sx, rx)
                rset.set_apply_callback(my_fnctns, _mex, mx, "ex090")
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

                rx = RadioSettingValueInteger(0, 256, _mex[mx].ex091)
                sx = my_labels(91)
                rset = RadioSetting("exset.ex091/%d" % mx, sx, rx)
                rset.set_apply_callback(my_fnctns, _mex, mx, "ex091")
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

                rx = RadioSettingValueInteger(0, 256, _mex[mx].ex092)
                sx = my_labels(92)
                rset = RadioSetting("exset.ex092/%d" % mx, sx, rx)
                rset.set_apply_callback(my_fnctns, _mex, mx, "ex092")
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

                rx = RadioSettingValueInteger(0, 256, _mex[mx].ex093)
                sx = my_labels(93)
                rset = RadioSetting("exset.ex093/%d" % mx, sx, rx)
                rset.set_apply_callback(my_fnctns, _mex, mx, "ex093")
                if mx == 0:
                    mena.append(rset)
                else:
                    menb.append(rset)

            # Now both S and SG models
            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex094)
            sx = my_labels(94)
            rset = RadioSetting("exset.ex094/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex094")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex095)
            sx = my_labels(95)
            rset = RadioSetting("exset.ex095/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex095")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex096)
            sx = my_labels(96)
            rset = RadioSetting("exset.ex096/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex096")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex097)
            sx = my_labels(97)
            rset = RadioSetting("exset.ex097/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex097")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex098)
            sx = my_labels(98)
            rset = RadioSetting("exset.ex098/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex098")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 256, _mex[mx].ex099)
            sx = my_labels(99)
            rset = RadioSetting("exset.ex099/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex099")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)
        # End of for mx loop

        # ==== Auto Scan Params (amode) ==============
        for ix in range(32):
            val = _asf[ix].asfreq / mhz1
            rx = RadioSettingValueFloat(0.03, 60.0, val, 0.001, 3)
            rset = RadioSetting("asf.asfreq/%d" % ix,
                                "Scan %02i Freq (MHz)" % ix, rx)
            rset.set_apply_callback(my_mhz_val, _asf, "asfreq", ix)
            amode.append(rset)

            mx = _asf[ix].asmode - 1     # Same logic as xmode
            if _asf[ix].asmode == 9:
                mx = 7
            if _asf[ix].asdata:
                if _asf[ix].asmode == 1:
                    mx = 8
                elif _asf[ix].asmode == 2:
                    mx = 9
                elif _asf[ix].asmode == 4:
                    mx = 10
            rx = RadioSettingValueList(TS590_MODES, TS590_MODES[mx])
            rset = RadioSetting("asf.asmode/%d" % ix, "   Mode", rx)
            rset.set_apply_callback(my_asf_mode, _asf, ix)
            amode.append(rset)

        # ==== Slow Scan Settings ===
        for ix in range(10):        # Chans
            for nx in range(5):     # spots
                px = ((ix * 5) + nx)
                val = _ssf[px].ssfreq / mhz1
                stx = "      -   -   -    Slot %02i Freq (MHz)" % nx
                if nx == 0:
                    stx = "Slow Scan %02i, Slot 0 Freq (MHz" % ix
                rx = RadioSettingValueFloat(0, 54.0, val, 0.001, 3)
                rset = RadioSetting("ssf.ssfreq/%d" % px, stx, rx)
                rset.set_apply_callback(my_mhz_val, _ssf, "ssfreq", px)
                ssc.append(rset)

        # ==== Equalizer subgroup =====
        mohd = ["SSB", "SSB-DATA", "CW/CW-R", "FM", "FM-DATA", "AM",
                "AM-DATA", "FSK/FSK-R"]
        tcurves = ["Off", "HB1", "HB2", "FP", "BB1", "BB2",
                   "C", "U"]
        rcurves = ["Off", "HB1", "HB2", "FP", "BB1", "BB2",
                   "FLAT", "U"]
        for ix in range(8):
            rx = RadioSettingValueList(tcurves, tcurves[_eqx[ix].txeq])
            rset = RadioSetting("eqx.txeq/%d" % ix, "TX %s Equalizer"
                                % mohd[ix], rx)
            rset.set_apply_callback(my_val_list, tcurves, _eqx,
                                    "txeq", 0, ix)
            equ.append(rset)

            rx = RadioSettingValueList(rcurves, rcurves[_eqx[ix].rxeq])
            rset = RadioSetting("eqx.rxeq/%d" % ix, "RX %s Equalizer"
                                % mohd[ix], rx)
            rset.set_apply_callback(my_val_list, rcurves, _eqx,
                                    "rxeq", 0, ix)
            equ.append(rset)

        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.settings
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
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, fdata, fyle):
        """ Included to prevent 'File > New' error """
        return False


@directory.register
class TS590SRadio(TS590Radio):
    """ Kenwood TS-590S variant of the TS590 """
    VENDOR = "Kenwood"
    MODEL = "TS-590S_CloneMode"
    ID = "ID021;"
    SG = False
    # This is the equivalent Menu A/B list for the TS-590S
    # The equivalnt S param is stored in the SG Mem_Format slot
    EX = ["EX087", "EX000", "EX001", "EX003", "EX004", "EX005",
          "EX006", "EX007", "EX008", "EX009", "EX010", "EX011", "EX014",
          "EX014", "EX015", "EX016", "EX017", "EX018", "EX019", "EX020",
          "EX021", "EX022", "EX048", "EX049", "EX069", "EX070", "EX079",
          "EX080", "EX080", "EX080", "EX080", "EX080", "EX080", "EX081",
          "EX082", "EX083", "EX084", "EX085", "EX086", "MF1"]
    # EX cross reference dictionary- key is S param, value is the SG
    EX_X = {"EX087": "EX001", "EX000": "EX002", "EX001": "EX003",
            "EX003": "EX005", "EX004": "EX006", "EX005": "EX007",
            "EX006": "EX008", "EX007": "EX009", "EX008": "EX010",
            "EX009": "EX011", "EX010": "EX012", "EX011": "EX013",
            "EX014": "EX016", "EX015": "EX018", "EX081": "EX094",
            "EX016": "EX019", "EX017": "EX021", "EX018": "EX022",
            "EX019": "EX023",
            "EX020": "EX024", "EX021": "EX025", "EX022": "EX026",
            "EX048": "EX054", "EX049": "EX055", "EX069": "EX076",
            "EX070": "EX077", "EX079": "EX087", "EX080": "EX088",
            "EX082": "EX095", "EX083": "EX096", "EX084": "EX097",
            "EX085": "EX098", "EX086": "EX099"}
