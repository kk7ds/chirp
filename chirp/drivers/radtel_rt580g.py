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
from typing import Optional, Tuple

LOG = logging.getLogger(__name__)

CMD_ACCEPT = b"\x06"
CHARSET_HEX = "0123456789ABCDEFabcdef"


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = 5  # 5000ms

    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _enter_programming_mode(radio) -> bytes:
    _clean_buffer(radio)

    radio.pipe.write(radio._magic)
    LOG.debug("Sent magic sequence")
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    LOG.debug("Received magic sequence response")
    if len(ack) != 1 or ack != CMD_ACCEPT:
        if ack:
            LOG.error("Received: Len=%i Data=%s"
                      % (len(ack), util.hexprint(ack)))
        raise errors.RadioError("Radio refused to enter programming mode")

    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(8)
    if not ident:
        raise errors.RadioNoContactLikelyK1()
    elif not ident.startswith(radio._fingerprint):
        raise errors.RadioError("Radio returned unknown identification string")

    LOG.info("Radio entered programming mode")
    LOG.debug("Radio identification: %s" % util.hexprint(ident))

    radio.pipe.write(CMD_ACCEPT)
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    elif ack != CMD_ACCEPT:
        if ack:
            LOG.error("Got %s" % util.hexprint(ack))
        raise errors.RadioError("Radio refused to enter programming mode")

    return ident


def _exit_programming_mode(radio):
    try:
        radio.pipe.write(b"\x45")
        ack = radio.pipe.read(1)
        if not ack:
            LOG.debug("No response to exit programming mode")
        radio.pipe.write(b"\x02")  # Probably reboot signal
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _get_memory_address(channel_id: int) -> Tuple[int, int]:
    """Calculates the memory address for a given channel_id"""
    block = (channel_id - 1) // 16           # Determines high byte
    offset = ((channel_id - 1) % 16) * 0x10  # Determines low byte

    return (block, offset)


def _read_block(radio, channel_id: int) -> bytes:
    """Reads two memory channels from the radio starting at channel_id
    + one extra byte"""

    address = bytes(_get_memory_address(channel_id))
    # 52=read | 20 = hex(32 bytes) = length of 2 channels
    # + settings without header
    cmd = struct.pack(">BBBB", 0x52, address[0], address[1], 0x20)

    radio.pipe.write(cmd)
    hdr = radio.pipe.read(4)  # Read 4 byte header
    if not hdr:
        raise errors.RadioNoContactLikelyK1()
    data = radio.pipe.read(32)  # Read the data (0x20)
    if not data:
        raise errors.RadioNoContactLikelyK1()
    checksum = radio.pipe.read(1)  # Read the checksum
    if not checksum:
        raise errors.RadioNoContactLikelyK1()

    # Verify checksum
    if checksum[0] != calculate_checksum(data):
        LOG.error("Checksum mismatch for block 0x%04s:" %
                  util.hexprint(address))
        raise errors.RadioError("Checksum mismatch")

    mode, a, resp_length = struct.unpack(">BHB", hdr)
    if a != int.from_bytes(address, byteorder="big") \
            or resp_length != 32 or mode != ord("W"):
        LOG.error("Invalid answer for block 0x%04s:" % util.hexprint(address))
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (mode, a, resp_length))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _write_blocks(radio, channel_id: int, data: bytes):
    assert len(data) == 0x20, "Data must be 32 bytes long"

    address = bytes(_get_memory_address(channel_id))
    cmd = struct.pack(">BBBB", 0x57, address[0], address[1], 0x20) + data

    # Calculate checksum
    checksum = calculate_checksum(data)
    cmd += struct.pack(">B", checksum)

    radio.pipe.write(cmd)
    response = radio.pipe.read(1)
    if not response:
        raise errors.RadioNoContactLikelyK1()
    elif response != CMD_ACCEPT:
        raise errors.RadioError("Radio refused to write blocks at %04s"
                                % util.hexprint(address))


