# Copyright 2025 Paul Oberosler <paul@paulober.dev>
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
from chirp import bitwise, chirp_common, directory, errors, memmap, util
from chirp.settings import (
    RadioSetting,
    RadioSettings,
    RadioSettingGroup,
    RadioSettingValueBoolean,
    RadioSettingValueList,
    RadioSettingValueInteger,
    RadioSettingValueString
)


LOG = logging.getLogger(__name__)

COMMAND_ACCEPT = b"\x06"
CHARSET_HEX = "0123456789ABCDEFabcdef"


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = 1  # 1000ms

    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _recv(radio, addr, length):
    """Get data from the radio """
    hdr = radio.pipe.read(4)  # Read 4 byte header
    if not hdr:
        raise errors.RadioNoContactLikelyK1()
    data = radio.pipe.read(length)  # Read the data
    if not data:
        raise errors.RadioNoContactLikelyK1()

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, resp_length = struct.unpack(">BHB", hdr)
    if a != int.from_bytes(addr, byteorder="big") \
            or resp_length != length or c != ord("W"):
        LOG.error("Invalid answer for block 0x%04s:" % util.hexprint(addr))
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, resp_length))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _enter_programming_mode(radio):
    _clean_buffer(radio)

    radio.pipe.write(radio._magic)
    LOG.debug("Sent magic sequence")
    ack = radio.pipe.read(2)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    LOG.debug("Received magic sequence response")
    if len(ack) != 2 or ack[1:2] != COMMAND_ACCEPT:
        if ack:
            LOG.error("Received: Len=%i Data=%s"
                      % (len(ack), util.hexprint(ack)))
        raise errors.RadioError("Radio refused to enter programming mode")

    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(radio._magic_response_length)
    if not ident:
        raise errors.RadioNoContactLikelyK1()
    elif not ident.startswith(radio._fingerprint):
        raise errors.RadioError("Radio returned unknown identification string")

    LOG.info("Radio entered programming mode")
    LOG.debug("Radio identification: %s" % util.hexprint(ident))

    radio.pipe.write(COMMAND_ACCEPT)
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    elif ack != COMMAND_ACCEPT:
        if ack:
            LOG.error("Got %s" % util.hexprint(ack))
        raise errors.RadioError("Radio refused to enter programming mode")

    return ident


def _exit_programming_mode(radio):
    try:
        radio.pipe.write(b"\x45")
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _get_memory_address(channel_id):
    block = (channel_id - 1) // 16           # Determines high byte
    offset = ((channel_id - 1) % 16) * 0x10  # Determines low byte

    return (block, offset)


def _read_block(radio, channel_id):
    address = bytes(_get_memory_address(channel_id))
    # 52=read | 20 = hex(32 bytes) = length of 2 channels
    # + settings without header
    cmd = struct.pack(">BBBB", 0x52, address[0], address[1], 0x20)

    radio.pipe.write(cmd)
    data = _recv(radio, address, 32)

    # Sending an accept after reading the first line will crash
    # the communication. The accept is sent when entering programming
    # mdoe, so before reading the first block
    if address != b"\x00\x00":
        radio.pipe.write(COMMAND_ACCEPT)
        response = radio.pipe.read(1)
        if not response:
            raise errors.RadioNoContactLikelyK1()
        elif response != COMMAND_ACCEPT:
            raise errors.RadioError("Radio refused to read block at %04s"
                                    % util.hexprint(address))

    return data


def _write_block(radio, channel_id, data):
    address = bytes(_get_memory_address(channel_id))
    cmd = struct.pack(">BBBB", 0x57, address[0], address[1], 0x10) + data

    radio.pipe.write(cmd)
    response = radio.pipe.read(1)
    if not response:
        raise errors.RadioNoContactLikelyK1()
    elif response != COMMAND_ACCEPT:
        raise errors.RadioError("Radio refused to write block at %04s"
                                % util.hexprint(address))


