# Copyright 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Experimental driver for the QYT KT-A16 air-band radio."""

import logging
import struct

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingValueFloat,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueMap,
    RadioSettingValueString,
    RadioSettings,
)


LOG = logging.getLogger(__name__)

ACK = b"\x06"
MAGIC = b"\x55\x20\x23\x04\x26\xff\xdc\x02"
MODEL_IDENT = b"KT-A16"
BLOCK_SIZE = 0x40
MEM_SIZE = 0x3E00
AIR_BAND = (108000000, 136999751)
WEATHER_BAND = (161650000, 163275001)
AIR_CHANNEL_REMAINDERS = (0, 8330, 8340, 16660, 16670)

TMR_OPTIONS = [
    "OFF", "M+A", "M+B", "M+C", "M+A+B", "M+A+C", "M+B+C",
    "M+A+B+C",
]
SAVE_OPTIONS = ["OFF", "1:1", "1:2", "1:3", "1:4"]
SCAN_RESUME_OPTIONS = ["TO", "CO", "SE"]
DISPLAY_OPTIONS = ["Channel+Frequency", "Channel", "Channel+Name"]
VOICE_OPTIONS = ["OFF", "English", "Chinese"]
TX_TMR_OPTIONS = ["Track", "Fixed"]
SPEAK_MUTE_OPTIONS = [
    "QT/DQT", "QT/DQT AND OPTSIG", "QT/DQT OR OPTSIG",
]
COLOR_OPTIONS = [
    "White", "Red", "Blue", "Green", "Yellow", "Indigo", "Purple",
    "Gray",
]
SHIFT_OPTIONS = ["OFF", "+", "-"]
STEP_OPTIONS = [
    "2.50 kHz", "5.00 kHz", "6.25 kHz", "10.00 kHz", "12.50 kHz",
    "25.00 kHz", "8.33 kHz",
]

TONE_MAP = [("OFF", 0)]
TONE_MAP += [("%.1f" % tone, round(tone * 10))
             for tone in chirp_common.TONES]
TONE_MAP += [("D%03iN" % code, index + 1)
             for index, code in enumerate(chirp_common.DTCS_CODES)]
TONE_MAP += [("D%03iI" % code, index + 106)
             for index, code in enumerate(chirp_common.DTCS_CODES)]

SETTING_BYTE_ADDRESSES = {
    "tmr": 0x0E00,
    "squelch": 0x0E02,
    "vox": 0x0E03,
    "auto_lock": 0x0E04,
    "tot": 0x0E05,
    "save": 0x0E06,
    "abr": 0x0E07,
    "beep": 0x0E08,
    "bcl": 0x0E09,
    "scan_add": 0x0E0A,
    "scan_rev": 0x0E0B,
    "display_a": 0x0E0C,
    "display_b": 0x0E0D,
    "display_c": 0x0E0E,
    "voice": 0x0E0F,
    "st_fc": 0x0E10,
    "mfl_fc": 0x0E11,
    "mfs_fc": 0x0E12,
    "sfa_fc": 0x0E13,
    "sfb_fc": 0x0E14,
    "sfc_fc": 0x0E15,
    "batt_c": 0x0E16,
    "sig_fc": 0x0E17,
    "menufc": 0x0E18,
    "tx_fc": 0x0E19,
    "rx_fc": 0x0E1A,
    "tmr_return": 0x0E1F,
    "tx_tmr": 0x0E20,
    "sql_am": 0x0E21,
    "anl_sw": 0x0E22,
    "vfo_a_speak_mute": 0x0F15,
    "vfo_a_optional_signal": 0x0F16,
    "vfo_a_bandwidth": 0x0F18,
    "vfo_a_power": 0x0F19,
    "vfo_b_speak_mute": 0x0F35,
    "vfo_b_optional_signal": 0x0F36,
    "vfo_b_bandwidth": 0x0F38,
    "vfo_b_power": 0x0F39,
    "vfo_c_speak_mute": 0x0F55,
    "vfo_c_optional_signal": 0x0F56,
    "vfo_c_bandwidth": 0x0F58,
    "vfo_c_power": 0x0F59,
    "vfo_a_shift": 0x0F1A,
    "vfo_b_shift": 0x0F3A,
    "vfo_c_shift": 0x0F5A,
    "vfo_a_step": 0x0F1B,
    "vfo_b_step": 0x0F3B,
    "vfo_c_step": 0x0F5B,
}

