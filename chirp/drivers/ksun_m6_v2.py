# Copyright 2012 Dan Smith <dsmith@danplanet.com>
# Copyright 2024 Yuri D'Elia <wavexx@thregr.org>
# Copyright 2026 Modified for M6 V2 (2024+ hardware revision)
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

from chirp import chirp_common, directory, memmap, bitwise, errors
from chirp.settings import (
    RadioSetting, RadioSettings, RadioSettingGroup,
    RadioSettingValueBoolean, RadioSettingValueInteger, RadioSettingValueList,
    RadioSettingValueString
)
import struct
import time

MEM_FORMAT = """
#seekto 0x0000;
struct {
  // Password Protection (bytes 0x00-0x0B)
  // DES encrypted with key "badworks", master password: "707070"
  // Empty password = all 0xFF
  u8 password[12];

  // Reserved section (bytes 0x0C-0x0F)
  u8 _reserved1[4];

  // Core Configuration (bytes 0x10-0x45)
  u8 signature;           // 0x10: Should be 0x50
  char startup_text[5];   // 0x11-0x15: Startup message (5 ASCII chars)
  ul16 freq_lower_limit;  // 0x16-0x17: Lower frequency limit in MHz (400-480)
  ul16 freq_upper_limit;  // 0x18-0x19: Upper frequency limit in MHz (400-480)
  u8 channel_limit;       // 0x1A: Channel limit - max channels (1-200)
  u8 current_channel;     // 0x1B: Current channel (0-based)
  u8 language;            // 0x1C: 0=Simplified, 1=Traditional, 2=English
  u8 beep;                // 0x1D: Bit 7=on/off, bits 0-6=volume (0-127)
  u8 keylock;             // 0x1E: Bit 7=on/off, bits 0-6=timeout (0-127 sec)
  u8 backlight;           // 0x1F: Bits 6-7=level, bits 0-5=timeout
  u8 roger_tot;           // 0x20: Bit 7=roger beep, bits 0-6=TOT
  u8 battery_save;        // 0x21: 0=off, 1=1:1, 2=1:2, 3=1:3, 4=1:4
  u8 squelch;             // 0x22: Squelch level (0-9)
  u8 mic_gain;            // 0x23: Microphone gain (0-255)
  u8 rx_volume;           // 0x24: RX volume (0-255)
  u8 vox;                 // 0x25: Bit 7=on/off, bits 0-6=delay (0-127)
  u8 vox_threshold;       // 0x26: VOX sensitivity (0-255)
  u8 alarm;               // 0x27: Alarm mode
  u8 apo;                 // 0x28: Auto power off (minutes)
  u8 channel_display;     // 0x29: Channel display mode
  u8 menu_timeout;        // 0x2A: Menu timeout (seconds)
  u8 key_function;        // 0x2B: Side key function
  u8 menu_settings[26];   // 0x2C-0x45: Menu customization

  // Reserved/padding (bytes 0x46-0xFF)
  u8 _reserved2[186];
} settings;

#seekto 0x0100;
struct {
  ul32 rx_freq;    // +0x00: RX frequency in units of 10 Hz (little-endian)
  ul16 rx_tone;    // +0x04: RX subaudio (CTCSS/DCS encoded, little-endian)
  ul32 tx_freq;    // +0x06: TX frequency in units of 10 Hz (little-endian)
  ul16 tx_tone;    // +0x0A: TX subaudio (CTCSS/DCS encoded, little-endian)
  u8 power: 1,     // +0x0C bit 7: power (0=high, 1=low)
     scan: 1,      // +0x0C bit 6: scan add (0=add, 1=skip)
     nfm: 1,       // +0x0C bit 5: bandwidth (0=wide/FM, 1=narrow/NFM)
     _unk1: 1,     // +0x0C bit 4: reserved
     scrambler: 4; // +0x0C bits 0-3: scrambler code (0=off, 1-8=code)
  u8 _unk2: 2,     // +0x0D bits 6-7: reserved
     compander: 1, // +0x0D bit 5: compander/tail tone (0=off, 1=on)
     busy: 2,      // +0x0D bits 3-4: busy lock (0=off, 1=carrier, 2=QT/DQT)
     encryption: 3;// +0x0D bits 0-2: encryption type (0=off, 1-5=various)
  u8 _reserved;    // +0x0E: Reserved
  char name[5];    // +0x0F-0x13: Channel name (5 ASCII chars, 0xFF padded)
  u8 id_data[12];  // +0x14-0x1F: Radio ID or encryption key
} memory[200];
"""

