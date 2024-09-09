# Copyright 2016-2023:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
# Modified for Baojie BJ-218: 2018
#    Rick DeWitt (RJD), <aa0rd@yahoo.com>
# Modified for Baojie BJ-318: April 2021
#    Mark Hartong, AJ4YI <mark.hartong@verizon.net>
# Modified for Baojie BJ-318: January 2023
#    Mark Hartong, AJ4YI <mark.hartong@verizon.net>
#    1. Removed Experimental Warning
#    2. Added Brown & Yellow as Color Selections
#    3. Max VFO Volume Setting to 15 ( vice 10)
# Modified UHF band limits: February 2023
#    Jim Unroe, KC9HI <rock.unroe@gmail.com>
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

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0200;
struct {
  u8  init_bank; // determines which VFO is primary A or B
  u8  volume;    // not used BJ-318, band volume is controlled vfo u8 bvol
  u16 fm_freq;   // not used BJ-318, freq is controlled hello_lims u16 fm_318
  u8  wtled;     // not used BJ-318
  u8  rxled;     // not used BJ-318
  u8  txled;     // not used BJ-318
  u8  ledsw;
  u8  beep;
  u8  ring;
  u8  bcl;
  u8  tot;
  u16 sig_freq;
  u16 dtmf_txms;
  u8  init_sql;  // not used BJ-318, band squelch is controlled vfo u8 sql
  u8  rptr_mode;
} settings;

#seekto 0x0240;
struct {
  u8  dtmf1_cnt;
  u8  dtmf1[7];
  u8  dtmf2_cnt;
  u8  dtmf2[7];
  u8  dtmf3_cnt;
  u8  dtmf3[7];
  u8  dtmf4_cnt;
  u8  dtmf4[7];
  u8  dtmf5_cnt;
  u8  dtmf5[7];
  u8  dtmf6_cnt;
  u8  dtmf6[7];
  u8  dtmf7_cnt;
  u8  dtmf7[7];
  u8  dtmf8_cnt;
  u8  dtmf8[7];
} dtmf_tab;

#seekto 0x0280;
struct {
  u8  native_id_cnt;
  u8  native_id_code[7];
  u8  master_id_cnt;
  u8  master_id_code[7];
  u8  alarm_cnt;
  u8  alarm_code[5];
  u8  id_disp_cnt;
  u8  id_disp_code[5];
  u8  revive_cnt;
  u8  revive_code[5];
  u8  stun_cnt;
  u8  stun_code[5];
  u8  kill_cnt;
  u8  kill_code[5];
  u8  monitor_cnt;
  u8  monitor_code[5];
  u8  state_now;
} codes;

#seekto 0x02d0;
struct {
  u8  hello1_cnt;    // not used in BJ-318, is set in memory map
  char  hello1[7];   // not used in BJ-318, is set in memory map
  u8  hello2_cnt;    // not used in BJ-318, is set in memory map
  char  hello2[7];   // not used in BJ-318, is set in memory map
  u32  vhf_low;
  u32  vhf_high;
  u32  uhf_low;
  u32  uhf_high;
  u8  lims_on;       // first byte @ at address 0x02f0;
  u8 unknown_1;      // use in BJ-318 unknown
  u8 lang;           // BJ-318 Display language
                     // 02 = English 00 and 01 are Asian
  u8 up_scr_color;   // BJ-318 upper screen character color
  u8 dn_scr_color;   // BJ-318 lower screen character color
                     // purple=00, red=01, emerald=02, blue=03,
                     // sky_blue=04, black=05, brown=06, yellow=07 required
                     // hex values for color
                     // Note   sky_blue and black look the same on the
                     // BJ-318 screen
  u16 fm_318;        // FM stored Frequency in BJ-318
} hello_lims;

struct vfo {
  u8  frq_chn_mode;
  u8  chan_num;
  u32 rxfreq;
  u16 is_rxdigtone:1,
      rxdtcs_pol:1,
      rx_tone:14;
  u8  rx_mode;
  u8  unknown_ff;
  u16 is_txdigtone:1,
      txdtcs_pol:1,
      tx_tone:14;
  u8  launch_sig;
  u8  tx_end_sig;
  u8  bpower;        // sets power Hi=02h, Medium=01h, Low=00
                     // sets power for entire vfo band
  u8  fm_bw;
  u8  cmp_nder;
  u8  scrm_blr;
  u8  shift;
  u32 offset;
  u16 step;
  u8  sql;           // squelch for entire vfo band
                     // integer values 0 (low) to 9 (high)
  u8  bvol;          // sets volume for vfo band
                     // integer values 0  (low) TO 15 (high)
};

#seekto 0x0300;
struct {
  struct vfo vfoa;
} upper;

#seekto 0x0380;
struct {
  struct vfo vfob;
} lower;

struct mem {
  u32 rxfreq;
  u16 is_rxdigtone:1,
      rxdtcs_pol:1,
      rxtone:14;
  u8  recvmode;
  u32 txfreq;
  u16 is_txdigtone:1,
      txdtcs_pol:1,
      txtone:14;
  u8  botsignal;
  u8  eotsignal;
  u8  power:1,            // binary value for
                          // individual channel power
                          // set to "High" or "Low"
                          // BJ-318 band power overrides any
                          // individual channel power setting
      wide:1,
      compander:1,
      scrambler:1,
      unknown:4;
  u8  namelen;
  u8  name[7];
};

#seekto 0x0400;
struct mem upper_memory[128];

#seekto 0x1000;
struct mem lower_memory[128];

