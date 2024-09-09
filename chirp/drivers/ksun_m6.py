# Copyright 2012 Dan Smith <dsmith@danplanet.com>
# Copyright 2024 Yuri D'Elia <wavexx@thregr.org>
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

from chirp import chirp_common, directory, memmap, bitwise, errors
from chirp.settings import (
    RadioSetting, RadioSettings, RadioSettingGroup,
    RadioSettingValueBoolean, RadioSettingValueInteger, RadioSettingValueList
)
import struct

MEM_FORMAT = """
struct {
  u8 _unk1;
  u8 voice: 2,
     beep: 1,
     _unk2: 1,
     vox: 4;
  u8 led_timeout: 4,
     led: 2,
     _unk3: 2;
  u8 _unk4: 4,
     sq: 4;
  u8 _unk5: 2,
     tot: 6;
  u8 _unk6: 4,
     lock_timeout: 4;
  u8 _unk7: 1,
     channel: 7;
  u8 _unk8: 5,
     bat_save: 3;
  u8 _unk9[2];
  u8 pass[6];
} settings;

struct {
  u8 freq[5]; // 20 bit rx + 20 bit tx
  u16 low_pwr: 1,
      no_tx: 1,
      rx_tone: 2,
      rx_code: 12;
  u16 nfm: 1,
      skip: 1,
      tx_tone: 2,
      tx_code: 12;
  u8 compander: 2, // only 0b00/0b01 allowed
     hopping: 2, // only 0b00/0b01 allowed
     scrambler: 4;
} memory[80];
"""

VOICE_LIST = ["off", "Chinese", "English"]
SCRAMBLER_LIST = ["off", "1", "2", "3", "4", "5", "6", "7", "8"]
LED_LIST = ["Low", "Medium", "High"]
BAT_SAVE_LIST = ["off", "1:1", "1:2", "1:3", "1:4"]
TONE_LIST = ["Tone", "DTCS_N", "DTCS_I", ""]
LED_TIMEOUT_LIST = ["Continuous", "5", "10", "15", "20", "25", "30",
                    "35", "40", "45", "50", "55", "60"]
LOCK_TIMEOUT_LIST = ["off", "5", "10", "15", "20", "25", "30",
                     "35", "40", "45", "50", "55", "60"]
TOT_LIST = ["off", "15", "30", "45", "60", "75", "90",
            "105", "120", "135", "150", "165", "180", "195",
            "210", "225", "240", "255", "270", "285",
            "300", "315", "330", "345", "360", "375", "390",
            "405", "420", "435", "450", "465", "480", "495",
            "510", "525", "540", "555", "570", "585", "600"]
POWER_LIST = [chirp_common.PowerLevel("High", watts=2.00),
              chirp_common.PowerLevel("Low",  watts=0.50)]


def _checksum(data):
    cs = 2
    for byte in data:
        cs += byte
    return cs % 256


def enter_programming_mode(radio):
    serial = radio.pipe

    cmd = b"\x32\x31\x05\x10"
    req = cmd + bytes([_checksum(cmd)])

    try:
        serial.write(req)
        res = serial.read(1)
        if res != b"\x06":
            raise Exception("invalid response")
    except Exception as e:
        msg = "Radio refused to enter programming mode: %s" % str(e)
        raise errors.RadioError(msg)


def exit_programming_mode(radio):
    serial = radio.pipe

    cmd = b"\x32\x31\x05\xee"
    req = cmd + bytes([_checksum(cmd)])

    try:
        # there is no response from this command as the radio resets
        serial.write(req)
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr):
    serial = radio.pipe

    cmd = struct.pack(">cH", b"R", block_addr)
    req = cmd + bytes([_checksum(cmd)])

    try:
        serial.write(req)
        res_len = len(cmd) + radio.BLOCK_SIZE + 1
        res = serial.read(res_len)

        if len(res) != res_len or res[:len(cmd)] != cmd:
            raise Exception("unexpected reply!")
        if res[-1] != _checksum(res[:-1]):
            raise Exception("block failed checksum!")

        block_data = res[len(cmd):-1]
    except Exception as e:
        msg = "Failed to read block at %04x: %s" % (block_addr, str(e))
        raise errors.RadioError(msg)

    return block_data


def _write_block(radio, block_addr, block_data):
    serial = radio.pipe

    cmd = struct.pack(">cH", b"W", block_addr) + block_data
    req = cmd + bytes([_checksum(cmd)])

    try:
        serial.write(req)
        res = serial.read(1)
        if res != b"\x06":
            raise Exception("unexpected reply!")
    except Exception as e:
        msg = "Failed to write block at %04x: %s" % (block_addr, str(e))
        raise errors.RadioError(msg)


