# Copyright 2026 Bastien Cabay <bastien@cabay.eu>
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

"""Yaesu FT-991A driver

The FT-991A has no clone mode, so this is a live driver: memories and
menu items are read and written one at a time with the CAT commands
described in the "FT-991A CAT Operation Reference Manual", as they are
edited.

Some things the manual does not say, as observed on a real radio:

 - The channel number in the answer to MT is the channel the radio is
   currently on, not the one that was asked for.
 - Reading or selecting an empty channel answers "?;".
 - Writing a channel with MT leaves the radio in memory mode on that
   channel, and the channel inherits the CTCSS tone and DCS code that
   were active when it was written. So channels are written from VFO
   mode, after setting the tone and code of the VFO with CN.
 - There is no CAT command to read the CTCSS tone and DCS code of a
   channel, other than selecting it, nor to erase a channel. Other
   programming software uses two undocumented commands that read (SPR)
   and write (SPW) two bytes of the radio's memory at a given address.
   This driver only writes that way to erase a channel:
    - A channel exists when its bit is set in each of two tables, which
      the radio sets itself when a channel is stored. Clearing both bits
      erases the channel.
    - Each channel has a 96 byte record, with the numbers of its CTCSS
      tone and DCS code at offset 70.
"""

import contextlib
import logging
import time

from chirp import chirp_common, directory, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueString, InvalidValueError

LOG = logging.getLogger(__name__)

# Answer of the radio to the ID command
RADIO_ID = "0670"
# Choices of menu 031 CAT RATE, the first one being ours
BAUDS = [38400, 19200, 9600, 4800]

# Mode parameter of the MT command
MODES = {
    "1": "LSB",
    "2": "USB",
    "3": "CW",
    "4": "FM",
    "5": "AM",
    "6": "RTTY",        # RTTY-LSB
    "7": "CWR",
    "8": "DIG",         # DATA-LSB
    "9": "RTTYR",       # RTTY-USB
    "A": "PKT",         # DATA-FM
    "B": "NFM",
    "C": "DIG",         # DATA-USB
    "D": "NAM",
    "E": "DN",          # C4FM
}
# DIG is stored as DATA-USB unless the channel already is DATA-LSB
MODES_REV = {v: k for k, v in MODES.items()}

# CTCSS parameter of the MT command
TMODE_OFF = "0"
TMODE_TSQL = "1"
TMODE_TONE = "2"
TMODE_DTCS = "3"
TMODE_DTCS_ENC = "4"
TMODES_CTCSS = (TMODE_TONE, TMODE_TSQL)
TMODES_DCS = (TMODE_DTCS, TMODE_DTCS_ENC)

# Shift parameter of the MT command
DUPLEX = {"0": "", "1": "+", "2": "-"}
DUPLEX_REV = {v: k for k, v in DUPLEX.items()}

# The repeater shift is not stored per channel, it is a menu item per band
# (band low, band high, menu number)
SHIFT_BANDS = [
    (28000000, 29700000, 80),
    (50000000, 54000000, 81),
    (144000000, 148000000, 82),
    (430000000, 450000000, 83),
]

# Channels 1 to 99 are the regular ones, followed by the nine pairs of
# lower and upper limits for programmable memory scan
LAST_REGULAR = 99
SPECIALS = {}
for _i in range(1, 10):
    SPECIALS["P-%iL" % _i] = 98 + _i * 2
    SPECIALS["P-%iU" % _i] = 99 + _i * 2
SPECIALS_REV = {v: k for k, v in SPECIALS.items()}
LAST_CHANNEL = max(SPECIALS.values())

NAME_LENGTH = 12

# Position of the fields in the stored spec
S_FREQ = slice(0, 9)
S_CLAR = slice(9, 16)
S_MODE = 16
S_VFO_MEM = 17
S_TMODE = 18
S_SHIFT = 21
S_NAME = slice(23, 35)
SPEC_LENGTH = 35
# The same in the answers to IF and MT, which start with the command and
# the channel number
ANSWER_SPEC = slice(5, 5 + SPEC_LENGTH)
ANSWER_CHANNEL = slice(2, 5)

# The radio tells if it is in VFO or memory mode in the answer to IF. It
# has to be this in what is sent with MT.
VFO_MODE = "0"

# Tables with one bit per channel, the first channel being the lowest bit
# of the first byte
CHANNEL_TABLES = (0x3229, 0x3239)
CHANNEL_RECORDS = 0x3249
CHANNEL_RECORD_SIZE = 0x60
# CTCSS tone number, followed by the DCS code number
RECORD_TONES = 0x46


def _int(lo, hi, step=1):
    """A menu item that is a number, sent with leading zeros"""
    return ("int", lo, hi, step)