def do_download(radio):
    """Expects caller to exit programming mode"""

    LOG.debug("Downloading data from radio")

    status = chirp_common.Status()
    status.msg = "Downloading from radio"

    status.cur = 0
    status.max = radio._upper
    radio.status_fn(status)

    data = bytearray()

    _enter_programming_mode(radio)
    for i in range(1, radio.MEM_ROWS, 2):
        status.cur = i
        radio.status_fn(status)

        result = _read_block(radio, i)
        data.extend(result)

        LOG.debug("Downloaded memory channel %i" % i)

    LOG.debug("Downloaded %i bytes of data" % len(data))

    return bytes(data)


def do_upload(radio):
    """Expects caller to exit programming mode"""

    LOG.debug("Uploading data to radio")
    _enter_programming_mode(radio)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    status.cur = 0
    status.max = radio._upper
    radio.status_fn(status)

    radio_mem = radio.get_mmap()
    for i in range(1, radio.MEM_ROWS, 1):
        status.cur = i
        radio.status_fn(status)

        block_offset = (i - 1) * radio.BLOCK_SIZE
        block = radio_mem[block_offset:block_offset + radio.BLOCK_SIZE]
        _write_block(radio, i, block)

        LOG.debug("Uploaded memory channel %i" % i)


DTCS_BYTE_LOOKUP_LOW = {
    0x13: 0, 0x15: 1, 0x16: 2, 0x19: 3, 0x1A: 4, 0x1E: 5,
    0x23: 6, 0x27: 7, 0x29: 8, 0x2B: 9, 0x2C: 10, 0x35: 11,
    0x39: 12, 0x3A: 13, 0x3B: 14, 0x3C: 15, 0x4C: 16, 0x4D: 17,
    0x4E: 18, 0x52: 19, 0x55: 20, 0x59: 21, 0x5A: 22, 0x5C: 23,
    0x63: 24, 0x65: 25, 0x6A: 26, 0x6D: 27, 0x6E: 28, 0x72: 29,
    0x75: 30, 0x7A: 31, 0x7C: 32, 0x85: 33, 0x8A: 34, 0x93: 35,
    0x95: 36, 0x96: 37, 0xA3: 38, 0xA4: 39, 0xA5: 40, 0xA6: 41,
    0xA9: 42, 0xAA: 43, 0xAD: 44, 0xB1: 45, 0xB3: 46, 0xB5: 47,
    0xB6: 48, 0xB9: 49, 0xBC: 50, 0xC6: 51, 0xC9: 52, 0xCD: 53,
    0xD5: 54, 0xD9: 55, 0xDA: 56, 0xE3: 57, 0xE6: 58, 0xE9: 59,
    0xEE: 60, 0xF4: 61, 0xF5: 62, 0xF9: 63
}

DTCS_BYTE_LOOKUP_HIGH = {
    0x09: 64, 0x0A: 65, 0x0B: 66, 0x13: 67, 0x19: 68, 0x1A: 69,
    0x25: 70, 0x26: 71, 0x2A: 72, 0x2C: 73, 0x2D: 74, 0x32: 75,
    0x34: 76, 0x35: 77, 0x36: 78, 0x43: 79, 0x46: 80, 0x4E: 81,
    0x53: 82, 0x56: 83, 0x5A: 84, 0x66: 85, 0x75: 86, 0x86: 87,
    0x8A: 88, 0x94: 89, 0x97: 90, 0x99: 91, 0x9A: 92, 0xA5: 93,
    0xAC: 94, 0xB2: 95, 0xB4: 96, 0xC3: 97, 0xCA: 98, 0xD3: 99,
    0xD9: 100, 0xDA: 101, 0xDC: 102, 0xE3: 103, 0xEC: 104,
}


# Reverse lookup for encoding
INDEX_TO_DTCS_BYTE_LOW = {v: k for k, v in DTCS_BYTE_LOOKUP_LOW.items()}
INDEX_TO_DTCS_BYTE_HIGH = {v: k for k, v in DTCS_BYTE_LOOKUP_HIGH.items()}