VOICE_LIST = ["off", "Chinese", "English"]
SCRAMBLER_LIST = ["off", "1", "2", "3", "4", "5", "6", "7", "8"]
LED_LIST = ["Low", "Medium", "High"]
BAT_SAVE_LIST = ["off", "1:1", "1:2", "1:3", "1:4"]
TONE_LIST = ["Tone", "DTCS_N", "DTCS_I", ""]

# Timeout lists - All use same 43-item pattern with different first item labels
# Pattern: Special item, then 5, 10, 15, 30, then +15 sec to 600
KEYLOCK_TIMEOUT_LIST = [
    "off", "5", "10", "15", "30", "45", "60", "75", "90", "105",
    "120", "135", "150", "165", "180", "195", "210", "225", "240", "255",
    "270", "285", "300", "315", "330", "345", "360", "375", "390", "405",
    "420", "435", "450", "465", "480", "495", "510", "525", "540", "555",
    "570", "585", "600"]

BACKLIGHT_TIMEOUT_LIST = [
    "Always On", "5", "10", "15", "30", "45", "60", "75", "90", "105",
    "120", "135", "150", "165", "180", "195", "210", "225", "240", "255",
    "270", "285", "300", "315", "330", "345", "360", "375", "390", "405",
    "420", "435", "450", "465", "480", "495", "510", "525", "540", "555",
    "570", "585", "600"]

TOT_TIMER_LIST = [
    "Unlimited", "5", "10", "15", "30", "45", "60", "75", "90", "105",
    "120", "135", "150", "165", "180", "195", "210", "225", "240", "255",
    "270", "285", "300", "315", "330", "345", "360", "375", "390", "405",
    "420", "435", "450", "465", "480", "495", "510", "525", "540", "555",
    "570", "585", "600"]

MENU_TIMEOUT_LIST = [
    "Hold", "5", "10", "15", "30", "45", "60", "75", "90", "105",
    "120", "135", "150", "165", "180", "195", "210", "225", "240", "255",
    "270", "285", "300", "315", "330", "345", "360", "375", "390", "405",
    "420", "435", "450", "465", "480", "495", "510", "525", "540", "555",
    "570", "585", "600"]

# VOX Delay and Squelch - Simple 0-9 lists
VOX_DELAY_LIST = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
SQUELCH_LIST = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]

# APO (Auto Power Off) - 201 items: Off, then 10-2000 min in steps
APO_LIST = ["Off"] + [str(i * 10) for i in range(1, 201)]

POWER_LIST = [chirp_common.PowerLevel("High", watts=2.00),
              chirp_common.PowerLevel("Low",  watts=0.50)]

# Frequency storage unit: 10 Hz (radio stores frequency in 10 Hz units)
FREQ_UNIT = 10

# Additional list constants
LANGUAGE_LIST = ["Chinese Simplified", "Chinese Traditional", "English"]
ALARM_LIST = ["Local", "Remote", "Local+Remote"]
DISPLAY_MODE_LIST = ["CH No.", "CH Alias"]
KEY_FUNCTION_LIST = ["CH-", "CH+", "Monitor", "Scan", "LED",
                     "Battery", "Freq Detect", "Alarm", "Talkaround",
                     "VOX"]


def _checksum(data):
    """Calculate checksum for radio protocol

    Args:
        data: bytes to checksum

    Returns:
        int: checksum value (0-255)
    """
    cs = 86
    for byte in data:
        cs += byte
    return cs % 256