SETTING_DOCS = {
    "tmr": (
        "Selects which A, B, and C displays are watched alongside M. M is the "
        "selected channel, indicated by the solid green arrow. OFF means "
        "single-watch; adding displays enables dual-, tri-, or quad-watch."
    ),
    "squelch": (
        "Sets the OEM/FM squelch threshold. This does not control airband AM "
        "squelch; use SQL-AM instead."
    ),
    "vox": (
        "Enables voice-operated transmission and sets its sensitivity. OFF "
        "requires the PTT key. Do not use VOX on aviation frequencies."
    ),
    "auto_lock": (
        "Enables automatic keypad locking to reduce accidental key presses."
    ),
    "tot": (
        "Limits the duration of one continuous transmission. The radio stops "
        "transmitting when the selected time-out period expires."
    ),
    "save": (
        "Selects the battery-save receive duty cycle. Larger ratios save more "
        "power but can delay detection of a short transmission."
    ),
    "abr": (
        "Sets how long the display backlight remains on after radio or keypad "
        "activity. OFF disables automatic backlighting."
    ),
    "beep": "Enables or disables keypad and control confirmation tones.",
    "bcl": (
        "Busy channel lockout. Prevents transmission while the selected "
        "frequency is already receiving a signal."
    ),
    "scan_add": (
        "Controls whether channels stored from the radio are added to the "
        "scan list by default."
    ),
    "scan_rev": (
        "Selects scan resume behavior: TO resumes after a timed pause, CO "
        "resumes after the carrier disappears, and SE stops the scan."
    ),
    "tmr_return": (
        "Sets the delay before returning to the main frequency during "
        "multi-frequency standby. OFF disables the timed return."
    ),
    "tx_tmr": (
        "Selects transmission behavior during multi-frequency standby. Track "
        "transmits on the currently selected sub-frequency; Fixed retains the "
        "main transmit frequency."
    ),
    "sql_am": (
        "Sets the AM airband squelch threshold. Lower values admit weaker "
        "signals and more noise; higher values require a stronger signal."
    ),
    "anl_sw": (
        "Automatic Noise Limiter. Reduces short impulsive noise such as "
        "ignition interference during AM reception."
    ),
    "active_slot": (
        "Shows which frequency-mode slot was active when the image was read. "
        "Change the active slot with the radio controls."
    ),
    "display_a": "Selects how memory channels are shown in display slot A.",
    "display_b": "Selects how memory channels are shown in display slot B.",
    "display_c": "Selects how memory channels are shown in display slot C.",
    "voice": (
        "Selects the spoken voice-prompt language, or disables voice prompts."
    ),
    "st_fc": "Sets the color of text in the upper status area.",
    "mfl_fc": "Sets the color of the main frequency text.",
    "mfs_fc": "Sets the color of the smaller main-frequency text.",
    "sfa_fc": "Sets the text color used for channel/frequency display A.",
    "sfb_fc": "Sets the text color used for channel/frequency display B.",
    "sfc_fc": "Sets the text color used for channel/frequency display C.",
    "batt_c": "Sets the color of the battery-voltage text.",
    "sig_fc": "Sets the color of the lower status and signal area.",
    "menufc": "Sets the text color used while viewing the radio menu.",
    "tx_fc": "Sets the active-channel display color while transmitting.",
    "rx_fc": (
        "Sets the active-channel display color while receiving a carrier."
    ),
    "model_name": (
        "Sets the model/identity text stored by the radio. Up to 15 letters, "
        "numbers, spaces, periods, dashes, or colons are supported."
    ),
}

