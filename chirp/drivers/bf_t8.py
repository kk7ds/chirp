# Copyright 2022 Jim Unroe <rock.unroe@gmail.com>
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
import os
import struct
import logging

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueFloat,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];       // RX Frequency
  lbcd txfreq[4];       // TX Frequency
  u8 rx_tmode;          // RX Tone Mode
  u8 rx_tone;           // PL/DPL Decode
  u8 tx_tmode;          // TX Tone Mode
  u8 tx_tone;           // PL/DPL Encode
  u8 unknown1:3,        //
     skip:1,            // Scan Add: 1 = Skip, 0 = Scan
     unknown2:2,
     isnarrow:1,        // W/N: 1 = Narrow, 0 = Wide
     lowpower:1;        // TX Power: 1 = Low, 0 = High
  u8 unknown3[3];       //
} memory[%d];

#seekto 0x0630;
struct {
  u8 squelch;           // SQL
  u8 vox;               // Vox Lv
  u8 tot;               // TOT
  u8 unk1:3,            //
     ste:1,             // Tail Clear
     bcl:1,             // BCL
     save:1,            // Save
     tdr:1,             // TDR
     beep:1;            // Beep
  u8 voice;             // Voice
  u8 abr;               // Back Light
  u8 ring;              // Ring
  u8 mdf;               // Display Type
  u8 mra;               // MR Channel A
  u8 mrb;               // MR Channel B
  u8 disp_ab;           // Display A/B Selected
  u16 fmcur;            // Broadcast FM station
  u8 workmode;          // Work Mode
  u8 wx;                // NOAA WX ch#
  u8 area;              // Area Selected
} settings;

