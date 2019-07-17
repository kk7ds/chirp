# Copyright 2019: Rick DeWitt (RJD), <aa0rd@yahoo.com>
# Version 1.0 for TYT-UV8000D/E
# Thanks to Damon Schaefer (K9CQB) and the Loudoun County, VA ARES
#    club for the donated radio.
# And thanks to Ian Harris (VA3IHX) for decoding the memory map.
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

import time
import struct
import logging
import re
import math
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct chns {
  ul32 rxfreq;
  ul32 txfreq;
  u8 rxtone[2];
  u8 txtone[2];
  u8  wide:1   // 0x0c
      vox_on:1
      chunk01:1
      bcl:1    // inv bool
      epilogue:1
      power:1
      chunk02:1
      chunk03:1;
  u8  ani:1     // 0x0d inv
      chunk08:1
      ptt:2
      chpad04:4;
  u8  chunk05;  // 0x0e
  u16 id_code; // 0x0f, 10
  u8  chunk06;
  u8  name[7];
  ul32 chpad06; // Need 56 byte pad
  ul16 chpad07;
  u8  chpad08;
};

struct fm_chn {
  ul16 rxfreq;
};

struct frqx {
  ul32 rxfreq;
  ul24 ofst;
  u8  fqunk01:4  // 0x07
      funk10:2
      duplx:2;
  u8 rxtone[2]; // 0x08, 9
  u8 txtone[2]; // 0x0a, b
  u8  wide:1    // 0x0c
      vox_on:1
      funk11:1
      bcl:1     // inv bool
      epilogue:1
      power:1
      fqunk02:2;
  u8  ani:1     // 0x0d inv bool
      fqunk03:1
      ptt:2
      fqunk12:1
      fqunk04:3;
  u8  fqunk07;  // 0x0e
  u16 id_code;  // 0x0f, 0x10
  u8  name[7];    // dummy
  u8 fqunk09[8];  // empty bytes after 1st entry
};

struct bitmap {
  u8  map[16];
};

#seekto 0x0010;
struct chns chan_mem[128];

#seekto 0x1010;
struct frqx frq[2];

#seekto 0x1050;
struct fm_chn fm_stations[25];

#seekto 0x1080;
struct {
  u8  fmunk01[14];
  ul16 fmcur;
} fmfrqs;

#seekto 0x1190;
struct bitmap chnmap;

#seekto 0x11a0;
struct bitmap skpchns;

#seekto 0x011b0;
struct {
  u8  fmset[4];
} fmmap;

#seekto 0x011b4;
struct {
  u8  setunk01[4];
  u8  setunk02[3];
  u8  chs_name:1    // 0x11bb
      txsel:1
      dbw:1
      setunk05:1
      ponfmchs:2
      ponchs:2;
  u8  voltx:2       // 0x11bc
      setunk04:1
      keylok:1
      setunk07:1
      batsav:3;
  u8  setunk09:1    // 0x11bd
      rxinhib:1
      rgrbeep:1    // inv bool
      lampon:2
      voice:2
      beepon:1;
  u8  setunk11:1    // 0x11be
      manualset:1
      xbandon:1     // inv
      xbandenable:1
      openmsg:2
      ledclr:2;
  u8  tot:4         // 0x11bf
      sql:4;
  u8  setunk27:1   // 0x11c0
      voxdelay:2
      setunk28:1
      voxgain:4;
  u8  fmstep:4      // 0x11c1
      freqstep:4;
  u8  scanspeed:4   // 0x11c2
      scanmode:4;
  u8  scantmo;      // 0x11c3
  u8  prichan;      // 0x11c4
  u8  setunk12:4    // 0x11c5
      supersave:4;
  u8  setunk13;
  u8  fmsclo;       // 0x11c7 ??? placeholder
  u8  radioname[7]; // hex char codes, not true ASCII
  u8  fmschi;       // ??? placeholder
  u8  setunk14[3];  // 0x11d0
  u8 setunk17[2];   // 0x011d3, 4
  u8  setunk18:4
      dtmfspd:4;
  u8  dtmfdig1dly:4 // 0x11d6
      dtmfdig1time:4;
  u8  stuntype:1
      setunk19:1
      dtmfspms:2
      grpcode:4;
  u8  setunk20:1    // 0x11d8
      txdecode:1
      codeabcd:1
      idedit:1
      pttidon:2
      setunk40:1,
      dtmfside:1;
  u8  setunk50:4,
      autoresettmo:4;
  u8  codespctim:4, // 0x11da
      decodetmo:4;
  u8  pttecnt:4     // 0x11db
      pttbcnt:4;
  lbcd  dtmfdecode[3];
  u8  setunk22;
  u8  stuncnt;      // 0x11e0
  u8  stuncode[5];
  u8  setunk60;
  u8  setunk61;
  u8  pttbot[8];    // 0x11e8-f
  u8  ptteot[8];    // 0x11f0-7
  u8  setunk62;     // 0x11f8
  u8  setunk63;
  u8  setunk64;     // 0x11fa
  u8  setunk65;
  u8  setunk66;
  u8  manfrqyn;     // 0x11fd
  u8  setunk27:3
      frqr3:1
      setunk28:1
      frqr2:1
      setunk29:1
      frqr1:1;
  u8  setunk25;
  ul32 frqr1lo;  // 0x1200
  ul32 frqr1hi;
  ul32 frqr2lo;
  ul32 frqr2hi;
  ul32 frqr3lo;  // 0x1210
  ul32 frqr3hi;
  u8 setunk26[8];
} setstuf;

#seekto 0x1260;
struct {
  u8 modnum[7];
} modcode;

