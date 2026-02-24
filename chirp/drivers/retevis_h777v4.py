# Copyright 2025 Jim Unroe <rock.unroe@gmail.com>
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

import logging
import struct

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.drivers import h777
from chirp.settings import (
    MemSetting,
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInvertedBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  ul32 rxfreq;        // 0-3
  ul32 txfreq;        // 4-7
  lbcd rx_tone[2];    // 8-9
  lbcd tx_tone[2];    // A-B
  u8 unknown0:2,      // C
     scramb:1,        //     Scramble  0 = Off, 1 = On
     scanadd:1,       //     Scan Add  0 = Scan, 1 = Skip
     ishighpower:1,   //     Power Level  0 = Low, 1 = High
     narrow:1,        //     Bandwidth  0 = Wide, 1 = Narrow
     unknown1:1,      //
     bcl:1;           //     Busy Channel Lockout  0 = On, 1 = Off
} memory[16];

struct {
  u8 codesw:1,        // 00D0  Code Switch
     scanm:1,         //       Scan Mode
     voxs:1,          //       VOX Switch
     roger:1,         //       Roger
     voice:1,         //       Voice Annunciation
     unknown_0:1,
     save:1,          //       Battery Save
     beep:1;          //       Beep Tone
  u8 squelch;         // 00D1  Squelch Level
  u8 tot;             // 00D2  Time-out Timer
  u8 vox;             // 00D3  VOX Level
  u8 voxd;            // 00D4  Vox Delay
  u8 unknown_1;
  u8 unknown_2;
  u8 skey2;           // 00D7  Side Key 2 (long)
  u8 unknown_3[5];    // 00D8 - 00DC
  u8 password[6];     // 00DD - 00E2  Password
} settings;
"""

MEM_FORMAT_RT21H = """
struct {
  ul24 rxfreq;        // 0-2
  ul24 txfreq;        // 3-5
  lbcd rx_tone[2];    // 6-7
  lbcd tx_tone[2];    // 8-9
  u8 speccode:1,      // A   Spec Code  0 = On, 1 = Off
     compand:1,       //     Compander  0 = On, 1 = Off
     scramb:1,        //     Scramble  0 = Off, 1 = On
     scanadd:1,       //     Scan Add  0 = Scan, 1 = Skip
     ishighpower:1,   //     Power Level  0 = Low, 1 = High
     narrow:1,        //     Bandwidth  0 = Wide, 1 = Narrow
     unknown1:1,      //
     bcl:1;           //     Busy Channel Lockout  0 = On, 1 = Off
  u8 scrambopt;       // B   Scramble Options
} memory[16];