def do_download(radio) -> bytes:
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
    for i in range(1, radio.MEM_ROWS, 2):
        status.cur = i
        radio.status_fn(status)

        block_offset = (i - 1) * radio.BLOCK_SIZE
        blocks = radio_mem[block_offset:block_offset + (radio.BLOCK_SIZE * 2)]
        _write_blocks(radio, i, blocks)

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
    if level == 0x80 or level == 0xA8:
        return int(format(byte, "x"))
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


def calculate_checksum(data: bytes) -> int:
    """
    Calculate the checksum for a 32-byte data block.

    (The checksum is computed as the sum of two 16-byte blocks modulo 256.)
    """
    if len(data) != 32:
        raise ValueError("Data must be exactly 32 bytes long.")

    first_block_sum = sum(data[:16]) % 256
    second_block_sum = sum(data[16:]) % 256

    return (first_block_sum + second_block_sum) % 256


def verify_checksum(data: bytes) -> bool:
    """
    Verify data integrity by checking the checksum.
    """
    if len(data) != 32 + 1:
        raise ValueError("Data must be exactly 32 bytes long.")

    # Replace last byte with 0 for calculation
    calculated_checksum = calculate_checksum(data[:-1])
    return calculated_checksum == data[-1]


@directory.register
class Radtel580GRadio(chirp_common.CloneModeRadio):
    """Acme Template"""
    VENDOR = "Radtel"
    MODEL = "RT-580G"
    BAUD_RATE = 38400
    WANTS_DTR = True
    WANTS_RTS = True

    _magic = b"\x50\x6a\x4f\x4a\x48\x5c\x44"
    _fingerprint = b"\x50\x33\x31\x31\x38\x33\xff\xff"
    _upper = 199

    BLOCK_SIZE = 16
    MEM_ROWS = 672

    # NOTE: wats are randomly chosen for now to allow comparison
    POWER_LEVELS = [
        chirp_common.PowerLevel("High", watts=10.0),
        chirp_common.PowerLevel("Low", watts=5.0),
    ]
    LENGTH_NAME = 8

    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

    MEM_FORMAT = """
    // skip first channel as it is unused
    #seekto 0x0010;
    struct {
        lbcd rxfreq[4];         // RX Frequency (BCD format)
        lbcd txfreq[4];         // TX Frequency (BCD format)
        ul16 rxtone;            // RX Tone (CTCSS/DCS) - 0xFFFF if OFF
        ul16 txtone;            // TX Tone (CTCSS/DCS) - 0xFFFF if OFF
        u8 unknown1;            // Unknown byte 1
        u8 unknown2:3,          // Unknwon bits 1
           spec:1,              // SPEC=on 0x10
           unknown3:1,          // Unknown bits 2
           busy_lock:1,          // Busy Lock = ON 0x04
           unknown4:2;          // Unknown bits 3
        u8 scramble:1,          // Scramble ON=1, OFF=0
           spec_qt_dqt:1,       // SPEC QT/DQT Enabled: OFF=0, ON=1
           spec_qt_dqt_mode:1,  // SPEC QT/DQT Mode: Normal=0, Special=1
           tx_power:1,          // Always 1=Low, 0=High
           wn_mode:1,           // W/N Mode: Wide=0, Narrow=1
           am_fm:1,             // AM=1, FM=0
           unknown5:2;          // Unknown bits 5
        u8 unknown6;            // Unknown byte 2
    } memory[199]; // last channel stored at address 0x0c60 (3200 bytes in)

    struct {
        char gps_id[4];         // GPS Identifier (ASCII, e.g. "GPS ")
        u8 unknown7[4];         // Unknown bytes
        u8 unknown8[8];         // Unknown bytes
        u8 pf1_short;           // PF1 (Short press) - Enum
                                // 0x00=None, 0x01=Scan, 0x02=FM,
                                // 0x03=Warn, 0x04=TONE
        u8 pf1_long;            // PF1 (Long press) - Enum
                                // 0x00=None, 0x01=Scan, 0x02=FM,
                                // 0x03=Warn, 0x04=TONE, 0x05=Monitor
        u8 pf2_short;           // PF2 (Short press) - Enum same as PF1S
        u8 pf2_long;            // PF2 (Long press) - Enum same as PF1L
        u8 unknown9[12];        // Unknown bytes
    } settings1; // 0c 80 - and 32 bytes long

    struct {
        u8 display_lcd_tx:1,   // Display LCD TX: OFF=0, ON=1
           display_lcd_rx:1,   // Display LCD RX: OFF=0, ON=1
           unknown10:3,        // Unknown bits 1
           unknown11:2,        // Unknown bit 2
           priority_tx:1;      // Priority TX: Edit=0, Busy=1

        u8 scan_mode:2,        // 00=TO, 01=CO, 10=SE
           gps:1,              // 1=ON, 0=OFF
           auto_lock:1,        // 1=ON, 0=OFF
           battery_save:1,     // 1=ON, 0=OFF
           beep:1,             // 1=ON, 0=OFF
           unknown12:1,         // Unknown
           voice_prompt:1;     // Voice Prompt: OFF=0, ON=1

        u8 work_mode:1,             // Unknown bit 1
           light_ctrl:2,            // 00=30S, 01=20S, 10=10S, 11=CONT
           only_ch_mode:1,
           forbid_receive:1,
           channel_name_display:1,
           unknown13:2;              // Unknown bits 4

        u8 unknown14:5,         // Unknown bits 5
           double_rx:1,        // Double RX: OFF=0, ON=1
           unknown15:2;         // Unknown bits 6

        u8 unknown16;           // Unknown byte 7
        u8 unknown17;           // Unknown byte 8

        u8 active_channel;     // Active Channel is (channel_nr - 1) to hex

        u8 unknown18:1,        // Unknown bits 9
           qt_dqt_tail:1,      // QT/DQT Tail: OFF=0, ON=1
           roger:1,            // Roger Beep: OFF=0, ON=1
           unknown19:3,        // Unknown bits 10
           vox_gain:2;         // VOX Gain Level: 0x00=Off, 0x01=1,
                               // 0x10=2, 0x11=3

        u8 unknown20;
        u8 squelch_level;
        u8 timeout_duration;    // 0x00=OFF, 0x01=30s, 0x02=60s,
                                //  0x03=90s, 0x04=120s, 0x05=150s,
                                //  0x06=180s, 0x07=210s

        u8 rx_gps:1,
           tx_gps:1,
           unknown21:5,
           language:1;

        u8 vox_delay;           // 0x00=0.5, 0x01=1.0, 0x02=2.0, 0x03=3.0

        u8 unknown22[17];       // Unknown bytes 13
    } settings2; // 0c a0 - and 32 bytes long

    struct {
        ul32 unused[4];         // 4 unused bytes
    } unused1[8];

    u8 unknown23[2];            // Unknown bytes 14

    struct {
        char channel_name[8];    // 8 bytes of channel name
    } channel_names[199];  // from address 0x0d40, to 0x1360 with 8 bytes
                           // left in this last block

    #seekto 0x1a20; // 0x1a20 is the address of this double channel
    struct {
        u8 scan_add_settings[16]; // 16 bytes of scan add settings
        u8 unknown1[16];          // 16 bytes of unknown data
                                  // (TODO: this may both be scan add)
    } scan_add_settings;

    // 19 unused duble rows
    struct {
        ul32 unused[4];
    } unused2[28];

    struct {
        ul32 special_code[4];   // Special Codes for 4 channels per row
    } special_codes[50];
    """

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_rx_dtcs = True
        rf.has_dtcs = True
        rf.has_ctone = True
        rf.has_dtcs_polarity = True
        rf.has_name = True
        rf.can_odd_split = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_variable_power = False
        rf.has_offset = True
        rf.has_mode = False

        rf.valid_modes = ["NFM", "WFM", "AM"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = self.LENGTH_NAME
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
        rf.valid_bands = [(100000000, 330000000), (330000000, 600000000)]
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
        return rf

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

    def _decode_qt_dqt(self, raw: bytes) -> Tuple[str, int, str]:
        assert len(raw) == 2, "QT/DQT value must be 2 bytes long"

        if raw == b"\xFF\xFF":
            return None, None, None
        elif raw[1] < 0x80:
            value = int(f"{raw[1]:02X}{raw[0]:02X}") / 10
            assert value in chirp_common.TONES
            return "Tone", value, None
        else:
            dtcs_polarity = "N" if (raw[1] & 0xF0) == 0x80 else "R"

            # Extract LBCD-encoded DTCS value
            dtcs_code = (raw[1] & 0x0F) * 100 + \
                ((raw[0] & 0xF0) >> 4) * 10 + (raw[0] & 0x0F)

            assert dtcs_code in self.DTCS_CODES
            return "DTCS", dtcs_code, dtcs_polarity

    def _encode_qt_dqt(
        self,
        tone_type: Optional[str],
        value: Optional[int],
        polarity: Optional[str]
    ) -> bytes:
        """
        Encodes a QT/DQT value into a 2-byte format.

        - `tone_type`: "Tone" for analog tones or "DTCS" for digital squelch
        - `value`: Tone frequency (Hz) for "Tone" or DTCS code for "DTCS"
        - `polarity`: "N" or "R" for DTCS polarity

        Returns: `bytes` (2-byte encoded value)
        """
        if tone_type is None or len(tone_type) == 0:
            return b"\xFF\xFF"  # No tone

        elif tone_type == "Tone" or tone_type == "TSQL":
            assert value in chirp_common.TONES, "Invalid tone frequency"

            # Convert frequency to LBCD (Little-endian BCD)
            hex_value = int(value * 10)
            bcd_low = hex_value % 100
            bcd_high = hex_value // 100

            return bytes([
                ((bcd_low // 10) << 4) | (bcd_low % 10),
                ((bcd_high // 10) << 4) | (bcd_high % 10)])

        elif tone_type == "DTCS":
            # LBCD Encoding + Polarity
            hundreds = (value // 100) % 10
            tens = (value // 10) % 10
            ones = value % 10

            bcd_value = (
                (tens << 4) | ones,
                (hundreds | (0x80 if polarity == "N" else 0xC0))
            )

            return bytes(bcd_value)

        else:
            raise ValueError("Unknown tone type '%s'" % tone_type)

    def get_scan_add_status(self, channel: int) -> bool:
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

    def set_scan_add_status(self, channel: int, status: bool):
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

    def get_channel_name(self, channel: int) -> str:
        """
        Get the name of a channel.

        Args:
            channel (int): The channel number (1-199).

        Returns:
            The channel name as a string.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")

        name_data = self._memobj.channel_names[channel - 1]
        return str(name_data.channel_name).replace('\xFF', ' ') \
            .replace('\x00', ' ').rstrip()

    def set_channel_name(self, channel: int, name: Optional[str]):
        """
        Set the name of a channel.

        Args:
            channel (int): The channel number (1-199).
            name (str): The name to set.
        """
        if not 1 <= channel <= 199:
            raise ValueError("Channel number must be between 1 and 199")
        assert name is None or \
            len(name) <= self.get_features().valid_name_length, \
            "Channel name must be 8 or less characters long"

        name_data = self._memobj.channel_names[channel - 1]
        _namelength = self.get_features().valid_name_length
        # TODO: writes 10 bytes or the position in mem is off
        # by 2 if writing ch 12 name
        name_data.channel_name = name.ljust(_namelength, '\x20') \
            if name else '\xFF' * _namelength

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

        mem.mode = ("WFM" if int(_mem.wn_mode) else "NFM") if not int(
            _mem.am_fm) else "AM"

        power_level = int(not _mem.tx_power)
        mem.power = self.POWER_LEVELS[power_level]

        scan_add = self.get_scan_add_status(mem.number)
        if not scan_add:
            mem.skip = "S"

        mem.name = self.get_channel_name(mem.number)

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting(
            "SPEC", "SPEC",
            RadioSettingValueBoolean(int(_mem.spec)))
        mem.extra.append(rs)

        rs = RadioSetting(
            "Busy Lock", "Busy Lock",
            RadioSettingValueBoolean(int(_mem.busy_lock)))
        mem.extra.append(rs)

        rs = RadioSetting(
            "Scramble Mode", "Scramble Mode",
            RadioSettingValueBoolean(bool(_mem.scramble)))
        mem.extra.append(rs)

        rs = RadioSetting(
            "SPEC QT/DQT", "SPEC QT/DQT",
            RadioSettingValueList(
                ["OFF", "Normal", "Special"],
                current_index=0 if int(_mem.spec_qt_dqt) == 0
                else (1 if int(_mem.spec_qt_dqt_mode) == 0 else 2)
            ))
        mem.extra.append(rs)

        special_code = self.get_special_code(mem.number)
        rs = RadioSetting(
            "Code", "Code",
            RadioSettingValueString(
                8, 8, special_code, True, CHARSET_HEX, "0"))
        mem.extra.append(rs)

        if mem.mode == "AM":
            mem.immutable = [
                "extra",
                "power",
                "tmode",
                "skip",
                "rx_dtcs",
                "rtone",
                "ctone",
                "dtcs",
                "cross_mode",
                "dtcs_polarity",
                "duplex",
                "offset",
                "tuning_step"
            ]

    def encode_mem_blob(self, mem, _mem):
        _mem.rxfreq = mem.freq / 10

        assert mem.duplex in ["", "-", "+"]
        if mem.duplex == "+":
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

        special_code = "FF" * 4
        for setting in mem.extra:
            if setting.get_name() == "SPEC":
                _mem.spec = int(setting.value)
            elif setting.get_name() == "Busy Lock":
                _mem.busy_lock = int(setting.value)
            elif setting.get_name() == "Scramble Mode":
                _mem.scramble = int(setting.value) if str(
                    setting.value) != "OFF" else 0
            elif setting.get_name() == "Special QT/DQT":
                val = int(setting.value)
                assert val in [0, 1, 2]
                if val == 0:
                    _mem.spec_qt_dqt = 0
                    _mem.spec_qt_dqt_mode = 0
                elif val == 1:
                    _mem.spec_qt_dqt = 1
                    _mem.spec_qt_dqt_mode = 0
                elif val == 2:
                    _mem.spec_qt_dqt = 1
                    _mem.spec_qt_dqt_mode = 1
            elif setting.get_name() == "Code":
                special_code = str(setting.value)

        _mem.wn_mode = 0 if mem.mode == "NFM" else 1
        _mem.am_fm = 1 if mem.mode == "AM" else 0

        _mem.tx_power = 0 if mem.power == self.POWER_LEVELS[1] else 1

        # Settings that are indepently stored from the memory channel
        self.set_scan_add_status(mem.number, mem.skip != "S")
        self.set_special_code(mem.number, special_code)
        self.set_channel_name(mem.number, mem.name)

    def get_memory(self, number):
        if number <= 0 or number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 1 and %i (included)" % self._upper)

        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number

        self.decode_mem_blob(_mem, mem)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xff" * 16)
            # Also reset all externally stored settings
            self.set_scan_add_status(mem.number, False)
            self.set_special_code(mem.number, "FF" * 4)
            self.set_channel_name(mem.number, None)
            return

        self.encode_mem_blob(mem, _mem)

    _SETTINGS_OPTIONS = {
        "LANG": ["Chinese", "English"],
        "LCTRL": ["CONT", "10S", "20S", "30S"],
        "SMOD": ["TO", "CO", "SE"],
        "TOUT": ["OFF", "30s", "60s", "90s", "120s", "150s", "180s", "210s"],
        "PTX": ["Edit", "Busy"],
        "VOXG": ["OFF", "1", "2", "3"],
        "VOXD": ["0.5S", "1.0S", "2.0S", "3.0S"],
        "PF1S": ["None", "Scan", "FM", "Warn", "TONE"],
        "PF1L": ["None", "Scan", "FM", "Warn", "TONE", "Monitor"],
        "PF2S": ["None", "Scan", "FM", "Warn", "TONE"],
        "PF2L": ["None", "Scan", "FM", "Warn", "TONE", "Monitor"],
        "WMODE": ["CH", "VFO"],
    }

    def _get_bool(self, key: str) -> bool:
        if key == "BATS":
            return bool(self._memobj.settings2.battery_save)
        elif key == "VP":
            return bool(self._memobj.settings2.voice_prompt)
        elif key == "DRX":
            return bool(self._memobj.settings2.double_rx)
        elif key == "ALOCK":
            return bool(self._memobj.settings2.auto_lock)
        elif key == "CHN":
            return bool(self._memobj.settings2.channel_name_display)
        elif key == "BEEP":
            return bool(self._memobj.settings2.beep)
        elif key == "DPLCDTX":
            return bool(self._memobj.settings2.display_lcd_tx)
        elif key == "DPLCDRX":
            return bool(self._memobj.settings2.display_lcd_rx)
        elif key == "OCHM":
            return bool(self._memobj.settings2.only_ch_mode)
        elif key == "RS":
            return bool(self._memobj.settings2.roger)
        elif key == "QDT":
            return bool(self._memobj.settings2.qt_dqt_tail)
        elif key == "FRC":
            return bool(self._memobj.settings2.forbid_receive)
        elif key == "GPS":
            return bool(self._memobj.settings2.gps)
        elif key == "RXGPS":
            return bool(self._memobj.settings2.rx_gps)
        elif key == "TXGPS":
            return bool(self._memobj.settings2.tx_gps)
        else:
            raise ValueError("Invalid boolean key: %s" % key)

    def _set_bool(self, key: str, value: bool):
        if key == "BATS":
            self._memobj.settings2.battery_save = int(value)
        elif key == "VP":
            self._memobj.settings2.voice_prompt = int(value)
        elif key == "DRX":
            self._memobj.settings2.double_rx = int(value)
        elif key == "ALOCK":
            self._memobj.settings2.auto_lock = int(value)
        elif key == "CHN":
            self._memobj.settings2.channel_name_display = int(value)
        elif key == "BEEP":
            self._memobj.settings2.beep = int(value)
        elif key == "DPLCDTX":
            self._memobj.settings2.display_lcd_tx = int(value)
        elif key == "DPLCDRX":
            self._memobj.settings2.display_lcd_rx = int(value)
        elif key == "OCHM":
            self._memobj.settings2.only_ch_mode = int(value)
        elif key == "RS":
            self._memobj.settings2.roger = int(value)
        elif key == "QDT":
            self._memobj.settings2.qt_dqt_tail = int(value)
        elif key == "FRC":
            self._memobj.settings2.forbid_receive = int(value)
        elif key == "GPS":
            self._memobj.settings2.gps = int(value)
        elif key == "RXGPS":
            self._memobj.settings2.rx_gps = int(value)
        elif key == "TXGPS":
            self._memobj.settings2.tx_gps = int(value)
        else:
            raise ValueError("Invalid boolean key: %s" % key)

    def _get_int(self, key: str) -> int:
        if key == "SQL":
            return int(self._memobj.settings2.squelch_level)
        elif key == "CH":
            return int(self._memobj.settings2.active_channel) + 1
        elif key == "LANG":
            return int(self._memobj.settings2.language)
        elif key == "LCTRL":
            return int(self._memobj.settings2.light_ctrl)
        elif key == "SMOD":
            return int(self._memobj.settings2.scan_mode)
        elif key == "TOUT":
            return int(self._memobj.settings2.timeout_duration)
        elif key == "PTX":
            return int(self._memobj.settings2.priority_tx)
        elif key == "VOXG":
            return int(self._memobj.settings2.vox_gain)
        elif key == "VOXD":
            return int(self._memobj.settings2.vox_delay)
        elif key == "PF1S":
            return int(self._memobj.settings1.pf1_short)
        elif key == "PF1L":
            return int(self._memobj.settings1.pf1_long)
        elif key == "PF2S":
            return int(self._memobj.settings1.pf2_short)
        elif key == "PF2L":
            return int(self._memobj.settings1.pf2_long)
        elif key == "WMODE":
            return int(self._memobj.settings2.work_mode)
        else:
            raise ValueError("Invalid integer key: %s" % key)

    def _set_int(self, key: str, value: int):
        if key == "SQL":
            self._memobj.settings2.squelch_level = value
        elif key == "CH":
            self._memobj.settings2.active_channel = value - 1
        elif key == "LANG":
            self._memobj.settings2.language = value
        elif key == "LCTRL":
            self._memobj.settings2.light_ctrl = value
        elif key == "SMOD":
            self._memobj.settings2.scan_mode = value
        elif key == "TOUT":
            self._memobj.settings2.timeout_duration = value
        elif key == "PTX":
            self._memobj.settings2.priority_tx = value
        elif key == "VOXG":
            self._memobj.settings2.vox_gain = value
        elif key == "VOXD":
            self._memobj.settings2.vox_delay = value
        elif key == "PF1S":
            self._memobj.settings1.pf1_short = value
        elif key == "PF1L":
            self._memobj.settings1.pf1_long = value
        elif key == "PF2S":
            self._memobj.settings1.pf2_short = value
        elif key == "PF2L":
            self._memobj.settings1.pf2_long = value
        elif key == "WMODE":
            self._memobj.settings2.work_mode = value
        else:
            raise ValueError("Invalid integer key: %s" % key)

    def _get_string(self, key: str) -> str:
        if key == "GPSID":
            return str(self._memobj.settings1.gps_id) \
                .replace('\xFF', ' ').replace('\x00', ' ').rstrip()
        else:
            raise ValueError("Invalid string key: %s" % key)

    def _set_string(self, key: str, value: str):
        if key == "GPSID":
            self._memobj.settings1.gps_id = value
        else:
            raise ValueError("Invalid string key: %s" % key)

    def get_settings(self):
        main = RadioSettingGroup("Main Settings", "Main")
        vox = RadioSettingGroup("VOX Settings", "VOX")
        key_set = RadioSettingGroup("Key Settings", "Key Set")
        radio_setup = RadioSettingGroup("Radio Setup", "Radio Setup")
        gps = RadioSettingGroup("GPS Settings", "GPS")
        radio_settings = RadioSettings(main, vox, key_set, radio_setup, gps)

        lists = [
            ("LANG", main, "Language"),
            ("LCTRL", main, "Light Control"),
            ("SMOD", main, "Scan Mode"),
            ("TOUT", main, "Timeout (sec)"),
            ("PTX", main, "Priority TX"),
            ("VOXG", vox, "VOX Gain"),
            ("VOXD", vox, "VOX Delay"),
            ("PF1S", key_set, "PF1 Short"),
            ("PF1L", key_set, "PF1 Long"),
            ("PF2S", key_set, "PF2 Short"),
            ("PF2L", key_set, "PF2 Long"),
            ("WMODE", radio_setup, "Work Mode"),
        ]

        bools = [
            ("BATS", main, "Battery Save"),
            ("VP", main, "Voice Prompt"),
            ("DRX", main, "Double RX"),
            ("ALOCK", main, "Auto Lock"),
            ("CHN", main, "Channel Name Display"),
            ("BEEP", main, "Beep Sound"),
            ("DPLCDTX", main, "Display LCD (TX)"),
            ("DPLCDRX", main, "Display LCD (RX)"),
            ("OCHM", main, "Only CH Mode"),
            ("RS", main, "Roger Sound"),
            ("QDT", main, "QT/DQT Tail"),
            ("FRC", radio_setup, "Forbid Receive"),
            ("GPS", gps, "GPS"),
            ("RXGPS", gps, "RX GPS"),
            ("TXGPS", gps, "TX GPS"),
        ]

        ints = [
            ("SQL", main, "Squelch", 0, 9),
            ("CH", radio_setup, "Channel", 1, 198),
        ]

        strings = [
            ("GPSID", gps, "GPS ID", 8),
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

        for setting, group, name, length in strings:
            value = self._get_string(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueString(0, length, value, False))
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
                options = self._SETTINGS_OPTIONS[element.get_name()]
                self._set_int(element.get_name(),
                              options.index(str(element.value)))
            elif isinstance(element.value, RadioSettingValueInteger):
                self._set_int(element.get_name(), int(element.value))
            elif isinstance(element.value, RadioSettingValueString):
                self._set_string(element.get_name(), str(element.value))
            else:
                LOG.error("Unknown setting type: %s" % element.value)