#seekto 0x1300;
struct {
  char  mod_num[9];
} mod_id;
"""

MEM_SIZE = 0x1300
BLOCK_SIZE = 0x10   # can read 0x20, but must write 0x10
STIMEOUT = 2
BAUDRATE = 4800
# Channel power: 2 levels
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                chirp_common.PowerLevel("High", watts=10.00)]

LIST_RECVMODE = ["QT/DQT", "QT/DQT + Signaling"]
LIST_COLOR = ["Off", "Orange", "Blue", "Purple"]
LIST_LEDSW = ["Auto", "On"]
LIST_TIMEOUT = ["Off"] + ["%s" % x for x in range(30, 390, 30)]
LIST_VFOMODE = ["Frequency Mode", "Channel Mode"]
# Tones are numeric, Defined in \chirp\chirp_common.py
TONES_CTCSS = sorted(chirp_common.TONES)
# Converted to strings
LIST_CTCSS = ["Off"] + [str(x) for x in TONES_CTCSS]
# Now append the DxxxN and DxxxI DTCS codes from chirp_common
for x in chirp_common.DTCS_CODES:
    LIST_CTCSS.append("D{:03d}N".format(x))
for x in chirp_common.DTCS_CODES:
    LIST_CTCSS.append("D{:03d}R".format(x))
LIST_BW = ["Narrow", "Wide"]
LIST_SHIFT = ["off", "+", "-"]
STEPS = [0.5, 2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 37.5, 50.0, 100.0]
LIST_STEPS = [str(x) for x in STEPS]
LIST_VOXDLY = ["0.5", "1.0", "2.0", "3.0"]      # LISTS must be strings
LIST_PTT = ["Both", "EoT", "BoT", "Off"]

SETTING_LISTS = {"tot": LIST_TIMEOUT, "wtled": LIST_COLOR,
                 "rxled": LIST_COLOR, "txled": LIST_COLOR,
                 "ledsw": LIST_LEDSW, "frq_chn_mode": LIST_VFOMODE,
                 "rx_tone": LIST_CTCSS, "tx_tone": LIST_CTCSS,
                 "rx_mode": LIST_RECVMODE, "fm_bw": LIST_BW,
                 "shift": LIST_SHIFT, "step": LIST_STEPS,
                 "vox_dly": LIST_VOXDLY, "ptt": LIST_PTT}


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


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the headder format"""
    frame = struct.pack(">shB", cmd, addr, length)
    # Add the data if set
    if len(data) != 0:
        frame += data
    # Return the data
    return frame


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

    # Flush input buffer
    _clean_buffer(radio)

    magic = "PROGRAMa"
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 1)
    # LOG.warning("PROGa Ack:" + util.hexprint(ack))
    if ack != "\x06":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")
    magic = "PROGRAMb"
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 1)
    if ack != "\x06":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to B")
    magic = chr(0x02)
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 1)    # s/b: 0x50
    magic = _rawrecv(radio, 7)  # s/b TC88...
    magic = "MTC88CUMHS3E7BN-"
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 1)    # s/b 0x80
    magic = chr(0x06)
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 1)

    return True


def _exit_program_mode(radio):
    endframe = "E"
    _rawsend(radio, endframe)


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_frame("R", addr, BLOCK_SIZE)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug("Frame=" + util.hexprint(frame))

        # Sending the read request
        _rawsend(radio, frame)
        dx = _rawrecv(radio, 4)

        # Now we read data
        d = _recv(radio, addr, BLOCK_SIZE)
        # LOG.warning("Data= " + util.hexprint(d))

        # Aggregate the data
        data += d

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)

    return data


def _upload(radio):
    """Upload procedure"""
    # Put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # The fun starts here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # Sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_frame("W", addr, BLOCK_SIZE, data)
        # LOG.warning("Frame:%s:" % util.hexprint(frame))
        _rawsend(radio, frame)

        # Receiving the response
        ack = _rawrecv(radio, 1)
        if ack != "\x06":
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def set_tone(_mem, txrx, ctdt, tval, pol):
    """Set rxtone[] or txtone[] word values as decimal bytes"""
    # txrx: Boolean T= set Rx tones, F= set Tx tones
    # ctdt: Boolean T = CTCSS, F= DTCS
    # tval = integer tone freq (*10) or DTCS code
    # pol = string for DTCS polarity "R" or "N"
    xv = int(str(tval), 16)
    if txrx:        # True = set rxtones
        _mem.rxtone[0] = xv & 0xFF  # Low byte
        _mem.rxtone[1] = (xv >> 8)   # Hi byte
        if not ctdt:    # dtcs,
            if pol == "R":
                _mem.rxtone[1] = _mem.rxtone[1] | 0xC0
            else:
                _mem.rxtone[1] = _mem.rxtone[1] | 0x80
    else:           # txtones
        _mem.txtone[0] = xv & 0xFF  # Low byte
        _mem.txtone[1] = (xv >> 8)
        if not ctdt:    # dtcs
            if pol == "R":
                _mem.txtone[1] = _mem.txtone[1] | 0xC0
            else:
                _mem.txtone[1] = _mem.txtone[1] | 0x80

    return 0


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