VFO_SETTING_DOCS = {
    "frequency": (
        "Operating frequency for frequency-mode slot {slot}, in MHz. The "
        "receive range is 108.00000-136.99975 MHz and the transmit range is "
        "118.00000-136.99975 MHz."
    ),
    "rx_tone": (
        "Receive CTCSS/DCS filter for frequency-mode slot {slot}. Aviation AM "
        "does not use CTCSS or DCS, so leave this OFF."
    ),
    "tx_tone": (
        "Transmit CTCSS/DCS tone for frequency-mode slot {slot}. Aviation AM "
        "does not use CTCSS or DCS, so leave this OFF."
    ),
    "speak_mute": (
        "Selects which tone and optional-signal conditions open the speaker "
        "for frequency-mode slot {slot}. Aviation AM does not use these "
        "signaling systems; select QT/DQT and leave both tone controls OFF."
    ),
    "optional_signal": (
        "Enables the optional FSK signaling function for frequency-mode slot "
        "{slot}. Aviation AM voice communication does not use this signaling, "
        "so leave it OFF."
    ),
    "bandwidth": (
        "Selects the stored WIDE/NARROW mode for frequency-mode slot {slot}. "
        "On this radio it does not select 25 kHz versus 8.33 kHz airband "
        "channel spacing, and its practical AM effect is uncertain."
    ),
    "power": (
        "Stores HIGH or LOW transmitter power for frequency-mode slot "
        "{slot}. The actual effect of this setting on the KT-A16 is "
        "uncertain."
    ),
    "shift": (
        "Applies no offset, a positive offset, or a negative offset to the "
        "transmit frequency for slot {slot}. Aviation AM voice channels are "
        "simplex, so leave this OFF."
    ),
    "offset": (
        "Transmit-frequency offset for slot {slot}, in MHz. It is applied in "
        "the direction selected by Shift. Aviation AM voice channels are "
        "simplex, so leave the main shift (SFT-D) setting off."
    ),
    "step": (
        "Tuning increment used when changing frequency in slot {slot}. The "
        "8.33 kHz choice controls tuning steps; the radio stores an actual "
        "frequency rather than an ICAO 8.33 kHz channel designator."
    ),
}


def _setting_doc(name):
    if name in SETTING_DOCS:
        return SETTING_DOCS[name]
    if name.startswith("vfo_"):
        _, slot, field = name.split("_", 2)
        if field in VFO_SETTING_DOCS:
            return VFO_SETTING_DOCS[field].format(slot=slot.upper())
    raise errors.RadioError("Missing help text for setting %s" % name)


def _apply_setting_docs(group):
    for element in group:
        if isinstance(element, RadioSetting):
            element.set_doc(_setting_doc(element.get_name()))
        else:
            _apply_setting_docs(element)


def _mode_for_frequency(frequency):
    if AIR_BAND[0] <= frequency < AIR_BAND[1]:
        return "AM"
    if WEATHER_BAND[0] <= frequency < WEATHER_BAND[1]:
        return "FM"
    return None


def _frequency_grid_error(frequency):
    mode = _mode_for_frequency(frequency)
    if mode is None:
        return (
            "Frequency %s MHz is outside the KT-A16 receive bands"
            % chirp_common.format_freq(frequency)
        )

    allowed = AIR_CHANNEL_REMAINDERS if mode == "AM" else (0,)
    if frequency % 25000 in allowed:
        return None

    preferred = (0, 8330, 16670) if mode == "AM" else (0,)
    base = frequency // 25000 * 25000
    candidates = [
        block + remainder
        for block in (base - 25000, base, base + 25000)
        for remainder in preferred
    ]
    nearest = min(candidates, key=lambda candidate: abs(candidate - frequency))
    if mode == "AM":
        spacing = (
            "Airband memories must be on a 25 kHz or 8.33 kHz channel "
            "frequency (8.33 kHz rounding forms such as 123.06666 and "
            "123.06667 MHz are accepted). Enter the actual carrier "
            "frequency, not an 8.33 kHz channel designator such as 119.210"
        )
    else:
        spacing = "Weather-band FM memories must be on a 25 kHz channel"
    return "%s. Nearest supported frequency: %s MHz" % (
        spacing, chirp_common.format_freq(nearest))


def _list_setting(name, label, options, current_index):
    options = list(options)
    if current_index >= len(options):
        options.append("Unknown (%i)" % current_index)
        current_index = len(options) - 1
    return RadioSetting(
        name, label,
        RadioSettingValueList(options, current_index=current_index))


