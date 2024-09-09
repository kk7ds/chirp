# Copyright 2023 Finn Thain <vk3fta@fastmail.com.au>
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

from chirp import chirp_common, bitwise, memmap, errors, directory, util
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueList, RadioSettingValueBoolean
from chirp.settings import RadioSettingValueInteger, RadioSettings

import logging

LOG = logging.getLogger(__name__)

HF90_MEM_FORMAT = """
#seekto 0x1800;
struct {
  u8 type:1, f_p_program:1, unknown1:1, auto_tune:1,
     tx_power:2, unknown2:1, mode_toggle:1;
  u8 unknown3;
  u24 pin;
  u16 selcall_id;
  u8 unknown4;
} settings;

struct {
  u8 unknown5:3, tx_equals_rx:1, usb:1, scan:1, selcall:1, alarm:1;
  ul16 rx0_15;
  u8 tx0_3:4, rx16_19:4;
  ul16 tx4_19;
  ul16 vnum;
} memory[255];
"""

HF90_CONFIG_ADDR = 0x1800
HF90_CONFIG_LEN = 0x800


def to_ihex(addr, kind, data):
    rec = [len(data) & 0xff, (addr >> 8) & 0xff, addr & 0xff, kind & 0xff]
    for d in data:
        rec.append(d)
    csum = 0
    for n in rec:
        csum += n
    rec.append((-csum) & 0xff)
    return rec


def reset_buffer(pipe):
    pipe.reset_input_buffer()
    timeout = pipe.timeout
    pipe.timeout = 0.05
    junk = pipe.read(32)
    count = len(junk)
    if count > 0:
        LOG.debug("reset_buffer: discarded %d bytes" % count)
        LOG.debug(util.hexprint(junk))
        junk = pipe.read(1)
        count = len(junk)
    pipe.timeout = timeout
    if count > 0:
        raise errors.RadioError("Unable to clean serial buffer. "
                                "Please check your serial port selection.")


