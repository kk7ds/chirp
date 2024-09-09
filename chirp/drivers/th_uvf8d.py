# Copyright 2013 Dan Smith <dsmith@danplanet.com>
#                Eric Allen <eric@hackerengineer.net>
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

"""TYT TH-UVF8D radio management module"""

# TODO: support FM Radio memories
# TODO: support bank B (another 128 memories)
# TODO: [setting] Battery Save
# TODO: [setting] Tail Eliminate
# TODO: [setting] Tail Mode

import struct
import logging

from chirp import chirp_common, bitwise, errors, directory, memmap, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)


def uvf8d_identify(radio):
    """Do identify handshake with TYT TH-UVF8D"""
    try:
        radio.pipe.write(b"\x02PROGRAM")
        ack = radio.pipe.read(2)
        if ack != b"PG":
            raise errors.RadioError("Radio did not ACK first command: %x" %
                                    ord(ack))
    except Exception:
        raise errors.RadioError("Unable to communicate with the radio")

    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(32)
    radio.pipe.write(b"A")
    r = radio.pipe.read(1)
    if r != b"A":
        raise errors.RadioError("Ack failed")
    return ident


def tyt_uvf8d_download(radio):
    data = uvf8d_identify(radio)
    for i in range(0, 0x4000, 0x20):
        msg = struct.pack(">cHb", b"R", i, 0x20)
        radio.pipe.write(msg)
        block = radio.pipe.read(0x20 + 4)
        if len(block) != (0x20 + 4):
            raise errors.RadioError("Radio sent a short block")
        radio.pipe.write(b"A")
        ack = radio.pipe.read(1)
        if ack != b"A":
            raise errors.RadioError("Radio NAKed block")
        data += block[4:]

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = 0x4000
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    radio.pipe.write(b"ENDR")

    return memmap.MemoryMapBytes(data)


def tyt_uvf8d_upload(radio):
    """Upload to TYT TH-UVF8D"""
    data = uvf8d_identify(radio)

    radio.pipe.timeout = 1

    if data != radio._mmap[0:32]:
        raise errors.RadioError("Model mismatch: \n%s\n%s" %
                                (util.hexprint(data),
                                 util.hexprint(radio._mmap[0:32])))

    for i in range(0, 0x4000, 0x20):
        addr = i + 0x20
        msg = struct.pack(">cHb", b"W", i, 0x20)
        msg += radio._mmap[addr:(addr + 0x20)]

        radio.pipe.write(msg)
        ack = radio.pipe.read(1)
        if ack != b"A":
            raise errors.RadioError("Radio did not ack block %i" % i)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = 0x4000
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    # End of clone?
    radio.pipe.write(b"ENDW")

    # Checksum?
    radio.pipe.read(3)

# these require working desktop software
# TODO: DTMF features (ID, delay, speed, kill, etc.)

# TODO: Display Name


UVF8D_MEM_FORMAT = """
struct memory {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];

  u8 apro:4,
     rpt_md:2,
     unknown1:2;
  u8 bclo:2,
     wideband:1,
     ishighpower:1,
     scanadd:1,
     vox:1,
     pttid:2;
  u8 unknown3:8;

  u8 unknown4:6,
     duplex:2;

  lbcd offset[4];

  char unknown5[4];

  char name[7];

  char unknown6[1];
};

struct fm_broadcast_memory {
  lbcd freq[3];
  u8 unknown;
};

struct enable_flags {
  bit flags[8];
};

#seekto 0x0020;
struct memory channels[128];

#seekto 0x2020;
struct memory vfo1;
struct memory vfo2;

#seekto 0x2060;
struct {
  u8 unknown2060:4,
     tot:4;
  u8 unknown2061;
  u8 squelch;
  u8 unknown2063:4,
     vox_level:4;
  u8 tuning_step;
  char unknown12;
  u8 lamp_t;
  char unknown11;
  u8 unknown2068;
  u8 ani:1,
     scan_mode:2,
     unknown2069:2,
     beep:1,
     tx_sel:1,
     roger:1;
  u8 light:2,
     led:2,
     taileliminate:1,
     autolk:1,
     unknown206ax:2;
  u8 unknown206b:1,
     b_display:2,
     a_display:2,
     ab_switch:1,
     dwait:1,
     mode:1;
  u8 dw:1,
     unknown206c:6,
     voice:1;
  u8 unknown206d:2,
     rxsave:2,
     opnmsg:2,
     lock_mode:2;
  u8 a_work_area:1,
     b_work_area:1,
     unknown206ex:6;
  u8 a_channel;
  u8 b_channel;
  u8 pad3[15];
  char ponmsg[7];
} settings;

#seekto 0x2E60;
struct enable_flags enable[16];
struct enable_flags skip[16];

#seekto 0x2FA0;
struct fm_broadcast_memory fm_current;

#seekto 0x2FA8;
struct fm_broadcast_memory fm_memories[20];
"""