def enter_programming_mode(radio):
    serial = radio.pipe

    # Command for entering programming mode
    cmd = b"\x32\x31\x05\x10"
    req = cmd + bytes([_checksum(cmd)])  # Should produce 0xCE (206)

    # Radio requires multiple attempts to enter programming mode
    # (manufacturer software tries 3+ times)
    for attempt in range(5):
        try:
            serial.write(req)
            time.sleep(0.1)  # Small delay for radio to process
            res = serial.read(1)
            if res == b"\x06":
                return  # Success!
        except Exception:
            pass
        time.sleep(0.1)  # Delay between attempts

    raise errors.RadioError(
        "Radio refused to enter programming mode after 5 attempts")


def exit_programming_mode(radio):
    serial = radio.pipe

    # Command for exiting programming mode
    cmd = b"\x32\x31\x05\xee"
    req = cmd + bytes([_checksum(cmd)])  # Should produce 0xAC (172)

    try:
        # there is no response from this command as the radio resets
        serial.write(req)
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr):
    serial = radio.pipe

    # Read command: 'R' + address
    cmd = struct.pack(">cH", b"R", block_addr)
    req = cmd + bytes([_checksum(cmd)])

    try:
        serial.write(req)
        time.sleep(0.05)  # Small delay for radio to process
        res_len = len(cmd) + radio.BLOCK_SIZE + 1
        res = serial.read(res_len)

        if len(res) != res_len or res[:len(cmd)] != cmd:
            raise Exception(
                "unexpected reply! Got %d bytes, expected %d"
                % (len(res), res_len))
        if res[-1] != _checksum(res[:-1]):
            raise Exception("block failed checksum!")

        block_data = res[len(cmd):-1]
    except Exception as e:
        msg = "Failed to read block at %04x: %s" % (block_addr, str(e))
        raise errors.RadioError(msg)

    return block_data


def _write_block(radio, block_addr, block_data):
    serial = radio.pipe

    # Write command: 'W' + address + data
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
    # Verify communication and check signature byte to confirm M6 V2
    # Attempt multiple times - radio may need time to respond
    # after power-on
    for attempt in range(5):
        try:
            # Read first block containing config data
            block = _read_block(radio, radio.START_ADDR)

            # Verify signature byte at offset 0x10 (byte 16)
            # should be 0x50
            if len(block) >= 17 and block[16] == 0x50:
                time.sleep(0.05)  # Small delay after successful
                return  # Success!
            else:
                raise Exception(
                    "Invalid signature byte "
                    "(expected 0x50 at offset 0x10)")
        except Exception:
            if attempt < 4:  # Don't sleep on last attempt
                time.sleep(0.2)  # Delay between attempts

    raise errors.RadioError(
        "Could not communicate with the radio or invalid signature "
        "after 5 attempts")


def do_download(radio):
    # Enter programming mode first
    enter_programming_mode(radio)

    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.max = radio._memsize

    data = b""
    try:
        for addr in range(radio.START_ADDR,
                          radio.START_ADDR + radio._memsize,
                          radio.BLOCK_SIZE):
            status.cur = addr - radio.START_ADDR
            radio.status_fn(status)

            block = _read_block(radio, addr)

            # Verify model on first block only (signature at offset
            # 0x10)
            if addr == radio.START_ADDR:
                if len(block) < 17 or block[16] != 0x50:
                    raise errors.RadioError(
                        "Invalid radio model (expected M6 V2 "
                        "signature 0x50)")

            data += block
    finally:
        # Always exit programming mode, even if download fails
        try:
            exit_programming_mode(radio)
        except Exception:
            pass  # Ignore exit errors - may already be disconnected

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    # Enter programming mode first
    enter_programming_mode(radio)

    # Verify we're talking to the correct radio model
    verify_model(radio)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.max = radio._memsize
    mmap = radio.get_mmap()

    try:
        for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
            status.cur = addr
            radio.status_fn(status)

            block = mmap[addr:addr + radio.BLOCK_SIZE]
            _write_block(radio, radio.START_ADDR + addr, block)
    finally:
        # Always exit programming mode, even if upload fails
        try:
            exit_programming_mode(radio)
        except Exception:
            # Ignore errors during exit - radio may already be
            # disconnected
            pass