def _signed(lo, hi, step=1):
    """A menu item that is a number, sent with its sign and leading zeros"""
    return ("signed", lo, hi, step)


def _hz(lo, hi, step):
    """A list of frequencies to choose from"""
    return ["%i Hz" % x for x in range(lo, hi + 1, step)]


OFF_ON = ["OFF", "ON"]
DISABLE_ENABLE = ["DISABLE", "ENABLE"]
NORMAL_REVERSE = ["NORMAL", "REVERSE"]
TEXT_MESSAGE = ["TEXT", "MESSAGE"]
COLORS = ["BLUE", "GRAY", "GREEN", "ORANGE", "PURPLE", "RED", "SKY BLUE"]
RATES = ["4800 bps", "9600 bps", "19200 bps", "38400 bps"]
TIMEOUTS = ["10 msec", "100 msec", "1000 msec", "3000 msec"]
LCUT_FREQS = ["OFF"] + _hz(100, 1000, 50)
HCUT_FREQS = ["OFF"] + _hz(700, 4000, 50)
SLOPES = ["6 dB/oct", "18 dB/oct"]
MIC_SELECT = ["MIC", "REAR"]
PTT_SELECT = ["DAKY", "RTS", "DTR"]
PORT_SELECT = ["DATA", "USB"]
EQ1_FREQS = ["OFF"] + _hz(100, 700, 100)
EQ2_FREQS = ["OFF"] + _hz(700, 1500, 100)
EQ3_FREQS = ["OFF"] + _hz(1500, 3200, 100)
LEVEL = _int(0, 100)
EQ_LEVEL = _signed(-20, 10)
EQ_WIDTH = _int(1, 10)
# From UTC-12:00 to UTC+14:00 by half an hour, sent like +0530
TIME_ZONES = {}
for _i in range(-24, 29):
    _sign = "-" if _i < 0 else "+"
    _hm = divmod(abs(_i) * 30, 60)
    TIME_ZONES["%s%02i%02i" % ((_sign,) + _hm)] = "UTC%s%02i:%02i" % (
        (_sign,) + _hm)