def _read_only_setting(name, label, value):
    value.set_mutable(False)
    return RadioSetting(name, label, value)


def _read_only_list(name, label, options, current_index):
    options = list(options)
    if current_index >= len(options):
        options.append("Unknown (%i)" % current_index)
        current_index = len(options) - 1
    return _read_only_setting(
        name, label,
        RadioSettingValueList(options, current_index=current_index))


# The OEM channel editor reads 0x0000-0x0CBF and 0x1000-0x1CBF,
# interleaving the two regions in 64-byte blocks.
CHANNEL_READ_ADDRESSES = tuple(
    address
    for low_address in range(0x0000, 0x0CC0, BLOCK_SIZE)
    for address in (low_address, low_address + 0x1000)
)

# The OEM settings editor reads a separate contiguous 512-byte region.
SETTINGS_READ_ADDRESSES = tuple(range(0x0E00, 0x1000, BLOCK_SIZE))

READ_ADDRESSES = CHANNEL_READ_ADDRESSES + SETTINGS_READ_ADDRESSES

CHANNEL_WRITE_ADDRESSES = tuple(
    address
    for low_address in range(0x0000, 0x0C90, 0x10)
    for address in (low_address, low_address + 0x1000)
)
SETTINGS_WRITE_ADDRESSES = tuple(range(0x0E00, 0x1000, 0x10))
SETTINGS_WRITE_MARKER_ADDRESS = 0x3B90
SETTINGS_WRITE_MARKER = bytes.fromhex(
    "20 12 23 34 45 56 67 78 00 00 00 00 00 00 00 FF")

MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  u8 decode_tone[2];
  u8 encode_tone[2];
  u8 options[4];
} memory[200];

#seekto 0x1000;
struct {
  char name[6];
  u8 unknown[10];
} names[200];
"""


def _read_exact(radio, count, description):
    data = b""
    while len(data) < count:
        chunk = radio.pipe.read(count - len(data))
        if not chunk:
            raise errors.RadioError(
                "Short read while receiving %s (%i/%i bytes)" %
                (description, len(data), count))
        data += chunk
    return data


def _read_block(radio, address, size):
    """Read a block using the KT-A16's ACK-split final byte."""
    radio.pipe.write(struct.pack(">cHB", b"S", address, size))

    # The radio sends the header and all but the last data byte, then waits
    # for ACK. After ACK it sends the final data byte and its own ACK.
    first = _read_exact(radio, 4 + size - 1,
                        "block 0x%04X" % address)
    command, response_address, response_size = struct.unpack(
        ">cHB", first[:4])
    if (command != b"X" or response_address != address or
            response_size != size):
        raise errors.RadioError(
            "Invalid response header for block 0x%04X" % address)

    radio.pipe.write(ACK)
    tail = _read_exact(radio, 2, "block trailer 0x%04X" % address)
    if tail[1:] != ACK:
        raise errors.RadioError(
            "Radio did not ACK block 0x%04X" % address)
    return first[4:] + tail[:1]


def _identify(radio):
    radio.pipe.baudrate = 9600
    radio.pipe.parity = "N"
    radio.pipe.timeout = 1.5
    radio.pipe.reset_input_buffer()

    radio.pipe.write(MAGIC)
    ident = _read_exact(radio, 49, "identification")
    LOG.debug("KT-A16 identification response (%i bytes): %s",
              len(ident), ident.hex(" "))
    if ident[:1] != ACK or MODEL_IDENT not in ident:
        LOG.debug("Unexpected KT-A16 identification: %r", ident)
        raise errors.RadioError("Radio identification failed")

    # Captured OEM sequence: acknowledge identification, receive 0x05,
    # then read the additional identification block at 0x3DF0.
    radio.pipe.write(ACK)
    preamble = _read_exact(radio, 1, "identification acknowledgement")
    if preamble == b"\x55":
        preamble += _read_exact(
            radio, 1, "identification acknowledgement trailer")
    LOG.debug("KT-A16 post-identification bytes: %s", preamble.hex(" "))
    if preamble not in (b"\x05", b"\x55\x05"):
        raise errors.RadioError(
            "Unexpected identification acknowledgement 0x%s" %
            preamble.hex())

    return _read_block(radio, 0x3DF0, 0x10)