THUVF8D_DUPLEX = ["", "-", "+"]
THUVF8D_CHARSET = "".join([chr(ord("0") + x) for x in range(0, 10)] +
                          [" -*+"] +
                          [chr(ord("A") + x) for x in range(0, 26)] +
                          ["_/"])
TXSEL_LIST = ["EDIT", "BUSY"]
LED_LIST = ["Off", "Auto", "On"]
MODE_LIST = ["Memory", "VFO"]
AB_LIST = ["A", "B"]
DISPLAY_LIST = ["Channel", "Frequency", "Name"]
LIGHT_LIST = ["Purple", "Orange", "Blue"]
RPTMD_LIST = ["Off", "Reverse", "Talkaround"]
VOX_LIST = ["1", "2", "3", "4", "5", "6", "7", "8"]
WIDEBAND_LIST = ["Narrow", "Wide"]
TOT_LIST = ["Off", "30s", "60s", "90s", "120s", "150s", "180s", "210s",
            "240s", "270s"]
SCAN_MODE_LIST = ["Time", "Carry", "Seek"]
OPNMSG_LIST = ["Off", "DC (Battery)", "Message"]

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Low", watts=0.5),
                ]

PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
BCLO_LIST = ["Off", "Wave", "Call"]
APRO_LIST = ["Off", "Compander", "Scramble 1", "Scramble 2", "Scramble 3",
             "Scramble 4", "Scramble 5", "Scramble 6", "Scramble 7",
             "Scramble 8"]
LOCK_MODE_LIST = ["PTT", "Key", "Key+S", "All"]

TUNING_STEPS_LIST = ["2.5", "5.0", "6.25", "10.0", "12.5",
                     "25.0", "50.0", "100.0"]
BACKLIGHT_TIMEOUT_LIST = ["1s", "2s", "3s", "4s", "5s",
                          "6s", "7s", "8s", "9s", "10s"]

SPECIALS = {
    "VFO1": -2,
    "VFO2": -1}


