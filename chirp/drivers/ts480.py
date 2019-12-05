# Copyright 2019 Rick DeWitt <aa0rd@yahoo.com>
# Implementing mem as Clone Mode
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
  u8   xmode;     // param stored as CAT value
  u8   tmode;
  u8   rtone;
  u8   ctone;
  u8   skip;
  u8   step;
  char name[8];
} ch_mem[110];   // 100 normal + 10 P-type

struct {        // 5 bytes each
  u32 asfreq;
  u8  asmode:4,     // param stored as CAT value (0 -9)
      asdata:2,
      asnu:2;
} asf[32];

struct {        // 10 x 5 4-byte frequencies
  u32  ssfreq;
} ssf[50];

struct {
  u8   ag;
  u8   an;
  u32  fa;
  u32  fb;
  u8   mf;
  u8   mg;
  u8   pc;
  u8   rg;
  u8   ty;
} settings;

struct {            // Menu A/B settings
  char ex000;
  u8   ex003;       // These params stored as nibbles
  u8   ex007;
  u8   ex008;
  u8   ex009;
  u8   ex010;
  u8   ex011;
  u8   ex012;
  u8   ex013;
  u8   ex014;
  u8   ex021;
  u8   ex022;
  u8   ex048;
  u8   ex049;
  u8   ex050;
  u8   ex051;
  u8   ex052;
} exset[2];

  char mdl_name[9];     // appended model name, first 9 chars