def _download(radio):
    status = chirp_common.Status()
    status.msg = "Cloning from radio..."
    status.max = len(READ_ADDRESSES)
    status.cur = 0

    memory = memmap.MemoryMapBytes(b"\xFF" * MEM_SIZE)
    probe = _identify(radio)
    memory.set(0x3DF0, probe)

    for index, address in enumerate(READ_ADDRESSES, 1):
        memory.set(address, _read_block(radio, address, BLOCK_SIZE))
        status.cur = index
        radio.status_fn(status)

    return memory


def _identify_upload(radio):
    radio.pipe.baudrate = 9600
    radio.pipe.parity = "N"
    radio.pipe.timeout = 1.5
    radio.pipe.reset_input_buffer()

    radio.pipe.write(MAGIC)
    ident = _read_exact(radio, 49, "identification")
    if ident[:1] != ACK or MODEL_IDENT not in ident:
        raise errors.RadioError("Radio identification failed")

    radio.pipe.write(ACK)
    trailer = _read_exact(radio, 2, "identification trailer")
    if trailer != b"\x55\x05":
        raise errors.RadioError(
            "Unexpected identification trailer 0x%s" % trailer.hex())

    radio.pipe.write(struct.pack(">cHB", b"S", 0x3DF0, 0x10))
    probe = _read_exact(radio, 20, "upload probe")
    command, address, size = struct.unpack(">cHB", probe[:4])
    if command != b"X" or address != 0x3DF0 or size != 0x10:
        raise errors.RadioError("Invalid upload probe response")


def _write_block(radio, address, payload):
    frame = ACK + struct.pack(">cHB", b"X", address, len(payload)) + payload
    radio.pipe.write(frame)
    response = _read_exact(
        radio, 1, "write acknowledgement 0x%04X" % address)
    if response != ACK:
        raise errors.RadioError(
            "Radio did not ACK write at 0x%04X" % address)


def _upload(radio):
    _identify_upload(radio)

    image = radio.get_mmap().get_byte_compatible()
    settings = image[0x0E00:0x1000]
    write_settings = settings != b"\xFF" * len(settings)
    settings_count = len(SETTINGS_WRITE_ADDRESSES) + 1 if write_settings else 0

    status = chirp_common.Status()
    status.msg = "Cloning to radio..."
    status.max = len(CHANNEL_WRITE_ADDRESSES) + settings_count
    status.cur = 0

    for address in CHANNEL_WRITE_ADDRESSES:
        _write_block(radio, address, image[address:address + 0x10])
        status.cur += 1
        radio.status_fn(status)

    if write_settings:
        _write_block(
            radio, SETTINGS_WRITE_MARKER_ADDRESS, SETTINGS_WRITE_MARKER)
        status.cur += 1
        radio.status_fn(status)

        for address in SETTINGS_WRITE_ADDRESSES:
            _write_block(radio, address, image[address:address + 0x10])
            status.cur += 1
            radio.status_fn(status)