def verify_model(radio):
    # Simply rely on the protocol/checksum to validate the radio model
    # for now: attempt at least twice, so that garbage in the line is
    # ignored on the first tries
    for _ in range(3):
        try:
            _read_block(radio, radio.START_ADDR)
            return
        except Exception:
            pass

    raise errors.RadioError("Could not communicate with the radio")


def do_download(radio):
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.max = radio._memsize

    verify_model(radio)

    data = b""
    for addr in range(radio.START_ADDR,
                      radio.START_ADDR + radio._memsize,
                      radio.BLOCK_SIZE):
        status.cur = addr
        radio.status_fn(status)

        block = _read_block(radio, addr)
        data += block

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    verify_model(radio)
    enter_programming_mode(radio)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.max = radio._memsize
    mmap = radio.get_mmap()

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr
        radio.status_fn(status)

        block = mmap[addr:addr + radio.BLOCK_SIZE]
        _write_block(radio, radio.START_ADDR + addr, block)

    exit_programming_mode(radio)


def mem_to_triplet(mem_tone, mem_code):
    mem_tone = TONE_LIST[mem_tone]
    if mem_tone == "Tone":
        mode = "Tone"
        code = mem_code / 10
        polarity = None
    elif mem_tone in ["DTCS_N", "DTCS_I"]:
        mode = "DTCS"
        code = int("%o" % mem_code)
        polarity = "N" if mem_tone == "DTCS_N" else "R"
    else:
        mode = None
        code = None
        polarity = None
    return (mode, code, polarity)


def triplet_to_mem(tone):
    mode, code, polarity = tone
    if mode == "Tone":
        mem_tone = "Tone"
        mem_code = int(code * 10)
    elif mode == "DTCS":
        mem_tone = "DTCS_N" if polarity == "N" else "DTCS_I"
        mem_code = int('%i' % code, 8)
    else:
        mem_tone = ""
        mem_code = 0
    mem_tone = TONE_LIST.index(mem_tone)
    return (mem_tone, mem_code)