#seekto 0x1C00;
struct {
  char  mod_num[6];
} mod_id;
"""

MEM_SIZE = 0x1C00
BLOCK_SIZE = 0x40
STIMEOUT = 2
LIST_RECVMODE = ["QT/DQT", "QT/DQT + Signaling"]
LIST_SIGNAL = ["Off"] + ["DTMF%s" % x for x in range(1, 9)] + \
              ["DTMF%s + Identity" % x for x in range(1, 9)] + \
              ["Identity code"]
# Band Power settings, can be different than channel power
LIST_BPOWER = ["Low", "Mid", "High"]    # Tri-power models

# Screen Color Settings
# BJ-218 Colors
LIST_COLOR = ["Off", "Orange", "Blue", "Purple"]
# BJ-318 Colors
LIST_COLOR318 = ["Purple", "Red", "Emerald", "Blue", "Sky_Blue", "Black",
                 "Brown", "Yellow"]
LIST_LEDSW = ["Auto", "On"]
LIST_RING = ["Off"] + ["%s" % x for x in range(1, 10)]
LIST_TDR_DEF = ["A-Upper", "B-Lower"]
LIST_TIMEOUT = ["Off"] + ["%s" % x for x in range(30, 630, 30)]
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
LIST_SHIFT = ["Off", " + ", " - "]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
LIST_STEPS = [str(x) for x in STEPS]
LIST_STATE = ["Normal", "Stun", "Kill"]
LIST_SSF = ["1000", "1450", "1750", "2100"]
LIST_DTMFTX = ["50", "100", "150", "200", "300", "500"]


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = b""
    try:
        data = radio.pipe.read(amount)
    except:
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
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = struct.pack(">4sHH", cmd, addr, length)
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
    # Set the serial discipline
    radio.pipe.baudrate = 19200
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # Flush input buffer
    _clean_buffer(radio)

    magic = b"PROM_LIN"

    _rawsend(radio, magic)

    ack = _rawrecv(radio, 1)
    if ack != b"\x06":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    return True


def _exit_program_mode(radio):
    endframe = b"EXIT"
    _rawsend(radio, endframe)


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = b""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_frame(b"READ", addr, BLOCK_SIZE)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug(util.hexprint(frame))

        # Sending the read request
        _rawsend(radio, frame)

        # Now we read
        d = _recv(radio, addr, BLOCK_SIZE)

        # Aggregate the data
        data += d

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

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # The fun starts here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # Sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_frame(b"WRIE", addr, BLOCK_SIZE, data)

        _rawsend(radio, frame)

        # Receiving the response
        ack = _rawrecv(radio, 1)
        if ack != b"\x06":
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    if len(data) == 0x1C08:
        rid = data[0x1C00:0x1C08]
        return rid.startswith(cls.MODEL.encode())
    else:
        return False


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # Determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # If the two freqs are on the same Band this is not a split
            return False

    # If you get here is because the freq pairs are split
    return True


@directory.register
class LT725UV(chirp_common.CloneModeRadio):
    """LUITON LT-725UV Radio"""
    VENDOR = "LUITON"
    MODEL = "LT-725UV"
    MODES = ["NFM", "FM"]
    TONES = chirp_common.TONES
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    NAME_LENGTH = 7
    DTMF_CHARS = list("0123456789ABCD*#")

    # Channel Power: 2 levels
    # BJ-318 uses 3 power levels for each VFO "Band"
    # Low = 5W, Med = 10W, High = 25W
    # The band power selection in a VFO applies to the VFO and overrides
    # the stored channel power selection
    # The firmware channel memory structure provides only 1 bit for
    # individual channel power settings, limiting potential channel
    # power selection options to 2 levels: Low or High.
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("High", watts=30.00)]

    VALID_BANDS = [(136000000, 176000000),
                   (400000000, 490000000)]

    # Valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        if cls.MODEL == "BJ-318":
            msg = \
                ('\n'
                 'The individual BJ-318 channel power settings set in CHIRP'
                 ' are ignored by \n'
                 'the radio. They are allowed to be set in hopes of a future'
                 ' firmware \n'
                 'change by the manufacturer. While the CHIRP driver will'
                 ' allow setting \n'
                 'the individual VFO power to High (25W), Med (10W) or Low'
                 ' (5W) they \n'
                 'are converted to just Low (5W) and High (25W) on upload. The'
                 ' Med setting \n'
                 'reverts to Low. \n'
                 '\n'
                 'Changing a channel power setting must be done manually using'
                 ' the front \n'
                 'panel menu control (or the microphone controls while in VFO'
                 ' mode.)'
                 )

        else:
            msg = \
                ('Some notes about POWER settings:\n'
                 '- The individual channel power settings are ignored'
                 ' by the radio.\n'
                 '  They are allowed to be set (and downloaded) in hopes of'
                 ' a future firmware update.\n'
                 '- Power settings done \'Live\' in the radio apply to the'
                 ' entire upper or lower band.\n'
                 '- Tri-power radio models will set and download the three'
                 ' band-power'
                 ' levels, but they are converted to just Low and High at'
                 ' upload.'
                 ' The Mid setting reverts to Low.'
                 )

        rp.info = msg

        rp.pre_download = _(
            "Follow this instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_sub_devices = self.VARIANT == ""
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = []
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, 128)
        rf.valid_tuning_steps = STEPS
        return rf

    def get_sub_devices(self):
        return [LT725UVUpper(self._mmap), LT725UVLower(self._mmap)]

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
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
        except:
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

    def _memory_obj(self, suffix=""):
        return getattr(self._memobj, "%s_memory%s" % (self._vfo, suffix))

    def _get_dcs(self, val):
        return int(str(val)[2:-18])

    def _set_dcs(self, val):
        return int(str(val), 16)

    def get_memory(self, number):
        _mem = self._memory_obj()[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw(asbytes=False)[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _split(self.get_features(), mem.freq, int(_mem.txfreq) * 10):
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _mem.name[0:_mem.namelen]:
            mem.name += chr(char)

        dtcs_pol = ["N", "N"]

        if _mem.rxtone == 0x3FFF:
            rxmode = ""
        elif _mem.is_rxdigtone == 0:
            # CTCSS
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            # Digital
            rxmode = "DTCS"
            mem.rx_dtcs = self._get_dcs(_mem.rxtone)
            if _mem.rxdtcs_pol == 1:
                dtcs_pol[1] = "R"

        if _mem.txtone == 0x3FFF:
            txmode = ""
        elif _mem.is_txdigtone == 0:
            # CTCSS
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # Digital
            txmode = "DTCS"
            mem.dtcs = self._get_dcs(_mem.txtone)
            if _mem.txdtcs_pol == 1:
                dtcs_pol[0] = "R"

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

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.power = self.POWER_LEVELS[_mem.power]

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        if _mem.recvmode == 0xFF:
            val = 0x00
        else:
            val = _mem.recvmode
        recvmode = RadioSetting("recvmode", "Receiving mode",
                                RadioSettingValueList(LIST_RECVMODE,
                                                      current_index=val))
        mem.extra.append(recvmode)

        if _mem.botsignal == 0xFF:
            val = 0x00
        else:
            val = _mem.botsignal
        botsignal = RadioSetting("botsignal", "Launch signaling",
                                 RadioSettingValueList(LIST_SIGNAL,
                                                       current_index=val))
        mem.extra.append(botsignal)

        if _mem.eotsignal == 0xFF:
            val = 0x00
        else:
            val = _mem.eotsignal

        rx = RadioSettingValueList(LIST_SIGNAL, current_index=val)
        eotsignal = RadioSetting("eotsignal", "Transmit end signaling", rx)
        mem.extra.append(eotsignal)

        rx = RadioSettingValueBoolean(bool(_mem.compander))
        compander = RadioSetting("compander", "Compander", rx)
        mem.extra.append(compander)

        rx = RadioSettingValueBoolean(bool(_mem.scrambler))
        scrambler = RadioSetting("scrambler", "Scrambler", rx)
        mem.extra.append(scrambler)

        return mem

    def set_memory(self, mem):
        _mem = self._memory_obj()[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * 24)
            _mem.namelen = 0
            return

        _mem.set_raw("\xFF" * 15 + "\x00\x00" + "\xFF" * 7)

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
            _mem.txfreq = mem.freq / 10

        _mem.namelen = len(mem.name.rstrip())
        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _mem.name[i] = ord(mem.name[i])
            except IndexError:
                _mem.name[i] = 0xFF

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

        if rxmode == "":
            _mem.rxdtcs_pol = 1
            _mem.is_rxdigtone = 1
            _mem.rxtone = 0x3FFF
        elif rxmode == "Tone":
            _mem.rxdtcs_pol = 0
            _mem.is_rxdigtone = 0
            _mem.rxtone = int(mem.ctone * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.dtcs)
        elif rxmode == "DTCS":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.rx_dtcs)

        if txmode == "":
            _mem.txdtcs_pol = 1
            _mem.is_txdigtone = 1
            _mem.txtone = 0x3FFF
        elif txmode == "Tone":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.rtone * 10)
        elif txmode == "TSQL":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.ctone * 10)
        elif txmode == "DTCS":
            _mem.txdtcs_pol = 1 if mem.dtcs_polarity[0] == "R" else 0
            _mem.is_txdigtone = 1
            _mem.txtone = self._set_dcs(mem.dtcs)

        _mem.wide = self.MODES.index(mem.mode)
        _mem.power = mem.power == self.POWER_LEVELS[1]

        # Extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        # Define mem struct write-back shortcuts
        _sets = self._memobj.settings
        _vfoa = self._memobj.upper.vfoa
        _vfob = self._memobj.lower.vfob
        _lims = self._memobj.hello_lims
        _codes = self._memobj.codes
        _dtmf = self._memobj.dtmf_tab

        basic = RadioSettingGroup("basic", "Basic Settings")
        a_band = RadioSettingGroup("a_band", "VFO A-Upper Settings")
        b_band = RadioSettingGroup("b_band", "VFO B-Lower Settings")
        codes = RadioSettingGroup("codes", "Codes & DTMF Groups")
        lims = RadioSettingGroup("lims", "PowerOn & Freq Limits")
        group = RadioSettings(basic, a_band, b_band, lims, codes)

        # Basic Settings
        bnd_mode = RadioSetting(
            "settings.init_bank", "TDR Band Default",
            RadioSettingValueList(
                LIST_TDR_DEF, current_index=_sets.init_bank))
        basic.append(bnd_mode)

        # BJ-318 set by vfo, skip
        if self.MODEL != "BJ-318":
            rs = RadioSettingValueInteger(0, 20, _sets.volume)
            volume = RadioSetting("settings.volume", "Volume", rs)
            basic.append(volume)

        # BJ-318 set by vfo, skip
        if self.MODEL != "BJ-318":
            vala = _vfoa.bpower        # 2bits values 0,1,2= Low, Mid, High
            rx = RadioSettingValueList(LIST_BPOWER, current_index=vala)
            powera = RadioSetting("upper.vfoa.bpower", "Power (Upper)", rx)
            basic.append(powera)

        # BJ-318 set by vfo, skip
        if self.MODEL != "BJ-318":
            valb = _vfob.bpower
            rx = RadioSettingValueList(LIST_BPOWER, current_index=valb)
            powerb = RadioSetting("lower.vfob.bpower", "Power (Lower)", rx)
            basic.append(powerb)

        def my_word2raw(setting, obj, atrb, mlt=10):
            """Callback function to convert UI floating value to u16 int"""
            if str(setting.value) == "Off":
                frq = 0x0FFFF
            else:
                frq = int(float(str(setting.value)) * float(mlt))
            if frq == 0:
                frq = 0xFFFF
            setattr(obj, atrb, frq)
            return

        def my_adjraw(setting, obj, atrb, fix):
            """Callback: add or subtract fix from value."""
            vx = int(str(setting.value))
            value = vx + int(fix)
            if value < 0:
                value = 0
            if atrb == "frq_chn_mode" and int(str(setting.value)) == 2:
                value = vx * 2         # Special handling for frq_chn_mode
            setattr(obj, atrb, value)
            return

        def my_dbl2raw(setting, obj, atrb, flg=1):
            """Callback: convert from freq 146.7600 to 14760000 U32."""
            value = chirp_common.parse_freq(str(setting.value)) / 10
            # flg=1 means 0 becomes ff, else leave as possible 0
            if flg == 1 and value == 0:
                value = 0xFFFFFFFF
            setattr(obj, atrb, value)
            return

        def my_val_list(setting, obj, atrb):
            """Callback:from ValueList with non-sequential, actual values."""
            value = int(str(setting.value))            # Get the integer value
            if atrb == "tot":
                value = int(value / 30)    # 30 second increments
            setattr(obj, atrb, value)
            return

        def my_spcl(setting, obj, atrb):
            """Callback: Special handling based on atrb."""
            if atrb == "frq_chn_mode":
                idx = LIST_VFOMODE.index(str(setting.value))  # Returns 0 or 1
                value = idx * 2            # Set bit 1
            setattr(obj, atrb, value)
            return

        def my_tone_strn(obj, is_atr, pol_atr, tone_atr):
            """Generate the CTCS/DCS tone code string."""
            vx = int(getattr(obj, tone_atr))
            if vx == 16383 or vx == 0:
                return "Off"                 # 16383 is all bits set
            if getattr(obj, is_atr) == 0:             # Simple CTCSS code
                tstr = str(vx / 10.0)
            else:        # DCS
                if getattr(obj, pol_atr) == 0:
                    tstr = "D{:03x}R".format(vx)
                else:
                    tstr = "D{:03x}N".format(vx)
            return tstr

        def my_set_tone(setting, obj, is_atr, pol_atr, tone_atr):
            """Callback- create the tone setting from string code."""
            sx = str(setting.value)        # '131.8'  or 'D231N' or 'Off'
            if sx == "Off":
                isx = 1
                polx = 1
                tonx = 0x3FFF
            elif sx[0] == "D":         # DCS
                isx = 1
                if sx[4] == "N":
                    polx = 1
                else:
                    polx = 0
                tonx = int(sx[1:4], 16)
            else:                                     # CTCSS
                isx = 0
                polx = 0
                tonx = int(float(sx) * 10.0)
            setattr(obj, is_atr, isx)
            setattr(obj, pol_atr, polx)
            setattr(obj, tone_atr, tonx)
            return

        # not used by BJ-318 skip
        if self.MODEL != "BJ-318":
            val = _sets.fm_freq / 10.0
            if val == 0:
                val = 88.9            # 0 is not valid
            rx = RadioSettingValueFloat(65, 108.0, val, 0.1, 1)
            rs = RadioSetting("settings.fm_freq",
                              "FM Broadcast Freq (MHz)", rx)
            rs.set_apply_callback(my_word2raw, _sets, "fm_freq")
            basic.append(rs)

        # BJ-318 fm frequency
        if self.MODEL == "BJ-318":
            val = _lims.fm_318 / 10.0
            if val == 0:
                val = 88.9            # 0 is not valid
            rx = RadioSettingValueFloat(65, 108.0, val, 0.1, 1)
            rs = RadioSetting("hello_lims.fm_318",
                              "FM Broadcast Freq (MHz)", rx)
            rs.set_apply_callback(my_word2raw, _lims, "fm_318")
            basic.append(rs)

        # not used in BJ-318, skip
        if self.MODEL != "BJ-318":
            rs = RadioSettingValueList(LIST_COLOR,
                                       current_index=_sets.wtled)
            wtled = RadioSetting("settings.wtled", "Standby LED Color", rs)
            basic.append(wtled)

        # not used in BJ-318, skip
        if self.MODEL != "BJ-318":
            rs = RadioSettingValueList(LIST_COLOR,
                                       current_index=_sets.rxled)
            rxled = RadioSetting("settings.rxled", "RX LED Color", rs)
            basic.append(rxled)

        # not used in BJ-318, skip
        if self.MODEL != "BJ-318":
            rs = RadioSettingValueList(LIST_COLOR,
                                       current_index=_sets.txled)
            txled = RadioSetting("settings.txled", "TX LED Color", rs)
            basic.append(txled)

        ledsw = RadioSetting(
            "settings.ledsw", "Back light mode",
            RadioSettingValueList(LIST_LEDSW, current_index=_sets.ledsw))
        basic.append(ledsw)

        beep = RadioSetting("settings.beep", "Beep",
                            RadioSettingValueBoolean(bool(_sets.beep)))
        basic.append(beep)

        ring = RadioSetting("settings.ring", "Ring",
                            RadioSettingValueList(
                                LIST_RING, current_index=_sets.ring))
        basic.append(ring)

        bcl = RadioSetting("settings.bcl", "Busy channel lockout",
                           RadioSettingValueBoolean(bool(_sets.bcl)))
        basic.append(bcl)

        # squelch for non-BJ-318 models
        # BJ-318 squelch set by VFO basis
        if self.MODEL != "BJ-318":
            if _vfoa.sql == 0xFF:
                val = 0x04
            else:
                val = _vfoa.sql
            sqla = RadioSetting("upper.vfoa.sql", "Squelch (Upper)",
                                RadioSettingValueInteger(0, 9, val))
            basic.append(sqla)

            if _vfob.sql == 0xFF:
                val = 0x04
            else:
                val = _vfob.sql
            sqlb = RadioSetting("lower.vfob.sql", "Squelch (Lower)",
                                RadioSettingValueInteger(0, 9, val))
            basic.append(sqlb)

        tmp = str(int(_sets.tot) * 30)     # 30 sec step counter
        rs = RadioSetting("settings.tot", "Transmit Timeout (Secs)",
                          RadioSettingValueList(LIST_TIMEOUT, tmp))
        rs.set_apply_callback(my_val_list, _sets, "tot")
        basic.append(rs)

        tmp = str(int(_sets.sig_freq))
        rs = RadioSetting("settings.sig_freq", "Single Signaling Tone (Hz)",
                          RadioSettingValueList(LIST_SSF, tmp))
        rs.set_apply_callback(my_val_list, _sets, "sig_freq")
        basic.append(rs)

        tmp = str(int(_sets.dtmf_txms))
        rs = RadioSetting("settings.dtmf_txms", "DTMF Tx Duration (mSecs)",
                          RadioSettingValueList(LIST_DTMFTX, tmp))
        rs.set_apply_callback(my_val_list, _sets, "dtmf_txms")
        basic.append(rs)

        rs = RadioSetting("settings.rptr_mode", "Repeater Mode",
                          RadioSettingValueBoolean(bool(_sets.rptr_mode)))
        basic.append(rs)

        # UPPER BAND SETTINGS

        # Freq Mode, convert bit 1 state to index pointer
        val = _vfoa.frq_chn_mode // 2

        rx = RadioSettingValueList(LIST_VFOMODE, current_index=val)
        rs = RadioSetting("upper.vfoa.frq_chn_mode", "Default Mode", rx)
        rs.set_apply_callback(my_spcl, _vfoa, "frq_chn_mode")
        a_band.append(rs)

        val = _vfoa.chan_num + 1                  # Add 1 for 1-128 displayed
        rs = RadioSetting("upper.vfoa.chan_num", "Initial Chan",
                          RadioSettingValueInteger(1, 128, val))
        rs.set_apply_callback(my_adjraw, _vfoa, "chan_num", -1)
        a_band.append(rs)

        val = _vfoa.rxfreq / 100000.0
        if (val < 136.0 or val > 176.0):
            val = 146.520            # 2m calling
        rs = RadioSetting("upper.vfoa.rxfreq ", "Default Recv Freq (MHz)",
                          RadioSettingValueFloat(136.0, 176.0, val, 0.001, 5))
        rs.set_apply_callback(my_dbl2raw, _vfoa, "rxfreq")
        a_band.append(rs)

        tmp = my_tone_strn(_vfoa, "is_rxdigtone", "rxdtcs_pol", "rx_tone")
        rs = RadioSetting("rx_tone", "Default Recv CTCSS (Hz)",
                          RadioSettingValueList(LIST_CTCSS, tmp))
        rs.set_apply_callback(my_set_tone, _vfoa, "is_rxdigtone",
                              "rxdtcs_pol", "rx_tone")
        a_band.append(rs)

        rx = RadioSettingValueList(LIST_RECVMODE,
                                   current_index=_vfoa.rx_mode)
        rs = RadioSetting("upper.vfoa.rx_mode", "Default Recv Mode", rx)
        a_band.append(rs)

        tmp = my_tone_strn(_vfoa, "is_txdigtone", "txdtcs_pol", "tx_tone")
        rs = RadioSetting("tx_tone", "Default Xmit CTCSS (Hz)",
                          RadioSettingValueList(LIST_CTCSS, tmp))
        rs.set_apply_callback(my_set_tone, _vfoa, "is_txdigtone",
                              "txdtcs_pol", "tx_tone")
        a_band.append(rs)

        rs = RadioSetting(
            "upper.vfoa.launch_sig", "Launch Signaling",
            RadioSettingValueList(
                LIST_SIGNAL, current_index=_vfoa.launch_sig))
        a_band.append(rs)

        rx = RadioSettingValueList(LIST_SIGNAL, current_index=_vfoa.tx_end_sig)
        rs = RadioSetting("upper.vfoa.tx_end_sig", "Xmit End Signaling", rx)
        a_band.append(rs)

        rx = RadioSettingValueList(LIST_BW, current_index=_vfoa.fm_bw)
        rs = RadioSetting("upper.vfoa.fm_bw", "Wide/Narrow Band", rx)
        a_band.append(rs)

        rx = RadioSettingValueBoolean(bool(_vfoa.cmp_nder))
        rs = RadioSetting("upper.vfoa.cmp_nder", "Compander", rx)
        a_band.append(rs)

        rs = RadioSetting("upper.vfoa.scrm_blr", "Scrambler",
                          RadioSettingValueBoolean(bool(_vfoa.scrm_blr)))
        a_band.append(rs)

        rx = RadioSettingValueList(LIST_SHIFT, current_index=_vfoa.shift)
        rs = RadioSetting("upper.vfoa.shift", "Xmit Shift", rx)
        a_band.append(rs)

        val = _vfoa.offset / 100000.0
        rs = RadioSetting("upper.vfoa.offset", "Xmit Offset (MHz)",
                          RadioSettingValueFloat(0, 100.0, val, 0.001, 3))
        # Allow zero value
        rs.set_apply_callback(my_dbl2raw, _vfoa, "offset", 0)
        a_band.append(rs)

        tmp = str(_vfoa.step / 100.0)
        rs = RadioSetting("step", "Freq step (kHz)",
                          RadioSettingValueList(LIST_STEPS, tmp))
        rs.set_apply_callback(my_word2raw, _vfoa, "step", 100)
        a_band.append(rs)

        # BJ-318 upper band squelch
        if self.MODEL == "BJ-318":
            if _vfoa.sql == 0xFF:
                valq = 0x04    # setting default squelch to 04
            else:
                valq = _vfoa.sql
                sqla = RadioSetting("upper.vfoa.sql", "Squelch",
                                    RadioSettingValueInteger(0, 9, valq))
            a_band.append(sqla)

        # BJ-318 upper band volume
        if self.MODEL == "BJ-318":
            bvolume_u = RadioSetting("upper.vfoa.bvol",
                                     "Volume", RadioSettingValueInteger(
                                         0, 15, _vfoa.bvol))
            a_band.append(bvolume_u)

        # BJ-318 Upper Screen Color
        if self.MODEL == "BJ-318":
            rs_u = RadioSettingValueList(LIST_COLOR318,
                                         current_index=_lims.up_scr_color)
            up_scr_color = RadioSetting("hello_lims.up_scr_color",
                                        "Screen Color", rs_u)
            a_band.append(up_scr_color)

        # BJ-318 Upper band power
        if self.MODEL == "BJ-318":
            val_b = _vfoa.bpower        # 2bits values 0,1,2= Low, Mid, High
            rx = RadioSettingValueList(LIST_BPOWER, current_index=val_b)
            power_u = RadioSetting("upper.vfoa.bpower", "Power", rx)
            a_band.append(power_u)

        # LOWER BAND SETTINGS

        val = _vfob.frq_chn_mode // 2
        rx = RadioSettingValueList(LIST_VFOMODE, current_index=val)
        rs = RadioSetting("lower.vfob.frq_chn_mode", "Default Mode", rx)
        rs.set_apply_callback(my_spcl, _vfob, "frq_chn_mode")
        b_band.append(rs)

        val = _vfob.chan_num + 1
        rs = RadioSetting("lower.vfob.chan_num", "Initial Chan",
                          RadioSettingValueInteger(1, 128, val))
        rs.set_apply_callback(my_adjraw, _vfob, "chan_num", -1)
        b_band.append(rs)

        val = _vfob.rxfreq / 100000.0
        if (val < 400.0 or val > 490.0):
            val = 446.0          # UHF calling
        rs = RadioSetting("lower.vfob.rxfreq ", "Default Recv Freq (MHz)",
                          RadioSettingValueFloat(400.0, 490.0, val, 0.001, 5))
        rs.set_apply_callback(my_dbl2raw, _vfob, "rxfreq")
        b_band.append(rs)

        tmp = my_tone_strn(_vfob, "is_rxdigtone", "rxdtcs_pol", "rx_tone")
        rs = RadioSetting("rx_tone", "Default Recv CTCSS (Hz)",
                          RadioSettingValueList(LIST_CTCSS, tmp))
        rs.set_apply_callback(my_set_tone, _vfob, "is_rxdigtone",
                              "rxdtcs_pol", "rx_tone")
        b_band.append(rs)

        rx = RadioSettingValueList(LIST_RECVMODE, current_index=_vfob.rx_mode)
        rs = RadioSetting("lower.vfob.rx_mode", "Default Recv Mode", rx)
        b_band.append(rs)

        tmp = my_tone_strn(_vfob, "is_txdigtone", "txdtcs_pol", "tx_tone")
        rs = RadioSetting("tx_tone", "Default Xmit CTCSS (Hz)",
                          RadioSettingValueList(LIST_CTCSS, tmp))
        rs.set_apply_callback(my_set_tone, _vfob, "is_txdigtone",
                              "txdtcs_pol", "tx_tone")
        b_band.append(rs)

        rx = RadioSettingValueList(LIST_SIGNAL, current_index=_vfob.launch_sig)
        rs = RadioSetting("lower.vfob.launch_sig", "Launch Signaling", rx)
        b_band.append(rs)

        rx = RadioSettingValueList(LIST_SIGNAL, current_index=_vfob.tx_end_sig)
        rs = RadioSetting("lower.vfob.tx_end_sig", "Xmit End Signaling", rx)
        b_band.append(rs)

        rx = RadioSettingValueList(LIST_BW, current_index=_vfob.fm_bw)
        rs = RadioSetting("lower.vfob.fm_bw", "Wide/Narrow Band", rx)
        b_band.append(rs)

        rs = RadioSetting("lower.vfob.cmp_nder", "Compander",
                          RadioSettingValueBoolean(bool(_vfob.cmp_nder)))
        b_band.append(rs)

        rs = RadioSetting("lower.vfob.scrm_blr", "Scrambler",
                          RadioSettingValueBoolean(bool(_vfob.scrm_blr)))
        b_band.append(rs)

        rx = RadioSettingValueList(LIST_SHIFT, current_index=_vfob.shift)
        rs = RadioSetting("lower.vfob.shift", "Xmit Shift", rx)
        b_band.append(rs)

        val = _vfob.offset / 100000.0
        rs = RadioSetting("lower.vfob.offset", "Xmit Offset (MHz)",
                          RadioSettingValueFloat(0, 100.0, val, 0.001, 3))
        rs.set_apply_callback(my_dbl2raw, _vfob, "offset", 0)
        b_band.append(rs)

        tmp = str(_vfob.step / 100.0)
        rs = RadioSetting("step", "Freq step (kHz)",
                          RadioSettingValueList(LIST_STEPS, tmp))
        rs.set_apply_callback(my_word2raw, _vfob, "step", 100)
        b_band.append(rs)

        # BJ-318 lower band squelch
        if self.MODEL == "BJ-318":
            if _vfob.sql == 0xFF:
                val_l = 0x04    # setting default squelch to 04
            else:
                val_l = _vfob.sql
                sql_b = RadioSetting("lower.vfob.sql", "Squelch",
                                     RadioSettingValueInteger(0, 9, val_l))
                b_band.append(sql_b)

        # BJ-318 lower band volume
        if self.MODEL == "BJ-318":
            bvolume_l = RadioSetting("lower.vfob.bvol",
                                     "Volume", RadioSettingValueInteger(
                                         0, 15, _vfob.bvol))
            b_band.append(bvolume_l)

        # BJ-318 Lower Screen Color
        if self.MODEL == "BJ-318":
            rs_l = RadioSettingValueList(LIST_COLOR318,
                                         current_index=_lims.dn_scr_color)
            dn_scr_color = RadioSetting("hello_lims.dn_scr_color",
                                        "Screen Color", rs_l)
            b_band.append(dn_scr_color)

        # BJ-318 lower band power
        if self.MODEL == "BJ-318":
            val_l = _vfoa.bpower        # 2bits values 0,1,2= Low, Mid, High
            rx = RadioSettingValueList(LIST_BPOWER, current_index=val_l)
            powera = RadioSetting("lower.vfob.bpower", "Power", rx)
            b_band.append(powera)

        # PowerOn & Freq Limits Settings
        def chars2str(cary, knt):
            """Convert raw memory char array to a string: NOT a callback."""
            stx = ""
            for char in cary[0:knt]:
                stx += chr(int(char))
            return stx

        def my_str2ary(setting, obj, atrba, atrbc):
            """Callback: convert 7-char string to char array with count."""
            ary = ""
            knt = 7
            for j in range(6, -1, -1):       # Strip trailing spaces
                if str(setting.value)[j] == "" or str(setting.value)[j] == " ":
                    knt = knt - 1
                else:
                    break
            for j in range(0, 7, 1):
                if j < knt:
                    ary += str(setting.value)[j]
                else:
                    ary += chr(0xFF)
            setattr(obj, atrba, ary)
            setattr(obj, atrbc, knt)
            return

        # not used in BJ-318 startup screen
        if self.MODEL != "BJ-318":
            tmp = chars2str(_lims.hello1, _lims.hello1_cnt)
            rs = RadioSetting("hello_lims.hello1", "Power-On Message 1",
                              RadioSettingValueString(0, 7, tmp))
            rs.set_apply_callback(my_str2ary, _lims, "hello1", "hello1_cnt")
            lims.append(rs)

        # not used in BJ-318 startup screen
        if self.MODEL != "BJ-318":
            tmp = chars2str(_lims.hello2, _lims.hello2_cnt)
            rs = RadioSetting("hello_lims.hello2", "Power-On Message 2",
                              RadioSettingValueString(0, 7, tmp))
            rs.set_apply_callback(my_str2ary, _lims, "hello2", "hello2_cnt")
            lims.append(rs)

        # VALID_BANDS = [(136000000, 176000000),400000000, 490000000)]

        lval = _lims.vhf_low / 100000.0
        uval = _lims.vhf_high / 100000.0
        if lval >= uval:
            lval = 144.0
            uval = 158.0

        rs = RadioSetting("hello_lims.vhf_low", "Lower VHF Band Limit (MHz)",
                          RadioSettingValueFloat(136.0, 176.0, lval, 0.001, 3))
        rs.set_apply_callback(my_dbl2raw, _lims, "vhf_low")
        lims.append(rs)

        rs = RadioSetting("hello_lims.vhf_high", "Upper VHF Band Limit (MHz)",
                          RadioSettingValueFloat(136.0, 176.0, uval, 0.001, 3))
        rs.set_apply_callback(my_dbl2raw, _lims, "vhf_high")
        lims.append(rs)

        lval = _lims.uhf_low / 100000.0
        uval = _lims.uhf_high / 100000.0
        if lval >= uval:
            lval = 420.0
            uval = 470.0

        rs = RadioSetting("hello_lims.uhf_low", "Lower UHF Band Limit (MHz)",
                          RadioSettingValueFloat(400.0, 490.0, lval, 0.001, 3))
        rs.set_apply_callback(my_dbl2raw, _lims, "uhf_low")
        lims.append(rs)

        rs = RadioSetting("hello_lims.uhf_high", "Upper UHF Band Limit (MHz)",
                          RadioSettingValueFloat(400.0, 490.0, uval, 0.001, 3))
        rs.set_apply_callback(my_dbl2raw, _lims, "uhf_high")
        lims.append(rs)

        # Codes and DTMF Groups Settings

        def make_dtmf(ary, knt):
            """Generate the DTMF code 1-8, NOT a callback."""
            tmp = ""
            if knt > 0 and knt != 0xff:
                for val in ary[0:knt]:
                    if val > 0 and val <= 9:
                        tmp += chr(val + 48)
                    elif val == 0x0a:
                        tmp += "0"
                    elif val == 0x0d:
                        tmp += "A"
                    elif val == 0x0e:
                        tmp += "B"
                    elif val == 0x0f:
                        tmp += "C"
                    elif val == 0x00:
                        tmp += "D"
                    elif val == 0x0b:
                        tmp += "*"
                    elif val == 0x0c:
                        tmp += "#"
                    else:
                        msg = ("Invalid Character. Must be: 0-9,A,B,C,D,*,#")
                        raise InvalidValueError(msg)
            return tmp

        def my_dtmf2raw(setting, obj, atrba, atrbc, syz=7):
            """Callback: DTMF Code; sends 5 or 7-byte string."""
            draw = []
            knt = syz
            for j in range(syz - 1, -1, -1):       # Strip trailing spaces
                if str(setting.value)[j] == "" or str(setting.value)[j] == " ":
                    knt = knt - 1
                else:
                    break
            for j in range(0, syz):
                bx = str(setting.value)[j]
                obx = ord(bx)
                dig = 0x0ff
                if j < knt and knt > 0:      # (Else) is pads
                    if bx == "0":
                        dig = 0x0a
                    elif bx == "A":
                        dig = 0x0d
                    elif bx == "B":
                        dig = 0x0e
                    elif bx == "C":
                        dig = 0x0f
                    elif bx == "D":
                        dig = 0x00
                    elif bx == "*":
                        dig = 0x0b
                    elif bx == "#":
                        dig = 0x0c
                    elif obx >= 49 and obx <= 57:
                        dig = obx - 48
                    else:
                        msg = ("Must be: 0-9,A,B,C,D,*,#")
                        raise InvalidValueError(msg)
                    # - End if/elif/else for bx
                # - End if J<=knt
                draw.append(dig)         # Generate string of bytes
            # - End for j
            setattr(obj, atrba, draw)
            setattr(obj, atrbc, knt)
            return

        tmp = make_dtmf(_codes.native_id_code, _codes.native_id_cnt)
        rs = RadioSetting("codes.native_id_code", "Native ID Code",
                          RadioSettingValueString(0, 7, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "native_id_code",
                              "native_id_cnt", 7)
        codes.append(rs)

        tmp = make_dtmf(_codes.master_id_code, _codes.master_id_cnt)
        rs = RadioSetting("codes.master_id_code", "Master Control ID Code",
                          RadioSettingValueString(0, 7, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "master_id_code",
                              "master_id_cnt", 7)
        codes.append(rs)

        tmp = make_dtmf(_codes.alarm_code, _codes.alarm_cnt)
        rs = RadioSetting("codes.alarm_code", "Alarm Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "alarm_code",
                              "alarm_cnt", 5)
        codes.append(rs)

        tmp = make_dtmf(_codes.id_disp_code, _codes.id_disp_cnt)
        rs = RadioSetting("codes.id_disp_code", "Identify Display Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "id_disp_code",
                              "id_disp_cnt", 5)
        codes.append(rs)

        tmp = make_dtmf(_codes.revive_code, _codes.revive_cnt)
        rs = RadioSetting("codes.revive_code", "Revive Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "revive_code",
                              "revive_cnt", 5)
        codes.append(rs)

        tmp = make_dtmf(_codes.stun_code, _codes.stun_cnt)
        rs = RadioSetting("codes.stun_code", "Remote Stun Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw,  _codes, "stun_code",
                              "stun_cnt", 5)
        codes.append(rs)

        tmp = make_dtmf(_codes.kill_code, _codes.kill_cnt)
        rs = RadioSetting("codes.kill_code", "Remote KILL Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "kill_code",
                              "kill_cnt", 5)
        codes.append(rs)

        tmp = make_dtmf(_codes.monitor_code, _codes.monitor_cnt)
        rs = RadioSetting("codes.monitor_code", "Monitor Code",
                          RadioSettingValueString(0, 5, tmp))
        rs.set_apply_callback(my_dtmf2raw, _codes, "monitor_code",
                              "monitor_cnt", 5)
        codes.append(rs)

        val = _codes.state_now
        if val > 2:
            val = 0

        rx = RadioSettingValueList(LIST_STATE, current_index=val)
        rs = RadioSetting("codes.state_now", "Current State", rx)
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf1, _dtmf.dtmf1_cnt)
        rs = RadioSetting("dtmf_tab.dtmf1", "DTMF1 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf1", "dtmf1_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf2, _dtmf.dtmf2_cnt)
        rs = RadioSetting("dtmf_tab.dtmf2", "DTMF2 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf2", "dtmf2_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf3, _dtmf.dtmf3_cnt)
        rs = RadioSetting("dtmf_tab.dtmf3", "DTMF3 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf3", "dtmf3_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf4, _dtmf.dtmf4_cnt)
        rs = RadioSetting("dtmf_tab.dtmf4", "DTMF4 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf4", "dtmf4_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf5, _dtmf.dtmf5_cnt)
        rs = RadioSetting("dtmf_tab.dtmf5", "DTMF5 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf5", "dtmf5_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf6, _dtmf.dtmf6_cnt)
        rs = RadioSetting("dtmf_tab.dtmf6", "DTMF6 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf6", "dtmf6_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf7, _dtmf.dtmf7_cnt)
        rs = RadioSetting("dtmf_tab.dtmf7", "DTMF7 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf7", "dtmf7_cnt")
        codes.append(rs)

        dtm = make_dtmf(_dtmf.dtmf8, _dtmf.dtmf8_cnt)
        rs = RadioSetting("dtmf_tab.dtmf8", "DTMF8 String",
                          RadioSettingValueString(0, 7, dtm))
        rs.set_apply_callback(my_dtmf2raw, _dtmf, "dtmf8", "dtmf8_cnt")
        codes.append(rs)

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
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # Testing the file data size
        if len(filedata) == MEM_SIZE + 8:
            match_size = True

        # Testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False


class LT725UVUpper(LT725UV):
    VARIANT = "Upper"
    _vfo = "upper"


class LT725UVLower(LT725UV):
    VARIANT = "Lower"
    _vfo = "lower"


class Zastone(chirp_common.Alias):
    """Declare BJ-218 alias for Zastone BJ-218."""
    VENDOR = "Zastone"
    MODEL = "BJ-218"


class Hesenate(chirp_common.Alias):
    """Declare BJ-218 alias for Hesenate BJ-218."""
    VENDOR = "Hesenate"
    MODEL = "BJ-218"


class Baojie218Upper(LT725UVUpper):
    VENDOR = "Baojie"
    MODEL = "BJ-218"


class Baojie218Lower(LT725UVLower):
    VENDOR = "Baojie"
    MODEL = "BJ-218"


@directory.register
class Baojie218(LT725UV):
    """Baojie BJ-218"""
    VENDOR = "Baojie"
    MODEL = "BJ-218"
    ALIASES = [Zastone, Hesenate, ]

    def get_sub_devices(self):
        return [Baojie218Upper(self._mmap), Baojie218Lower(self._mmap)]


class Baojie318Upper(LT725UVUpper):
    VENDOR = "Baojie"
    MODEL = "BJ-318"


class Baojie318Lower(LT725UVLower):
    VENDOR = "Baojie"
    MODEL = "BJ-318"


@directory.register
class Baojie318(LT725UV):
    """Baojie BJ-318"""
    VENDOR = "Baojie"
    MODEL = "BJ-318"

    def get_sub_devices(self):
        return [Baojie318Upper(self._mmap), Baojie318Lower(self._mmap)]