# What a menu item can be set to is either a list of choices, numbered from
# zero, a dict of choices by value, or one of the tuples made by the
# functions above.
# (first menu number, name of the group, [(name, digits, values), ...])
MENUS = [
    (1, "General", [
        ("AGC FAST DELAY (msec)", 4, _int(20, 4000, 20)),
        ("AGC MID DELAY (msec)", 4, _int(20, 4000, 20)),
        ("AGC SLOW DELAY (msec)", 4, _int(20, 4000, 20)),
        ("HOME FUNCTION", 1, ["SCOPE", "FUNCTION"]),
        ("MY CALL INDICATION (sec)", 1, _int(0, 5)),
        ("DISPLAY COLOR", 1, COLORS),
        ("DIMMER LED", 1, ["1", "2"]),
        ("DIMMER TFT", 2, _int(0, 15)),
        ("BAR MTR PEAK HOLD", 1, ["OFF", "0.5 sec", "1.0 sec", "2.0 sec"]),
        ("DVS RX OUT LEVEL", 3, LEVEL),
        ("DVS TX OUT LEVEL", 3, LEVEL),
    ]),
    (12, "Keyer", [
        ("KEYER TYPE", 1, ["OFF", "BUG", "ELEKEY-A", "ELEKEY-B", "ELEKEY-Y",
                           "ACS"]),
        ("KEYER DOT/DASH", 1, NORMAL_REVERSE),
        ("CW WEIGHT (x0.1)", 2, _int(25, 45)),
        ("BEACON INTERVAL (sec, 0 is OFF)", 3, _int(0, 690)),
        ("NUMBER STYLE", 1, ["1290", "AUNO", "AUNT", "A2NO", "A2NT", "12NO",
                             "12NT"]),
        ("CONTEST NUMBER", 4, _int(0, 9999)),
        ("CW MEMORY 1", 1, TEXT_MESSAGE),
        ("CW MEMORY 2", 1, TEXT_MESSAGE),
        ("CW MEMORY 3", 1, TEXT_MESSAGE),
        ("CW MEMORY 4", 1, TEXT_MESSAGE),
        ("CW MEMORY 5", 1, TEXT_MESSAGE),
    ]),
    (23, "Operation", [
        ("NB WIDTH", 1, ["1 ms", "3 ms", "10 ms"]),
        ("NB REJECTION", 1, ["10 dB", "30 dB", "50 dB"]),
        ("NB LEVEL", 2, _int(0, 10)),
        ("BEEP LEVEL", 3, LEVEL),
        ("TIME ZONE", 5, TIME_ZONES),
        ("GPS/232C SELECT", 1, ["GPS1", "GPS2", "RS232C"]),
        ("232C RATE", 1, RATES),
        ("232C TOT", 1, TIMEOUTS),
        ("CAT RATE", 1, RATES),
        ("CAT TOT", 1, TIMEOUTS),
        ("CAT RTS", 1, DISABLE_ENABLE),
        ("MEM GROUP", 1, DISABLE_ENABLE),
        ("QUICK SPLIT FREQ (kHz)", 3, _signed(-20, 20)),
        ("TX TOT (min, 0 is OFF)", 2, _int(0, 30)),
        ("MIC SCAN", 1, DISABLE_ENABLE),
        ("MIC SCAN RESUME", 1, ["PAUSE", "TIME"]),
        ("REF FREQ ADJ", 3, _signed(-25, 25)),
        ("CLAR MODE SELECT", 1, ["RX", "TX", "TRX"]),
    ]),
    (41, "AM", [
        ("AM LCUT FREQ", 2, LCUT_FREQS),
        ("AM LCUT SLOPE", 1, SLOPES),
        ("AM HCUT FREQ", 2, HCUT_FREQS),
        ("AM HCUT SLOPE", 1, SLOPES),
        ("AM MIC SELECT", 1, MIC_SELECT),
        ("AM OUT LEVEL", 3, LEVEL),
        ("AM PTT SELECT", 1, PTT_SELECT),
        ("AM PORT SELECT", 1, PORT_SELECT),
        ("AM DATA GAIN", 3, LEVEL),
    ]),
    (50, "CW", [
        ("CW LCUT FREQ", 2, LCUT_FREQS),
        ("CW LCUT SLOPE", 1, SLOPES),
        ("CW HCUT FREQ", 2, HCUT_FREQS),
        ("CW HCUT SLOPE", 1, SLOPES),
        ("CW OUT LEVEL", 3, LEVEL),
        ("CW AUTO MODE", 1, ["OFF", "50 MHz", "ON"]),
        ("CW BK-IN TYPE", 1, ["SEMI BREAK-IN", "FULL BREAK-IN"]),
        ("CW BK-IN DELAY (msec)", 4, _int(30, 3000, 10)),
        ("CW WAVE SHAPE", 1, ["1 msec", "2 msec", "4 msec", "6 msec"]),
        ("CW FREQ DISPLAY", 1, ["DIRECT FREQ", "PITCH OFFSET"]),
        ("PC KEYING", 1, ["OFF", "DAKY", "RTS", "DTR"]),
        ("QSK DELAY TIME", 1, ["15 msec", "20 msec", "25 msec", "30 msec"]),
    ]),
    (62, "Data", [
        ("DATA MODE", 1, ["PSK", "OTHER"]),
        ("PSK TONE", 1, ["1000 Hz", "1500 Hz", "2000 Hz"]),
        ("OTHER DISP (SSB) (Hz)", 5, _signed(-3000, 3000, 10)),
        ("OTHER SHIFT (SSB) (Hz)", 5, _signed(-3000, 3000, 10)),
        ("DATA LCUT FREQ", 2, LCUT_FREQS),
        ("DATA LCUT SLOPE", 1, SLOPES),
        ("DATA HCUT FREQ", 2, HCUT_FREQS),
        ("DATA HCUT SLOPE", 1, SLOPES),
        ("DATA IN SELECT", 1, MIC_SELECT),
        ("DATA PTT SELECT", 1, PTT_SELECT),
        ("DATA PORT SELECT", 1, PORT_SELECT),
        ("DATA OUT LEVEL", 3, LEVEL),
    ]),
    (74, "FM", [
        ("FM MIC SELECT", 1, MIC_SELECT),
        ("FM OUT LEVEL", 3, LEVEL),
        ("FM PKT PTT SELECT", 1, PTT_SELECT),
        ("FM PKT PORT SELECT", 1, PORT_SELECT),
        ("FM PKT TX GAIN", 3, LEVEL),
        ("FM PKT MODE", 1, ["1200", "9600"]),
        ("RPT SHIFT 28MHz (kHz)", 4, _int(0, 1000, 10)),
        ("RPT SHIFT 50MHz (kHz)", 4, _int(0, 4000, 10)),
        ("RPT SHIFT 144MHz (kHz)", 4, _int(0, 4000, 10)),
        ("RPT SHIFT 430MHz (kHz)", 5, _int(0, 10000, 10)),
        ("ARS 144MHz", 1, OFF_ON),
        ("ARS 430MHz", 1, OFF_ON),
        ("DCS POLARITY", 1, ["Tn-Rn", "Tn-Riv", "Tiv-Rn", "Tiv-Riv"]),
        ("RADIO ID", 5, None),
        ("GM DISPLAY", 1, ["DISTANCE", "STRENGTH"]),
        ("DISTANCE", 1, ["km", "mile"]),
        ("AMS TX MODE", 1, ["AUTO", "MANUAL", "DN", "VW", "ANALOG"]),
        ("STANDBY BEEP", 1, OFF_ON),
    ]),
    (92, "RTTY", [
        ("RTTY LCUT FREQ", 2, LCUT_FREQS),
        ("RTTY LCUT SLOPE", 1, SLOPES),
        ("RTTY HCUT FREQ", 2, HCUT_FREQS),
        ("RTTY HCUT SLOPE", 1, SLOPES),
        ("RTTY SHIFT PORT", 1, ["SHIFT", "DTR", "RTS"]),
        ("RTTY POLARITY-RX", 1, NORMAL_REVERSE),
        ("RTTY POLARITY-TX", 1, NORMAL_REVERSE),
        ("RTTY OUT LEVEL", 3, LEVEL),
        ("RTTY SHIFT FREQ", 1, ["170 Hz", "200 Hz", "425 Hz", "850 Hz"]),
        ("RTTY MARK FREQ", 1, ["1275 Hz", "2125 Hz"]),
    ]),
    (102, "SSB", [
        ("SSB LCUT FREQ", 2, LCUT_FREQS),
        ("SSB LCUT SLOPE", 1, SLOPES),
        ("SSB HCUT FREQ", 2, HCUT_FREQS),
        ("SSB HCUT SLOPE", 1, SLOPES),
        ("SSB MIC SELECT", 1, MIC_SELECT),
        ("SSB OUT LEVEL", 3, LEVEL),
        ("SSB PTT SELECT", 1, PTT_SELECT),
        ("SSB PORT SELECT", 1, PORT_SELECT),
        ("SSB TX BPF", 1, ["50-3000", "100-2900", "200-2800", "300-2700",
                           "400-2600"]),
    ]),
    (111, "RX DSP", [
        ("APF WIDTH", 1, ["NARROW", "MEDIUM", "WIDE"]),
        ("CONTOUR LEVEL", 3, _signed(-40, 20)),
        ("CONTOUR WIDTH", 2, _int(1, 11)),
        ("IF NOTCH WIDTH", 1, ["NARROW", "WIDE"]),
    ]),
    (115, "Scope", [
        ("SCP DISPLAY MODE", 1, ["SPECTRUM", "WATER FALL"]),
        ("SCP SPAN FREQ", 2, {"03": "50 kHz", "04": "100 kHz",
                              "05": "200 kHz", "06": "500 kHz",
                              "07": "1000 kHz"}),
        ("SPECTRUM COLOR", 1, COLORS),
        ("WATER FALL COLOR", 1, COLORS + ["MULTI"]),
    ]),
    (119, "TX Audio", [
        ("PRMTRC EQ1 FREQ", 2, EQ1_FREQS),
        ("PRMTRC EQ1 LEVEL", 3, EQ_LEVEL),
        ("PRMTRC EQ1 BWTH", 2, EQ_WIDTH),
        ("PRMTRC EQ2 FREQ", 2, EQ2_FREQS),
        ("PRMTRC EQ2 LEVEL", 3, EQ_LEVEL),
        ("PRMTRC EQ2 BWTH", 2, EQ_WIDTH),
        ("PRMTRC EQ3 FREQ", 2, EQ3_FREQS),
        ("PRMTRC EQ3 LEVEL", 3, EQ_LEVEL),
        ("PRMTRC EQ3 BWTH", 2, EQ_WIDTH),
        ("P-PRMTRC EQ1 FREQ", 2, EQ1_FREQS),
        ("P-PRMTRC EQ1 LEVEL", 3, EQ_LEVEL),
        ("P-PRMTRC EQ1 BWTH", 2, EQ_WIDTH),
        ("P-PRMTRC EQ2 FREQ", 2, EQ2_FREQS),
        ("P-PRMTRC EQ2 LEVEL", 3, EQ_LEVEL),
        ("P-PRMTRC EQ2 BWTH", 2, EQ_WIDTH),
        ("P-PRMTRC EQ3 FREQ", 2, EQ3_FREQS),
        ("P-PRMTRC EQ3 LEVEL", 3, EQ_LEVEL),
        ("P-PRMTRC EQ3 BWTH", 2, EQ_WIDTH),
    ]),
    (137, "TX General", [
        ("HF TX MAX POWER (W)", 3, _int(5, 100)),
        ("50M TX MAX POWER (W)", 3, _int(5, 100)),
        ("144M TX MAX POWER (W)", 3, _int(5, 50)),
        ("430M TX MAX POWER (W)", 3, _int(5, 50)),
        ("TUNER SELECT", 1, ["OFF", "INTERNAL", "EXTERNAL", "ATAS", "LAMP"]),
        ("VOX SELECT", 1, ["MIC", "DATA"]),
        ("VOX GAIN", 3, LEVEL),
        ("VOX DELAY (msec)", 4, _int(30, 3000, 10)),
        ("ANTI VOX GAIN", 3, LEVEL),
        ("DATA VOX GAIN", 3, LEVEL),
        ("DATA VOX DELAY (msec)", 4, _int(30, 3000, 10)),
        ("ANTI DVOX GAIN", 3, LEVEL),
        ("EMERGENCY FREQ TX", 1, DISABLE_ENABLE),
        ("PRT/WIRES FREQ", 1, ["MANUAL", "PRESET"]),
        ("PRESET FREQUENCY (x10 Hz)", 8, _int(30000, 47000000)),
        ("SEARCH SETUP", 1, ["HISTORY", "ACTIVITY"]),
        ("WIRES DG-ID", 3, ["AUTO"] + ["DG-ID %02i" % x
                                       for x in range(1, 100)]),
    ]),
]
# Changing how the radio talks to us would break the connection, and the
# radio does not let the last one be set
MENU_CAT_RATE = 31
MENU_CAT_RTS = 33
MENU_RADIO_ID = 87
MENUS_READ_ONLY = (MENU_CAT_RATE, MENU_CAT_RTS, MENU_RADIO_ID)
MENU_ITEMS = {}
for _first, _group, _items in MENUS:
    for _i, _item in enumerate(_items, _first):
        MENU_ITEMS[_i] = _item