@directory.register
class TYTUVF8DRadio(chirp_common.CloneModeRadio):
    VENDOR = "TYT"
    MODEL = "TH-UVF8D"
    BAUD_RATE = 9600

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 128)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_tuning_step = False
        rf.has_cross = False
        rf.has_rx_dtcs = True
        rf.has_settings = True
        # it may actually be supported, but I haven't tested
        rf.can_odd_split = False
        rf.valid_duplexes = THUVF8D_DUPLEX
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_special_chans = list(SPECIALS.keys())
        rf.valid_name_length = 7
        return rf

    def sync_in(self):
        self._mmap = tyt_uvf8d_download(self)
        self.process_mmap()

    def sync_out(self):
        tyt_uvf8d_upload(self)

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata.startswith(b"TYT-F10\x00")

    def process_mmap(self):
        self._memobj = bitwise.parse(UVF8D_MEM_FORMAT, self._mmap)

    def _decode_tone(self, toneval):
        pol = "N"
        rawval = (toneval[1].get_bits(0xFF) << 8) | toneval[0].get_bits(0xFF)

        if toneval[0].get_bits(0xFF) == 0xFF:
            mode = ""
            val = 0
        elif toneval[1].get_bits(0xC0) == 0xC0:
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
            pol = "R"
        elif toneval[1].get_bits(0x80):
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
        else:
            mode = "Tone"
            val = int(toneval) / 10.0

        return mode, val, pol

    def _encode_tone(self, _toneval, mode, val, pol):
        toneval = 0
        if mode == "Tone":
            toneval = int("%i" % (val * 10), 16)
        elif mode == "DTCS":
            toneval = int("%i" % val, 16)
            toneval |= 0x8000
            if pol == "R":
                toneval |= 0x4000
        else:
            toneval = 0xFFFF

        _toneval[0].set_raw(toneval & 0xFF)
        _toneval[1].set_raw((toneval >> 8) & 0xFF)

    def get_raw_memory(self, number):
        return repr(self._memobj.channels[number - 1])

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()), None)
        elif number < 0:
            for k, v in SPECIALS.items():
                if number == v:
                    return (getattr(self._memobj, k.lower()), None)
        else:
            return (self._memobj.channels[number - 1],
                    None)

    def get_memory(self, number):
        _mem, _name = self._get_memobjs(number)

        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = SPECIALS[number]
            mem.extd_number = number
        else:
            mem.number = number

        if _mem.get_raw(asbytes=False).startswith("\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        if isinstance(number, int):
            e = self._memobj.enable[(number - 1) / 8]
            enabled = e.flags[7 - ((number - 1) % 8)]
            s = self._memobj.skip[(number - 1) / 8]
            dont_skip = s.flags[7 - ((number - 1) % 8)]
        else:
            enabled = True
            dont_skip = True

        if not enabled:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        mem.duplex = THUVF8D_DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset) * 10

        txmode, txval, txpol = self._decode_tone(_mem.tx_tone)
        rxmode, rxval, rxpol = self._decode_tone(_mem.rx_tone)

        chirp_common.split_tone_decode(mem,
                                       (txmode, txval, txpol),
                                       (rxmode, rxval, rxpol))

        mem.name = str(_mem.name).rstrip('\xFF ')

        if dont_skip:
            mem.skip = ''
        else:
            mem.skip = 'S'

        mem.mode = _mem.wideband and "FM" or "NFM"
        mem.power = POWER_LEVELS[1 - _mem.ishighpower]

        mem.extra = RadioSettingGroup("extra", "Extra Settings")

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_LIST,
                                                current_index=_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("vox", "VOX",
                          RadioSettingValueBoolean(_mem.vox))
        mem.extra.append(rs)

        rs = RadioSetting("bclo", "Busy Channel Lockout",
                          RadioSettingValueList(BCLO_LIST,
                                                current_index=_mem.bclo))
        mem.extra.append(rs)

        rs = RadioSetting("apro", "APRO",
                          RadioSettingValueList(APRO_LIST,
                                                current_index=_mem.apro))
        mem.extra.append(rs)

        rs = RadioSetting("rpt_md", "Repeater Mode",
                          RadioSettingValueList(RPTMD_LIST,
                                                current_index=_mem.rpt_md))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem, _name = self._get_memobjs(mem.number)

        e = self._memobj.enable[(mem.number - 1) / 8]
        s = self._memobj.skip[(mem.number - 1) / 8]
        if mem.empty:
            _mem.set_raw("\xFF" * 32)
            e.flags[7 - ((mem.number - 1) % 8)] = False
            s.flags[7 - ((mem.number - 1) % 8)] = False
            return
        else:
            e.flags[7 - ((mem.number - 1) % 8)] = True

        if _mem.get_raw(asbytes=False) == ("\xFF" * 32):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 32)

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        _mem.duplex = THUVF8D_DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset / 10

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.tx_tone, txmode, txval, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        _mem.name = mem.name.rstrip(' ').ljust(7, "\xFF")

        flag_index = 7 - ((mem.number - 1) % 8)
        s.flags[flag_index] = (mem.skip == "")
        _mem.scanadd = (mem.skip == "")
        _mem.wideband = mem.mode == "FM"
        _mem.ishighpower = mem.power == POWER_LEVELS[0]

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)

    def get_settings(self):
        _settings = self._memobj.settings

        group = RadioSettingGroup("basic", "Basic")
        top = RadioSettings(group)

        group.append(RadioSetting(
                "mode", "Mode",
                RadioSettingValueList(
                    MODE_LIST, current_index=_settings.mode)))

        group.append(RadioSetting(
                "ab_switch", "A/B",
                RadioSettingValueList(
                    AB_LIST, current_index=_settings.ab_switch)))

        group.append(RadioSetting(
                "a_channel", "A Selected Memory",
                RadioSettingValueInteger(1, 128,
                                         min(_settings.a_channel + 1, 128))))

        group.append(RadioSetting(
                "b_channel", "B Selected Memory",
                RadioSettingValueInteger(1, 128,
                                         min(_settings.b_channel + 1, 128))))

        group.append(RadioSetting(
                "a_display", "A Channel Display",
                RadioSettingValueList(
                    DISPLAY_LIST, current_index=_settings.a_display)))
        group.append(RadioSetting(
                "b_display", "B Channel Display",
                RadioSettingValueList(
                    DISPLAY_LIST, current_index=_settings.b_display)))
        group.append(RadioSetting(
                "tx_sel", "Priority Transmit",
                RadioSettingValueList(
                    TXSEL_LIST, current_index=_settings.tx_sel)))
        group.append(RadioSetting(
                "vox_level", "VOX Level",
                RadioSettingValueList(
                    VOX_LIST, current_index=_settings.vox_level)))

        group.append(RadioSetting(
                "squelch", "Squelch Level",
                RadioSettingValueInteger(0, 9, _settings.squelch)))

        group.append(RadioSetting(
                "dwait", "Dual Wait",
                RadioSettingValueBoolean(_settings.dwait)))

        group.append(RadioSetting(
                "led", "LED Mode",
                RadioSettingValueList(LED_LIST, current_index=_settings.led)))

        group.append(RadioSetting(
                "light", "Light Color",
                RadioSettingValueList(
                    LIGHT_LIST, current_index=_settings.light)))

        group.append(RadioSetting(
                "beep", "Beep",
                RadioSettingValueBoolean(_settings.beep)))

        group.append(RadioSetting(
                "ani", "ANI",
                RadioSettingValueBoolean(_settings.ani)))

        group.append(RadioSetting(
                "tot", "Timeout Timer",
                RadioSettingValueList(TOT_LIST, current_index=_settings.tot)))

        group.append(RadioSetting(
                "roger", "Roger Beep",
                RadioSettingValueBoolean(_settings.roger)))

        group.append(RadioSetting(
                "dw", "Dual Watch",
                RadioSettingValueBoolean(_settings.dw)))

        group.append(RadioSetting(
                "rxsave", "RX Save",
                RadioSettingValueBoolean(_settings.rxsave)))

        def _filter(name):
            return str(name).rstrip("\xFF").rstrip()

        group.append(RadioSetting(
                "ponmsg", "Power-On Message",
                RadioSettingValueString(0, 7, _filter(_settings.ponmsg))))

        group.append(RadioSetting(
                "scan_mode", "Scan Mode",
                RadioSettingValueList(
                    SCAN_MODE_LIST, current_index=_settings.scan_mode)))

        group.append(RadioSetting(
            'taileliminate', 'Tail Eliminate',
            RadioSettingValueBoolean(_settings.taileliminate)))

        group.append(RadioSetting(
                "autolk", "Auto Lock",
                RadioSettingValueBoolean(_settings.autolk)))

        group.append(RadioSetting(
                "lock_mode", "Keypad Lock Mode",
                RadioSettingValueList(
                    LOCK_MODE_LIST, current_index=_settings.lock_mode)))

        group.append(RadioSetting(
                "voice", "Voice Prompt",
                RadioSettingValueBoolean(_settings.voice)))

        group.append(RadioSetting(
                "opnmsg", "Opening Message",
                RadioSettingValueList(
                    OPNMSG_LIST, current_index=_settings.opnmsg)))

        group.append(RadioSetting(
                "tuning_step", "Tuning Step",
                RadioSettingValueList(
                    TUNING_STEPS_LIST,
                    current_index=_settings.tuning_step)))

        group.append(RadioSetting(
                "lamp_t", "Backlight Timeout",
                RadioSettingValueList(
                    BACKLIGHT_TIMEOUT_LIST,
                    current_index=_settings.lamp_t)))

        group.append(RadioSetting(
                "a_work_area", "A Work Area",
                RadioSettingValueList(
                    AB_LIST, current_index=_settings.a_work_area)))

        group.append(RadioSetting(
                "b_work_area", "B Work Area",
                RadioSettingValueList(
                    AB_LIST, current_index=_settings.b_work_area)))

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings

        for element in settings:
            if element.get_name() == 'rxsave':
                if bool(element.value.get_value()):
                    _settings.rxsave = 3
                else:
                    _settings.rxsave = 0
                continue
            if element.get_name().endswith('_channel'):
                LOG.debug('%s %s', element.value, type(element.value))
                setattr(_settings, element.get_name(), int(element.value) - 1)
                continue
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            setattr(_settings, element.get_name(), element.value)