def decode_tone(tone_value):
    """
    Decode M6 V2 tone format (16-bit little-endian)

    Bits 4-5 of high byte:
      00 = CTCSS (tone value = freq_Hz * 10)
      01 = DCS Normal
      10 = DCS Inverted
      11 = No tone

    Bits 0-3 of high byte + low byte = 12-bit tone value

    Returns: (mode, value, polarity)
      mode: '', 'Tone', or 'DTCS'
      value: tone frequency (Hz) or DCS code (decimal)
      polarity: None, 'N', or 'R'
    """
    # Extract tone value (lower 12 bits)
    tone_val = tone_value & 0x0FFF

    # Extract tone type (bits 12-13)
    tone_type = (tone_value >> 12) & 0x03

    if tone_type == 0x00:  # CTCSS
        if tone_val == 0:
            return ('', 0, None)
        freq = tone_val / 10.0
        return ('Tone', freq, None)
    elif tone_type == 0x01:  # DCS Normal
        if tone_val == 0:
            return ('', 0, None)
        return ('DTCS', tone_val, 'N')
    elif tone_type == 0x02:  # DCS Inverted
        if tone_val == 0:
            return ('', 0, None)
        return ('DTCS', tone_val, 'R')
    else:  # 0x03 = No tone
        return ('', 0, None)


def encode_tone(mode, value, polarity):
    """
    Encode tone to M6 V2 format (16-bit little-endian)

    Args:
      mode: '', 'Tone', or 'DTCS'
      value: tone frequency (Hz) or DCS code (decimal)
      polarity: None, 'N', or 'R'

    Returns: 16-bit tone value (little-endian format expected by radio)
    """
    if mode == 'Tone' and value:
        # CTCSS: type 00, value = freq * 10
        tone_val = int(value * 10) & 0x0FFF
        return tone_val | 0x0000  # Type bits already 00
    elif mode == 'DTCS' and value:
        # DCS: type 01 (normal) or 10 (inverted)
        tone_val = int(value) & 0x0FFF
        if polarity == 'N':
            return tone_val | 0x1000  # Type = 01
        else:  # 'R' or inverted
            return tone_val | 0x2000  # Type = 10
    else:
        # No tone: type 11
        return 0x3000