struct {
  u8 unknown_4:1,                  // 00C0
     scanm:1,                      //       Scan Mode
     roger:1,                      //       Roger
     lowbattwarn:1,                //       Low Battery Warning
     unknown_0:1,
     voice:1,                      //       Voice Annunciation
     save:1,                       //       Battery Save
     voxs:1;                       //       VOX Switch
  u8 squelch;                      // 00C1  Squelch Level
  u8 tot;                          // 00C2  Time-out Timer
  u8 voxd;                         // 00C3  Vox Delay
  u8 vox_level;                    // 00C4  VOX Level
  u8 unknown_1;
  u8 unknown_2;
  u8 skey1L:4,                     // 00C7  Side Key 1 (long)
     skey1S:4;                     //       Side Key 1 (short)
  u8 unknown_3:5,                  // 00C8
     removectdcs:1,                //       Remove CT/DCS
     beep:1,                       //       Beep Tone
     specmode:1;                   //       Spec Mode
} settings;
"""


CMD_ACK = b"\x06"

DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

OFF1TO9_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
ONE_TO_NINE_LIST = OFF1TO9_LIST[1:]  # ["1", "2", ..., "9"]
SCANM_LIST = ["Carrier", "Time"]
SCRAMBOPT_LIST = ["1", "2", "3", "4", "5", "6", "7", "8"]
SPECMODE_LIST = ["Spec Code 1", "Spec Code 2"]
SKEY1_LIST = ["Off", "Monitor", "Scan", "Channel Lock", "VOX", "Power",
              "Alarm", "Roger"]
SKEY2_LIST = ["Off", "VOX", "Power", "Scan"]
TIMEOUTTIMER_LIST = ["Off"] + ["%s seconds" % x for x in range(30, 210, 30)]
VOICE_LIST = ["Off", "English"]

MODEL_CONFIG = {
    "RT21H": {
        "base_freq_offset": 0x2000000,
        "freq_storage_bits": 24,
    },
}

DEFAULT_CONFIG = {
    "base_freq_offset": 0,
    "freq_storage_bits": 32,
}


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
    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

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
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")

    h777._h777_enter_single_programming_mode(radio)

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

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    h777._h777_enter_single_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)


class H777V4BaseRadio(chirp_common.CloneModeRadio):
    """RETEVIS H777 V4 Base"""
    VENDOR = "Retevis"
    MODEL = "H777 V4 Base"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x0D
    BLOCK_SIZE_UP = 0x0D

    VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
    VOXD_DOC = "VOX Delay: 0.5, 1.0, 1.5, 2.0, 2.5, 3.0 seconds"
    VOXL_DOC = "VOX Level: Off, 1, 2, 3, 4, 5, 6, 7, 8, 9"

    _has_codeswitch = True
    _has_compander = False
    _has_low_battery_warning = False
    _has_remove_ctdcs = False
    _has_scramble_options = False
    _has_spec_code = False
    _has_sidekey1 = False
    _has_sidekey2 = True
    _has_spec_mode = False
    _has_vox_level_off = True

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)
                    ]
    VALID_BANDS = [(400000000, 520000000)]

    PROGRAM_CMD = b"C777HAM"
    _ranges = [
               (0x0000, 0x00EA),
              ]
    _memsize = 0x00EA

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_dtcs_codes = DTCS
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 20., 25., 50.]
        rf.valid_bands = self.VALID_BANDS
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
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
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def _decode_tone(self, toneval, txrx, chnum):
        pol = "N"
        rawval = (toneval[1].get_bits(0xFF) << 8) | toneval[0].get_bits(0xFF)

        if toneval[0].get_bits(0xFF) == 0xFF:
            mode = ""
            val = 0
        elif toneval[1].get_bits(0xC0) == 0xC0:
            val = int(f'{rawval & 0x1FF:o}')
            if val in DTCS:
                mode = "DTCS"
                pol = "R"
            else:
                LOG.error('unknown value: CH# %i DTCS %fR %s' % (
                    chnum, val, txrx))
                mode = ""
                val = 0
        elif toneval[1].get_bits(0x80):
            val = int(f'{rawval & 0x1FF:o}')
            if val in DTCS:
                mode = "DTCS"
            else:
                LOG.error('unknown value: CH# %i DTCS %fN %s' % (
                    chnum, val, txrx))
                mode = ""
                val = 0
        else:
            val = int(toneval) / 10.0
            if val in chirp_common.TONES:
                mode = "Tone"
            else:
                LOG.error('unknown value: CH# %i CTCSS %fHZ %s' % (
                    chnum, val, txrx))
                mode = ""
                val = 0

        return mode, val, pol

    def _encode_tone(self, _toneval, mode, val, pol):
        toneval = 0
        if mode == "Tone":
            v = int(round(val * 10))

            thousands = (v // 1000) % 10
            hundreds = (v // 100) % 10
            tens = (v // 10) % 10
            ones = v % 10

            toneval = (
                (thousands << 12)
                | (hundreds << 8)
                | (tens << 4)
                | ones
            )
        elif mode == "DTCS":
            toneval = int('%i' % val, 8)
            toneval |= 0x8000
            if pol == "R":
                toneval |= 0x4000
        else:
            toneval = 0xFFFF

        _toneval[0].set_raw(toneval & 0xFF)
        _toneval[1].set_raw((toneval >> 8) & 0xFF)

    def _model_cfg(self):
        cfg = MODEL_CONFIG.get(self.MODEL, DEFAULT_CONFIG).copy()
        cfg["tx_unused_marker"] = (1 << cfg["freq_storage_bits"]) - 1
        return cfg

    def _decode_freq(self, raw):
        cfg = self._model_cfg()
        return (int(raw) + cfg["base_freq_offset"]) * 10

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:1] == b"\xFF":
            mem.empty = True
            return mem

        cfg = self._model_cfg()

        rx_hz = self._decode_freq(_mem.rxfreq)
        mem.freq = rx_hz

        if _mem.txfreq == cfg["tx_unused_marker"]:
            mem.duplex = "off"
            mem.offset = 0
        else:
            tx_hz = self._decode_freq(_mem.txfreq)
            diff = rx_hz - tx_hz

            if abs(diff) > 25_000_000:
                mem.duplex = "split"
                mem.offset = tx_hz
            elif diff == 0:
                mem.duplex = ""
                mem.offset = 0
            else:
                mem.duplex = "-" if diff > 0 else "+"
                mem.offset = abs(diff)

        txmode, txval, txpol = self._decode_tone(_mem.tx_tone, 'TX', number)
        rxmode, rxval, rxpol = self._decode_tone(_mem.rx_tone, 'RX', number)

        chirp_common.split_tone_decode(mem,
                                       (txmode, txval, txpol),
                                       (rxmode, rxval, rxpol))

        if _mem.scanadd:
            mem.skip = "S"

        mem.power = self.POWER_LEVELS[_mem.ishighpower]

        mem.mode = _mem.narrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        # BCL (Busy Channel Lockout)
        rs = RadioSettingValueInvertedBoolean(not bool(_mem.bcl))
        rset = MemSetting("bcl", "BCL", rs)
        rset.set_doc("Busy Channel Lockout")
        mem.extra.append(rset)

        # Scramble
        rs = RadioSettingValueInvertedBoolean(not bool(_mem.scramb))
        rset = MemSetting("scramb", "Scramble", rs)
        rset.set_doc("Frequency inversion Scramble")
        mem.extra.append(rset)

        # Compander
        if self._has_compander:
            rs = RadioSettingValueInvertedBoolean(not bool(_mem.compand))
            rset = MemSetting("compand", "Compander", rs)
            rset.set_doc("Voice Compander")
            mem.extra.append(rset)

        # Spec Code
        if self._has_spec_code:
            rs = RadioSettingValueInvertedBoolean(not bool(_mem.speccode))
            rset = MemSetting("speccode", "Spec Code", rs)
            rset.set_doc("Spec Code")
            mem.extra.append(rset)

        # Scramble Options
        if self._has_scramble_options:
            if _mem.scrambopt > 0x07:
                val = 0x00
            else:
                val = _mem.scrambopt
            rs = RadioSettingValueList(SCRAMBOPT_LIST, current_index=val)
            rset = MemSetting("scrambopt", "Scramble Options", rs)
            rset.set_doc("Scramble Options: 1, 2, 3, 4, 5, 6, 7, 8")
            mem.extra.append(rset)

        return mem

    def _encode_freq(self, hz):
        cfg = self._model_cfg()
        raw = int(hz / 10) - cfg["base_freq_offset"]
        if not (0 <= raw <= cfg["tx_unused_marker"]):
            raise ValueError(f"Frequency {hz} out of 24-bit range")
        return raw

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        cfg = self._model_cfg()

        if mem.empty:
            _mem.set_raw(b"\xFF" * (_mem.size() // 8))
            return

        rx = self._encode_freq(mem.freq)
        _mem.rxfreq = rx

        if mem.duplex == "off":
            tx = cfg["tx_unused_marker"]
        elif mem.duplex == "split":
            tx = self._encode_freq(mem.offset)
        elif mem.duplex == "+":
            tx = self._encode_freq(mem.freq + mem.offset)
        elif mem.duplex == "-":
            tx = self._encode_freq(mem.freq - mem.offset)
        else:
            tx = rx

        _mem.txfreq = tx

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.tx_tone, txmode, txval, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        _mem.scanadd = mem.skip == "S"
        _mem.narrow = mem.mode == "NFM"

        _mem.ishighpower = mem.power == self.POWER_LEVELS[1]

        for setting in mem.extra:
            setting.apply_to_memobj(_mem)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Squelch
        rs = RadioSettingValueInteger(0, 9, _settings.squelch)
        rset = MemSetting("squelch", "Squelch", rs)
        rset.set_doc("Squelch Level: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9")
        basic.append(rset)

        # Time Out Timer
        rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                   current_index=_settings.tot)
        rset = MemSetting("tot", "Time-out Timer", rs)
        rset.set_doc("TX Time-out Timer: Off, 30, 60, 90, 120, 150," +
                     " 180 seconds")
        basic.append(rset)

        # Vox Level
        if self._has_vox_level_off:
            # H777 behavior: 0-9 maps directly
            rs = RadioSettingValueList(
                OFF1TO9_LIST,
                current_index=_settings.vox
            )
            rset = MemSetting("vox", "VOX Level", rs)
        else:
            # RT21H behavior: hide "Off"
            # Firmware: 1-9
            # UI index: 0-8
            index = min(8, max(0, _settings.vox_level - 1))
            rs = RadioSettingValueList(
                ONE_TO_NINE_LIST,
                current_index=index
            )
            rset = MemSetting("vox_level", "VOX Level", rs)

        rset.set_doc(self.VOXL_DOC)
        basic.append(rset)

        # Vox Delay
        rs = RadioSettingValueList(self.VOXD_LIST,
                                   current_index=_settings.voxd)
        rset = MemSetting("voxd", "Vox Delay", rs)
        rset.set_doc(self.VOXD_DOC)
        basic.append(rset)

        # Spec Mode
        if self._has_spec_mode:
            rs = RadioSettingValueList(SPECMODE_LIST,
                                       current_index=_settings.specmode)
            rset = MemSetting("specmode", "Spec Mode", rs)
            rset.set_doc("Spec Mode: Spec Code 1, Spec Code 2")
            basic.append(rset)

        # Scan Mode
        rs = RadioSettingValueList(SCANM_LIST, current_index=_settings.scanm)
        rset = MemSetting("scanm", "Scan Mode", rs)
        rset.set_doc("Scan Mode: Carrier, Time")
        basic.append(rset)

        # Voice Annunciation
        rs = RadioSettingValueList(VOICE_LIST,
                                   current_index=_settings.voice)
        rset = MemSetting("voice", "Voice", rs)
        rset.set_doc("Voice Prompts: Off, English")
        basic.append(rset)

        # Side Key 1
        if self._has_sidekey1:
            SKEY1_DOC = ("Off, Monitor, Scan, Channel Lock, VOX, Power," +
                         " Alarm, Roger")

            # Side Key 1 (short)
            rs = RadioSettingValueList(SKEY1_LIST,
                                       current_index=_settings.skey1S)
            rset = MemSetting("skey1S", "Side Key 1 (short)", rs)
            rset.set_doc("Side Key 1 (short press): " + SKEY1_DOC)
            basic.append(rset)

            # Side Key 1 (long)
            rs = RadioSettingValueList(SKEY1_LIST,
                                       current_index=_settings.skey1L)
            rset = MemSetting("skey1L", "Side Key 1 (long)", rs)
            rset.set_doc("Side Key 1 (long press): " + SKEY1_DOC)
            basic.append(rset)

        # Side key 2
        if self._has_sidekey2:
            # Side Key 2 (long)
            rs = RadioSettingValueList(SKEY2_LIST,
                                       current_index=_settings.skey2)
            rset = MemSetting("skey2", "Side Key 2", rs)
            rset.set_doc("Side Key 2 (long press): Off, VOX, Power, Scan")
            basic.append(rset)

        # Code Switch
        if self._has_codeswitch:
            rs = RadioSettingValueBoolean(_settings.codesw)
            rset = MemSetting("codesw", "Code Switch", rs)
            rset.set_doc("Code Switch: Off, Enabled")
            basic.append(rset)

        # Battery Save
        rs = RadioSettingValueBoolean(_settings.save)
        rset = MemSetting("save", "Battery Save", rs)
        rset.set_doc("Battery Save: Off, Enabled")
        basic.append(rset)

        # Beep Tone
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = MemSetting("beep", "Beep", rs)
        rset.set_doc("Beep Prompt: Off, Enabled")
        basic.append(rset)

        # VOX Switch
        rs = RadioSettingValueBoolean(_settings.voxs)
        rset = MemSetting("voxs", "VOX Switch", rs)
        rset.set_doc("VOX Switch: Off, Enabled")
        basic.append(rset)

        # Low Battery Warning
        if self._has_low_battery_warning:
            rs = RadioSettingValueBoolean(_settings.lowbattwarn)
            rset = MemSetting("lowbattwarn", "Low Battery Warning", rs)
            rset.set_doc("Low Battery Warning: Off, Enabled")
            basic.append(rset)

        # Roger
        rs = RadioSettingValueBoolean(_settings.roger)
        rset = MemSetting("roger", "Roger", rs)
        rset.set_doc("Roger: Off, Enabled")
        basic.append(rset)

        # Remove CT/DCS
        if self._has_remove_ctdcs:
            rs = RadioSettingValueBoolean(_settings.removectdcs)
            rset = MemSetting("removectdcs", "Remove CT/DCS", rs)
            rset.set_doc("Remove CT/DCS: Off, Enabled")
            basic.append(rset)

        return group

    def set_settings(self, settings):
        others = settings.apply_to(self._memobj.settings)
        if others:
            LOG.error('Did not apply %s' % others)

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
@directory.detected_by(h777.RetevisH777)
class H777V4(H777V4BaseRadio):
    """RETEVIS H777V4"""
    VENDOR = "Retevis"
    MODEL = "H777"
    VARIANT = 'V4'
    IDENT = [b'\x00' * 6, b'\xFF' * 6]

    # SKU #: A9294A (sold as FRS radio but supports full band TX/RX)
    # Serial #: 2412R777XXXXXXX

    # SKU #: A9294C (same as SKU #: A9294A (2 pack))
    # Serial #: 2406R777XXXXXXX

    # SKU #: A9294B (sold as PMR radio but supports full band TX/RX)
    # Serial #: 2412R777XXXXXXX

    # SKU #: A9294D (same as SKU #: A9294B (2 pack))
    # Serial #: 24XXR777XXXXXXX


@directory.register
class RT21HRadio(H777V4BaseRadio):
    """RETEVIS RT21H"""
    VENDOR = "Retevis"
    MODEL = "RT21H"

    # SKU #: A9118R (sold as FRS radio but supports full band TX/RX)
    # SKU #: A9118S (sold as PMR radio but supports full band TX/RX)

    IDENT = [b'SMP558\x02\xFF', b'SMP558\x02\x00']
    BLOCK_SIZE = 0x0C
    BLOCK_SIZE_UP = 0x0C

    VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "3.5"]
    VOXD_DOC = "VOX Delay: 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5 seconds"
    VOXL_DOC = "VOX Level: 1, 2, 3, 4, 5, 6, 7, 8, 9"

    _has_codeswitch = False
    _has_compander = True
    _has_low_battery_warning = True
    _has_remove_ctdcs = True
    _has_scramble_options = True
    _has_sidekey1 = True
    _has_sidekey2 = False
    _has_spec_code = True
    _has_spec_mode = True
    _has_vox_level_off = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)
                    ]
    VALID_BANDS = [(400000000, 502000000)]

    PROGRAM_CMD = b"T210GAM"
    _ranges = [
               (0x0000, 0x00D8),
              ]
    _memsize = 0x00D8

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT21H, self._mmap)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            obj = self._memobj.settings
            setting = element.get_name()

            try:
                if setting == "vox_level":
                    # UI index 0-8 ? firmware value 1-9
                    value = min(9, max(1, int(element.value) + 1))
                else:
                    value = element.value

                LOG.debug("Setting %s = %s", setting, value)
                setattr(obj, setting, value)

            except Exception:
                LOG.debug("Error applying setting %s", setting)
                raise
