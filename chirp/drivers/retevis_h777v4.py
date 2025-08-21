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
     bcl:1;           //     Busy Channel Locklut  0 = On, 1 = Off
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


CMD_ACK = b"\x06"

DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

OFF1TO9_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
SCANM_LIST = ["Carrier", "Time"]
SKEY2_LIST = ["Off", "VOX", "Power", "Scan"]
TIMEOUTTIMER_LIST = ["Off"] + ["%s seconds" % x for x in range(30, 210, 30)]
VOICE_LIST = ["Off", "English"]
VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]


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

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)
                    ]

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
        rf.valid_bands = [(400000000, 520000000)]
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
            toneval = int("%i" % (val * 10), 16)
        elif mode == "DTCS":
            toneval = int('%i' % val, 8)
            toneval |= 0x8000
            if pol == "R":
                toneval |= 0x4000
        else:
            toneval = 0xFFFF

        _toneval[0].set_raw(toneval & 0xFF)
        _toneval[1].set_raw((toneval >> 8) & 0xFF)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:1] == b"\xFF":
            mem.empty = True
            return mem

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

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        _mem.set_raw(b"\xff" * 13)
        if mem.empty:
            return

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

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.tx_tone, txmode, txval, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        _mem.scanadd = mem.skip == "S"
        _mem.narrow = mem.mode == "NFM"

        _mem.ishighpower = mem.power == self.POWER_LEVELS[1]

        # resetting unknowns, this have to be set by hand
        _mem.unknown0 = 3
        _mem.unknown1 = 1

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
        rs = RadioSettingValueList(OFF1TO9_LIST, current_index=_settings.vox)
        rset = MemSetting("vox", "VOX Level", rs)
        rset.set_doc("VOX Level: Off, 1, 2, 3, 4, 5, 6, 7, 8, 9")
        basic.append(rset)

        # Vox Delay
        rs = RadioSettingValueList(VOXD_LIST,
                                   current_index=_settings.voxd)
        rset = MemSetting("voxd", "Vox Delay", rs)
        rset.set_doc("VOX Delay: 0.5, 1.0, 1.5, 2.0, 2.5, 3.0 seconds")
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

        # Side Key 2 (long)
        rs = RadioSettingValueList(SKEY2_LIST,
                                   current_index=_settings.skey2)
        rset = MemSetting("skey2", "Side Key 2", rs)
        rset.set_doc("Side Key 2 (long press): Off, VOX, Power, Scan")
        basic.append(rset)

        # Code Switch
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

        # Roger
        rs = RadioSettingValueBoolean(_settings.roger)
        rset = MemSetting("roger", "Roger", rs)
        rset.set_doc("Roger: Off, Enabled")
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