def _choices(digits, values):
    """Return the choices of a menu item as a dict of value to name"""
    if isinstance(values, dict):
        return values
    return {"%0*i" % (digits, i): x for i, x in enumerate(values)}


@directory.register
class FT991ARadio(chirp_common.LiveRadio):
    """Yaesu FT-991A"""
    VENDOR = "Yaesu"
    MODEL = "FT-991A"
    BAUD_RATE = 38400
    # The radio does not answer unless RTS is asserted when menu
    # 033 CAT RTS is set to ENABLE, which is the default
    WANTS_RTS = True
    WANTS_DTR = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # What was read from the radio or written to it, by channel and
        # menu number
        self._channels = {}
        self._menus = {}
        self._identified = False
        if self.pipe:
            self._check_radio()

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = (
            "Connect the USB cable and select the \"Enhanced\" COM "
            "port.\n"
            "Menu 031 CAT RATE can be set to any speed, it is detected "
            "automatically.\n"
            "To write a memory, the radio is put in VFO mode, then "
            "returns to where it was.")
        return rp

    def _read_reply(self, timeout=1.0):
        """Return an answer of the radio, without the ; that ends it"""
        data = b""
        start = time.time()
        while not data.endswith(b";"):
            data += self.pipe.read(1)
            if time.time() - start > timeout:
                LOG.debug("RADIO->PC (timeout): %r" % data)
                raise errors.RadioNoResponse()
        LOG.debug("RADIO->PC: %r" % data)
        return data[:-1].decode("ascii", errors="replace")

    def _query(self, cmd, timeout=1.0):
        """Send read command @cmd and return the answer"""
        LOG.debug("PC->RADIO: %s;" % cmd)
        # Anything still waiting is not an answer to this
        self.pipe.reset_input_buffer()
        self.pipe.write(("%s;" % cmd).encode("ascii"))
        answer = self._read_reply(timeout)
        # Skip a stray byte in front of the answer, as seen once on a real
        # radio
        start = answer.find(cmd[:2])
        if start > 0:
            LOG.warning("Ignoring %r before answer to %s" % (
                answer[:start], cmd))
            answer = answer[start:]
        return answer

    def _set(self, cmd):
        """Send set command @cmd, which the radio only answers if it fails"""
        LOG.debug("PC->RADIO: %s;" % cmd)
        self.pipe.reset_input_buffer()
        # Follow with a command that is always answered, so that we do
        # not have to wait for a timeout to know that this one worked
        self.pipe.write(("%s;ID;" % cmd).encode("ascii"))
        failed = False
        while True:
            resp = self._read_reply()
            if resp.startswith("ID"):
                break
            failed = True
        if failed:
            raise errors.RadioError("Radio refused command %s" % cmd)

    def _read_bytes(self, count, timeout=1.0):
        """Return an answer of the radio of a known length"""
        data = b""
        start = time.time()
        while len(data) < count:
            data += self.pipe.read(count - len(data))
            if time.time() - start > timeout:
                LOG.debug("RADIO->PC (timeout): %r" % data)
                raise errors.RadioNoResponse()
        LOG.debug("RADIO->PC: %r" % data)
        return data

    @staticmethod
    def _memory_frame(cmd, addr, data=b""):
        """Build an SPR or SPW command, or the answer expected to SPR

        This is the command, the address with its high byte first, the
        two bytes of data if any, the low byte of the sum of all that,
        and the usual ; to end it.
        """
        frame = cmd + bytes([addr >> 8, addr & 0xFF]) + data
        return frame + bytes([sum(frame) & 0xFF]) + b";"

    def _peek(self, addr):
        """Read the two bytes of the radio's memory at @addr"""
        frame = self._memory_frame(b"SPR", addr)
        LOG.debug("PC->RADIO: %r" % frame)
        self.pipe.write(frame)
        # The data can be anything, so this can not be read up to a ";"
        resp = self._read_bytes(len(frame) + 2)
        if resp != self._memory_frame(b"SPR", addr, resp[5:7]):
            raise errors.RadioError("Unexpected response from radio")
        return resp[5:7]

    def _poke(self, addr, data):
        """Write two bytes of the radio's memory at @addr"""
        frame = self._memory_frame(b"SPW", addr, data)
        LOG.debug("PC->RADIO: %r" % frame)
        self.pipe.write(frame)
        if self._read_bytes(2) != b"A;":
            raise errors.RadioError("Radio refused to change its memory")

    def _delete_channel(self, number):
        """Erase a channel by clearing its bit in the tables of channels"""
        byte, bit = divmod(number - 1, 8)
        for table in CHANNEL_TABLES:
            # This also reads and writes back the next byte, unchanged
            data = self._peek(table + byte)
            self._poke(table + byte,
                       bytes([data[0] & ~(1 << bit) & 0xFF, data[1]]))
        if self._query("MT%03i" % number) != "?":
            raise errors.RadioError("Radio did not delete memory %i" % number)

    def _identify(self):
        """Find the baud rate of the radio and check that it is an FT-991A"""
        self.pipe.timeout = 0.1
        # Start with the one that worked last time, if any
        bauds = [self.pipe.baudrate] + [x for x in BAUDS
                                        if x != self.pipe.baudrate]
        saw_response = False
        for baud in bauds:
            LOG.info("Trying ID at baud %i" % baud)
            self.pipe.baudrate = baud
            # The first attempt may be answered with an error because of
            # what was sent at the previous baud rate
            for _attempt in range(2):
                self.pipe.reset_input_buffer()
                try:
                    resp = self._query("ID", timeout=0.5)
                except errors.RadioNoResponse:
                    break
                saw_response = True
                if resp == "ID" + RADIO_ID:
                    return
                if resp.startswith("ID") and resp[2:].isdigit():
                    raise errors.RadioError(
                        "Radio reports ID %s, which is not an %s" % (
                            resp[2:], self.MODEL))
        if saw_response:
            raise errors.RadioError("Unexpected response from radio")
        raise errors.RadioNoResponse()

    def _check_radio(self):
        """Identify the radio the first time it is used"""
        if self._identified:
            return
        self._identify()
        self._identified = True
        # Read these now, so that checking a memory does not have to
        # talk to the radio
        for _lo, _hi, menu in SHIFT_BANDS:
            self._get_menu(menu)

    def _is_vfo_mode(self):
        return self._query("IF")[ANSWER_SPEC][S_VFO_MEM] == VFO_MODE

    def _enter_vfo_mode(self):
        if not self._is_vfo_mode():
            self._set("VM")
            if not self._is_vfo_mode():
                raise errors.RadioError("Unable to put radio in VFO mode")

    @contextlib.contextmanager
    def _vfo_mode(self):
        """Put the radio in VFO mode, then back as it was"""
        state = self._query("IF")
        self._enter_vfo_mode()
        # Writing channels changes the tone and code of the VFO
        tones = self._query("CN00"), self._query("CN01")
        try:
            yield
        finally:
            self._enter_vfo_mode()
            for tone in tones:
                # The answers are also the commands to set them
                self._set(tone)
            # Selecting a channel puts the radio in memory mode
            try:
                self._set("MC%s" % state[ANSWER_CHANNEL])
            except errors.RadioError:
                # The channel it was on has been deleted
                LOG.warning("Unable to return to channel %s" %
                            state[ANSWER_CHANNEL])
            else:
                if state[ANSWER_SPEC][S_VFO_MEM] == VFO_MODE:
                    self._set("VM")

    def _read_channel(self, number):
        """Return the spec, tone and code of a channel, None if empty"""
        answer = self._query("MT%03i" % number)
        if answer == "?":
            return None
        spec = answer[ANSWER_SPEC]
        if not answer.startswith("MT") or len(spec) != SPEC_LENGTH:
            raise errors.RadioError("Unexpected response from radio")
        # This is not a property of the channel
        spec = spec[:S_VFO_MEM] + VFO_MODE + spec[S_VFO_MEM + 1:]

        ctcss = dcs = 0
        if spec[S_TMODE] != TMODE_OFF:
            # Only keep the one that is used, as the other one is whatever
            # the radio was set to when the channel was stored
            tones = self._peek(CHANNEL_RECORDS + RECORD_TONES +
                               CHANNEL_RECORD_SIZE * (number - 1))
            if spec[S_TMODE] in TMODES_CTCSS:
                ctcss = tones[0]
            else:
                dcs = tones[1]
            if (ctcss >= len(chirp_common.TONES) or
                    dcs >= len(chirp_common.DTCS_CODES)):
                raise errors.RadioError(
                    "Unexpected tone in memory %i" % number)
        return spec, ctcss, dcs

    def _write_channel(self, number, spec, ctcss, dcs):
        """Write a channel, with the radio in VFO mode"""
        # The channel gets the tone and code of the VFO
        if spec[S_TMODE] in TMODES_CTCSS:
            self._set("CN00%03i" % ctcss)
        elif spec[S_TMODE] in TMODES_DCS:
            self._set("CN01%03i" % dcs)
        self._set("MT%03i%s" % (number, spec))
        # Which has put the radio in memory mode on that channel
        self._enter_vfo_mode()
        # Make sure that the radio stored what we expect
        if self._read_channel(number) != (spec, ctcss, dcs):
            raise errors.RadioError(
                "Radio did not store memory %i as expected" % number)

    def _get_channel(self, number):
        """Return what _read_channel() does, reading the radio only once"""
        if number not in self._channels:
            self._check_radio()
            self._channels[number] = self._read_channel(number)
        return self._channels[number]

    def _get_menu(self, number):
        """Return the value of a menu item, reading the radio only once"""
        if number not in self._menus:
            self._check_radio()
            answer = self._query("EX%03i" % number)
            if not answer.startswith("EX%03i" % number):
                raise errors.RadioError("Unexpected response from radio")
            self._menus[number] = answer[5:]
        return self._menus[number]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_settings = True
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.has_cross = True
        rf.valid_modes = sorted(MODES_REV.keys(),
                                key=chirp_common.MODES.index)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["DTCS->"]
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_tuning_steps = []
        rf.valid_skips = []
        rf.valid_bands = [(30000, 56000000),
                          (118000000, 164000000),
                          (420000000, 470000000)]
        rf.valid_characters = chirp_common.CHARSET_ASCII.replace(";", "")
        rf.valid_name_length = NAME_LENGTH
        rf.valid_special_chans = sorted(SPECIALS.keys())
        rf.memory_bounds = (1, LAST_REGULAR)
        return rf

    def _get_shift(self, freq):
        """Return the repeater shift that the radio uses at @freq"""
        for lo, hi, menu in SHIFT_BANDS:
            # The menu items are in kHz
            if lo <= freq < hi:
                return int(self._get_menu(menu)) * 1000
        return 0

    def _channel(self, number):
        """Return the channel number of a memory number or special name"""
        if isinstance(number, str):
            try:
                number = SPECIALS[number]
            except KeyError:
                raise errors.InvalidMemoryLocation(
                    "Unknown channel %s" % number)
        if number < 1 or number > LAST_CHANNEL:
            raise errors.InvalidMemoryLocation(
                "Number must be between 1 and %i" % LAST_CHANNEL)
        return number

    def get_raw_memory(self, number):
        return repr(self._get_channel(self._channel(number)))

    def get_memory(self, number):
        number = self._channel(number)
        record = self._get_channel(number)

        mem = chirp_common.Memory()
        mem.number = number
        if number in SPECIALS_REV:
            mem.extd_number = SPECIALS_REV[number]
            mem.immutable = ["number", "extd_number"]

        if record is None:
            mem.empty = True
            return mem

        spec, ctcss, dcs = record
        mem.freq = int(spec[S_FREQ])
        mem.mode = MODES[spec[S_MODE]]
        mem.duplex = DUPLEX[spec[S_SHIFT]]
        mem.offset = self._get_shift(mem.freq) if mem.duplex else 0
        mem.name = spec[S_NAME].rstrip()

        tmode = spec[S_TMODE]
        if tmode in TMODES_CTCSS:
            # The radio has a single tone for both
            mem.rtone = mem.ctone = chirp_common.TONES[ctcss]
            mem.tmode = "Tone" if tmode == TMODE_TONE else "TSQL"
        elif tmode in TMODES_DCS:
            mem.dtcs = chirp_common.DTCS_CODES[dcs]
            if tmode == TMODE_DTCS:
                mem.tmode = "DTCS"
            else:
                mem.tmode = "Cross"
                mem.cross_mode = "DTCS->"

        return mem

    def set_memory(self, mem):
        if mem.empty:
            self.erase_memory(mem.extd_number or mem.number)
            return
        number = self._channel(mem.extd_number or mem.number)
        current = self._get_channel(number)

        mode = MODES_REV[mem.mode]
        # Clarifier offset, followed by RX and TX clarifier off
        clar = "+000000"
        if current:
            # Keep what CHIRP has no way to show
            old_spec = current[0]
            clar = old_spec[S_CLAR]
            # Two modes of the radio are shown as DIG
            if MODES[old_spec[S_MODE]] == mem.mode:
                mode = old_spec[S_MODE]

        tmode = {"": TMODE_OFF,
                 "Tone": TMODE_TONE,
                 "TSQL": TMODE_TSQL,
                 "DTCS": TMODE_DTCS,
                 "Cross": TMODE_DTCS_ENC}[mem.tmode]
        ctcss = dcs = 0
        if tmode in TMODES_CTCSS:
            tone = mem.rtone if mem.tmode == "Tone" else mem.ctone
            ctcss = chirp_common.TONES.index(tone)
        elif tmode in TMODES_DCS:
            dcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        name = self.filter_name(mem.name).ljust(NAME_LENGTH)
        # The zeros are parameters that the manual says are fixed
        spec = "%09i%s%s%s%s00%s0%s" % (
            mem.freq, clar, mode, VFO_MODE, tmode, DUPLEX_REV[mem.duplex],
            name)
        if (spec, ctcss, dcs) == current:
            return

        # Read it again next time if this fails half way
        del self._channels[number]
        with self._vfo_mode():
            self._write_channel(number, spec, ctcss, dcs)
        self._channels[number] = spec, ctcss, dcs

    def erase_memory(self, number):
        number = self._channel(number)
        if self._get_channel(number) is None:
            return
        # Do not leave the radio on a channel that no longer exists
        state = self._query("IF")
        if (state[ANSWER_SPEC][S_VFO_MEM] != VFO_MODE and
                int(state[ANSWER_CHANNEL]) == number):
            self._enter_vfo_mode()
        del self._channels[number]
        self._delete_channel(number)
        self._channels[number] = None

    def validate_memory(self, mem):
        msgs = chirp_common.LiveRadio.validate_memory(self, mem)
        if mem.duplex in ("+", "-"):
            # The radio decides this from the frequency
            shift = self._get_shift(mem.freq)
            if mem.offset != shift:
                msgs.append(chirp_common.ValidationWarning(
                    "The radio will use the offset set in its menu for "
                    "this band (%s) instead of %s" % (
                        chirp_common.format_freq(shift),
                        chirp_common.format_freq(mem.offset))))
        return msgs

    def _get_setting_value(self, number):
        """Return the value of a menu item of the radio, as a setting"""
        _name, digits, values = MENU_ITEMS[number]
        current = self._get_menu(number)
        try:
            if isinstance(values, tuple):
                _kind, lo, hi, step = values
                if not lo <= int(current) <= hi:
                    raise ValueError("Out of range")
                return RadioSettingValueInteger(lo, hi, int(current), step)
            elif values:
                choices = _choices(digits, values)
                return RadioSettingValueList(
                    choices.values(),
                    current_index=list(choices).index(current))
        except (ValueError, KeyError, InvalidValueError):
            LOG.warning("Menu %03i has unexpected value %r" % (
                number, current))
        # Show what we do not understand, but do not let it be changed
        value = RadioSettingValueString(0, 8, current, autopad=False)
        value.set_mutable(False)
        return value

    def get_settings(self):
        top = RadioSettings()
        for first, group_name, items in MENUS:
            group = RadioSettingGroup(group_name.lower().replace(" ", "_"),
                                      group_name)
            top.append(group)
            for number, item in enumerate(items, first):
                value = self._get_setting_value(number)
                if number in MENUS_READ_ONLY:
                    value.set_mutable(False)
                group.append(RadioSetting("menu_%03i" % number,
                                          "%03i %s" % (number, item[0]),
                                          value))
        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            number = int(element.get_name().split("_")[1])
            _name, digits, values = MENU_ITEMS[number]
            # Send it the way the radio wants it
            if isinstance(values, tuple):
                fmt = "%+0*i" if values[0] == "signed" else "%0*i"
                value = fmt % (digits, int(element.value))
            else:
                value = util.get_dict_rev(_choices(digits, values),
                                          str(element.value))
            if value != self._get_menu(number):
                self._set("EX%03i%s" % (number, value))
                self._menus[number] = value