class HF90StyleRadio(chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    """Base class for HF-90 radio variants"""
    VENDOR = "Q-MAC"
    MODEL = "HF-90"
    MODES = ["LSB", "USB"]
    DUPLEX = ["", "+", "-", "split", "off"]
    BAUD_RATE = 4800

    HF90_POWER_LEVELS = ["Low", "High"]

    _memsize = HF90_CONFIG_ADDR + HF90_CONFIG_LEN
    _lower = 1
    _upper = 255

    def _send(self, data):
        LOG.debug("PC->R: (%2i)\n%s" % (len(data), util.hexprint(data)))
        self.pipe.write(data)
        echo = self.pipe.read(len(data))
        if echo != data:
            LOG.error("Bad echo: (%2i)\n%s" % (len(data), util.hexprint(data)))

    def _read(self, length):
        data = self.pipe.read(length)
        LOG.debug("R->PC: (%2i)\n%s" % (len(data), util.hexprint(data)))
        return data

    def _serial_prompt(self):
        reset_buffer(self.pipe)
        self._send(b'\r')
        return self._read(3) == b'\r\n#'

    def _download_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        # Response format:
        # 1. Four-digit address, followed by a space
        # 2. 16 pairs of hex digits, each pair followed by a space
        # 3. One additional space
        # 4. 16 char ASCII representation
        # 5. \r\n
        resp_len = 5 + 48 + 1 + 16 + 2

        resp = self._read(resp_len).strip()
        if b'  ' not in resp:
            raise errors.RadioError("Incorrect data received from radio")
        words = resp.split(b' ')
        if addr != int(words[0], 16):
            raise errors.RadioError("Incorrect address received from radio")
        data = []
        for hh in words[1:17]:
            data.append(int(hh, 16))

        if len(data) != 16:
            LOG.debug(data)
            raise errors.RadioError("Radio sent %d bytes" % len(data))

        return bytes(data)

    def _download(self, limit):
        self.pipe.baudrate = self.BAUD_RATE
        if not self._serial_prompt():
            raise errors.RadioError("Did not get initial prompt from radio")

        data = b'\x00' * HF90_CONFIG_ADDR

        cmd = b'D%04X%04X' % (HF90_CONFIG_ADDR, limit - HF90_CONFIG_ADDR)
        self._send(cmd)

        resp = self._read(2)
        if resp != b'\r\n':
            raise errors.RadioError("Incorrect separator received from radio")

        for addr in range(HF90_CONFIG_ADDR, limit, 16):
            data += self._download_chunk(addr)

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr + 16 - HF90_CONFIG_ADDR
                status.max = limit - HF90_CONFIG_ADDR
                status.msg = "Downloading from radio"
                self.status_fn(status)

        resp = self._read(3)
        if resp != b'\r\n#':
            raise errors.RadioError("Incorrect response from radio")

        return memmap.MemoryMapBytes(data)

    def _upload_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        data = self._mmap.get_byte_compatible()[addr:addr + 16]
        ihex_rec = to_ihex(addr, 0, list(data[0:16]))
        cmd = b':' + b''.join(b'%02X' % b for b in ihex_rec)
        LOG.debug(cmd)
        self._send(cmd)

        resp = self._read(4)
        if resp != b'\x13\x11\r\n':
            LOG.debug(util.hexprint(resp))
            raise errors.RadioError("Did not receive ack from radio")

    def _upload(self, limit):
        self.pipe.baudrate = self.BAUD_RATE
        if not self._serial_prompt():
            raise errors.RadioError("Did not get initial prompt from radio")

        timeout = self.pipe.timeout
        self.pipe.timeout = 1

        self._send(b'L0000')

        resp = self._read(4)
        if resp != b'\r\n\r\n':
            raise errors.RadioError("Did not get initial response from radio")

        for addr in range(HF90_CONFIG_ADDR, limit, 16):
            self._upload_chunk(addr)

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr + 16 - HF90_CONFIG_ADDR
                status.max = limit - HF90_CONFIG_ADDR
                status.msg = "Uploading to radio"
                self.status_fn(status)

        self._send(b':00000001FF\r')

        resp = self._read(5)
        if resp != b'\r\n\r\n#':
            raise errors.RadioError("Did not get final response from radio")

        # Reset radio
        # self._send(b'E')

        self.pipe.timeout = timeout

    def process_mmap(self):
        self._memobj = bitwise.parse(HF90_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download(self._memsize)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        if self._memobj is None:
            self.process_mmap()

        highest_nonempty = None
        lowest_empty = None
        for i in range(self._lower, self._upper + 1):
            m = self.get_memory(i)
            if m.empty:
                if lowest_empty is None:
                    lowest_empty = i
            else:
                highest_nonempty = i
                msgs = self.validate_memory(m)
                if msgs:
                    raise Exception("Memory %d failed validation: %s" %
                                    (i, ", ".join(msgs)))

        if highest_nonempty is None:
            raise Exception("Cannot upload with no channels defined")
        if isinstance(self, EarlyHF90Radio):
            if lowest_empty is not None and lowest_empty < highest_nonempty:
                raise Exception(
                    "Cannot upload with gaps between defined channels")

        try:
            self._upload(self._memsize)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    @classmethod
    def match_model(cls, filedata, filename):
        return False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development."
                           "\nThere are no known issues with it, but you "
                           "should proceed with caution.\n")
        rp.pre_download = ("Follow these instructions to down/upload:\n"
                           "1. Turn off your radio.\n"
                           "2. Connect the serial interface cable.\n"
                           "3. Turn on your radio.\n"
                           "4. Hold down 'CHAN UP' and 'CHAN DOWN' buttons "
                           "until 'RS-232' is displayed.\n"
                           "5. Click OK to proceed.\n"
                           "6. After the process completes, cycle power on "
                           "the radio to exit RS-232 mode.\n"
                           "Please refer to the CHIRP wiki for information "
                           "about HF-90 serial port compatibility issues.\n")
        rp.pre_upload = rp.pre_download
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = False
        rf.has_nostep_tuning = True
        rf.has_settings = True
        rf.has_tuning_step = False
        rf.memory_bounds = (self._lower, self._upper)
        rf.valid_bands = self.BANDS
        rf.valid_cross_modes = []
        rf.valid_duplexes = list(self.DUPLEX)
        rf.valid_modes = list(self.MODES)
        rf.valid_skips = []
        rf.valid_tmodes = []
        rf.valid_tones = []
        # TODO how does one make the Tone column go away?
        return rf

    def apply_txpower(self, setting, obj):
        v = setting.value
        LOG.debug("apply_power: %s" % v)
        obj.tx_power = 3 * self.HF90_POWER_LEVELS.index(str(v))

    def apply_type(self, setting, obj):
        v = setting.value
        LOG.debug("apply_type: %s %d" % (v, obj.type))
        obj.type = self.HF90_TYPES.index(str(v))

    def apply_selcall_id(self, setting, obj):
        v = setting.value
        LOG.debug("apply_selcall_id: %s %x" % (v, obj.selcall_id))
        if isinstance(self, EarlyHF90Radio):
            # BCD, big endian, left aligned, "f" padded
            s = "%-4d" % int(v)
            s = s.replace(" ", "f")
        else:
            # BCD, big endian, right aligned, "0" padded
            s = "%04d" % int(v)
        obj.selcall_id = int(s[0:4], 16)

    def _get_selcall_id(self, _settings):
        s = "%04x" % _settings.selcall_id
        try:
            i = int(s.rstrip("f"))
        except ValueError:
            i = 9999
        return i

    def get_settings(self):
        _settings = self._memobj.settings

        LOG.debug("get_settings: %s %s" % (type(self), self.MODEL))

        grp = RadioSettingGroup("settings", "Settings")

        rs = RadioSetting("type", "Type",
                          RadioSettingValueList(
                              self.HF90_TYPES,
                              current_index=_settings.type))
        rs.set_apply_callback(self.apply_type, _settings)
        grp.append(rs)

        if isinstance(self, EarlyHF90Radio):
            rs = RadioSetting("selcall_id", "Selcall ID (0 for standard type)",
                              RadioSettingValueInteger(
                                  0, 9999,
                                  self._get_selcall_id(_settings)))
            rs.set_apply_callback(self.apply_selcall_id, _settings)
            grp.append(rs)
        else:
            rs = RadioSetting("selcall_id", "Selcall ID",
                              RadioSettingValueInteger(
                                  1, 9999,
                                  self._get_selcall_id(_settings)))
            rs.set_apply_callback(self.apply_selcall_id, _settings)
            grp.append(rs)

        rs = RadioSetting("f_p_program", "Front panel programming",
                          RadioSettingValueBoolean(_settings.f_p_program))
        grp.append(rs)

        rs = RadioSetting("auto_tune", "Auto tuning",
                          RadioSettingValueBoolean(_settings.auto_tune))
        grp.append(rs)

        rs = RadioSetting("mode_toggle", "Mode toggling",
                          RadioSettingValueBoolean(_settings.mode_toggle))
        grp.append(rs)

        hp = int(_settings.tx_power == 3)
        rs = RadioSetting("tx_power", "Tx Power",
                          RadioSettingValueList(self.HF90_POWER_LEVELS,
                                                current_index=hp))
        rs.set_apply_callback(self.apply_txpower, _settings)
        grp.append(rs)

        return RadioSettings(grp)

    def set_settings(self, uisettings):
        _settings = self._memobj.settings

        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue

            try:
                name = element.get_name()
                value = element.value

                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    setattr(_settings, name, value)

                LOG.debug("Setting %s: %s" % (name, value))
            except Exception:
                LOG.debug(element.get_name())
                raise

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        _rx = _mem.rx0_15 | (_mem.rx16_19 << 16)
        _tx = _mem.tx0_3 | (_mem.tx4_19 << 4)

        mem.empty = _rx == 0 or _mem.vnum == 0

        if not mem.empty:
            if (_tx == _rx) ^ _mem.tx_equals_rx:
                LOG.warn("get_memory(%d): tx_equals_rx incorrect" % number)
            if 0 < _rx * 100 < self._min_rx_freq:
                LOG.warn("get_memory(%d): rx frequency too low" % number)
            if _rx * 100 >= self._max_freq:
                LOG.warn("get_memory(%d): rx frequency too high" % number)
            if 0 < _tx * 100 < self._min_tx_freq:
                LOG.warn("get_memory(%d): tx frequency too low" % number)
            if _tx * 100 >= self._max_freq:
                LOG.warn("get_memory(%d): tx frequency too high" % number)

        mem.freq = int(_rx) * 100

        if _tx == 0:
            mem.duplex = "off"
            mem.offset = 0
        elif _tx > _rx:
            mem.duplex = "+"
            mem.offset = (int(_tx) - int(_rx)) * 100
        elif _tx < _rx:
            mem.duplex = "-"
            mem.offset = (int(_rx) - int(_tx)) * 100
        else:
            mem.duplex = ""
            mem.offset = 0

        if _mem.usb:
            mem.mode = "USB"
        else:
            mem.mode = "LSB"

        n = _mem.vnum & 0xff
        if n == 0:
            n = number

        rsg = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("vnum", "Number",
                          RadioSettingValueInteger(self._lower,
                                                   self._upper, n))
        rsg.append(rs)
        rs = RadioSetting("selcall", "Selcall",
                          RadioSettingValueBoolean(_mem.selcall))
        rsg.append(rs)
        rs = RadioSetting("scan", "Scan",
                          RadioSettingValueBoolean(_mem.scan))
        rsg.append(rs)
        mem.extra = rsg

        return mem

    def _get_tx_freq(self, mem):
        if mem.duplex == "":
            return mem.freq
        elif mem.duplex == "split":
            return mem.offset
        elif mem.duplex == "+":
            return mem.freq + mem.offset
        elif mem.duplex == "-":
            return mem.freq - mem.offset
        return 0

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        _mem.set_raw("\x00" * 8)

        if mem.empty:
            return

        rx = int(mem.freq / 100)
        tx = int(self._get_tx_freq(mem) / 100)

        _mem.tx_equals_rx = tx == rx

        _mem.rx0_15 = (rx >> 0) & 0xffff
        _mem.rx16_19 = (rx >> 16) & 0xf

        _mem.tx0_3 = (tx >> 0) & 0xf
        _mem.tx4_19 = (tx >> 4) & 0xffff

        _mem.usb = mem.mode == "USB"

        _mem.vnum = mem.number

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), int(setting.value))

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        if 0 < self._get_tx_freq(mem) < self._min_tx_freq:
            msgs.append(chirp_common.ValidationWarning(
                "tx frequency too low"))

        if mem.extra and isinstance(self, EarlyHF90Radio):
            if self._memobj.settings.selcall_id == 0x0fff:
                if mem.extra["scan"].value or mem.extra["selcall"].value:
                    msgs.append(chirp_common.ValidationWarning(
                        "standard type but scan or selcall enabled"))
            else:
                if mem.extra["scan"].value and not mem.extra["selcall"].value:
                    msgs.append(chirp_common.ValidationWarning(
                        "scan enabled but selcall disabled"))

        return msgs