@directory.register
class KSunM6Radio(chirp_common.CloneModeRadio):
    VENDOR = "KSUN"
    MODEL = "M6"
    BAUD_RATE = 4800
    BLOCK_SIZE = 0x10
    START_ADDR = 0x0050
    CHANNELS = 80
    _memsize = BLOCK_SIZE + 10 * CHANNELS

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_name = False
        rf.has_settings = True
        rf.memory_bounds = (1, self.CHANNELS)

        rf.can_odd_split = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_duplexes = ["", "split", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS", "Tone->DTCS",
                                "DTCS->Tone", "->Tone", "DTCS->DTCS"]

        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.valid_bands = [(400000000, 480000000)]

        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LIST

        return rf

    def get_settings(self):
        settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        voice = settings.voice
        rsv = RadioSettingValueList(VOICE_LIST, current_index=voice)
        rs = RadioSetting("voice", "Voice language", rsv)
        basic.append(rs)

        led = settings.led
        rsv = RadioSettingValueList(LED_LIST, current_index=led)
        rs = RadioSetting("led", "LED brightness", rsv)
        basic.append(rs)

        led_timeout = settings.led_timeout
        rsv = RadioSettingValueList(LED_TIMEOUT_LIST,
                                    current_index=led_timeout)
        rs = RadioSetting("led_timeout", "LED timeout", rsv)
        basic.append(rs)

        lock_timeout = settings.lock_timeout
        rsv = RadioSettingValueList(LOCK_TIMEOUT_LIST,
                                    current_index=lock_timeout)
        rs = RadioSetting("lock_timeout", "Key Lock timeout", rsv)
        basic.append(rs)

        tot = settings.tot
        rsv = RadioSettingValueList(TOT_LIST, current_index=tot)
        rs = RadioSetting("tot", "Time-Out Timer", rsv)
        basic.append(rs)

        bat_save = settings.bat_save
        rsv = RadioSettingValueList(BAT_SAVE_LIST, current_index=bat_save)
        rs = RadioSetting("bat_save", "Battery Save", rsv)
        basic.append(rs)

        rsv = RadioSettingValueInteger(0, 9, settings.sq)
        rs = RadioSetting("sq", "Squelch Level", rsv)
        basic.append(rs)

        rsv = RadioSettingValueInteger(0, 9, settings.vox)
        rs = RadioSetting("vox", "VOX Level", rsv)
        basic.append(rs)

        rsv = RadioSettingValueBoolean(settings.beep)
        rs = RadioSetting("beep", "Beep", rsv)
        basic.append(rs)

        channel = settings.channel + 1
        rsv = RadioSettingValueInteger(1, self.CHANNELS, channel)
        rs = RadioSetting("channel", "Current Channel", rsv)
        basic.append(rs)

        return top

    def set_settings(self, settings):
        settings = settings[0]
        _settings = self._memobj.settings
        _settings.voice = VOICE_LIST.index(settings["voice"].value.get_value())
        _settings.led = LED_LIST.index(settings["led"].value.get_value())
        _settings.led_timeout = LED_TIMEOUT_LIST.index(
            settings["led_timeout"].value.get_value())
        _settings.lock_timeout = LOCK_TIMEOUT_LIST.index(
            settings["lock_timeout"].value.get_value())
        _settings.tot = TOT_LIST.index(settings["tot"].value.get_value())
        _settings.bat_save = BAT_SAVE_LIST.index(
            settings["bat_save"].value.get_value())
        _settings.sq = settings["sq"].value.get_value()
        _settings.vox = settings["vox"].value.get_value()
        _settings.beep = settings["beep"].value.get_value()
        _settings.channel = settings["channel"].value.get_value() - 1

    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.freq.get_raw() == bytes([255] * 5):
            mem.empty = True
        else:
            rx_freq = ((_mem.freq[0] << 12)
                       + (_mem.freq[1] << 4) + (_mem.freq[2] >> 4))
            tx_freq = (((_mem.freq[2] & 0xF) << 16)
                       + (_mem.freq[3] << 8) + _mem.freq[4])

            mem.freq = rx_freq * 1000000 // 2000
            mem.offset = tx_freq * 1000000 // 2000

            if _mem.no_tx:
                mem.duplex = "off"
            elif rx_freq != tx_freq:
                mem.duplex = "split"

            chirp_common.split_tone_decode(
                mem,
                mem_to_triplet(_mem.tx_tone, _mem.tx_code),
                mem_to_triplet(_mem.rx_tone, _mem.rx_code))

        mem.mode = "NFM" if not mem.empty and _mem.nfm else "FM"
        mem.power = POWER_LIST[int(not mem.empty and _mem.low_pwr)]
        mem.skip = "S" if not mem.empty and _mem.skip else ""

        mem.extra = RadioSettingGroup("Extra", "extra")

        hopping = False if mem.empty else _mem.hopping
        rsv = RadioSettingValueBoolean(hopping)
        rs = RadioSetting("hopping", "Hopping", rsv)
        mem.extra.append(rs)

        compander = False if mem.empty else _mem.compander
        rsv = RadioSettingValueBoolean(compander)
        rs = RadioSetting("compander", "Compander", rsv)
        mem.extra.append(rs)

        scrambler = False if mem.empty else _mem.scrambler
        rsv = RadioSettingValueList(SCRAMBLER_LIST, current_index=scrambler)
        rs = RadioSetting("scrambler", _("Scrambler"), rsv)
        mem.extra.append(rs)

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]

        if mem.empty:
            _mem.fill_raw(b"\xff")
        else:
            rx_freq = mem.freq
            if mem.duplex == "split" and mem.offset:
                tx_freq = mem.offset
            else:
                tx_freq = rx_freq

            rx_freq = round(rx_freq / 1000000 * 2000)
            tx_freq = round(tx_freq / 1000000 * 2000)

            _mem.freq[0] = (rx_freq >> 12) & 0xff
            _mem.freq[1] = (rx_freq >> 4) & 0xff
            _mem.freq[2] = ((rx_freq << 4) & 0xf0) | ((tx_freq >> 16) & 0x0f)
            _mem.freq[3] = (tx_freq >> 8) & 0xff
            _mem.freq[4] = (tx_freq) & 0xff

            tx_tone, rx_tone = chirp_common.split_tone_encode(mem)
            _mem.tx_tone, _mem.tx_code = triplet_to_mem(tx_tone)
            _mem.rx_tone, _mem.rx_code = triplet_to_mem(rx_tone)

            _mem.no_tx = (mem.duplex == "off")
            _mem.nfm = (mem.mode == "NFM")
            _mem.skip = (mem.skip == "S")

            if mem.power in POWER_LIST:
                _mem.low_pwr = POWER_LIST.index(mem.power)
            else:
                _mem.low_pwr = False

            if "hopping" in mem.extra:
                _mem.hopping = mem.extra["hopping"].value.get_value()
            else:
                _mem.hopping = False

            if "compander" in mem.extra:
                _mem.compander = mem.extra["compander"].value.get_value()
            else:
                _mem.compander = False

            if "scrambler" in mem.extra:
                _mem.scrambler = SCRAMBLER_LIST.index(
                    mem.extra["scrambler"].value.get_value())
            else:
                _mem.scrambler = 0
