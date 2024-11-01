# Copyright 2024 Jacob Calvert <jcalvert@jacobncalvert.com>
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

from chirp import chirp_common, bitwise, errors, memmap, directory, util
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.drivers.alinco import ALINCO_TONES, CHARSET

import logging
import codecs

MEM_FORMAT = """
struct {
  u8 used;
  u8 skip;
  u8 favorite;
  u8 unknown3;
  ul32 frequency;
  ul32 shift;
  u8 shift_direction;
  u8 subtone_selection;
  u8 rx_tone_index;
  u8 tx_tone_index;
  u8 dcs_index;
  u8 unknown17;
  u8 power_index;
  u8 busy_channel_lockout;
  u8 mode;
  u8 heterodyne_mode;
  u8 unknown22;
  u8 bell;
  u8 name[6];
  u8 dcs_off;
  u8 unknown31;
  u8 standby_screen_color;
  u8 rx_screen_color;
  u8 tx_screen_color;
  u8 unknown35_to_63[29];
} memory[1000];
"""


LOG = logging.getLogger(__name__)


@directory.register
class AlincoDR735T(chirp_common.CloneModeRadio):
    """Base class for DR735T radio"""

    """Alinco DR735T"""
    VENDOR = "Alinco"
    MODEL = "DR735T"
    BAUD_RATE = 38400

    TONE_MODE_MAP = {
        0x00: "",
        0x01: "Tone",
        0x03: "TSQL",
        0x0C: "DTCS"
    }

    SHIFT_DIR_MAP = ["", "-", "+"]

    POWER_MAP = [
        chirp_common.PowerLevel("High", watts=50.0),
        chirp_common.PowerLevel("Mid", watts=25.00),
        chirp_common.PowerLevel("Low", watts=5.00),
    ]
    MODE_MAP = {
        0x00: "FM",
        0x01: "NFM",
        0x02: "AM",
        0x03: "NAM",
        0x80: "Auto"
    }

    HET_MODE_MAP = ["Normal", "Reverse"]

    SCREEN_COLOR_MAP = [f"Color {n+1}" for n in range(16)]

    _freq_ranges = [
        (108000000, 136000000),
        (136000000, 174000000),
        (400000000, 480000000)
    ]
    _no_channels = 1000

    _model = b"DR735TN"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        # convert to list to deal with dict_values unsubscriptable
        rf.valid_tmodes = list(self.TONE_MODE_MAP.values())
        rf.valid_modes = list(self.MODE_MAP.values())
        rf.valid_skips = ["", "S"]
        rf.valid_bands = self._freq_ranges
        rf.valid_tuning_steps = [5.0, 6.25, 12.5]
        rf.memory_bounds = (0, self._no_channels-1)
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False

        rf.can_delete = False
        rf.valid_name_length = 6
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC
        rf.valid_power_levels = self.POWER_MAP
        rf.valid_dtcs_codes = chirp_common.DTCS_CODES

        return rf

    def _identify(self) -> bool:
        command = b"AL~WHO\r\n"
        self.pipe.write(command)
        self.pipe.read(len(command))
        # expect DR735TN\r\n
        radio_id = self.pipe.read(9).strip()
        if not radio_id:
            raise errors.RadioError("No response from radio")
        LOG.debug('Model string is %s' % util.hexprint(radio_id))
        return radio_id in (b"DR735TN", b"DR735TE")

    def do_download(self):
        if not self._identify():
            raise errors.RadioError("Unsupported radio model.")

        channel_data = b""

        for channel_no in range(0, self._no_channels):

            command = f"AL~EEPEL{channel_no<<6 :04X}R\r\n".encode()
            self.pipe.write(command)
            self.pipe.read(len(command))
            channel_spec = self.pipe.read(128)  # 64 bytes, as hex
            self.pipe.read(2)  # \r\n
            channel_spec = codecs.decode(channel_spec, "hex")
            if len(channel_spec) != 64:
                exit(1)
            channel_data += channel_spec

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = channel_no
                status.max = self._no_channels
                status.msg = f"Downloading channel {channel_no} from radio"
                self.status_fn(status)

        return memmap.MemoryMapBytes(channel_data)

    def do_upload(self):
        if not self._identify():
            raise errors.RadioError("Unsupported radio model.")

        command = b"AL~DR735J\r\n"
        self.pipe.write(command)
        self.pipe.read(len(command))
        resp = self.pipe.read(4)
        if resp != b"OK\r\n":
            errors.RadioError("Could not go into download mode.")

        for channel_no in range(0, self._no_channels):
            write_data = self.get_mmap()[channel_no*64:(channel_no+1)*64]
            write_data = codecs.encode(write_data, 'hex').upper()
            command = f"AL~EEPEL{channel_no<<6 :04X}W".encode(
            ) + write_data + b"\r\n"
            LOG.debug(f"COMM: {command}")
            self.pipe.write(command)
            back = self.pipe.read(len(command))
            LOG.debug(f"BACK: {back}")
            resp = self.pipe.read(4)
            LOG.debug(f"RESP: {resp}")
            if resp != b"OK\r\n":
                raise errors.RadioError("failed to write to channel")

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = channel_no
                status.max = self._no_channels
                status.msg = f"Uploading channel {channel_no} to radio"
                self.status_fn(status)

        command = b"AL~RESET\r\n"
        self.pipe.write(command)
        self.pipe.read(len(command))  # command + OK\r\n
        self.pipe.read(4)

    def sync_in(self):
        try:
            self._mmap = self.do_download()
        except Exception as exc:
            raise errors.RadioError(f"Failed to download from radio: {exc}")
        self.process_mmap()

    def sync_out(self):
        try:
            self.do_upload()
        except Exception as exc:
            raise errors.RadioError(f"Failed to download from radio: {exc}")

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):

        _mem = self._memobj.memory[number]
        mem = chirp_common.Memory()
        mem.number = number                 # Set the memory number
        if _mem.used != 0x55:
            mem.empty = True
            mem.freq = 400000000
            mem.name = ""

            mem.tmode = self.TONE_MODE_MAP[0]
            mem.duplex = self.SHIFT_DIR_MAP[0]
            mem.offset = 0

            mem.rtone = ALINCO_TONES[0]
            mem.ctone = ALINCO_TONES[0]
            mem.dtcs = chirp_common.DTCS_CODES[0]
            mem.power = self.POWER_MAP[0]
            mem.skip = ''
            mem.mode = self.MODE_MAP[0]
            self._get_extra_default(mem)

            return mem
        else:
            mem.empty = False
            mem.freq = int(_mem.frequency)
            mem.name = "".join([CHARSET[_mem.name[i]]
                               for i in range(6)]).strip()

            mem.tmode = self.TONE_MODE_MAP[int(_mem.subtone_selection)]
            mem.duplex = self.SHIFT_DIR_MAP[_mem.shift_direction]
            mem.offset = _mem.shift

            mem.rtone = ALINCO_TONES[_mem.rx_tone_index]
            mem.ctone = ALINCO_TONES[_mem.tx_tone_index]
            mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs_index]
            mem.power = self.POWER_MAP[_mem.power_index]
            mem.skip = 'S' if bool(_mem.skip) else ''
            mem.mode = self.MODE_MAP[int(_mem.mode)]

            self._get_extra(_mem, mem)

            return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number]

        def find_key_in(d: dict, target_val):
            for k, v in d.items():
                if v == target_val:
                    return k

        if not mem.empty:
            mapped_name = [CHARSET.index(' ').to_bytes(1, 'little')]*6
            for (i, c) in enumerate(mem.name.ljust(6)[:6].upper().strip()):
                if c not in chirp_common.CHARSET_UPPER_NUMERIC:
                    c = " "  # just make it a space
                mapped_name[i] = CHARSET.index(c).to_bytes(1, 'little')
            _mem.frequency = int(mem.freq)
            _mem.name = b''.join(mapped_name)
            _mem.mode = find_key_in(self.MODE_MAP, mem.mode)
            _mem.subtone_selection = find_key_in(self.TONE_MODE_MAP, mem.tmode)
            _mem.shift = mem.offset
            _mem.used = 0x00 if mem.empty else 0x55
            _mem.power_index = self.POWER_MAP.index(
                mem.power) if mem.power in self.POWER_MAP else 0
            _mem.skip = 0x01 if mem.skip == "S" else 0x00
            try:
                _mem.rx_tone_index = ALINCO_TONES.index(mem.rtone)
            except ValueError:
                raise errors.UnsupportedToneError("This radio does "
                                                  "not support "
                                                  "tone %.1fHz" % mem.rtone)
            try:

                _mem.tx_tone_index = ALINCO_TONES.index(mem.ctone)
            except ValueError:
                raise errors.UnsupportedToneError("This radio does "
                                                  "not support "
                                                  "tone %.1fHz" % mem.ctone)
            _mem.dcs_index = chirp_common.DTCS_CODES.index(
                mem.dtcs if mem.dtcs else chirp_common.DTCS_CODES[0])
            _mem.shift_direction = self.SHIFT_DIR_MAP.index(
                mem.duplex if mem.duplex else self.SHIFT_DIR_MAP[0])
        else:
            _mem.frequency = 0
            _mem.name = b"\x00"*6
            _mem.mode = find_key_in(self.MODE_MAP, "Auto")
            _mem.subtone_selection = find_key_in(self.TONE_MODE_MAP, "")
            _mem.shift = 0
            _mem.used = 0x00 if mem.empty else 0x55
            _mem.power_index = 0
            _mem.skip = 0x01 if mem.skip == "S" else 0x00
            _mem.rx_tone_index = 0
            _mem.tx_tone_index = 0
            _mem.dcs_index = 0
            _mem.shift_direction = self.SHIFT_DIR_MAP.index("")

        self._set_extra(_mem, mem)

    def _get_extra_default(self, mem):
        mem.extra = RadioSettingGroup("extra", "Extra")
        het_mode = RadioSetting("heterodyne_mode", "Heterodyne Mode",
                                RadioSettingValueList(
                                    self.HET_MODE_MAP,
                                    current=self.HET_MODE_MAP[0]
                                ))
        het_mode.set_doc("Heterodyne Mode")

        bcl = RadioSetting("bcl", "BCL",
                           RadioSettingValueBoolean(False))
        bcl.set_doc("Busy Channel Lockout")

        fav = RadioSetting("fav", "Favorite",
                           RadioSettingValueBoolean(False))
        fav.set_doc("Favorite Channel")

        bell = RadioSetting("bell", "Bell",
                            RadioSettingValueBoolean(False))
        bell.set_doc("Bell Alert")

        stby_screen = RadioSetting("stby_screen", "Standby Screen Color",
                                   RadioSettingValueList(
                                       self.SCREEN_COLOR_MAP,
                                       current=self.SCREEN_COLOR_MAP[0]))
        stby_screen.set_doc("Standby Screen Color")

        rx_screen = RadioSetting("rx_screen", "RX Screen Color",
                                 RadioSettingValueList(
                                     self.SCREEN_COLOR_MAP,
                                     current=self.SCREEN_COLOR_MAP[0]))
        rx_screen.set_doc("RX Screen Color")

        tx_screen = RadioSetting("tx_screen", "TX Screen Color",
                                 RadioSettingValueList(
                                     self.SCREEN_COLOR_MAP,
                                     current=self.SCREEN_COLOR_MAP[0]))

        tx_screen.set_doc("TX Screen Color")

        mem.extra.append(het_mode)
        mem.extra.append(bcl)
        mem.extra.append(fav)
        mem.extra.append(bell)
        mem.extra.append(stby_screen)
        mem.extra.append(rx_screen)
        mem.extra.append(tx_screen)

    def _get_extra(self, _mem, mem):
        mem.extra = RadioSettingGroup("extra", "Extra")
        het_mode = RadioSetting(
            "heterodyne_mode", "Heterodyne Mode",
            RadioSettingValueList(
                self.HET_MODE_MAP,
                current=self.HET_MODE_MAP[int(_mem.heterodyne_mode)]))
        het_mode.set_doc("Heterodyne Mode")

        bcl = RadioSetting("bcl", "BCL",
                           RadioSettingValueBoolean(
                               bool(_mem.busy_channel_lockout)))
        bcl.set_doc("Busy Channel Lockout")

        fav = RadioSetting("fav", "Favorite",
                           RadioSettingValueBoolean(bool(_mem.favorite)))
        fav.set_doc("Favorite Channel")

        bell = RadioSetting("bell", "Bell",
                            RadioSettingValueBoolean(bool(_mem.bell)))
        bell.set_doc("Bell Alert")

        stby_screen = RadioSetting(
            "stby_screen", "Standby Screen Color",
            RadioSettingValueList(
                self.SCREEN_COLOR_MAP,
                current=self.SCREEN_COLOR_MAP[int(_mem.standby_screen_color)]))
        stby_screen.set_doc("Standby Screen Color")

        rx_screen = RadioSetting(
            "rx_screen", "RX Screen Color",
            RadioSettingValueList(
                self.SCREEN_COLOR_MAP,
                current=self.SCREEN_COLOR_MAP[int(_mem.rx_screen_color)]))
        rx_screen.set_doc("RX Screen Color")

        tx_screen = RadioSetting(
            "tx_screen", "TX Screen Color",
            RadioSettingValueList(
                self.SCREEN_COLOR_MAP,
                current=self.SCREEN_COLOR_MAP[int(_mem.tx_screen_color)]))
        tx_screen.set_doc("TX Screen Color")

        mem.extra.append(het_mode)
        mem.extra.append(bcl)
        mem.extra.append(stby_screen)
        mem.extra.append(fav)
        mem.extra.append(bell)
        mem.extra.append(rx_screen)
        mem.extra.append(tx_screen)

    def _set_extra(self, _mem, mem):
        for setting in mem.extra:
            if setting.get_name() == "heterodyne_mode":
                _mem.heterodyne_mode = \
                    self.HET_MODE_MAP.index(
                        setting.value) if \
                    setting.value else self.HET_MODE_MAP[0]

            if setting.get_name() == "bcl":
                _mem.busy_channel_lockout = int(setting.value)

            if setting.get_name() == "fav":
                _mem.favorite = int(setting.value)

            if setting.get_name() == "bell":
                _mem.bell = int(setting.value)

            if setting.get_name() == "stby_screen":
                _mem.standby_screen_color = \
                    self.SCREEN_COLOR_MAP.index(setting.value) if \
                    setting.value else self.SCREEN_COLOR_MAP[0]

            if setting.get_name() == "rx_screen":
                _mem.rx_screen_color = \
                    self.SCREEN_COLOR_MAP.index(setting.value) if \
                    setting.value else self.SCREEN_COLOR_MAP[0]

            if setting.get_name() == "tx_screen":
                _mem.tx_screen_color = \
                    self.SCREEN_COLOR_MAP.index(setting.value) if \
                    setting.value else self.SCREEN_COLOR_MAP[0]