# EarlyHF90Radio imitates version 2 of the dealer software whereas
# LateHF90Radio imitates version 3. It seems both are needed because
# version 3 warns that it is incompatible with firmware revisions below V301.
# Unfortunately, the author does not have access to the technical information
# required to better accommodate the quirks of the various firmware revisions.

@directory.register
class EarlyHF90Radio(HF90StyleRadio):
    """Base class for early HF-90 radios"""
    VARIANT = "v300 or earlier"
    _min_rx_freq = 2000000
    _min_tx_freq = 2000000
    _max_freq = 30000000
    BANDS = [(_min_rx_freq, _max_freq)]
    HF90_TYPES = ["HF-90A (Australia)", "HF-90E (Export)"]


@directory.register
class LateHF90Radio(HF90StyleRadio):
    """Base class for late HF-90 radios"""
    VARIANT = "v301 or later"
    _min_rx_freq = 500000
    _min_tx_freq = 1800000
    _max_freq = 30000000
    # band is split into two pieces to avoid unit test failures
    BANDS = [(_min_rx_freq, _min_tx_freq), (_min_tx_freq, _max_freq)]
    HF90_TYPES = ["Standard", "Advanced"]


if __name__ == "__main__":
    import sys
    import serial
    s = serial.Serial(port=sys.argv[1], baudrate=4800, timeout=0.1)
    reset_buffer(s)
    s.write(b"\r")
    print(s.read(32))
    print(s.out_waiting)