@directory.register
class THUV8000Radio(chirp_common.CloneModeRadio):
    """TYT UV8000D Radio"""
    VENDOR = "TYT"
    MODEL = "TH-UV8000"
    MODES = ["NFM", "FM"]
    TONES = chirp_common.TONES
    DTCS_CODES = sorted(chirp_common.DTCS_CODES + [645])
    NAME_LENGTH = 7
    DTMF_CHARS = list("0123456789ABCD*#")
    # NOTE: SE Model supports 220-260 MHz
    # The following bands are the the range the radio is capable of,
    #   not the legal FCC amateur bands
    VALID_BANDS = [(87500000, 107900000), (136000000, 174000000),
                   (220000000, 260000000), (400000000, 520000000)]

    # Valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`!\"#$%&'()*+,-./:;<=>?@[]^_"

    # Special Channels Declaration
    # WARNING Indecis are hard wired in get/set_memory code !!!
    # Channels print in + increasing index order (most negative first)
    SPECIAL_MEMORIES = {
       "UpVFO": -2,
       "LoVFO": -1
    }
    FIRST_FREQ_INDEX = -1
    LAST_FREQ_INDEX = -2

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = \
            ('Click on the "Special Channels" toggle-button of the memory '
             'editor to see/set the upper and lower frequency-mode values.\n')

        rp.pre_download = _(dedent("""\
            Follow these instructions to download the radio memory:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio, volume @ 50%
            4 - Radio > Download from radio
            """))
        rp.pre_upload = _(dedent("""\
            Follow these instructions to upload the radio memory:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio, volume @ 50%
            4 - Radio > Upload to radio
            """))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        # .has. attributes are boolean, .valid. are lists
        rf.has_settings = True
        rf.has_bank = False
        rf.has_comment = False
        rf.has_nostep_tuning = True     # Radio accepts any entered freq
        rf.has_tuning_step = False      # Not as chan feature
        rf.can_odd_split = False
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
        rf.valid_duplexes = ["-", "+", "off", ""]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS",
                                "Tone->DTCS", "DTCS->Tone", "->Tone",
                                "DTCS->DTCS"]
        rf.valid_skips = []
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, 128)
        rf.valid_skips = ["", "S"]
        rf.valid_special_chans = sorted(self.SPECIAL_MEMORIES.keys())
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
        self._mmap = memmap.MemoryMap(data)
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
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        elif number < 0:
            # I can't stop delete operation from loosing extd_number but
            # I know how to get it back
            return self._get_special(self.SPECIAL_MEMORIES_REV[number])
        else:
            return self._get_normal(number)

    def set_memory(self, memory):
        """A value in a UI column for chan 'number' has been modified."""
        # update all raw channel memory values (_mem) from UI (mem)
        if memory.number < 0:
            return self._set_special(memory)
        else:
            return self._set_normal(memory)

    def _get_normal(self, number):
        # radio first channel is 1, mem map is base 0
        _mem = self._memobj.chan_mem[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        return self._get_memory(mem, _mem)

    def _get_memory(self, mem, _mem):
        """Convert raw channel memory data into UI columns"""
        mem.extra = RadioSettingGroup("extra", "Extra")

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.empty = False
        # This function process both 'normal' and Freq up/down' entries
        mem.freq = int(_mem.rxfreq) * 10
        mem.power = POWER_LEVELS[_mem.power]
        mem.mode = self.MODES[_mem.wide]
        dtcs_pol = ["N", "N"]

        if _mem.rxtone[0] == 0xFF:
            rxmode = ""
        elif _mem.rxtone[1] < 0x26:
            # CTCSS
            rxmode = "Tone"
            tonehi = int(str(_mem.rxtone[1])[2:])
            tonelo = int(str(_mem.rxtone[0])[2:])
            mem.ctone = int(tonehi * 100 + tonelo) / 10.0
        else:
            # Digital
            rxmode = "DTCS"
            tonehi = int(str(_mem.rxtone[1] & 0x3f))
            tonelo = int(str(_mem.rxtone[0])[2:])
            mem.rx_dtcs = int(tonehi * 100 + tonelo)
            if (_mem.rxtone[1] & 0x40) != 0:
                dtcs_pol[1] = "R"

        if _mem.txtone[0] == 0xFF:
            txmode = ""
        elif _mem.txtone[1] < 0x26:
            # CTCSS
            txmode = "Tone"
            tonehi = int(str(_mem.txtone[1])[2:])
            tonelo = int(str(_mem.txtone[0])[2:])
            mem.rtone = int(tonehi * 100 + tonelo) / 10.0
        else:
            # Digital
            txmode = "DTCS"
            tonehi = int(str(_mem.txtone[1] & 0x3f))
            tonelo = int(str(_mem.txtone[0])[2:])
            mem.dtcs = int(tonehi * 100 + tonelo)
            if (_mem.txtone[1] & 0x40) != 0:
                dtcs_pol[0] = "R"

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

        mem.dtcs_polarity = "".join(dtcs_pol)

        # Now test the mem.number to process special vs normal
        if mem.number >= 0:      # Normal
            mem.name = ""
            for i in range(self.NAME_LENGTH):   # 0 - 6
                mem.name += chr(_mem.name[i] + 32)
            mem.name = mem.name.rstrip()    # remove trailing spaces

            if _mem.txfreq == 0xFFFFFFFF:
                # TX freq not set
                mem.duplex = "off"
                mem.offset = 0
            elif int(_mem.rxfreq) == int(_mem.txfreq):
                mem.duplex = ""
                mem.offset = 0
            else:
                mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) \
                    and "-" or "+"
                mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

            if _do_map(mem.number, 2, self._memobj.skpchns.map) > 0:
                mem.skip = "S"
            else:
                mem.skip = ""

        else:       # specials VFO
            mem.name = "----"
            mem.duplex = LIST_SHIFT[_mem.duplx]
            mem.offset = int(_mem.ofst) * 10
            mem.skip = ""
        # End if specials

        # Channel Extra settings: Only Boolean & List methods, no call-backs
        rx = RadioSettingValueBoolean(bool(not _mem.bcl))   # Inverted bool
        # NOTE: first param of RadioSetting is the object attribute name
        rset = RadioSetting("bcl", "Busy Channel Lockout", rx)
        mem.extra.append(rset)

        rx = RadioSettingValueBoolean(bool(not _mem.vox_on))
        rset = RadioSetting("vox_on", "Vox", rx)
        mem.extra.append(rset)

        rx = RadioSettingValueBoolean(bool(not _mem.ani))
        rset = RadioSetting("ani", "Auto Number ID (ANI)", rx)
        mem.extra.append(rset)

        # ID code can't be done in extra - no Integer method or call-back

        rx = RadioSettingValueList(LIST_PTT, LIST_PTT[_mem.ptt])
        rset = RadioSetting("ptt", "Xmit PTT ID", rx)
        mem.extra.append(rset)

        rx = RadioSettingValueBoolean(bool(_mem.epilogue))
        rset = RadioSetting("epilogue", "Epilogue/Tail", rx)
        mem.extra.append(rset)

        return mem

    def _get_special(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_MEMORIES[number]
        mem.extd_number = number
        # Unused attributes are ignored in Set_memory
        if (mem.number == -1) or (mem.number == -2):
            # Print Upper[1] first, and Lower[0] next
            rx = 0
            if mem.number == -2:
                rx = 1
            _mem = self._memobj.frq[rx]
            # immutable = ["number", "extd_number", "name"]
            mem = self._get_memory(mem, _mem)
        else:
            raise Exception("Sorry, you can't edit that special"
                            " memory channel %i." % mem.number)

        # mem.immutable = immutable

        return mem

    def _set_memory(self, mem, _mem):
        """Convert UI column data (mem) into MEM_FORMAT memory (_mem)."""
        # At this point mem points to either normal or Freq chans
        # These first attributes are common to all types
        if mem.empty:
            if mem.number > 0:
                _mem.rxfreq = 0xffffffff
                # Set 'empty' and 'skip' bits
                _do_map(mem.number, 1, self._memobj.chnmap.map)
                _do_map(mem.number, 1, self._memobj.skpchns.map)
            elif mem.number == -2:  # upper VFO Freq
                _mem.rxfreq = 14652000   # VHF National Calling freq
            elif mem.number == -1:  # lower VFO
                _mem.rxfreq = 44600000   # UHF National Calling freq
            return

        _mem.rxfreq = mem.freq / 10

        if str(mem.power) == "Low":
            _mem.power = 0
        else:
            _mem.power = 1

        _mem.wide = self.MODES.index(mem.mode)

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

        sx = mem.dtcs_polarity[1]
        if rxmode == "":
            _mem.rxtone[0] = 0xFF
            _mem.rxtone[1] = 0xFF
        elif rxmode == "Tone":
            val = int(mem.ctone * 10)
            i = set_tone(_mem, True, True, val, sx)
        elif rxmode == "DTCSSQL":
            i = set_tone(_mem, True, False, mem.dtcs, sx)
        elif rxmode == "DTCS":
            i = set_tone(_mem, True, False, mem.rx_dtcs, sx)

        sx = mem.dtcs_polarity[0]
        if txmode == "":
            _mem.txtone[0] = 0xFF
            _mem.txtone[1] = 0xFF
        elif txmode == "Tone":
            val = int(mem.rtone * 10)
            i = set_tone(_mem, False, True, val, sx)
        elif txmode == "TSQL":
            val = int(mem.ctone * 10)
            i = set_tone(_mem, False, True, val, sx)
        elif txmode == "DTCS":
            i = set_tone(_mem, False, False, mem.dtcs, sx)

        if mem.number > 0:      # Normal chans
            for i in range(self.NAME_LENGTH):
                pq = ord(mem.name.ljust(self.NAME_LENGTH)[i]) - 32
                if pq < 0:
                    pq = 0
                _mem.name[i] = pq

            if mem.duplex == "off":
                _mem.txfreq = 0xFFFFFFFF
            elif mem.duplex == "+":
                _mem.txfreq = (mem.freq + mem.offset) / 10
            elif mem.duplex == "-":
                _mem.txfreq = (mem.freq - mem.offset) / 10
            else:
                _mem.txfreq = mem.freq / 10

            # Set the channel map bit FALSE = Enabled
            _do_map(mem.number, 0, self._memobj.chnmap.map)
            # Skip
            if mem.skip == "S":
                _do_map(mem.number, 1, self._memobj.skpchns.map)
            else:
                _do_map(mem.number, 0, self._memobj.skpchns.map)

        else:    # Freq (VFO) chans
            _mem.duplx = 0
            _mem.ofst = 0
            if mem.duplex == "+":
                _mem.duplx = 1
                _mem.ofst = mem.offset / 10
            elif mem.duplex == "-":
                _mem.duplx = 2
                _mem.ofst = mem.offset / 10
            for i in range(self.NAME_LENGTH):
                _mem.name[i] = 0xff

        # All mem.extra << Once the channel is defined
        for setting in mem.extra:
            # Overide list strings with signed value
            if setting.get_name() == "ptt":
                sx = str(setting.value)
                for i in range(0, 4):
                    if sx == LIST_PTT[i]:
                        val = i
                setattr(_mem, "ptt", val)
            elif setting.get_name() == "epilogue":  # not inverted bool
                setattr(_mem, setting.get_name(), setting.value)
            else:       # inverted booleans
                setattr(_mem, setting.get_name(), not setting.value)

    def _set_special(self, mem):

        cur_mem = self._get_special(self.SPECIAL_MEMORIES_REV[mem.number])

        if mem.number == -2:    # upper frq[1]
            _mem = self._memobj.frq[1]
        elif mem.number == -1:  # lower frq[0]
            _mem = self._memobj.frq[0]
        else:
            raise Exception("Sorry, you can't edit that special memory.")

        self._set_memory(mem, _mem)     # Now update the _mem

    def _set_normal(self, mem):
        _mem = self._memobj.chan_mem[mem.number - 1]

        self._set_memory(mem, _mem)

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        # Define mem struct write-back shortcuts
        _sets = self._memobj.setstuf
        _fmx = self._memobj.fmfrqs

        basic = RadioSettingGroup("basic", "Basic Settings")
        adv = RadioSettingGroup("adv", "Other Settings")
        fmb = RadioSettingGroup("fmb", "FM Broadcast")
        scn = RadioSettingGroup("scn", "Scan Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        frng = RadioSettingGroup("frng", "Frequency Ranges")
        group = RadioSettings(basic, adv, scn, fmb, dtmf, frng)

        def my_val_list(setting, obj, atrb):
            """Callback:from ValueList with non-sequential, actual values."""
            # This call back also used in get_settings
            value = int(str(setting.value))  # Get the integer value
            setattr(obj, atrb, value)
            return

        def my_adjraw(setting, obj, atrb, fix):
            """Callback from Integer add or subtract fix from value."""
            vx = int(str(setting.value))
            value = vx + int(fix)
            if value < 0:
                value = 0
            setattr(obj, atrb, value)
            return

        def my_strnam(setting, obj, atrb, mln):
            """Callback from String to build u8 array with -32 offset."""
            # mln is max string length
            ary = []
            knt = mln
            for j in range(mln - 1, -1, -1):  # Strip trailing spaces or nulls
                pq = str(setting.value)[j]
                if pq == "" or pq == " ":
                    knt = knt - 1
                else:
                    break
            for j in range(mln):  # 0 to mln-1
                pq = str(setting.value).ljust(mln)[j]
                if j < knt:
                    ary.append(ord(pq) - 32)
                else:
                    ary.append(0)
            setattr(obj, atrb, ary)
            return

        def unpack_str(cary, cknt, mxw):
            """Convert u8 nibble array to a string: NOT a callback."""
            # cknt is char count, 2/word; mxw is max WORDS
            stx = ""
            mty = True
            for i in range(mxw):    # unpack entire array
                nib = (cary[i] & 0xf0) >> 4  # LE, Hi nib first
                if nib != 0xf:
                    mty = False
                stx += format(nib, '0X')
                nib = cary[i] & 0xf
                if nib != 0xf:
                    mty = False
                stx += format(nib, '0X')
            stx = stx[:cknt]
            if mty:     # all ff, empty string
                sty = ""
            else:
                # Convert E to #, F to *
                sty = ""
                for i in range(cknt):
                    if stx[i] == "E":
                        sty += "#"
                    elif stx[i] == "F":
                        sty += "*"
                    else:
                        sty += stx[i]

            return sty

        def pack_chars(setting, obj, atrstr, atrcnt, mxl):
            """Callback to build 0-9,A-D,*# nibble array from string"""
            # cknt is generated char count, 2 chars per word
            # String will be f padded to mxl
            # Chars are stored as hex values
            # store cknt-1 in atrcnt, 0xf if empty
            cknt = 0
            ary = []
            stx = str(setting.value).upper()
            stx = stx.strip()       # trim spaces
            # Remove illegal characters first
            sty = ""
            for j in range(0, len(stx)):
                if stx[j] in self.DTMF_CHARS:
                    sty += stx[j]
            for j in range(mxl):
                if j < len(sty):
                    if sty[j] == "#":
                        chrv = 0xE
                    elif sty[j] == "*":
                        chrv = 0xF
                    else:
                        chrv = int(sty[j], 16)
                    cknt += 1      # char count
                else:   # pad to mxl, cknt does not increment
                    chrv = 0xF
                if (j % 2) == 0:  # odd count (0-based), high nibble
                    hi_nib = chrv
                else:   # even count, lower nibble
                    lo_nib = chrv
                    nibs = lo_nib | (hi_nib << 4)
                    ary.append(nibs)    # append word
            setattr(obj, atrstr, ary)
            if setting.get_name() != "setstuf.stuncode":  # cknt is actual
                if cknt > 0:
                    cknt = cknt - 1
                else:
                    cknt = 0xf
            setattr(obj, atrcnt, cknt)
            return

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        def my_invbool(setting, obj, atrb):
            """Callback to invert the boolean """
            bval = not setting.value
            setattr(obj, atrb, bval)
            return

        def my_batsav(setting, obj, atrb):
            """Callback to set batsav attribute """
            stx = str(setting.value)  # Off, 1:1...
            if stx == "Off":
                value = 0x1     # bit value 4 clear, ratio 1 = 1:2
            elif stx == "1:1":
                value = 0x4     # On, ratio 0 = 1:1
            elif stx == "1:2":
                value = 0x5     # On, ratio 1 = 1:2
            elif stx == "1:3":
                value = 0x6     # On, ratio 2 = 1:3
            else:
                value = 0x7     # On, ratio 3 = 1:4
            # LOG.warning("Batsav stx:%s:, value= %x" % (stx, value))
            setattr(obj, atrb, value)
            return

        def my_manfrq(setting, obj, atrb):
            """Callback to set 2-byte manfrqyn yes/no """
            # LOG.warning("Manfrq value = %d" % setting.value)
            if (str(setting.value)) == "No":
                value = 0xff
            else:
                value = 0xaa
            setattr(obj, atrb, value)
            return

        def myset_mask(setting, obj, atrb, nx):
            if bool(setting.value):     # Enabled = 0
                vx = 0
            else:
                vx = 1
            _do_map(nx + 1, vx, self._memobj.fmmap.fmset)
            return

        def myset_fmfrq(setting, obj, atrb, nx):
            """ Callback to set xx.x FM freq in memory as xx.x * 40"""
            # in-valid even KHz freqs are allowed; to satisfy run_tests
            vx = float(str(setting.value))
            vx = int(vx * 40)
            setattr(obj[nx], atrb, vx)
            return

        rx = RadioSettingValueInteger(1, 9, _sets.voxgain + 1)
        rset = RadioSetting("setstuf.voxgain", "Vox Level", rx)
        rset.set_apply_callback(my_adjraw, _sets, "voxgain", -1)
        basic.append(rset)

        rx = RadioSettingValueList(LIST_VOXDLY, LIST_VOXDLY[_sets.voxdelay])
        rset = RadioSetting("setstuf.voxdelay", "Vox Delay (secs)", rx)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 9, _sets.sql)
        rset = RadioSetting("setstuf.sql", "Squelch", rx)
        basic.append(rset)

        rx = RadioSettingValueList(LIST_STEPS, LIST_STEPS[_sets.freqstep])
        rset = RadioSetting("setstuf.freqstep", "VFO Tune Step (KHz))", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.dbw))     # true logic
        rset = RadioSetting("setstuf.dbw", "Dual Band Watch (D.WAIT)", rx)
        basic.append(rset)

        options = ["Off", "On", "Auto"]
        rx = RadioSettingValueList(options, options[_sets.lampon])
        rset = RadioSetting("setstuf.lampon", "Backlight (LED)", rx)
        basic.append(rset)

        options = ["Orange", "Purple", "Blue"]
        rx = RadioSettingValueList(options, options[_sets.ledclr])
        rset = RadioSetting("setstuf.ledclr", "Backlight Color (LIGHT)", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.beepon))
        rset = RadioSetting("setstuf.beepon", "Keypad Beep", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.xbandenable))
        rset = RadioSetting("setstuf.xbandenable", "Cross Band Allowed", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(not _sets.xbandon))
        rset = RadioSetting("setstuf.xbandon", "Cross Band On", rx)
        rset.set_apply_callback(my_invbool, _sets, "xbandon")
        basic.append(rset)

        rx = RadioSettingValueList(LIST_TIMEOUT, LIST_TIMEOUT[_sets.tot])
        rset = RadioSetting("setstuf.tot", "TX Timeout (Secs)", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(not _sets.rgrbeep))  # Invert
        rset = RadioSetting("setstuf.rgrbeep", "Beep at Eot (Roger)", rx)
        rset.set_apply_callback(my_invbool, _sets, "rgrbeep")
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(not _sets.keylok))
        rset = RadioSetting("setstuf.keylok", "Keypad AutoLock", rx)
        rset.set_apply_callback(my_invbool, _sets, "keylok")
        basic.append(rset)

        options = ["None", "Message", "DC Volts"]
        rx = RadioSettingValueList(options, options[_sets.openmsg])
        rset = RadioSetting("setstuf.openmsg", "Power-On Display", rx)
        basic.append(rset)

        options = ["Channel Name", "Frequency"]
        rx = RadioSettingValueList(options, options[_sets.chs_name])
        rset = RadioSetting("setstuf.chs_name", "Display Name/Frq", rx)
        basic.append(rset)

        sx = ""
        for i in range(7):
            if _sets.radioname[i] != 0:
                sx += chr(_sets.radioname[i] + 32)
        rx = RadioSettingValueString(0, 7, sx)
        rset = RadioSetting("setstuf.radioname", "Power-On Message", rx)
        rset.set_apply_callback(my_strnam, _sets, "radioname", 7)
        basic.append(rset)

        # Advanced (Strange) Settings
        options = ["Busy: Last Tx Band", "Edit: Current Band"]
        rx = RadioSettingValueList(options, options[_sets.txsel])
        rset = RadioSetting("setstuf.txsel", "Transmit Priority", rx)
        rset.set_doc("'Busy' transmits on last band used, not current one.")
        adv.append(rset)

        options = ["Off", "English", "Unk", "Chinese"]
        val = _sets.voice
        rx = RadioSettingValueList(options, options[val])
        rset = RadioSetting("setstuf.voice", "Voice", rx)
        adv.append(rset)

        options = ["Off", "1:1", "1:2", "1:3", "1:4"]
        val = (_sets.batsav & 0x3) + 1     # ratio
        if (_sets.batsav & 0x4) == 0:    # Off
            val = 0
        rx = RadioSettingValueList(options, options[val])
        rset = RadioSetting("setstuf.batsav", "Battery Saver", rx)
        rset.set_apply_callback(my_batsav, _sets, "batsav")
        adv.append(rset)

        # Find out what & where SuperSave is
        options = ["Off", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
        rx = RadioSettingValueList(options, options[_sets.supersave])
        rset = RadioSetting("setstuf.supersave", "Super Save (Secs)", rx)
        rset.set_doc("Unknown radio attribute??")
        adv.append(rset)

        sx = unpack_str(_sets.pttbot, _sets.pttbcnt + 1, 8)
        rx = RadioSettingValueString(0, 16, sx)
        rset = RadioSetting("setstuf.pttbot", "PTT BoT Code", rx)
        rset.set_apply_callback(pack_chars, _sets, "pttbot", "pttbcnt", 16)
        adv.append(rset)

        sx = unpack_str(_sets.ptteot, _sets.pttecnt + 1, 8)
        rx = RadioSettingValueString(0, 16, sx)
        rset = RadioSetting("setstuf.ptteot", "PTT EoT Code", rx)
        rset.set_apply_callback(pack_chars, _sets, "ptteot", "pttecnt", 16)
        adv.append(rset)

        options = ["None", "Low", "High", "Both"]
        rx = RadioSettingValueList(options, options[_sets.voltx])
        rset = RadioSetting("setstuf.voltx", "Transmit Inhibit Voltage", rx)
        rset.set_doc("Block Transmit if battery volts are too high or low,")
        adv.append(rset)

        val = 0     # No = 0xff
        if _sets.manfrqyn == 0xaa:
            val = 1
        options = ["No", "Yes"]
        rx = RadioSettingValueList(options, options[val])
        rset = RadioSetting("setstuf.manfrqyn", "Manual Frequency", rx)
        rset.set_apply_callback(my_manfrq, _sets, "manfrqyn")
        adv.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.manualset))
        rset = RadioSetting("setstuf.manualset", "Manual Setting", rx)
        adv.append(rset)

        # Scan Settings
        options = ["CO: During Rx", "TO: Timed", "SE: Halt"]
        rx = RadioSettingValueList(options, options[_sets.scanmode])
        rset = RadioSetting("setstuf.scanmode",
                            "Scan Mode (Scan Pauses When)", rx)
        scn.append(rset)

        options = ["100", "150", "200", "250",
                   "300", "350", "400", "450"]
        rx = RadioSettingValueList(options, options[_sets.scanspeed])
        rset = RadioSetting("setstuf.scanspeed", "Scan Speed (ms)", rx)
        scn.append(rset)

        val = _sets.scantmo + 3
        rx = RadioSettingValueInteger(3, 30, val)
        rset = RadioSetting("setstuf.scantmo",
                            "TO Mode Timeout (secs)", rx)
        rset.set_apply_callback(my_adjraw, _sets, "scantmo", -3)
        scn.append(rset)

        val = _sets.prichan
        if val <= 0:
            val = 1
        rx = RadioSettingValueInteger(1, 128, val)
        rset = RadioSetting("setstuf.prichan", "Priority Channel", rx)
        scn.append(rset)

        # FM Broadcast Settings
        val = _fmx.fmcur
        val = val / 40.0
        if val < 87.5 or val > 107.9:
            val = 88.0
        rx = RadioSettingValueFloat(87.5, 107.9, val, 0.1, 1)
        rset = RadioSetting("fmfrqs.fmcur", "Manual FM Freq (MHz)", rx)
        rset.set_apply_callback(myset_freq, _fmx, "fmcur", 40)
        fmb.append(rset)

        options = ["5", "50", "100", "200(USA)"]    # 5 is not used
        rx = RadioSettingValueList(options, options[_sets.fmstep])
        rset = RadioSetting("setstuf.fmstep", "FM Freq Step (KHz)", rx)
        fmb.append(rset)

        # FM Scan Range fmsclo and fmschi are unknown memory locations,
        # Not supported at this time

        rx = RadioSettingValueBoolean(bool(_sets.rxinhib))
        rset = RadioSetting("setstuf.rxinhib",
                            "Rcvr Will Interupt FM (DW)", rx)
        fmb.append(rset)

        _fmfrq = self._memobj.fm_stations
        _fmap = self._memobj.fmmap
        for j in range(0, 25):
            val = _fmfrq[j].rxfreq
            if val == 0xFFFF:
                val = 88.0
                fmset = False
            else:
                val = (float(int(val)) / 40)
                # get fmmap bit value: 0 = enabled
                ndx = int(math.floor((j) / 8))
                bv = j % 8
                msk = 1 << bv
                vx = _fmap.fmset[ndx]
                fmset = not bool(vx & msk)
            rx = RadioSettingValueBoolean(fmset)
            rset = RadioSetting("fmmap.fmset/%d" % j,
                                "FM Preset %02d" % (j + 1), rx)
            rset.set_apply_callback(myset_mask, _fmap, "fmset", j)
            fmb.append(rset)

            rx = RadioSettingValueFloat(87.5, 107.9, val, 0.1, 1)
            rset = RadioSetting("fm_stations/%d.rxfreq" % j,
                                "    Preset %02d Freq" % (j + 1), rx)
            # This callback uses the array index
            rset.set_apply_callback(myset_fmfrq, _fmfrq, "rxfreq", j)
            fmb.append(rset)

        # DTMF Settings
        options = [str(x) for x in range(4, 16)]
        rx = RadioSettingValueList(options, options[_sets.dtmfspd])
        rset = RadioSetting("setstuf.dtmfspd",
                            "Tx Speed (digits/sec)", rx)
        dtmf.append(rset)

        options = [str(x) for x in range(0, 1100, 100)]
        rx = RadioSettingValueList(options, options[_sets.dtmfdig1time])
        rset = RadioSetting("setstuf.dtmfdig1time",
                            "Tx 1st Digit Time (ms)", rx)
        dtmf.append(rset)

        options = [str(x) for x in range(100, 1100, 100)]
        rx = RadioSettingValueList(options, options[_sets.dtmfdig1dly])
        rset = RadioSetting("setstuf.dtmfdig1dly",
                            "Tx 1st Digit Delay (ms)", rx)
        dtmf.append(rset)

        options = ["0", "100", "500", "1000"]
        rx = RadioSettingValueList(options, options[_sets.dtmfspms])
        rset = RadioSetting("setstuf.dtmfspms",
                            "Tx Star & Pound Time (ms)", rx)
        dtmf.append(rset)

        options = ["None"] + [str(x) for x in range(600, 2100, 100)]
        rx = RadioSettingValueList(options, options[_sets.codespctim])
        rset = RadioSetting("setstuf.codespctim",
                            "Tx Code Space Time (ms)", rx)
        dtmf.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.codeabcd))
        rset = RadioSetting("setstuf.codeabcd", "Tx Codes A,B,C,D", rx)
        dtmf.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.dtmfside))
        rset = RadioSetting("setstuf.dtmfside", "DTMF Side Tone", rx)
        dtmf.append(rset)

        options = ["Off", "A", "B", "C", "D"]
        rx = RadioSettingValueList(options, options[_sets.grpcode])
        rset = RadioSetting("setstuf.grpcode", "Rx Group Code", rx)
        dtmf.append(rset)

        options = ["Off"] + [str(x) for x in range(1, 16)]
        rx = RadioSettingValueList(options, options[_sets.autoresettmo])
        rset = RadioSetting("setstuf.autoresettmo",
                            "Rx Auto Reset Timeout (secs)", rx)
        dtmf.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.txdecode))
        rset = RadioSetting("setstuf.txdecode", "Tx Decode", rx)
        dtmf.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.idedit))
        rset = RadioSetting("setstuf.idedit", "Allow ANI Code Edit", rx)
        dtmf.append(rset)

        options = [str(x) for x in range(500, 1600, 100)]
        rx = RadioSettingValueList(options, options[_sets.decodetmo])
        rset = RadioSetting("setstuf.decodetmo",
                            "Rx Decode Timeout (ms)", rx)
        dtmf.append(rset)

        options = ["Tx & Rx Inhibit", "Tx Inhibit"]
        rx = RadioSettingValueList(options, options[_sets.stuntype])
        rset = RadioSetting("setstuf.stuntype", "Stun Type", rx)
        dtmf.append(rset)

        sx = unpack_str(_sets.stuncode, _sets.stuncnt, 5)
        rx = RadioSettingValueString(0, 10, sx)
        rset = RadioSetting("setstuf.stuncode", "Stun Code", rx)
        rset.set_apply_callback(pack_chars, _sets,
                                "stuncode", "stuncnt", 10)
        dtmf.append(rset)

        # Frequency ranges
        rx = RadioSettingValueBoolean(bool(_sets.frqr1))
        rset = RadioSetting("setstuf.frqr1", "Freq Range 1 (UHF)", rx)
        rset.set_doc("Enable the UHF frequency bank.")
        frng.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.frqr2))
        rset = RadioSetting("setstuf.frqr2", "Freq Range 2 (VHF)", rx)
        rset.set_doc("Enable the VHF frequency bank.")
        frng.append(rset)

        mod_se = True     # UV8000SE has 3rd freq bank
        if mod_se:
            rx = RadioSettingValueBoolean(bool(_sets.frqr3))
            rset = RadioSetting("setstuf.frqr3", "Freq Range 3 (220Mhz)", rx)
            rset.set_doc("Enable the 220MHz frequency bank.")
            frng.append(rset)

        frqm = 100000
        val = _sets.frqr1lo / frqm
        rx = RadioSettingValueFloat(400.0, 520.0, val, 0.005, 3)
        rset = RadioSetting("setstuf.frqr1lo",
                            "UHF Range Low Limit (MHz)", rx)
        rset.set_apply_callback(myset_freq, _sets, "frqr1lo", frqm)
        rset.set_doc("Low limit of the UHF frequency bank.")
        frng.append(rset)

        val = _sets.frqr1hi / frqm
        rx = RadioSettingValueFloat(400.0, 520.0, val, 0.005, 3)
        rset = RadioSetting("setstuf.frqr1hi",
                            "UHF Range High Limit (MHz)", rx)
        rset.set_apply_callback(myset_freq, _sets, "frqr1hi", frqm)
        rset.set_doc("High limit of the UHF frequency bank.")
        frng.append(rset)

        val = _sets.frqr2lo / frqm
        rx = RadioSettingValueFloat(136.0, 174.0, val, 0.005, 3)
        rset = RadioSetting("setstuf.frqr2lo",
                            "VHF Range Low Limit (MHz)", rx)
        rset.set_apply_callback(myset_freq, _sets, "frqr2lo", frqm)
        rset.set_doc("Low limit of the VHF frequency bank.")
        frng.append(rset)

        val = _sets.frqr2hi / frqm
        rx = RadioSettingValueFloat(136.0, 174.0, val, 0.005, 3)
        rset = RadioSetting("setstuf.frqr2hi",
                            "VHF Range High Limit (MHz)", rx)
        rset.set_apply_callback(myset_freq, _sets, "frqr2hi", frqm)
        rset.set_doc("High limit of the VHF frequency bank.")
        frng.append(rset)

        if mod_se:
            val = _sets.frqr3lo / frqm
            if val < 220.0:
                val = 220.0
            rx = RadioSettingValueFloat(220.0, 260.0, val, 0.005, 3)
            rset = RadioSetting("setstuf.frqr3lo",
                                "1.25m Range Low Limit (MHz)", rx)
            rset.set_apply_callback(myset_freq, _sets, "frqr3lo", frqm)
            frng.append(rset)

            val = _sets.frqr3hi / frqm
            if val < 220.0:
                val = 260.0
            rx = RadioSettingValueFloat(220.0, 260.0, val, 0.005, 3)
            rset = RadioSetting("setstuf.frqr3hi",
                                "1.25m Range High Limit (MHz)", rx)
            rset.set_apply_callback(myset_freq, _sets, "frqr3hi", 1000)
            frng.append(rset)

        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.setstuf
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