#seekto 0x0D00;
struct {
  char name[6];
  u8 unknown1[2];
} names[%d];
"""

CMD_ACK = b"\x06"

TONES = chirp_common.TONES
TMODES = ["", "Tone", "DTCS", "DTCS"]

AB_LIST = ["A", "B"]
ABR_LIST = ["OFF", "ON", "Key"]
AREA_LIST = ["China", "Japan", "Korea", "Malaysia", "American",
             "Australia", "Iran", "Taiwan", "Europe", "Russia"]
MDF_LIST = ["Frequency", "Channel #", "Name"]
RING_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
TOT_LIST = ["OFF"] + ["%s seconds" % x for x in range(30, 210, 30)]
TOT2_LIST = TOT_LIST[1:]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 6)]
WORKMODE_LIST = ["General", "PMR"]
WX_LIST = ["CH01 - 162.550",
           "CH02 - 162.400",
           "CH03 - 162.475",
           "CH04 - 162.425",
           "CH05 - 162.450",
           "CH06 - 162.500",
           "CH07 - 162.525",
           "CH08 - 161.650",
           "CH09 - 161.775",
           "CH10 - 161.750",
           "CH11 - 162.000"
           ]

SETTING_LISTS = {
    "ab": AB_LIST,
    "abr": ABR_LIST,
    "area": AREA_LIST,
    "mdf": MDF_LIST,
    "ring": RING_LIST,
    "tot": TOT_LIST,
    "tot": TOT2_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    "workmode": WORKMODE_LIST,
    "wx": WX_LIST,
    }

FRS_FREQS1 = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625,
              462.6875, 462.7125]
FRS_FREQS2 = [467.5625, 467.5875, 467.6125, 467.6375, 467.6625,
              467.6875, 467.7125]
FRS_FREQS3 = [462.5500, 462.5750, 462.6000, 462.6250, 462.6500,
              462.6750, 462.7000, 462.7250]
FRS_FREQS = FRS_FREQS1 + FRS_FREQS2 + FRS_FREQS3

GMRS_FREQS = FRS_FREQS + FRS_FREQS3

MURS_FREQS = [151.820, 151.880, 151.940, 154.570, 154.600]

PMR_FREQS1 = [446.00625, 446.01875, 446.03125, 446.04375, 446.05625,
              446.06875, 446.08125, 446.09375]
PMR_FREQS2 = [446.10625, 446.11875, 446.13125, 446.14375, 446.15625,
              446.16875, 446.18125, 446.19375]
PMR_FREQS = PMR_FREQS1 + PMR_FREQS2

VOICE_CHOICES = ["Off", "On"]
VOICE_VALUES = [0x00, 0x02]


def _enter_programming_mode(radio):
    serial = radio.pipe

    exito = False
    for i in range(0, 5):
        serial.write(radio._magic)
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        _exit_programming_mode(radio)
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write(b"\x02")
        ident = serial.read(len(radio._fingerprint))
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if not ident == radio._fingerprint:
        _exit_programming_mode(radio)
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        _exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        _exit_programming_mode(radio)
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


class BFT8Radio(chirp_common.CloneModeRadio):
    """Baofeng BF-T8"""
    VENDOR = "Baofeng"
    MODEL = "BF-T8"
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False
    BLOCK_SIZE = BLOCK_SIZE_UP = 0x10
    ODD_SPLIT = True
    HAS_NAMES = False
    NAME_LENGTH = 0
    VALID_CHARS = ""
    CH_OFFSET = False
    SKIP_VALUES = []
    DTCS_CODES = sorted(chirp_common.DTCS_CODES)
    DUPLEXES = ["", "-", "+", "split", "off"]

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]
    VALID_BANDS = [(400000000, 470000000)]

    _magic = b"\x02" + b"PROGRAM"
    _fingerprint = b"\x2E" + b"BF-T6" + b"\x2E"
    _upper = 99
    _mem_params = (_upper,  # number of channels
                   _upper   # number of names
                   )
    _frs = _gmrs = _murs = _pmr = False

    _ranges = [
               (0x0000, 0x0B60),
              ]
    _memsize = 0x0B60

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.has_name = self.HAS_NAMES
        rf.can_odd_split = self.ODD_SPLIT
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_characters = self.VALID_CHARS
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = self.DUPLEXES
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 KHz.
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = self.VALID_BANDS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def validate_memory(self, mem):
        msgs = ""
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        _msg_freq = 'Memory location cannot change frequency'
        _msg_simplex = 'Memory location only supports Duplex:(None)'
        _msg_duplex = 'Memory location only supports Duplex: +'
        _msg_nfm = 'Memory location only supports Mode: NFM'
        _msg_txp = 'Memory location only supports Power: Low'

        # FRS only models
        if self._frs:
            # range of memories with values set by FCC rules
            if mem.freq != int(FRS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 22 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 22 are NFM only
            if str(mem.mode) != "NFM":
                # warn user can't change mode
                msgs.append(chirp_common.ValidationError(_msg_nfm))

            # channels 8 - 14 are low power only
            if mem.number >= 8 and mem.number <= 14:
                if str(mem.power) != "Low":
                    # warn user can't change power
                    msgs.append(chirp_common.ValidationError(_msg_txp))

        # MURS only models
        if self._murs:
            # range of memories with values set by FCC rules
            if mem.freq != int(MURS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 5 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 3 are NFM only
            if mem.number <= 3:
                if mem.mode != "NFM":
                    # warn user can't change mode
                    msgs.append(chirp_common.ValidationError(_msg_nfm))

        # PMR only models
        if self._pmr:
            # range of memories with values set by governmental rules
            if mem.freq != int(PMR_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 16 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 16 are NFM only
            if mem.mode != "NFM":
                # warn user can't change mode
                msgs.append(chirp_common.ValidationError(_msg_nfm))

            # channels 1 - 16 are low power only
            if str(mem.power) != "Low":
                # warn user can't change power
                msgs.append(chirp_common.ValidationError(_msg_txp))

        return msgs

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, mem, _mem):
        rx_tone = tx_tone = None

        tx_tmode = TMODES[_mem.tx_tmode]
        rx_tmode = TMODES[_mem.rx_tmode]

        if tx_tmode == "Tone":
            tx_tone = TONES[_mem.tx_tone]
        elif tx_tmode == "DTCS":
            tx_tone = self.DTCS_CODES[_mem.tx_tone]

        if rx_tmode == "Tone":
            rx_tone = TONES[_mem.rx_tone]
        elif rx_tmode == "DTCS":
            rx_tone = self.DTCS_CODES[_mem.rx_tone]

        tx_pol = _mem.tx_tmode == 0x03 and "R" or "N"
        rx_pol = _mem.rx_tmode == 0x03 and "R" or "N"

        chirp_common.split_tone_decode(mem, (tx_tmode, tx_tone, tx_pol),
                                       (rx_tmode, rx_tone, rx_pol))

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def _get_mem(self, number):
        return self._memobj.memory[number - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        if self.HAS_NAMES:
            _nam = self._get_nam(number)

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 13 + "\xFF" * 3)

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        # wide/narrow
        mem.mode = _mem.isnarrow and "NFM" or "FM"

        mem.skip = _mem.skip and "S" or ""

        if self.HAS_NAMES:
            for char in _nam.name:
                if str(char) == "\xFF":
                    char = " "  # The OEM software may have 0xFF mid-name
                mem.name += str(char)
            mem.name = mem.name.rstrip()

        # tone data
        self._get_tone(mem, _mem)

        # tx power
        levels = self.POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                      (_mem.lowpower, levels))
            mem.power = levels[0]

        if mem.number <= 22 and self._frs:
            FRS_IMMUTABLE = ["freq", "duplex", "offset", "mode"]
            if mem.number >= 8 and mem.number <= 14:
                mem.immutable = FRS_IMMUTABLE + ["power"]
            else:
                mem.immutable = FRS_IMMUTABLE

        if mem.number <= 30 and self._gmrs:
            GMRS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number >= 8 and mem.number <= 14:
                mem.immutable = GMRS_IMMUTABLE + ["mode", "power"]
            else:
                mem.immutable = GMRS_IMMUTABLE

        if mem.number <= 5 and self._murs:
            MURS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number <= 3:
                mem.immutable = MURS_IMMUTABLE + ["mode"]
            else:
                mem.immutable = MURS_IMMUTABLE

        if mem.number <= 16 and self._pmr:
            PMR_IMMUTABLE = ["freq", "duplex", "offset", "mode", "power"]
            mem.immutable = PMR_IMMUTABLE

        return mem

    def _set_tone(self, mem, _mem):
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.tx_tmode = TMODES.index(txmode)
        _mem.rx_tmode = TMODES.index(rxmode)
        if txmode == "Tone":
            _mem.tx_tone = TONES.index(txtone)
        elif txmode == "DTCS":
            _mem.tx_tmode = txpol == "R" and 0x03 or 0x02
            _mem.tx_tone = self.DTCS_CODES.index(txtone)
        if rxmode == "Tone":
            _mem.rx_tone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            _mem.rx_tmode = rxpol == "R" and 0x03 or 0x02
            _mem.rx_tone = self.DTCS_CODES.index(rxtone)

    def _set_mem(self, number):
        return self._memobj.memory[number - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]

    def set_memory(self, mem):
        _mem = self._set_mem(mem.number)
        if self.HAS_NAMES:
            _nam = self._set_nam(mem.number)

        # if empty memory
        if mem.empty:
            if mem.number <= 22 and self._frs:
                _mem.set_raw("\xFF" * 8 + "\x00" * 5 + "\xFF" * 3)
                FRS_FREQ = int(FRS_FREQS[mem.number - 1] * 100000)
                _mem.rxfreq = _mem.txfreq = FRS_FREQ
                _mem.isnarrow = True
                if mem.number >= 8 and mem.number <= 14:
                    _mem.lowpower = True
                else:
                    _mem.lowpower = False
            elif self._murs:
                if mem.number <= 5:
                    _mem.set_raw("\xFF" * 8 + "\x00" * 5 + "\xFF" * 3)
                    MURS_FREQ = int(MURS_FREQS[mem.number - 1] * 100000)
                    _mem.rxfreq = _mem.txfreq = MURS_FREQ
                    _mem.lowpower = False
                    if mem.number <= 3:
                        _mem.isnarrow = True
                    else:
                        _mem.isnarrow = False
            elif self._pmr:
                if mem.number <= 16:
                    _mem.set_raw("\xFF" * 8 + "\x00" * 5 + "\xFF" * 3)
                    PMR_FREQ = int(PMR_FREQS[mem.number - 1] * 100000)
                    _mem.rxfreq = _mem.txfreq = PMR_FREQ
                    _mem.lowpower = True
                    _mem.isnarrow = True
            else:
                _mem.set_raw("\xFF" * 8 + "\x00" * 4 + "\x03" + "\xFF" * 3)

            if self.HAS_NAMES:
                for i in range(0, self.NAME_LENGTH):
                    _nam.name[i].set_raw("\xFF")

            return mem

        _mem.set_raw("\x00" * 13 + "\xFF" * 3)

        if self._gmrs:
            if mem.number >= 1 and mem.number <= 30:
                GMRS_FREQ = int(GMRS_FREQS[mem.number - 1] * 1000000)
                mem.freq = GMRS_FREQ
                if mem.number <= 22:
                    mem.duplex = ''
                    mem.offset = 0
                    if mem.number >= 8 and mem.number <= 14:
                        mem.mode = "NFM"
                        mem.power = self.POWER_LEVELS[1]
                if mem.number > 22:
                    mem.duplex = '+'
                    mem.offset = 5000000
            elif float(mem.freq) / 1000000 in GMRS_FREQS:
                if float(mem.freq) / 1000000 in FRS_FREQS1:
                    mem.duplex = ''
                    mem.offset = 0
                if float(mem.freq) / 1000000 in FRS_FREQS2:
                    mem.duplex = ''
                    mem.offset = 0
                    mem.mode = "NFM"
                    mem.power = self.POWER_LEVELS[1]
                if float(mem.freq) / 1000000 in FRS_FREQS3:
                    if mem.duplex == '+':
                        mem.offset = 5000000
                    else:
                        mem.duplex = ''
                        mem.offset = 0
            else:
                mem.duplex = 'off'
                mem.offset = 0

        # frequency
        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        # wide/narrow
        _mem.isnarrow = mem.mode == "NFM"

        _mem.skip = mem.skip == "S"

        if self.HAS_NAMES:
            for i in range(self.NAME_LENGTH):
                try:
                    _nam.name[i] = mem.name[i]
                except IndexError:
                    _nam.name[i] = "\xFF"

        # tone data
        self._set_tone(mem, _mem)

        # tx power
        if mem.power:
            _mem.lowpower = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        return mem

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        # Menu 03
        rs = RadioSettingValueInteger(0, 9, _settings.squelch)
        rset = RadioSetting("squelch", "Squelch Level", rs)
        basic.append(rset)

        model_list = ["RB27B", "RB27V", "RB627B"]
        if self.MODEL in model_list:
            # Menu 09 (RB27x/RB627x)
            rs = RadioSettingValueList(TOT2_LIST, TOT2_LIST[_settings.tot])
        else:
            # Menu 11 / 09 (RB27)
            rs = RadioSettingValueList(TOT_LIST, TOT_LIST[_settings.tot])
        rset = RadioSetting("tot", "Time-out timer", rs)
        basic.append(rset)

        # Menu 06
        rs = RadioSettingValueList(VOX_LIST, VOX_LIST[_settings.vox])
        rset = RadioSetting("vox", "VOX Level", rs)
        basic.append(rset)

        # Menu 15 (BF-T8) / Menu 14 (FRS-A1)
        if self.MODEL == "FRS-A1":
            # Menu 14 (FRS-A1)
            def apply_voice_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = VOICE_CHOICES.index(val)
                val = VOICE_VALUES[index]
                obj.set_value(val)

            if _settings.voice in VOICE_VALUES:
                idx = VOICE_VALUES.index(_settings.voice)
            else:
                idx = VOICE_VALUES.index(0x00)
            rs = RadioSettingValueList(VOICE_CHOICES, VOICE_CHOICES[idx])
            rset = RadioSetting("voice", "Voice", rs)
            rset.set_apply_callback(apply_voice_listvalue, _settings.voice)
            basic.append(rset)
        else:
            # Menu 15 (BF-T8)
            rs = RadioSettingValueList(VOICE_LIST, VOICE_LIST[_settings.voice])
            rset = RadioSetting("voice", "Voice", rs)
            basic.append(rset)

        # Menu 12
        rs = RadioSettingValueBoolean(_settings.bcl)
        rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
        basic.append(rset)

        # Menu 10 / 08 (RB27/RB627)
        rs = RadioSettingValueBoolean(_settings.save)
        rset = RadioSetting("save", "Battery Saver", rs)
        basic.append(rset)

        # Menu 08 / 07 (RB-27/RB627)
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = RadioSetting("tdr", "Dual Watch", rs)
        basic.append(rset)

        # Menu 05
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("beep", "Beep", rs)
        basic.append(rset)

        # Menu 04
        rs = RadioSettingValueList(ABR_LIST, ABR_LIST[_settings.abr])
        rset = RadioSetting("abr", "Back Light", rs)
        basic.append(rset)

        # Menu 13 / 11 (RB-27/RB627)
        rs = RadioSettingValueList(RING_LIST, RING_LIST[_settings.ring])
        rset = RadioSetting("ring", "Ring", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(not _settings.ste)
        rset = RadioSetting("ste", "Squelch Tail Eliminate", rs)
        basic.append(rset)

        # Menu 15 (FRS-A1)
        if self.MODEL == "FRS-A1":
            rs = RadioSettingValueList(MDF_LIST, MDF_LIST[_settings.mdf])
            rset = RadioSetting("mdf", "Display Type", rs)
            basic.append(rset)

        if self.CH_OFFSET:
            rs = RadioSettingValueInteger(1, self._upper, _settings.mra + 1)
        else:
            rs = RadioSettingValueInteger(1, self._upper, _settings.mra)
        rset = RadioSetting("mra", "MR A Channel #", rs)
        basic.append(rset)

        if self.CH_OFFSET:
            rs = RadioSettingValueInteger(1, self._upper, _settings.mrb + 1)
        else:
            rs = RadioSettingValueInteger(1, self._upper, _settings.mrb)
        rset = RadioSetting("mrb", "MR B Channel #", rs)
        basic.append(rset)

        rs = RadioSettingValueList(AB_LIST, AB_LIST[_settings.disp_ab])
        rset = RadioSetting("disp_ab", "Selected Display Line", rs)
        basic.append(rset)

        if not self.MODEL.startswith("RB627"):
            if self.MODEL == "FRS-A1":
                del WX_LIST[7:]
            rs = RadioSettingValueList(WX_LIST, WX_LIST[_settings.wx])
            rset = RadioSetting("wx", "NOAA WX Radio", rs)
            basic.append(rset)

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        # FM Broadcast Settings
        val = _settings.fmcur
        val = val / 10.0
        val_low = 76.0
        if self.MODEL == "FRS-A1":
            val_low = 87.0
        if val < val_low or val > 108.0:
            val = 90.4
        rx = RadioSettingValueFloat(val_low, 108.0, val, 0.1, 1)
        rset = RadioSetting("settings.fmcur", "Broadcast FM Radio (MHz)", rx)
        rset.set_apply_callback(myset_freq, _settings, "fmcur", 10)
        basic.append(rset)

        model_list = ["BF-T8", "BF-U9", "AR-8"]
        if self.MODEL in model_list:
            rs = RadioSettingValueList(WORKMODE_LIST,
                                       WORKMODE_LIST[_settings.workmode])
            rset = RadioSetting("workmode", "Work Mode", rs)
            basic.append(rset)

            rs = RadioSettingValueList(AREA_LIST, AREA_LIST[_settings.area])
            rs.set_mutable(False)
            rset = RadioSetting("area", "Area", rs)
            basic.append(rset)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "mra" and self.CH_OFFSET:
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "mrb" and self.CH_OFFSET:
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "ste":
                        setattr(obj, setting, not int(element.value))
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


class BFU9Alias(chirp_common.Alias):
    VENDOR = "Baofeng"
    MODEL = "BF-U9"


class AR8Alias(chirp_common.Alias):
    VENDOR = "Arcshell"
    MODEL = "AR-8"


@directory.register
class BaofengBFT8Generic(BFT8Radio):
    ALIASES = [BFU9Alias, AR8Alias, ]


@directory.register
class RetevisRT16(BFT8Radio):
    VENDOR = "Retevis"
    MODEL = "RT16"

    _upper = 22
    _frs = True


@directory.register
class RetevisRB27B(BFT8Radio):
    VENDOR = "Retevis"
    MODEL = "RB27B"
    DTCS_CODES = sorted(chirp_common.DTCS_CODES + [645])
    HAS_NAMES = True
    NAME_LENGTH = 6
    VALID_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "-"
    CH_OFFSET = True
    SKIP_VALUES = ["", "S"]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]
    VALID_BANDS = [(400000000, 520000000)]

    _upper = 22
    _frs = True
    _gmrs = _murs = _pmr = False

    _ranges = [
               (0x0000, 0x0640),
               (0x0D00, 0x1040),
              ]
    _memsize = 0x1040


@directory.register
class RetevisRB27(RetevisRB27B):
    VENDOR = "Retevis"
    MODEL = "RB27"
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]
    VALID_BANDS = [(136000000, 174000000),
                   (400000000, 520000000)]

    _upper = 99
    _gmrs = True
    _frs = _murs = _pmr = False


@directory.register
class RetevisRB27V(RetevisRB27B):
    VENDOR = "Retevis"
    MODEL = "RB27V"
    VALID_BANDS = [(136000000, 174000000)]

    _upper = 5
    _murs = True
    _frs = _gmrs = _pmr = False


@directory.register
class RetevisRB627B(RetevisRB27B):
    VENDOR = "Retevis"
    MODEL = "RB627B"
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=0.50),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _upper = 16
    _pmr = True
    _frs = _gmrs = _murs = False


@directory.register
class FRSA1Radio(BFT8Radio):
    """BTECH FRS-A1"""
    VENDOR = "BTECH"
    MODEL = "FRS-A1"
    ODD_SPLIT = False
    HAS_NAMES = True
    NAME_LENGTH = 6
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = sorted(chirp_common.DTCS_CODES + [645])
    DUPLEXES = ["", "-", "+", "off"]

    _fingerprint = b"BF-T8A" + b"\x2E"
    _upper = 22
    _frs = _upper == 22

    _ranges = [
               (0x0000, 0x0640),
               (0x0D00, 0x0DC0),
              ]
    _memsize = 0x0DC0

    def get_features(self):
        rf = BFT8Radio.get_features(self)
        rf.valid_name_length = 6
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        return rf