@directory.register
class QYTKTA16Radio(chirp_common.CloneModeRadio,
                    chirp_common.ExperimentalRadio):
    """QYT KT-A16 air-band radio."""

    VENDOR = "QYT"
    MODEL = "KT-A16"
    BAUD_RATE = 9600

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = (
            "This driver is experimental. Keep a backup made with the "
            "manufacturer software before writing to the radio.")
        prompts.pre_download = _(
            "Turn the radio off, connect the programming cable, turn the "
            "radio on, dismiss the blue warning screen with the MENU button, "
            "and start the download.")
        prompts.pre_upload = _(
            "Turn the radio off, connect the programming cable, turn the "
            "radio on, dismiss the blue warning screen with the MENU button, "
            "and start the upload. Do not interrupt the write.")
        return prompts

    def get_features(self):
        features = chirp_common.RadioFeatures()
        features.has_bank = False
        features.has_settings = True
        features.has_name = True
        features.has_offset = False
        features.has_mode = True
        features.has_tuning_step = False
        features.has_nostep_tuning = True
        features.has_ctone = False
        features.has_dtcs = False
        features.has_rx_dtcs = False
        features.has_dtcs_polarity = False
        features.has_cross = False
        features.memory_bounds = (0, 199)
        features.valid_bands = [AIR_BAND, WEATHER_BAND]
        features.valid_modes = ["FM", "AM"]
        features.valid_tmodes = []
        features.valid_tones = []
        features.valid_tuning_steps = []
        features.valid_duplexes = []
        features.valid_name_length = 6
        features.valid_skips = ["", "S"]
        return features

    def sync_in(self):
        try:
            self._mmap = _download(self)
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                "Failed to communicate with the radio: %s" % exc)

    def sync_out(self):
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                "Failed to communicate with the radio: %s" % exc)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_settings(self):
        """Return confirmed KT-A16 settings as read-only values."""
        data = self._mmap.get_byte_compatible()

        def byte(address):
            return data.get(address, 1)[0]

        def word(address):
            return struct.unpack("<H", data.get(address, 2))[0]

        general = RadioSettingGroup("general", "General")
        display = RadioSettingGroup("display", "Display")
        vfo = RadioSettingGroup("vfo", "Frequency Slots")

        general.append(_list_setting(
            "tmr", "Tuned Memory Channels (TMR)",
            TMR_OPTIONS, byte(0x0E00)))
        general.append(RadioSetting(
            "squelch", "FM Squelch Level (SQL-FM)",
            RadioSettingValueInteger(0, 9, byte(0x0E02))))
        general.append(_list_setting(
            "auto_lock", "Automatic Keypad Lock (AUTOLK)",
            ["OFF", "ON"], byte(0x0E04)))
        general.append(_list_setting(
            "tot", "Time-Out Timer (TOT)",
            ["OFF"] + ["%i seconds" % x for x in range(15, 601, 15)],
            byte(0x0E05)))
        general.append(_list_setting(
            "save", "Battery Save (SAVE)", SAVE_OPTIONS, byte(0x0E06)))
        general.append(_list_setting(
            "abr", "Automatic Backlight (ABR)",
            ["OFF"] + ["%i seconds" % x for x in range(5, 47)],
            byte(0x0E07)))
        general.append(_list_setting(
            "beep", "Key Beep (BEEP)", ["OFF", "ON"], byte(0x0E08)))
        general.append(_list_setting(
            "bcl", "Busy Channel Lockout (BCL)", ["OFF", "ON"],
            byte(0x0E09)))
        general.append(_list_setting(
            "scan_add", "Scan-List Default (SC-ADD)",
            ["OFF", "ON"], byte(0x0E0A)))
        general.append(_list_setting(
            "scan_rev", "Scan Resume Mode (SC-REV)",
            SCAN_RESUME_OPTIONS, byte(0x0E0B)))
        general.append(_list_setting(
            "tmr_return", "Main-Frequency Return Delay (TMR-MR)",
            ["OFF"] + ["%i seconds" % x for x in range(1, 51)],
            byte(0x0E1F)))
        general.append(_list_setting(
            "tx_tmr", "TMR Transmit Selection (TMR-TX)", TX_TMR_OPTIONS,
            byte(0x0E20)))
        general.append(RadioSetting(
            "sql_am", "AM Squelch Level (SQL-AM)",
            RadioSettingValueInteger(0, 16, byte(0x0E21))))
        general.append(_list_setting(
            "anl_sw", "Automatic Noise Limiter (ANL-SW)",
            ["OFF", "ON"], byte(0x0E22)))
        general.append(_read_only_list(
            "active_slot", "Active Slot", ["A", "B", "C"],
            byte(0x0E7C)))

        for offset, slot in enumerate("ABC"):
            display.append(_list_setting(
                "display_%s" % slot.lower(),
                "Channel %s Display (C%s-MDF)" % (slot, slot),
                DISPLAY_OPTIONS, byte(0x0E0C + offset)))

        general.append(RadioSetting(
            "vox", "Voice-Operated Transmission (VOX)",
            RadioSettingValueInteger(0, 7, byte(0x0E03))))
        general.append(_list_setting(
            "voice", "Voice Prompts (VOICE)", VOICE_OPTIONS, byte(0x0E0F)))

        color_names = [
            ("st_fc", "Top status text color (ST-FC)"),
            ("mfl_fc", "Main frequency text color (MFL-FC)"),
            ("mfs_fc", "Main frequency small text color (MFS-FC)"),
            ("sfa_fc", "Channel A text color (SFA-FC)"),
            ("sfb_fc", "Channel B text color (SFB-FC)"),
            ("sfc_fc", "Channel C text color (SFC-FC)"),
            ("batt_c", "Battery voltage text color (BATT-C)"),
            ("sig_fc", "Bottom status bar color (SIG-FC)"),
            ("menufc", "Menu text color (MENUFC)"),
            ("tx_fc", "Active channel transmit color (TX-FC)"),
            ("rx_fc", "Active channel receive color (RX-FC)"),
        ]
        for offset, (name, label) in enumerate(color_names):
            display.append(_list_setting(
                name, label, COLOR_OPTIONS, byte(0x0E10 + offset)))

        for slot_index, slot in enumerate("ABC"):
            base = 0x0F00 + slot_index * 0x20
            group = RadioSettingGroup(
                "vfo_%s" % slot.lower(), "Slot %s" % slot)
            frequency_digits = [byte(base + i) for i in range(5)]
            frequency = int("".join(
                str(digit) for digit in frequency_digits)) / 100.0
            group.append(RadioSetting(
                "vfo_%s_frequency" % slot.lower(), "Frequency in MHz (FREQ)",
                RadioSettingValueFloat(
                    108.0, 136.99, frequency, resolution=0.01,
                    precision=5)))
            group.append(_list_setting(
                "vfo_%s_step" % slot.lower(), "Tuning Step (STEP)",
                STEP_OPTIONS, byte(base + 0x1B)))
            group.append(RadioSetting(
                "vfo_%s_rx_tone" % slot.lower(), "RX QT/DQT",
                RadioSettingValueMap(TONE_MAP, mem_val=word(base + 0x10))))
            group.append(RadioSetting(
                "vfo_%s_tx_tone" % slot.lower(), "TX QT/DQT",
                RadioSettingValueMap(TONE_MAP, mem_val=word(base + 0x12))))
            group.append(_list_setting(
                "vfo_%s_speak_mute" % slot.lower(),
                "Speaker Mute Logic (SPMUTE)",
                SPEAK_MUTE_OPTIONS, byte(base + 0x15)))
            group.append(_list_setting(
                "vfo_%s_optional_signal" % slot.lower(),
                "Optional Signaling (OPTSIG)",
                ["OFF", "FSK"], byte(base + 0x16)))
            group.append(_list_setting(
                "vfo_%s_bandwidth" % slot.lower(), "W/N",
                ["WIDE", "NARROW"], byte(base + 0x18)))
            group.append(_list_setting(
                "vfo_%s_power" % slot.lower(), "Transmit Power (TXP)",
                ["HIGH", "LOW"], byte(base + 0x19)))
            group.append(_list_setting(
                "vfo_%s_shift" % slot.lower(), "Shift Direction (SFT-D)",
                SHIFT_OPTIONS, byte(base + 0x1A)))
            offset_digits = [byte(base + 0x09 + i) for i in range(5)]
            offset = int("".join(
                str(digit) for digit in offset_digits)) / 1000.0
            group.append(RadioSetting(
                "vfo_%s_offset" % slot.lower(),
                "Transmit Offset in MHz (OFFSET)",
                RadioSettingValueFloat(
                    0.0, 99.95, offset, resolution=0.05, precision=3)))
            vfo.append(group)

        model = data.get(0x0FE0, 16).decode("ascii", errors="replace")
        model = model.rstrip("\x00\xFF ")
        display.append(RadioSetting(
            "model_name", "Model Text (MODEL)",
            RadioSettingValueString(
                0, 15, model, autopad=False,
                charset=(chirp_common.CHARSET_ALPHANUMERIC + " -.:"))))

        settings = RadioSettings(general, display, vfo)
        _apply_setting_docs(settings)
        return settings

    def set_settings(self, settings):
        """Apply confirmed settings changes to the downloaded image."""
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue

            name = element.get_name()
            if name == "model_name":
                model = str(element.value).ljust(16).encode("ascii")
                self._mmap.set(0x0FE0, model)
                continue
            if name.startswith("vfo_") and name.endswith("_tone"):
                slot = "abc".index(name[4])
                base = 0x0F00 + slot * 0x20
                tone_offset = 0x10 if "_rx_tone" in name else 0x12
                self._mmap.set(
                    base + tone_offset, struct.pack("<H", int(element.value)))
                continue
            if name.startswith("vfo_") and name.endswith("_frequency"):
                slot = "abc".index(name[4])
                base = 0x0F00 + slot * 0x20
                digits = "%05i" % round(float(element.value) * 100)
                for offset, digit in enumerate(digits):
                    self._mmap.set(base + offset, int(digit))
                continue
            if name.startswith("vfo_") and name.endswith("_offset"):
                slot = "abc".index(name[4])
                base = 0x0F00 + slot * 0x20
                digits = "%05i" % round(float(element.value) * 1000)
                for offset, digit in enumerate(digits):
                    self._mmap.set(base + 0x09 + offset, int(digit))
                continue

            address = SETTING_BYTE_ADDRESSES.get(name)
            if address is None:
                LOG.warning("Ignoring unconfirmed setting change: %s", name)
                continue
            self._mmap.set(address, int(element.value))

    def get_raw_memory(self, number):
        return "%s\n%s" % (
            repr(self._memobj.memory[number]),
            repr(self._memobj.names[number]))

    def get_memory(self, number):
        raw = self._memobj.memory[number]
        raw_name = self._memobj.names[number]

        memory = chirp_common.Memory()
        memory.number = number
        memory.empty = raw.rx_freq.get_raw() == b"\xFF\xFF\xFF\xFF"
        if memory.empty:
            return memory

        memory.freq = int(raw.rx_freq) * 10
        memory.duplex = ""
        memory.offset = 0

        memory.name = str(raw_name.name).rstrip("\x00\xFF ").lstrip()
        memory.skip = "" if int(raw.options[3]) & 0x04 else "S"
        memory.mode = _mode_for_frequency(memory.freq)
        return memory

    def validate_memory(self, memory):
        messages = []
        in_range = chirp_common.in_range
        if (in_range(memory.freq, [AIR_BAND]) and
                memory.mode != "AM"):
            messages.append(chirp_common.ValidationWarning(
                "Frequency in this range requires AM mode"))
        if (not in_range(memory.freq, [AIR_BAND]) and
                memory.mode == "AM"):
            messages.append(chirp_common.ValidationWarning(
                "Frequency in this range must not be AM mode"))
        messages += super().validate_memory(memory)
        if not memory.empty:
            message = _frequency_grid_error(memory.freq)
            if message:
                messages.append(chirp_common.ValidationError(message))
        return messages

    def set_memory(self, memory):
        raw = self._memobj.memory[memory.number]
        raw_name = self._memobj.names[memory.number]
        was_empty = raw.rx_freq.get_raw() == b"\xFF\xFF\xFF\xFF"

        if memory.empty:
            raw.set_raw(b"\xFF" * 16)
            raw_name.set_raw(b"\xFF" * 16)
            return

        frequency_error = _frequency_grid_error(memory.freq)
        if frequency_error:
            raise errors.RadioError(frequency_error)

        if was_empty:
            raw.set_raw(b"\xFF" * 12 + b"\x00\x00\x00\x00")

        raw.rx_freq = memory.freq // 10
        raw.tx_freq = memory.freq // 10

        options = bytearray(raw.options.get_raw())
        if memory.skip:
            options[3] &= ~0x04
        else:
            options[3] |= 0x04
        raw.options.set_raw(bytes(options))

        try:
            name = memory.name.encode("ascii")
        except UnicodeEncodeError:
            raise errors.RadioError(
                "Channel names must contain ASCII characters only")
        if len(name) > 6:
            raise errors.RadioError(
                "Channel names may contain at most 6 characters")
        if name or not was_empty:
            raw_name.name.set_raw(name.rjust(6, b" "))