"""

STIMEOUT = 0.6
LOCK = threading.Lock()
BAUD = 0    # Initial baud rate
MEMSEL = 0  # Default Menu A
BEEPVOL = 5     # Default beep level
W8S = 0.01      # short wait, secs
W8L = 0.05      # long wait

TS480_DUPLEX = ["", "-", "+"]
TS480_SKIP = ["", "S"]

# start at 0:LSB
TS480_MODES = ["LSB", "USB", "CW", "FM", "AM", "FSK", "CW-R", "FSK-R"]
EX_MODES = ["FSK-R", "CW-R"]
for ix in EX_MODES:
    if ix not in chirp_common.MODES:
        chirp_common.MODES.append(ix)

TS480_TONES = list(chirp_common.TONES)
TS480_TONES.append(1750.0)

TS480_BANDS = [(50000, 24999999),  # VFO Rx range. TX has lockouts
               (25000000, 59999999)]

TS480_TUNE_STEPS = [0.5, 1.0, 2.5, 5.0, 6.25, 10.0, 12.5,
                    15.0, 20.0, 25.0, 30.0, 50.0, 100.0]

RADIO_IDS = {   # From kenwood_live.py; used to report wrong radio
    "ID019;": "TS-2000",
    "ID009;": "TS-850",
    "ID020:": "TS-480",
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
    bauds = [9600, 115200, 57600, 38400, 19200, 4800]
    if BAUD > 0:
        bauds.insert(0, BAUD)       # Make the detected one first
    # Flush the input buffer
    radio.pipe.timeout = 0.005
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
    status.max = radio._upper + 10  # 10 P chans
    status.msg = "Reading Channel Memory..."
    radio.status_fn(status)

    result0 = command(radio.pipe, "EX0120000", 12, W8S)
    BEEPVOL = int(result0[6:12])
    result0 = command(radio.pipe, "EX01200000", 0, W8L)   # Silence beeps
    data = ""
    mrlen = 41      # Expected fixed return string length
    for chn in range(0, (radio._upper + 11)):   # Loop stops at +10
        # Request this mem chn
        r0ch = 999
        r1ch = r0ch
        # return results can come back out of order
        while (r0ch != chn):
            # simplex
            result0 = command(radio.pipe, "MR0%03i" % chn,
                              mrlen, W8S)
            result0 += read_str(radio)
            r0ch = int(result0[3:6])
        while (r1ch != chn):
            # split
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


def _sets_val(stx, nv, nb):
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
    a2 = 0                          # not used in TS-480
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
    status.max = 32 + 50 + 8 + 17 + 17
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
        if (cmc == "FA") or (cmc == "FB"):    # Response is 11-bit frq
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
    # Now set the initial menu selection back
    result0 = command(radio.pipe, "MF", 0, W8L, "%1i" % MEMSEL)
    # And the original Beep Volume
    result0 = command(radio.pipe, "EX0120000%i" % BEEPVOL, 0, W8L)
    return setts


def _write_mem(radio):
    """ Send MW commands for each channel """
    global BEEPVOL
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._upper + 10  # 10 P chans
    status.msg = "Writing Channel Memory"
    radio.status_fn(status)

    result0 = command(radio.pipe, "EX0120000", 12, W8S)
    BEEPVOL = int(result0[6:12])
    result0 = command(radio.pipe, "EX01200000", 0, W8L)   # Silence beeps

    for chn in range(0, (radio._upper + 11)):   # Loop stops at +20
        _mem = radio._memobj.ch_mem[chn]
        cmx = "MW0%03i" % chn
        stm = cmx + radio._make_base_spec(_mem, _mem.rxfreq)
        result0 = command(radio.pipe, stm, 0, W8L)     # No response
        if _mem.txfreq > 0:            # Don't write MW1 if empty/deleted
            cmx = "MW1%03i" % chn
            stm = cmx + radio._make_base_spec(_mem, _mem.txfreq)
            result0 = command(radio.pipe, stm, 0, W8L)
        status.cur = chn
        radio.status_fn(status)
    return


def _write_sets(radio):
    """ Send settings and Menu a/b """
    status = chirp_common.Status()
    status.cur = 0
    status.max = 124   # Total to send
    status.msg = "Writing Settings"
    radio.status_fn(status)
    # Define mem struct shortcuts
    _sets = radio._memobj.settings
    _asf = radio._memobj.asf
    _ssf = radio._memobj.ssf
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
    # Send 8 thingies
    scm = "AG0%03i" % _sets.ag
    result0 = command(radio.pipe, scm, stlen, W8S)
    scm = "AN%1i" % _sets.an
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
    # TY cmd is firmware read-only
    scm = "MF0"   # Select menu A/B
    result0 = command(radio.pipe, scm, stlen, W8S)
    snx += 8
    status.cur = snx
    radio.status_fn(status)
    # Send 17 Menu A EX
    setc = radio.EX     # list of EX cmds
    for ix in range(2):
        for cmx in setc:
            if str(cmx)[0:2] == "MF":
                scm = cmx
            else:       # The EX cmds
                scm = "%s0000%i" % (cmx, getattr(_mex[ix],
                                    cmx.lower()))
            result0 = command(radio.pipe, scm, stlen, W8S)
            snx += 1
            status.cur = snx
            radio.status_fn(status)
    # Now set the initial menu selection back
    result0 = command(radio.pipe, "MF", 0, W8L, "%1i" % _sets.mf)
    # And the original Beep Volume
    result0 = command(radio.pipe, "EX0120000%i" % BEEPVOL, 0, W8L)
    return


@directory.register
class TS480Radio(chirp_common.CloneModeRadio):
    """Kenwood TS-590"""
    VENDOR = "Kenwood"
    MODEL = "TS-480_CloneMode"
    ID = "ID020;"
    # Settings read/write cmd sequence list
    SETC = ["AS0", "SS", "AG0", "AN", "FA", "FB",
            "MF", "MG", "PC", "RG", "TY", "MF0"]
    # This is the TS-590SG MENU A/B read_settings paramter tuple list
    # The order is mandatory; to match the Mem_Format sequence
    EX = ["EX000", "EX003", "EX007", "EX008", "EX009", "EX010", "EX011",
          "EX012", "EX013", "EX014", "EX021", "EX022", "EX048", "EX049",
          "EX050", "EX051", "EX052", "MF1"]
    # EX menu settings label dictionary. Key is the EX number
    EX_LBL = {0: " Display brightness",
              3: "  Tuning control adj rate (Hz)",
              12: " Beep volume",
              13: " Sidetone volume",
              14: " Message playback volume",
              7: " Temporary MR Chan freq allowed",
              8: " Program Scan slowdown",
              9: " Program Scan slowdown range (Hz)",
              10: " Program Scan hold",
              11: " Scan Resume method",
              21: " TX Power fine adjust",
              22: " Timeout timer (Secs)",
              48: " Panel PF-A function",
              49: " MIC PF1 function",
              50: " MIC PF2 function",
              51: " MIC PF3 function",
              52: " MIC PF4 function"}

    _upper = 99

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
        rf.has_tuning_step = True
        rf.has_nostep_tuning = True     # Radio accepts any entered freq
        rf.has_cross = False
        rf.has_comment = False
        rf.memory_bounds = (0, self._upper)
        rf.valid_bands = TS480_BANDS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "*+-/"
        rf.valid_duplexes = TS480_DUPLEX
        rf.valid_modes = TS480_MODES
        rf.valid_skips = TS480_SKIP
        rf.valid_tuning_steps = TS480_TUNE_STEPS
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_name_length = 8    # 8 character channel names

        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = _(dedent("""\
            P-VFO channels 100-109 are considered Settings.\n
            Only a subset of the over 130 available radio settings
            are supported in this release.\n
            """))
        rp.pre_download = _(dedent("""\
            Follow these instructions to download the radio memory:
            1 - Connect your interface cable
            2 - Radio > Download from radio: Don't adjust any settings
            on the radio head!
            3 - Disconnect your interface cable
            """))
        rp.pre_upload = _(dedent("""\
            Follow these instructions to upload the radio memory:
            1 - Connect your interface cable
            2 - Radio > Upload to radio: Don't adjust any settings
            on the radio head!
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
        if number > 99 and number < 110:
            return          # Don't show VFO edges as mem chans
        _mem = self._memobj.ch_mem[number]
        mem.number = number
        mnx = ""
        for char in _mem.name:
            mnx += chr(char)
        mem.name = mnx.strip()
        mem.name = mem.name.upper()
        if _mem.rxfreq == 0:
            mem.empty = True
            return mem
        mem.empty = False
        mem.freq = int(_mem.rxfreq)
        mem.duplex = TS480_DUPLEX[0]    # None by default
        mem.offset = 0
        if _mem.rxfreq < _mem.txfreq:   # + shift
            mem.duplex = TS480_DUPLEX[2]
            mem.offset = _mem.txfreq - _mem.rxfreq
        if _mem.rxfreq > _mem.txfreq:   # - shift
            mem.duplex = TS480_DUPLEX[1]
            mem.offset = _mem.rxfreq - _mem.txfreq
        if _mem.txfreq == 0:
            # leave offset alone, or run_tests will bomb
            mem.duplex = TS480_DUPLEX[0]
        mx = _mem.xmode - 1     # CAT modes start at 1
        if _mem.xmode == 9:     # except there is no xmode 9
            mx = 7
        mem.mode = TS480_MODES[mx]
        mem.tmode = ""
        mem.cross_mode = "Tone->Tone"
        mem.ctone = TS480_TONES[_mem.ctone]
        mem.rtone = TS480_TONES[_mem.rtone]
        if _mem.tmode == 1:
            mem.tmode = "Tone"
        elif _mem.tmode == 2:
            mem.tmode = "TSQL"
        elif _mem.tmode == 3:
            mem.tmode = "Cross"
        mem.skip = TS480_SKIP[_mem.skip]
        # Tuning step depends on mode
        options = [0.5, 1.0, 2.5, 5.0, 10.0]    # SSB/CS/FSK
        if _mem.xmode == 4 or _mem.xmode == 5:   # AM/FM
            options = TS480_TUNE_STEPS[3:]
        mem.tuning_step = options[_mem.step]
        return mem

    def set_memory(self, mem):
        """Convert UI column data (mem) into MEM_FORMAT memory (_mem)"""
        _mem = self._memobj.ch_mem[mem.number]
        if mem.empty:
            _mem.rxfreq = 0
            _mem.txfreq = 0
            _mem.xmode = 0
            _mem.step = 0
            _mem.tmode = 0
            _mem.rtone = 0
            _mem.ctone = 0
            _mem.skip = 0
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
        ix = TS480_MODES.index(mem.mode)
        _mem.xmode = ix + 1     # stored as CAT values, LSB= 1
        if ix == 7:     # FSK-R
            _mem.xmode = 9      # There is no CAT 8
        _mem.tmode = 0
        _mem.rtone = TS480_TONES.index(mem.rtone)
        _mem.ctone = TS480_TONES.index(mem.ctone)
        if mem.tmode == "Tone":
            _mem.tmode = 1
        if mem.tmode == "TSQL":
            _mem.tmode = 2
        _mem.skip = 0
        if mem.skip == "S":
            _mem.skip = 1
        options = [0.5, 1.0, 2.5, 5.0, 10.0]    # SSB/CS/FSK steps
        if _mem.xmode == 4 or _mem.xmode == 5:   # AM/FM
            options = TS480_TUNE_STEPS[3:]
        _mem.step = options.index(mem.tuning_step)
        return

    def _parse_mem_spec(self, spec0, spec1):
        """ Extract ascii memory paramters; build data string """
        # spec0 is simplex result, spec1 is split
        # pad string so indexes match Kenwood docs
        spec0 = "x" + spec0  # match CAT document 1-based description
        ix = len(spec0)
        # _pxx variables are STRINGS
        _p1 = spec0[3]       # P1    Split Specification
        _p3 = spec0[5:7]     # P3    Memory Channel
        _p4 = spec0[7:18]    # P4    Frequency
        _p5 = spec0[18]      # P5    Mode
        _p6 = spec0[19]      # P6    Chan Lockout (Skip)
        _p7 = spec0[20]      # P7    Tone Mode
        _p8 = spec0[21:23]   # P8    Tone Frequency Index
        if _p8 == "00":
            _p8 = "08"
        _p9 = spec0[23:25]   # P9    CTCSS Frequency Index
        if _p9 == "00":
            _p9 = "08"
        _p14 = spec0[39:41]  # P14   Step Size
        _p16 = spec0[41:50]  # P16   Max 8-Char Name if assigned

        spec1 = "x" + spec1
        _p4s = int(spec1[7:18])  # P4: Offset freq

        datm = ""   # Fill in MEM_FORMAT sequence
        datm += _make_dat(_p4, 4)   # rxreq: u32, 4 bytes/chars
        datm += _make_dat(_p4s, 4)  # tx freq
        datm += chr(int(_p5))       # xmode: 0-9
        datm += chr(int(_p7))       # Tmode: 0-3
        datm += chr(int(_p8))       # rtone: 00-41
        datm += chr(int(_p9))       # ctone: 00-41
        datm += chr(int(_p6))       # skip: 0/1
        datm += chr(int(_p14))      # step: 0-9
        v1 = len(_p16)
        for ix in range(8):
            if ix < v1:
                datm += _p16[ix]
            else:
                datm += " "
        return datm

    def _make_base_spec(self, mem, freq):
        spec = "%011i%1i%1i%1i%02i%02i00000000000000%02i0%s" \
            % (freq, mem.xmode, mem.skip, mem.tmode, mem.rtone,
                mem.ctone, mem.step, mem.name)

        return spec.strip()

    def get_settings(self):
        """Translate the MEM_FORMAT structs into settings in the UI"""
        # Define mem struct write-back shortcuts
        _sets = self._memobj.settings
        _asf = self._memobj.asf
        _ssf = self._memobj.ssf
        _mex = self._memobj.exset
        _chm = self._memobj.ch_mem
        basic = RadioSettingGroup("basic", "Basic Settings")
        pvfo = RadioSettingGroup("pvfo", "VFO Band Edges")
        mena = RadioSettingGroup("mena", "Menu A")
        menb = RadioSettingGroup("menb", "Menu B")
        amode = RadioSettingGroup("amode", "Auto Mode")
        ssc = RadioSettingGroup("ssc", "Slow Scan")
        group = RadioSettings(basic, pvfo, mena, menb, amode, ssc)

        mhz1 = 1000000.

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
            v1 = TS480_MODES.index(str(setting.value))
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
            if vx > 79:
                vx = 99       # Off
            setattr(obj[ndx], atrb, vx)
            return

        def my_labels(kx):
            lbl = "%03i:" % kx      # SG EX number
            lbl += self.EX_LBL[kx]      # and the label to match
            return lbl

        # ===== BASIC GROUP =====

        options = ["TS-480HX (200W)", "TS-480SAT (100W + AT)",
                   "Japanese 50W type", "Japanese 20W type"]
        rx = RadioSettingValueString(14, 22, options[_sets.ty])
        rset = RadioSetting("settings.ty", "FirmwareVersion", rx)
        rset.set_apply_callback(_my_readonly, _sets, "ty")
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 255, _sets.ag)
        rset = RadioSetting("settings.ag", "AF Gain", rx)
        #  rset.set_apply_callback(my_adjraw, _sets, "ag", -1)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 100, _sets.rg)
        rset = RadioSetting("settings.rg", "RF Gain", rx)
        #   rset.set_apply_callback(my_adjraw, _sets, "rg", -1)
        basic.append(rset)

        options = ["ANT1", "ANT2"]
        # CAUTION: an has value of 1 or 2
        rx = RadioSettingValueList(options, options[_sets.an - 1])
        rset = RadioSetting("settings.an", "Antenna Selected", rx)
        # Add 1 to the changed value. S/b 1/2
        rset.set_apply_callback(my_val_list, options, _sets, "an", 1)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 100, _sets.mg)
        rset = RadioSetting("settings.mg", "Microphone gain", rx)
        basic.append(rset)

        nx = 5      # Coarse step
        if bool(_mex[0].ex021):   # Power Fine enabled in menu A
            nx = 1
        vx = _sets.pc       # Trap invalid values from run_tests.py
        if vx < 5:
            vx = 5
        options = [200, 100, 50, 20]    # subject to firmware
        rx = RadioSettingValueInteger(5, options[_sets.ty], vx, nx)
        sx = "TX Output power (Watts)"
        rset = RadioSetting("settings.pc", sx, rx)
        basic.append(rset)

        val = _sets.fa / mhz1       # valid range is for receiver
        rx = RadioSettingValueFloat(0.05, 60.0, val, 0.001, 3)
        sx = "VFO-A Frequency (MHz)"
        rset = RadioSetting("settings.fa", sx, rx)
        rset.set_apply_callback(my_mhz_val, _sets, "fa")
        basic.append(rset)

        val = _sets.fb / mhz1
        rx = RadioSettingValueFloat(0.05, 60.0, val, 0.001, 3)
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
            sx = my_labels(0)
            rx = RadioSettingValueInteger(0, 4, _mex[mx].ex000)
            rset = RadioSetting("exset.ex000", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 9, _mex[mx].ex012)
            sx = my_labels(12)
            rset = RadioSetting("exset.ex012", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(13)
            rx = RadioSettingValueInteger(0, 9, _mex[mx].ex013)
            rset = RadioSetting("exset.ex013", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            sx = my_labels(14)
            rx = RadioSettingValueInteger(0, 9, _mex[mx].ex014)
            rset = RadioSetting("exset.ex014", sx, rx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["250", "500", "1000"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex003])
            sx = my_labels(3)
            rset = RadioSetting("exset.ex003/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex003", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex007))
            sx = my_labels(7)
            rset = RadioSetting("exset.ex007/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex007", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex008))
            sx = my_labels(8)
            rset = RadioSetting("exset.ex008/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex008", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["100", "200", "300", "400", "500"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex009])
            sx = my_labels(9)
            rset = RadioSetting("exset.ex009/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex009", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex010))
            sx = my_labels(10)
            rset = RadioSetting("exset.ex010/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex010", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["TO", "CO"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex011])
            sx = my_labels(11)
            rset = RadioSetting("exset.ex011/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex011", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueBoolean(bool(_mex[mx].ex021))
            sx = my_labels(21)
            rset = RadioSetting("exset.ex021/%d" % mx, sx, rx)
            rset.set_apply_callback(my_bool, _mex, "ex021", mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            options = ["Off", "3", "5", "10", "20", "30"]
            rx = RadioSettingValueList(options, options[_mex[mx].ex022])
            sx = my_labels(22)
            rset = RadioSetting("exset.ex022/%d" % mx, sx, rx)
            rset.set_apply_callback(my_val_list, options, _mex,
                                    "ex022", 0, mx)
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 99, _mex[mx].ex048)
            sx = my_labels(48)
            rset = RadioSetting("exset.ex048/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex048")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 99, _mex[mx].ex049)
            sx = my_labels(49)
            rset = RadioSetting("exset.ex049/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex049")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 99, _mex[mx].ex050)
            sx = my_labels(50)
            rset = RadioSetting("exset.ex050/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex050")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 99, _mex[mx].ex051)
            sx = my_labels(51)
            rset = RadioSetting("exset.ex051/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex051")
            if mx == 0:
                mena.append(rset)
            else:
                menb.append(rset)

            rx = RadioSettingValueInteger(0, 99, _mex[mx].ex052)
            sx = my_labels(52)
            rset = RadioSetting("exset.ex052/%d" % mx, sx, rx)
            rset.set_apply_callback(my_fnctns, _mex, mx, "ex052")
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
            rx = RadioSettingValueList(TS480_MODES, TS480_MODES[mx])
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
        return