@directory.register
class KSunM6V2Radio(chirp_common.CloneModeRadio):
    VENDOR = "KSUN"
    MODEL = "M6-V2"
    BAUD_RATE = 38400
    BLOCK_SIZE = 0x80
    START_ADDR = 0x0300
    CHANNELS = 200
    # 256 byte config + (32 bytes × 200 channels) = 6656 bytes
    _memsize = 256 + (32 * CHANNELS)

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_name = True
        rf.valid_name_length = 5
        rf.has_settings = True
        rf.memory_bounds = (1, self.CHANNELS)

        rf.can_odd_split = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_duplexes = ["", "split", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone", "DTCS->", "->DTCS", "Tone->DTCS",
            "DTCS->Tone", "->Tone", "DTCS->DTCS"]

        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.valid_bands = [(400000000, 480000000)]

        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LIST

        return rf

    def get_settings(self):
        """Get radio settings from configuration block"""
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        top = RadioSettings(basic, advanced)

        # Startup Text
        startup_text = ""
        for i in range(5):
            char = int(_settings.startup_text[i])
            if char != 0xFF and 0x20 <= char <= 0x7E:
                startup_text += chr(char)
        rs = RadioSetting(
            "startup_text", "Startup Text",
            RadioSettingValueString(0, 5, startup_text))
        basic.append(rs)

        # Language
        lang_idx = (
            int(_settings.language)
            if int(_settings.language) < 3 else 2)
        rs = RadioSetting(
            "language", "Language",
            RadioSettingValueList(LANGUAGE_LIST, current_index=lang_idx))
        basic.append(rs)

        # Beep (bit 7 = on/off, bits 0-6 = volume)
        beep_on = (int(_settings.beep) >> 7) & 1
        rs = RadioSetting(
            "beep", "Beep",
            RadioSettingValueBoolean(bool(beep_on)))
        basic.append(rs)

        beep_vol = int(_settings.beep) & 0x7F
        rs = RadioSetting(
            "beep_volume", "Beep Volume",
            RadioSettingValueInteger(0, 15, beep_vol))
        basic.append(rs)

        # Squelch Level
        squelch_idx = (
            int(_settings.squelch)
            if int(_settings.squelch) < 10 else 5)
        rs = RadioSetting(
            "squelch", "Squelch Level",
            RadioSettingValueList(SQUELCH_LIST, current_index=squelch_idx))
        basic.append(rs)

        # MIC Gain
        rs = RadioSetting(
            "mic_gain", "Microphone Gain",
            RadioSettingValueInteger(0, 31, int(_settings.mic_gain)))
        advanced.append(rs)

        # RX Volume
        rs = RadioSetting(
            "rx_volume", "RX Volume",
            RadioSettingValueInteger(1, 63, int(_settings.rx_volume)))
        basic.append(rs)

        # VOX (bit 7 = on/off, bits 0-6 = delay)
        vox_on = (int(_settings.vox) >> 7) & 1
        rs = RadioSetting(
            "vox", "VOX",
            RadioSettingValueBoolean(bool(vox_on)))
        advanced.append(rs)

        vox_delay = int(_settings.vox) & 0x7F
        vox_delay_idx = vox_delay if vox_delay < 10 else 0
        rs = RadioSetting(
            "vox_delay", "VOX Delay",
            RadioSettingValueList(VOX_DELAY_LIST, current_index=vox_delay_idx))
        advanced.append(rs)

        # VOX Threshold
        rs = RadioSetting(
            "vox_threshold", "VOX Threshold",
            RadioSettingValueInteger(1, 255,
                                     int(_settings.vox_threshold)))
        advanced.append(rs)

        # Battery Save
        save_idx = (
            int(_settings.battery_save)
            if int(_settings.battery_save) < 5 else 0)
        rs = RadioSetting(
            "battery_save", "Battery Save",
            RadioSettingValueList(BAT_SAVE_LIST, current_index=save_idx))
        advanced.append(rs)

        # Key Lock (bit 7 = on/off, bits 0-6 = timeout)
        lock_on = (int(_settings.keylock) >> 7) & 1
        rs = RadioSetting(
            "key_lock", "Key Lock",
            RadioSettingValueBoolean(bool(lock_on)))
        advanced.append(rs)

        lock_timeout = int(_settings.keylock) & 0x7F
        lock_timeout_idx = lock_timeout if lock_timeout < 43 else 0
        rs = RadioSetting(
            "lock_timeout", "Lock Timeout (sec)",
            RadioSettingValueList(KEYLOCK_TIMEOUT_LIST,
                                  current_index=lock_timeout_idx))
        advanced.append(rs)

        # Backlight Level (bits 6-7)
        light_idx = (int(_settings.backlight) >> 6) & 0x03
        light_idx = light_idx if light_idx < 3 else 1
        rs = RadioSetting(
            "backlight", "Backlight Level",
            RadioSettingValueList(LED_LIST, current_index=light_idx))
        basic.append(rs)

        # Backlight Timeout (bits 0-5)
        light_timeout = int(_settings.backlight) & 0x3F
        light_timeout_idx = light_timeout if light_timeout < 43 else 0
        rs = RadioSetting(
            "backlight_timeout", "Backlight Timeout (sec)",
            RadioSettingValueList(BACKLIGHT_TIMEOUT_LIST,
                                  current_index=light_timeout_idx))
        basic.append(rs)

        # TOT (bits 0-6)
        tot = int(_settings.roger_tot) & 0x7F
        tot_idx = tot if tot < 43 else 0
        rs = RadioSetting(
            "tot", "Time-Out Timer (sec)",
            RadioSettingValueList(TOT_TIMER_LIST, current_index=tot_idx))
        advanced.append(rs)

        # Roger Beep (bit 7)
        roger = (int(_settings.roger_tot) >> 7) & 1
        rs = RadioSetting(
            "roger", "Roger Beep",
            RadioSettingValueBoolean(bool(roger)))
        advanced.append(rs)

        # Frequency Band Limits
        rs = RadioSetting(
            "freq_lower_limit", "Lower Frequency Limit (MHz)",
            RadioSettingValueInteger(400, 480,
                                     int(_settings.freq_lower_limit)))
        advanced.append(rs)

        rs = RadioSetting(
            "freq_upper_limit", "Upper Frequency Limit (MHz)",
            RadioSettingValueInteger(400, 480,
                                     int(_settings.freq_upper_limit)))
        advanced.append(rs)

        # Channel Limit (Max accessible channels: 1-200)
        channel_limit = int(_settings.channel_limit)
        # Ensure value is in valid range (1-200), default to 200 if invalid
        if channel_limit < 1 or channel_limit > 200:
            channel_limit = 200
        rs = RadioSetting(
            "channel_limit", "Channel Limit (Max Channels)",
            RadioSettingValueInteger(1, 200, channel_limit))
        advanced.append(rs)

        # Alarm Mode (no "Off" option in official software)
        alarm_idx = int(_settings.alarm) if int(_settings.alarm) < 3 else 0
        rs = RadioSetting(
            "alarm", "Alarm Mode",
            RadioSettingValueList(ALARM_LIST, current_index=alarm_idx))
        advanced.append(rs)

        # Auto Power Off (APO)
        apo_idx = (
            int(_settings.apo) if int(_settings.apo) < 201 else 0)
        rs = RadioSetting(
            "apo", "Auto Power Off (minutes)",
            RadioSettingValueList(APO_LIST, current_index=apo_idx))
        advanced.append(rs)

        # Channel Display Mode
        disp_idx = (
            int(_settings.channel_display)
            if int(_settings.channel_display) < 2 else 0)
        rs = RadioSetting(
            "channel_display", "Channel Display",
            RadioSettingValueList(DISPLAY_MODE_LIST, current_index=disp_idx))
        basic.append(rs)

        # Menu Timeout
        menu_timeout_idx = (
            int(_settings.menu_timeout)
            if int(_settings.menu_timeout) < 43 else 0)
        rs = RadioSetting(
            "menu_timeout", "Menu Timeout (sec)",
            RadioSettingValueList(MENU_TIMEOUT_LIST,
                                  current_index=menu_timeout_idx))
        advanced.append(rs)

        # Current Channel (Startup Channel) - 0-based storage,
        # 1-based display
        current_ch = int(_settings.current_channel) + 1
        # Convert 0-199 to 1-200
        current_ch = current_ch if 1 <= current_ch <= 200 else 1
        rs = RadioSetting(
            "current_channel", "Startup Channel",
            RadioSettingValueInteger(1, 200, current_ch))
        basic.append(rs)

        # Side Key Function (Key 2 Press Long)
        key_idx = (
            int(_settings.key_function)
            if int(_settings.key_function) < 10 else 0)
        rs = RadioSetting(
            "key_function", "Side Key Function (Long Press)",
            RadioSettingValueList(KEY_FUNCTION_LIST, current_index=key_idx))
        advanced.append(rs)

        return top

    def set_settings(self, settings):
        """Write settings to configuration block"""
        _settings = self._memobj.settings

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            try:
                name = element.get_name()
                value = element.value

                if name == "startup_text":
                    text = str(value).strip()[:5]
                    for i in range(5):
                        if i < len(text):
                            _settings.startup_text[i] = ord(text[i])
                        else:
                            _settings.startup_text[i] = 0xFF

                elif name == "language":
                    _settings.language = LANGUAGE_LIST.index(str(value))

                elif name == "beep":
                    beep_val = int(_settings.beep)
                    if value.get_value():
                        beep_val |= 0x80
                    else:
                        beep_val &= 0x7F
                    _settings.beep = beep_val

                elif name == "beep_volume":
                    _settings.beep = (
                        (int(_settings.beep) & 0x80) |
                        (int(value) & 0x7F))

                elif name == "squelch":
                    _settings.squelch = SQUELCH_LIST.index(str(value))

                elif name == "mic_gain":
                    _settings.mic_gain = int(value)

                elif name == "rx_volume":
                    _settings.rx_volume = int(value)

                elif name == "vox":
                    vox_val = int(_settings.vox)
                    if value.get_value():
                        vox_val |= 0x80
                    else:
                        vox_val &= 0x7F
                    _settings.vox = vox_val

                elif name == "vox_delay":
                    _settings.vox = (
                        (int(_settings.vox) & 0x80) |
                        (VOX_DELAY_LIST.index(str(value)) & 0x7F))

                elif name == "vox_threshold":
                    _settings.vox_threshold = int(value)

                elif name == "battery_save":
                    _settings.battery_save = BAT_SAVE_LIST.index(str(value))

                elif name == "key_lock":
                    lock_val = int(_settings.keylock)
                    if value.get_value():
                        lock_val |= 0x80
                    else:
                        lock_val &= 0x7F
                    _settings.keylock = lock_val

                elif name == "lock_timeout":
                    _settings.keylock = (
                        (int(_settings.keylock) & 0x80) |
                        (KEYLOCK_TIMEOUT_LIST.index(str(value)) & 0x7F))

                elif name == "backlight":
                    light_idx = LED_LIST.index(str(value))
                    _settings.backlight = (
                        (int(_settings.backlight) & 0x3F) |
                        (light_idx << 6))

                elif name == "backlight_timeout":
                    _settings.backlight = (
                        (int(_settings.backlight) & 0xC0) |
                        (BACKLIGHT_TIMEOUT_LIST.index(str(value)) &
                         0x3F))

                elif name == "tot":
                    _settings.roger_tot = (
                        (int(_settings.roger_tot) & 0x80) |
                        (TOT_TIMER_LIST.index(str(value)) & 0x7F))

                elif name == "roger":
                    roger_val = int(_settings.roger_tot)
                    if value.get_value():
                        roger_val |= 0x80
                    else:
                        roger_val &= 0x7F
                    _settings.roger_tot = roger_val

                elif name == "freq_lower_limit":
                    _settings.freq_lower_limit = int(value)

                elif name == "freq_upper_limit":
                    _settings.freq_upper_limit = int(value)

                elif name == "channel_limit":
                    # Channel Limit: valid range is 1-200
                    limit_value = int(value)
                    if limit_value < 1 or limit_value > 200:
                        raise ValueError(
                            "Channel Limit must be between 1 and 200")
                    _settings.channel_limit = limit_value

                elif name == "alarm":
                    _settings.alarm = ALARM_LIST.index(str(value))

                elif name == "apo":
                    _settings.apo = APO_LIST.index(str(value))

                elif name == "channel_display":
                    _settings.channel_display = DISPLAY_MODE_LIST.index(
                        str(value))

                elif name == "menu_timeout":
                    _settings.menu_timeout = MENU_TIMEOUT_LIST.index(
                        str(value))

                elif name == "current_channel":
                    # Convert 1-200 to 0-199
                    _settings.current_channel = int(value) - 1

                elif name == "key_function":
                    _settings.key_function = KEY_FUNCTION_LIST.index(
                        str(value))

            except Exception as e:
                raise errors.RadioError(
                    "Error setting %s: %s" % (name, str(e)))

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

        # V2 uses 32-bit frequency, check if channel is empty (all 0xFF)
        if _mem.rx_freq == 0xFFFFFFFF:
            mem.empty = True
        else:
            # Frequency storage: radio stores in 10 Hz units, convert to Hz
            mem.freq = int(_mem.rx_freq) * FREQ_UNIT
            tx_freq = int(_mem.tx_freq) * FREQ_UNIT

            # Determine duplex mode
            if tx_freq == 0:
                mem.duplex = "off"
            elif mem.freq == tx_freq:
                mem.duplex = ""
            else:
                mem.duplex = "split"
                mem.offset = tx_freq

            # Decode tones using V2 format
            txtone = decode_tone(_mem.tx_tone)
            rxtone = decode_tone(_mem.rx_tone)
            chirp_common.split_tone_decode(mem, txtone, rxtone)

            # Decode channel name (5 ASCII chars, 0xFF padded)
            name = ""
            for i in range(5):
                char = int(_mem.name[i])
                if char != 0xFF and 0x20 <= char <= 0x7E:
                    name += chr(char)
                else:
                    break
            mem.name = name.rstrip()

        mem.mode = "NFM" if not mem.empty and _mem.nfm else "FM"
        # power bit: 0=high, 1=low
        mem.power = POWER_LIST[1 if _mem.power else 0]
        # scan bit: 0=add, 1=skip
        mem.skip = "S" if not mem.empty and _mem.scan else ""

        mem.extra = RadioSettingGroup("Extra", "extra")

        compander = False if mem.empty else _mem.compander
        rsv = RadioSettingValueBoolean(compander)
        rs = RadioSetting("compander", "Compander", rsv)
        mem.extra.append(rs)

        scrambler = 0 if mem.empty else _mem.scrambler
        rsv = RadioSettingValueList(SCRAMBLER_LIST, current_index=scrambler)
        rs = RadioSetting("scrambler", "Scrambler", rsv)
        mem.extra.append(rs)

        # Encryption field
        encryption = 0 if mem.empty else _mem.encryption
        rsv = RadioSettingValueInteger(0, 7, encryption)
        rs = RadioSetting("encryption", "Encryption", rsv)
        mem.extra.append(rs)

        # Busy lock field
        busy = 0 if mem.empty else _mem.busy
        rsv = RadioSettingValueInteger(0, 3, busy)
        rs = RadioSetting("busy", "Busy Lock", rsv)
        mem.extra.append(rs)

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]

        if mem.empty:
            _mem.fill_raw(b"\xff")
        else:
            # Frequency storage: convert from Hz to 10 Hz units
            _mem.rx_freq = int(mem.freq) // FREQ_UNIT

            if mem.duplex == "off":
                _mem.tx_freq = 0
            elif mem.duplex == "split" and mem.offset:
                _mem.tx_freq = int(mem.offset) // FREQ_UNIT
            else:
                _mem.tx_freq = int(mem.freq) // FREQ_UNIT

            # Encode tones using V2 format
            txtone, rxtone = chirp_common.split_tone_encode(mem)
            _mem.tx_tone = encode_tone(*txtone)
            _mem.rx_tone = encode_tone(*rxtone)

            _mem.nfm = (mem.mode == "NFM")
            _mem.scan = (mem.skip == "S")  # scan bit: 0=add, 1=skip

            if mem.power in POWER_LIST:
                # 0=High, 1=Low
                _mem.power = (POWER_LIST.index(mem.power) == 1)
            else:
                # Default to high power (bit 0)
                _mem.power = False

            # Encode channel name (5 ASCII chars, 0xFF padded)
            # Limit to 5 chars
            name = mem.name.strip()[:5]
            for i in range(5):
                if i < len(name):
                    _mem.name[i] = ord(name[i])
                else:
                    _mem.name[i] = 0xFF

            if "compander" in mem.extra:
                _mem.compander = mem.extra["compander"].value.get_value()
            else:
                _mem.compander = False

            if "scrambler" in mem.extra:
                _mem.scrambler = SCRAMBLER_LIST.index(
                    mem.extra["scrambler"].value.get_value())
            else:
                _mem.scrambler = 0

            if "encryption" in mem.extra:
                _mem.encryption = mem.extra["encryption"].value.get_value()
            else:
                _mem.encryption = 0

            if "busy" in mem.extra:
                _mem.busy = mem.extra["busy"].value.get_value()
            else:
                _mem.busy = 0