def _decode_dtcs_byte(byte: int, level: int) -> int:
    """
    Translates a DTCS byte to an index (starting from 0).

    :param byte: The first byte of the DTCS value.
    :param level: The DTCS level / second byte (0x28 or 0x29).
    :return: The corresponding index (0-based) or -1 if not found.
    """
    if level == 0x28 or level == 0xA8:
        return DTCS_BYTE_LOOKUP_LOW.get(byte, -1)
    elif level == 0x29 or level == 0xA9:
        return DTCS_BYTE_LOOKUP_HIGH.get(byte, -1)
    else:
        return -1


def _encode_dtcs_byte(index: int) -> int:
    """
    Translates an index back to a DTCS first byte.

    :param index: The index to look up.
    :return: The corresponding DTCS first byte, or 0xFF if not found.
    """
    if index <= 63:
        return INDEX_TO_DTCS_BYTE_LOW.get(index, 0xFF)
    elif index <= 104:
        return INDEX_TO_DTCS_BYTE_HIGH.get(index, 0xFF)
    else:
        return 0xFF


@directory.register
class Radtel493Radio(chirp_common.CloneModeRadio):
    """Acme Template"""
    VENDOR = "Radtel"
    MODEL = "RT-493"
    BAUD_RATE = 9600

    # All new drivers should be "Byte Clean" so leave this in place.

    # sometimes second last bute is 06 sometimes 05
    _fingerprint = b"\x50\x33\x32\x30\x37\x33"  # + \x05\xff or + \x06\xff
    _magic = b"\x50\x48\x4f\x47\x52\x89\x83"
    _magic_response_length = 8
    _upper = 199

    BLOCK_SIZE = 16
    MEM_ROWS = 256

    # NOTE: wats are randomly chosen for now to allow comparison
    POWER_LEVELS = [
        chirp_common.PowerLevel("High", watts=10.0),
        chirp_common.PowerLevel("Low", watts=5.0),
    ]

    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

    MEM_FORMAT = """
    struct {
        lbcd rxfreq[4];         // RX Frequency (BCD format)
        lbcd txfreq[4];         // TX Frequency (BCD format)
        ul16 rxtone;            // RX Tone (CTCSS/DCS) - 0xFFFF if OFF
        ul16 txtone;            // TX Tone (CTCSS/DCS) - 0xFFFF if OFF
        u8 compander:1,         // Compander (1=ON, 0=OFF)
           special_qt_dqt:2,    // Special QT/DQT (00=OFF, 01=A, 10=B)
           wn_mode:1,           // Wide/Narrow mode (1=Wide, 0=Narrow)
           unknown1:1,          // Unknown bit
           scramble:3;          // Scramble mode (0-7, 0 = OFF)
        u8 global1;             // Global settings byte 1 (varies per channel)
        u8 global2;             // Global settings byte 2
        u8 global3;             // Global settings byte 3
    } memory[199];

    struct {
        ul32 special_code[4];   // Special Codes for 4 channels per row
    } special_codes[50];        // Covers 199 channels (50 * 4 = 200,
                                //               last ignored / unused)

    struct {
        u8 scan_add1[16];       // "Scan Add" settings for channels 1-128
        u8 scan_add2[16];       // "Scan Add" settings for channels 129-199
    } scan_add_settings;

    struct {
        u8 learn_code1[16];     // "Learn Code" settings for channels 1-128
        u8 learn_code2[16];     // "Learn Code" settings for channels 129-199
    } learn_code_settings;

    struct {
        u8 power_level1[16];    // Power level settings (1-128)
        u8 power_level2[16];    // Power level settings (129-199)
    } power_settings;

    u8 unknown1[16];            // Unknown data
    u8 unknown2[16];            // Unknown data
    """

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_rx_dtcs = True
        rf.has_dtcs = True
        rf.has_ctone = True
        rf.has_dtcs_polarity = True
        rf.has_name = False
        rf.can_odd_split = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_variable_power = False
        rf.has_offset = True
        rf.has_mode = False

        rf.valid_modes = ["NFM", "WFM"]
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS",
            # "Tone->"
        ]
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (1, 199)
        # TODO: maybe limit to EU version (430000000, 440000000)
        rf.valid_bands = [(400000000, 470000000)]
        return rf

    def _decode_qt_dqt(self, qt_bytes):
        assert len(qt_bytes) == 2

        value = int.from_bytes(qt_bytes, "little")
        byte1 = qt_bytes[0]
        byte2 = qt_bytes[1]

        if value == 0xFFFF or value == 0x0000:
            return None, None, None
        elif byte2 <= 9:
            if value / 10 in chirp_common.TONES:
                return "Tone", value / 10, None
            else:
                raise ValueError("Invalid tone value: %i" % value)

        # DTCS Normal Polarity (DxxxN) and DTCS Inverted Polarity (DxxxI)
        dtcs_code_idx = _decode_dtcs_byte(byte1, byte2)
        assert dtcs_code_idx != -1
        dtcs_polarity = "N" if byte2 == 0x28 or byte2 == 0x29 else "R"
        if 0 <= dtcs_code_idx <= len(self.DTCS_CODES) - 1:
            return "DTCS", self.DTCS_CODES[dtcs_code_idx], dtcs_polarity
        else:
            return None, None, None

    def get_scan_add_status(self, channel):
        """
        Get the Scan Add setting for a given channel number.

        Args:
            channel (int): The channel number (1-199).

        Returns:
            True -> If the channel is included in the scan list.
            False -> If the channel is excluded from the scan list.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        raw_bytes = self._memobj.scan_add_settings.get_raw()

        # Each byte represents 8 channels, find the correct byte and bit
        byte_index = (channel - 1) // 8
        bit_index = (channel - 1) % 8

        # Check if the bit for the channel is set (1 = Add, 0 = Del)
        return bool(raw_bytes[byte_index] & (1 << bit_index))

    def set_scan_add_status(self, channel, status):
        """
        Set the Scan Add setting for a given channel number.

        Args:
            channel (int): The channel number (1-199).
            status (bool): "Add" to include in scan list, "Del"
            to remove from scan list.

        Raises:
            ValueError: If channel is out of range.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        # Fetch current scan add settings as raw bytes
        scan_add_data = self._memobj.scan_add_settings
        raw_bytes = bytearray(scan_add_data.get_raw())

        # Determine byte and bit position
        byte_index = (channel - 1) // 8
        bit_index = (channel - 1) % 8

        # Modify the bit based on the status
        if status:
            raw_bytes[byte_index] |= (1 << bit_index)  # Set bit to 1
        else:
            raw_bytes[byte_index] &= ~(1 << bit_index)  # Clear bit to 0

        # Apply the new settings back to memory
        scan_add_data.set_raw(bytes(raw_bytes))

    def get_learn_code_status(self, channel):
        """
        Get the Learn Code setting for a given channel number.

        Returns:
            True -> If Learn Code is enabled.
            False -> If Learn Code is disabled.

        Raises:
            ValueError: If channel is out of range.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        # Get Learn Code memory
        raw_bytes = self._memobj.learn_code_settings.get_raw()

        # Calculate byte and bit index
        byte_index = (channel - 1) // 8
        bit_index = (channel - 1) % 8

        # Extract the relevant bit
        return bool(raw_bytes[byte_index] & (1 << bit_index))

    def set_learn_code_status(self, channel, status):
        """
        Set the Learn Code setting for a given channel number.

        Args:
            channel (int): The channel number (1-199).
            status (bool): True="ON" to enable Learn Code,
                           False="OFF" to disable.

        Raises:
            ValueError: If channel is out of range.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        # Fetch Learn Code settings as raw bytes
        learn_code_data = self._memobj.learn_code_settings
        raw_bytes = bytearray(learn_code_data.get_raw())

        # Determine byte and bit position
        byte_index = (channel - 1) // 8
        bit_index = (channel - 1) % 8

        # Modify the bit based on the status
        if status:
            raw_bytes[byte_index] |= (1 << bit_index)  # Set bit to 1
        else:
            raw_bytes[byte_index] &= ~(1 << bit_index)  # Clear bit to 0

        # Apply the new settings back to memory
        learn_code_data.set_raw(bytes(raw_bytes))

    def get_power_level(self, channel: int):
        """Get the power level setting for a given channel.
        (True = High, False = Low)"""
        if not (1 <= channel <= 199):
            raise ValueError("Channel must be between 1 and 199")

        index = (channel - 1) // 8
        bit_pos = (channel - 1) % 8

        raw_bytes = self._memobj.power_settings.get_raw()

        return bool((raw_bytes[index] & (1 << bit_pos)))

    def set_power_level(self, channel: int, level: bool):
        """Set the power level for a given channel
        (True='High' or False='Low')."""
        if not (1 <= channel <= 199):
            raise ValueError("Channel must be between 1 and 199")

        index = (channel - 1) // 8
        bit_pos = (channel - 1) % 8

        if channel <= 128:
            current_byte = self._memobj.power_settings.power_level1[index]
        else:
            current_byte = self._memobj.power_settings \
                .power_level2[index - 16]

        # Modify the bit
        if level:
            new_byte = current_byte | (1 << bit_pos)  # Set bit
        else:
            new_byte = current_byte & ~(1 << bit_pos)  # Clear bit

        # Write back the new byte
        if channel <= 128:
            self._memobj.power_settings.power_level1[index] = new_byte
        else:
            self._memobj.power_settings.power_level2[index - 16] = new_byte

    def decode_mem_blob(self, _mem, mem):
        if _mem.rxfreq[0].get_raw() == b'\xff' \
                or _mem.rxfreq[3].get_raw() == b'\x00':
            mem.empty = True
            return

        mem.freq = int(_mem.rxfreq) * 10
        chirp_common.split_to_offset(mem, int(_mem.rxfreq), int(_mem.txfreq))
        txtone = self._decode_qt_dqt(_mem.txtone.get_raw())
        rxtone = self._decode_qt_dqt(_mem.rxtone.get_raw())
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # main_settings_byte = _mem.settings.get_raw()
        # main_settings = _decode_channel_settings(main_settings_byte)
        mem.mode = "WFM" if int(_mem.wn_mode) else "NFM"

        power_level = self.get_power_level(mem.number)
        mem.power = self.POWER_LEVELS[0 if power_level else 1]

        scan_add = self.get_scan_add_status(mem.number)
        if not scan_add:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting(
            "Compander", "Compander",
            RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting(
            "Scramble Mode", "Scramble Mode",
            RadioSettingValueList(
                ["OFF", "1", "2", "3", "4", "5", "6", "7"],
                current_index=_mem.scramble
            ))
        mem.extra.append(rs)

        rs = RadioSetting(
            "Special QT/DQT", "Special QT/DQT",
            RadioSettingValueList(
                ["OFF", "A", "B"],
                current_index=0 if _mem.special_qt_dqt == 0x00
                else (1 if _mem.special_qt_dqt == 0x01 else 2)
            ))
        mem.extra.append(rs)

        LOG.debug("WN Mode: %i, Compander: %i, Scramble: %i, Special QT/DQT: \
                  %i" % (int(_mem.wn_mode), int(_mem.compander),
                         int(_mem.scramble), int(_mem.special_qt_dqt)))

        learn_code = self.get_learn_code_status(mem.number)
        rs = RadioSetting(
            "Learn Code", "Learn Code",
            RadioSettingValueBoolean(learn_code))
        mem.extra.append(rs)

        special_code = self.get_special_code(mem.number)
        rs = RadioSetting(
            "Special Code", "Special Code",
            RadioSettingValueString(
                8, 8, special_code, True, CHARSET_HEX, "0"))
        mem.extra.append(rs)

    def get_memory(self, number):
        if number <= 0 or number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 1 and %i (included)" % self._upper)

        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number

        self.decode_mem_blob(_mem, mem)

        return mem

    def _encode_qt_dqt(self, tone_mode, tone_value=None, tone_polarity=None):
        if tone_mode == "Tone" or tone_mode == "TSQL":
            assert tone_value is not None
            return int(tone_value * 10).to_bytes(2, "little")  # Encode as Hz

        elif tone_mode == "DTCS":
            assert tone_value is not None
            if tone_polarity not in ("N", "R"):
                raise ValueError("Invalid DTCS polarity. Must be 'N' or 'R'.")
            dtcs_idx = self.DTCS_CODES.index(tone_value)
            dtcs_code = _encode_dtcs_byte(dtcs_idx)
            dtcs_polarity_bit = (0x28 if dtcs_idx <= 63 else 0x29) \
                if tone_polarity == "N" else (
                0xA8 if dtcs_idx <= 63 else 0xA9)
            return bytes([dtcs_code, dtcs_polarity_bit])  # Encode

        else:
            return b"\xFF\xFF"

    def encode_mem_blob(self, mem, _mem):
        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = _mem.rxfreq

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)

        tx_value = self._encode_qt_dqt(txmode, txtone, txpol)
        rx_value = self._encode_qt_dqt(rxmode, rxtone, rxpol)

        _mem.rxtone.set_raw(rx_value)
        _mem.txtone.set_raw(tx_value)

        # maybe they have been edited while mem was in UI
        memraw = self._memobj.memory[mem.number - 1]
        global1 = memraw.global1.get_raw()
        global2 = memraw.global2.get_raw()
        global3 = memraw.global3.get_raw()

        learn_code = False
        special_code = "FF" * 4
        for setting in mem.extra:
            if setting.get_name() == "Compander":
                _mem.compander = int(setting.value)
            elif setting.get_name() == "Scramble Mode":
                _mem.scramble = int(setting.value) if str(
                    setting.value) != "OFF" else 0
            elif setting.get_name() == "Special QT/DQT":
                _mem.special_qt_dqt = [0x00, 0x01, 0x10][int(setting.value)]
            elif setting.get_name() == "Learn Code":
                learn_code = bool(setting.value)
            elif setting.get_name() == "Special Code":
                special_code = str(setting.value)

        _mem.wn_mode = 1 if mem.mode == "Wide" else 0

        _mem.global1.set_raw(global1)
        _mem.global2.set_raw(global2)
        _mem.global3.set_raw(global3)

        # Settings that are indepently stored from the memory channel
        self.set_scan_add_status(mem.number, mem.skip != "S")
        self.set_learn_code_status(mem.number, learn_code)
        self.set_power_level(mem.number, mem.power == self.POWER_LEVELS[0])
        self.set_special_code(mem.number, special_code)

    def get_special_code(self, channel):
        """
        Get the special code for a given channel.

        Args:
            channel (int): The channel number (1-199).

        Returns:
            str: The special code (8 characters long).
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        special_code = self._memobj.special_codes[(channel - 1) // 4] \
            .special_code[(channel - 1) % 4].get_raw()
        return special_code.hex().upper()

    def set_special_code(self, channel, code):
        """
        Set the special code for a given channel.

        Args:
            channel (int): The channel number (1-199).
            code (str): The special code (8 characters long).

        Raises:
            ValueError: If channel is out of range or code is
            not 8 characters long.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        if len(code) != 8:
            raise ValueError("Special code must be exactly 8 characters long")

        # Get the special code memory
        special_code = self._memobj.special_codes[(channel - 1) // 4] \
            .special_code[(channel - 1) % 4]
        special_code.set_raw(bytes.fromhex(code))

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xff" * 16)
            # Also reset all externally stored settings
            self.set_power_level(mem.number, False)
            self.set_scan_add_status(mem.number, False)
            self.set_learn_code_status(mem.number, False)
            self.set_special_code(mem.number, "FF" * 4)
            return

        self.encode_mem_blob(mem, _mem)

    def _get_bool(self, setting):
        if setting == "BATS":
            byte1 = self._memobj.memory[3-1].global1.get_raw()

            return bool(int.from_bytes(byte1, byteorder="big") & 0x08)
        elif setting == "BEEP":
            byte1 = self._memobj.memory[3-1].global1.get_raw()

            return bool(int.from_bytes(byte1, byteorder="big") & 0x04)
        elif setting == "WARN":
            byte1 = self._memobj.memory[7-1].global1.get_raw()

            return bool(int.from_bytes(byte1, byteorder="big") & 0x01)
        elif setting == "SCAN":
            byte2 = self._memobj.memory[7-1].global2.get_raw()

            return bool(int.from_bytes(byte2, byteorder="big") & 0x01)
        elif setting == "CPYC":
            byte1 = self._memobj.memory[6-1].global3.get_raw()

            return bool(int.from_bytes(byte1, byteorder="big") & 0x01)
        elif setting == "VOXF":
            byte1 = self._memobj.memory[4-1].global1.get_raw()

            return bool(int.from_bytes(byte1, byteorder="big") & 0x01)

    def _set_bool(self, setting, value):
        if setting == "BATS":
            byte = self._memobj.memory[3-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x08).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x08).to_bytes(1, byteorder="big"))
        elif setting == "BEEP":
            byte = self._memobj.memory[3-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x04).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x04).to_bytes(1, byteorder="big"))
        elif setting == "WARN":
            byte = self._memobj.memory[7-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x01).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x01).to_bytes(1, byteorder="big"))
        elif setting == "SCAN":
            byte = self._memobj.memory[7-1].global2
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x01).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x01).to_bytes(1, byteorder="big"))
        elif setting == "CPYC":
            byte = self._memobj.memory[6-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x01).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x01).to_bytes(1, byteorder="big"))
        elif setting == "VOXF":
            byte = self._memobj.memory[4-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value:
                byte.set_raw((num | 0x01).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x01).to_bytes(1, byteorder="big"))

    def _get_int(self, setting):
        if setting == "SQL":
            byte2 = self._memobj.memory[3-1].global2.get_raw()

            return int.from_bytes(byte2, byteorder="big") & 0x0F
        elif setting == "CH":
            byte2 = self._memobj.memory[8-1].global2.get_raw()

            return (int.from_bytes(byte2, byteorder="big") & 0xFF) + 1
        elif setting == "DCSTM":
            byte3 = self._memobj.memory[7-1].global3.get_raw()

            return 1 if int.from_bytes(byte3, byteorder="big") & 0x01 else 0
        elif setting == "TOT":
            byte3 = self._memobj.memory[3-1].global3.get_raw()

            return int.from_bytes(byte3, byteorder="big")
        elif setting == "VP":
            byte1 = self._memobj.memory[3-1].global1.get_raw()

            if int.from_bytes(byte1, byteorder="big") & 0x01:
                return 1
            elif int.from_bytes(byte1, byteorder="big") & 0x02:
                return 2
            else:
                return 0
        elif setting == "LCDT":
            byte1 = self._memobj.memory[8-1].global1.get_raw()

            return int.from_bytes(byte1, byteorder="big")
        elif setting == "BATR":
            byte3 = self._memobj.memory[8-1].global3.get_raw()

            return int.from_bytes(byte3, byteorder="big")
        elif setting == "VOXL":
            byte2 = self._memobj.memory[4-1].global2.get_raw()

            return int.from_bytes(byte2, byteorder="big") & 0x0F
        elif setting == "VOXD":
            byte3 = self._memobj.memory[4-1].global3.get_raw()

            return int.from_bytes(byte3, byteorder="big")

    def _set_int(self, setting, value):
        if setting == "SQL":
            byte = self._memobj.memory[3-1].global2
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            byte.set_raw(((num & 0xF0) | (value & 0x0F))
                         .to_bytes(1, byteorder="big"))
        elif setting == "CH":
            byte = self._memobj.memory[8-1].global2
            byte.set_raw((value - 1).to_bytes(1, byteorder="big"))
        elif setting == "DCSTM":
            byte = self._memobj.memory[7-1].global3
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value == 1:
                byte.set_raw((num | 0x01).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((num & ~0x01).to_bytes(1, byteorder="big"))
        elif setting == "TOT":
            byte = self._memobj.memory[3-1].global3
            byte.set_raw(value.to_bytes(1, byteorder="big"))
        elif setting == "VP":
            byte = self._memobj.memory[3-1].global1
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            if value == 1:
                byte.set_raw((0x01).to_bytes(1, byteorder="big"))
            elif value == 2:
                byte.set_raw((0x02).to_bytes(1, byteorder="big"))
            else:
                byte.set_raw((0x00).to_bytes(1, byteorder="big"))
        elif setting == "LCDT":
            byte = self._memobj.memory[8-1].global1
            byte.set_raw(value.to_bytes(1, byteorder="big"))
        elif setting == "BATR":
            byte = self._memobj.memory[8-1].global3
            byte.set_raw(value.to_bytes(1, byteorder="big"))
        elif setting == "VOXL":
            byte = self._memobj.memory[4-1].global2
            num = int.from_bytes(byte.get_raw(), byteorder="big")
            new_byte = (num & 0xF0) | (value & 0x0F)
            byte.set_raw(new_byte.to_bytes(1, byteorder="big"))
        elif setting == "VOXD":
            byte = self._memobj.memory[4-1].global3
            byte.set_raw(value.to_bytes(1, byteorder="big"))

    _SETTINGS_OPTIONS = {
        "DCSTM": ["Normal", "Special"],
        "TOT": ["OFF"] + [str(x) for x in range(15, 615, 15)],
        "VP": ["OFF", "Chinese", "English"],
        "LCDT": ["OFF"] + [f"{i}S" for i in range(5, 30, 5)] + ["CONT"],
        "BATR": ["1:3", "1:5", "1:7", "1:9", "1:12"],
        "VOXL": ["OFF"] + [str(x) for x in range(1, 10)],
        "VOXD": ["0.5", "1", "1.5", "2", "2.5", "3"],
    }

    def get_settings(self):
        main = RadioSettingGroup("Main Settings", "Main")
        vox = RadioSettingGroup("VOX Settings", "VOX")
        radio_settings = RadioSettings(main, vox)\

        lists = [
            ("DCSTM", main, "DCS Tail Mode"),
            ("TOT", main, "Time out(sec)"),
            ("VP", main, "Voice Prompts"),
            ("LCDT", main, "LCD Timeout"),
            ("BATR", main, "Battery Save"),
            ("VOXL", vox, "VOX Level"),
            ("VOXD", vox, "VOX Delay Time(sec)"),
        ]

        bools = [
            ("BATS", main, "Battery Save"),
            ("BEEP", main, "Beep"),
            ("WARN", main, "Warn"),
            ("SCAN", main, "Scan"),
            ("CPYC", main, "Copy Channel"),
            ("VOXF", vox, "VOX Function"),
        ]

        ints = [
            ("SQL", main, "Squelch", 0, 9),
            ("CH", main, "Channel", 1, 198),
        ]

        for setting, group, name in bools:
            value = self._get_bool(setting)
            rs = RadioSetting(setting, name, RadioSettingValueBoolean(value))
            group.append(rs)

        for setting, group, name in lists:
            value = self._get_int(setting)
            options = self._SETTINGS_OPTIONS[setting]
            rs = RadioSetting(setting, name,
                              RadioSettingValueList(options,
                                                    current_index=value))
            group.append(rs)

        for setting, group, name, minv, maxv in ints:
            value = self._get_int(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueInteger(minv, maxv, value))
            group.append(rs)

        return radio_settings

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            elif isinstance(element.value, RadioSettingValueBoolean):
                self._set_bool(element.get_name(), element.value)
            elif isinstance(element.value, RadioSettingValueList):
                # options = self._get_setting_options(element.get_name())
                options = self._SETTINGS_OPTIONS[element.get_name()]
                self._set_int(element.get_name(),
                              options.index(str(element.value)))
            elif isinstance(element.value, RadioSettingValueInteger):
                self._set_int(element.get_name(), int(element.value))
            else:
                LOG.error("Unknown setting type: %s" % element.value)

    def sync_in(self):
        try:
            data = do_download(self)
        except errors.RadioError:
            raise
        except Exception:
            LOG.exception("Failed to download data to radio")
            raise errors.RadioError("Failed to download data from radio")
        finally:
            _exit_programming_mode(self)
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception:
            LOG.exception("Failed to upload data from radio")
            raise errors.RadioError("Failed to upload data to radio")
        finally:
            _exit_programming_mode(self)
