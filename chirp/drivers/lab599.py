# Copyright 2026 Marek Kudlacz <marek@kudlacz.com>
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

"""Lab599 CAT protocol document, rev. 3 for TX-500 and TX-500MP"""

import abc
from collections.abc import Callable
from dataclasses import KW_ONLY, astuple, dataclass, field, fields
import enum
import logging
import os
import re
import threading
import time

from chirp import chirp_common, directory, errors
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings, \
    RadioSettingSubGroup, RadioSettingValueBoolean, \
    RadioSettingValueInteger, RadioSettingValueList, RadioSettingValueString

LOG = logging.getLogger(__name__)

TERMINATOR = ';'

ID_TS2000 = '019'
ID_TX500 = '500'
ID_TX500MP = '505'
CLOCK_MIN_FIRMWARE = 'v1.29.01'

ERROR_SYNTAX = '?;'
ERROR_COMMS = 'E;'
ERROR_INCOMPLETE = 'O;'
ERROR_REPLIES = {
    ERROR_SYNTAX: 'Radio rejected the command',
    ERROR_COMMS: 'Radio reported a communication error',
    ERROR_INCOMPLETE: 'Radio did not finish processing the command',
}

FREQ_MIN_HZ = 500000
# Manual says 56 MHz max, but radio won't store anything above 55.99 MHz
FREQ_MAX_HZ = 55990000

# Index is the CAT value from the spec, e.g. mode 2 is USB
LAB599_MODES = ["", "LSB", "USB", "CW", "FM", "AM", "DIG", "CWR"]
LAB599_RF_PATHS = ["Off", "Preamp", "ATT"]
VFO_FUNCTIONS = ["VFO A", "VFO B", "Memory"]
RX_FILTERS = ["Filter 1", "Filter 2", "Filter 3", "Filter 4"]
TX_FILTERS = ["Filter 1", "Filter 2"]
NOTCH_TYPES = ["Type 1", "Type 2"]
METER_FUNCTIONS = ["Power", "SWR", "MIC/DIG", "ALC"]
CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
    97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8,
    136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8, 179.9, 186.2,
    192.8, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3,
    254.1,
]
# RG takes 0-100, but the radio only has 57 levels. Maps each level to the
# value we write
# {level read back: value to write}
RF_GAIN_LEVELS = {
    0: 0, 2: 6, 4: 7, 6: 9, 8: 11, 9: 12, 11: 14, 13: 16, 15: 17, 17: 19,
    18: 21, 20: 23, 22: 24, 24: 26, 25: 28, 27: 29, 29: 31, 31: 33, 33: 34,
    34: 36, 36: 38, 38: 40, 40: 41, 42: 43, 43: 45, 45: 46, 47: 48, 49: 50,
    50: 51, 52: 53, 54: 55, 56: 57, 58: 58, 59: 60, 61: 62, 63: 63, 65: 65,
    67: 67, 68: 68, 70: 70, 72: 72, 74: 74, 75: 75, 77: 77, 79: 79, 81: 80,
    83: 82, 84: 84, 86: 85, 88: 87, 90: 89, 92: 91, 93: 92, 95: 94, 97: 96,
    99: 97, 100: 99,
}
# Radio goes down to -51, not -50 like the manual says
RF_GAIN_LABELS = dict(zip(
    RF_GAIN_LEVELS,
    (f'{value:+d}' if value else '0' for value in range(-51, 6)),
    strict=True))

SSB_MODES = ('LSB', 'USB')
CW_MODES = ('CW', 'CWR')
DIG_MODES = ('DIG',)
AM_MODES = ('AM',)
FM_MODES = ('FM',)
MIC_MODES = ('LSB', 'USB', 'FM', 'AM')
# These settings are saved per mode, and some modes share a value. CAT can
# only change the current mode's value. Modes not listed here can't be changed.
MODE_GROUPS = {
    'RG': {'SSB': SSB_MODES, 'CW': CW_MODES, 'DIG': DIG_MODES,
           'AM': AM_MODES, 'FM': FM_MODES},
    'GT': {'SSB': SSB_MODES, 'CW': CW_MODES, 'AM': AM_MODES},
    'SQ': {'SSB/AM': SSB_MODES + CW_MODES + AM_MODES + DIG_MODES,
           'FM': FM_MODES},
    'VX': {'CW': CW_MODES, 'MIC': MIC_MODES, 'DIG': DIG_MODES},
    'VG': {'MIC': MIC_MODES, 'DIG': DIG_MODES},
    'VD': {'CW': CW_MODES, 'MIC': MIC_MODES, 'DIG': DIG_MODES},
}

MEMORY_RECORD_LENGTH = 50
EMPTY_MEMORY_MODE = LAB599_MODES.index("USB")
MEMORY_WRITE_PATTERN = re.compile(
    r'MW00[0-9]{2}[0-9]{11}[1-7][0-2]0{22} {8};')


class CommandRejected(errors.RadioError):
    pass


class Kind(enum.Enum):
    SETTING = 'read and set'
    STATUS = 'read only'
    MEMORY = 'memory channel'
    ACTION = 'acts immediately; never sent by this driver'
    UNSUPPORTED = 'answers with no value'


@dataclass(frozen=True)
class Param:
    name: str
    offset: int
    width: int
    lo: int
    hi: int
    step: int = 1

    def accepts(self, value):
        return (self.lo <= value <= self.hi and
                (value - self.lo) % self.step == 0)


@dataclass(frozen=True)
class Command:
    code: str
    summary: str
    kind: Kind
    read: str = ''
    template: str = ''
    params: tuple[Param, ...] = ()

    @property
    def pattern(self):
        parts = self.template.split('{}')
        body = re.escape(parts[0])
        for param, part in zip(self.params, parts[1:]):
            body += '([0-9]{%i})%s' % (param.width, re.escape(part))
        return re.compile(body)

    def accepts(self, frame):
        if not self.template:
            return False
        match = self.pattern.fullmatch(frame)
        return bool(match) and all(
            param.accepts(int(text))
            for param, text in zip(self.params, match.groups()))

    def set_frame(self, *values):
        if self.kind is not Kind.SETTING:
            raise errors.RadioError('%s cannot be set' % self.code)
        if len(values) != len(self.params) or not all(
                param.accepts(value)
                for param, value in zip(self.params, values)):
            raise errors.RadioError('Invalid value for %s: %r' % (self.code,
                                                                  values))
        return self.template.format(*[
            '%0*i' % (param.width, value)
            for param, value in zip(self.params, values)])

    def parse(self, reply):
        try:
            return [int(reply[param.offset:param.offset + param.width])
                    for param in self.params]
        except ValueError as e:
            raise errors.RadioError(
                f'Malformed {self.code} answer: {reply!r}') from e


def _setting(code, summary, *params, read=None, template=None):
    return Command(code, summary, Kind.SETTING, read or code + ';',
                   template or code + '{};', params)


def _flag(code, summary):
    return _setting(code, summary, Param('state', 2, 1, 0, 1))


def _level(code, summary, lo, hi, width=3, step=1):
    return _setting(code, summary, Param('value', 2, width, lo, hi, step))


def _status(code, summary, read=None):
    return Command(code, summary, Kind.STATUS, read or code + ';')


def _action(code, summary, template, *params):
    return Command(code, summary, Kind.ACTION, '', template, params)


def _unsupported(code, summary):
    return Command(code, summary, Kind.UNSUPPORTED, code + ';')


def _by_code(*commands):
    return {command.code: command for command in commands}


SETTING_COMMANDS = _by_code(
    _setting('AC', 'Antenna tuner on/off', Param('atu', 3, 1, 0, 1),
             template='AC0{}0;'),
    _setting('AG', 'AF gain', Param('level', 3, 3, 0, 250), read='AG0;',
             template='AG0{};'),
    _flag('AL', 'Notch filter type'),
    _level('CN', 'CTCSS tone number', 0, len(CTCSS_TONES) - 1, width=2),
    _flag('CT', 'CTCSS on/off'),
    _level('FA', 'VFO A frequency in Hz', FREQ_MIN_HZ, FREQ_MAX_HZ, width=11),
    _setting('FL', 'RX and TX filter', Param('rx', 2, 1, 0, 3),
             Param('tx', 3, 1, 0, 1), template='FL{}{};'),
    _level('FR', 'Receive function', 0, 2, width=1),
    _level('FT', 'Transmit function', 0, 2, width=1),
    # Protocol says 2 digits, but radio uses 3
    _level('GT', 'AGC time constant', 1, 10),
    _flag('IS', 'DSP IF (DIF) on/off'),
    # Protocol says 4-60, but radio uses characters per minute, 30-300
    _level('KS', 'Keyer speed in characters per minute', 30, 300),
    _setting('LK', 'Lock', Param('state', 2, 1, 0, 1), template='LK{}0;'),
    _level('MA', 'DIG gain', 0, 100),
    _setting('MC', 'Memory channel', Param('channel', 3, 2, 0, 99),
             template='MC0{};'),
    _level('MD', 'Operating mode', 1, len(LAB599_MODES) - 1, width=1),
    _level('MG', 'Microphone gain', 0, 100),
    _level('ML', 'TX monitor level', 0, 250),
    _flag('MO', 'TX monitor mute'),
    _flag('NB', 'Noise blanker on/off'),
    _level('NL', 'Noise blanker level', 30, 100),
    _flag('NR', 'Noise reduction on/off'),
    _flag('NT', 'Auto notch on/off'),
    _flag('PA', 'Preamplifier on/off'),
    _level('PC', 'Output power percent', 10, 100),
    _level('PL', 'Speech compressor level', 1, 100),
    _flag('PR', 'Speech compressor on/off'),
    _level('RA', 'RF attenuator on/off', 0, 1, width=2),
    _level('RG', 'RF gain', 0, 100),
    # Protocol says 100 max, but radio won't store above 99
    _level('RL', 'Noise reduction level', 1, 99),
    _level('RM', 'Meter function', 0, len(METER_FUNCTIONS) - 1, width=1),
    _setting('SQ', 'Squelch level', Param('level', 3, 3, 0, 255), read='SQ0;',
             template='SQ0{};'),
    _setting('TM', 'Clock', Param('hours', 2, 2, 0, 23),
             Param('minutes', 5, 2, 0, 59), Param('seconds', 8, 2, 0, 59),
             template='TM{}:{}:{};'),
    _flag('TO', 'Tone on/off'),
    _level('TP', 'TX tune power', 5, 50),
    _level('VD', 'VOX delay in ms', 0, 5000, width=4, step=100),
    _level('VG', 'VOX gain', 0, 100),
    _flag('VX', 'VOX on/off'),
)

STATUS_COMMANDS = _by_code(
    _status('BY', 'Busy signal'),
    # Writing CG clears CG and TP, so only read it
    _status('CG', 'Carrier level'),
    _status('ID', 'Radio ID'),
    _status('IF', 'Transceiver status'),
    _status('PS', 'Power state'),
    _status('PT', 'PTT state'),
    _status('SM', 'S-meter, or power out while transmitting', read='SM0;'),
    _status('VL', 'Supply voltage'),
)

ACTION_COMMANDS = _by_code(
    _action('TX', 'Key the transmitter', 'TX;'),
    _action('RX', 'Return to receive', 'RX;'),
    _action('PTT', 'Set PTT state; not in r3', 'PT{};',
            Param('state', 2, 1, 0, 1)),
    _action('TUNE', 'Start antenna tuning', 'AC0{}1;',
            Param('atu', 3, 1, 0, 1)),
    _action('BD', 'Band down', 'BD;'),
    _action('BU', 'Band up', 'BU;'),
    _action('VV', 'VFO copy (A=B)', 'VV;'),
    _action('PS', 'Set power state', 'PS{};', Param('state', 2, 1, 0, 1)),
    # Undocumented: Lab599's Settings app uses XL and XS to back up and
    # restore the radio's settings memory in bulk, XL1000; to XL2023;.
    # Placeholder for now, not explicitly needed for full functionality
    _action('XL', 'Read settings memory', 'XL{};',
            Param('address', 2, 4, 1000, 2023)),
    _action('XS', 'Write settings memory', 'XS{} {};',
            Param('address', 2, 4, 1000, 2023), Param('value', 7, 3, 0, 255)),
)

UNSUPPORTED_COMMANDS = _by_code(
    _unsupported('FB', 'VFO B frequency'),
    _unsupported('NF', 'Notch filter type; AL sets it'),
    _unsupported('RT', 'RIT on/off'),
    _unsupported('SP', 'Split on/off'),
    _unsupported('TN', 'Tone number; r3 names it under IF but has no entry'),
    _unsupported('XT', 'XIT on/off'),
)

MEMORY_READ = Command('MR', 'Read a memory channel', Kind.MEMORY, '',
                      'MR00{};', (Param('channel', 4, 2, 0, 99),))

# v1.31.02 reads squelch with SQ;. Older firmware uses SQ0; like the spec.
# v1.31.02 answers SQ0; with just ;
SQUELCH_READ = 'SQ;'
SQUELCH_READ_V130 = 'SQ0;'

READ_FRAMES = frozenset(
    command.read for command in (*SETTING_COMMANDS.values(),
                                 *STATUS_COMMANDS.values())
) | {SQUELCH_READ}


UNKNOWN_OPTION = "Radio value %i"
VOX_WARNING = ("With VOX on, the radio can transmit without PTT. Do not "
               "enable it unless an antenna or dummy load is connected.")
NOT_READ = "Not read: %s"
BLOCKED_BY_MEMORY = "radio is on a memory channel"
BLOCKED_BY_TX = "radio is transmitting"
NEEDS_FIRMWARE = "needs firmware %s or newer"
MODE_ATTEMPTS = 3
MODE_SETTLE = 0.15


@dataclass(frozen=True)
class SettingSpec(abc.ABC):
    name: str
    label: str
    code: str
    _: KW_ONLY
    param: int = 0
    doc: str | None = None
    warning: str | None = None
    safe_value: bool | None = None
    modes: tuple[str, ...] | None = None
    page: str | None = None
    min_firmware: str | None = None

    @property
    def command(self):
        return SETTING_COMMANDS[self.code]

    @property
    def limits(self):
        return self.command.params[self.param]

    @property
    def read_frame(self):
        return self.command.read

    @abc.abstractmethod
    def make_value(self, code):
        ...

    @abc.abstractmethod
    def to_code(self, value):
        ...

    def write_code(self, code):
        return code

    def frame_codes(self, values):
        codes = list(values)
        codes[self.param] = self.write_code(values[self.param])
        return codes

    def matches(self, stored, wanted):
        return stored == wanted

    def build(self, reply):
        code = self.command.parse(reply)[self.param]
        setting = RadioSetting(self.name, self.label, self.make_value(code))
        if self.doc:
            setting.set_doc(self.doc)
        if self.warning:
            setting.set_warning(self.warning, self.safe_value)
        return setting

    def build_unread(self, reason):
        value = RadioSettingValueString(0, 64, NOT_READ % reason,
                                        autopad=False)
        value.set_mutable(False)
        return RadioSetting(self.name, self.label, value)


@dataclass(frozen=True)
class IntSpec(SettingSpec):
    def make_value(self, code):
        limits = self.limits
        if limits.accepts(code):
            return RadioSettingValueInteger(limits.lo, limits.hi, code,
                                            limits.step)
        value = RadioSettingValueInteger(code, code, code)
        value.set_mutable(False)
        return value

    def to_code(self, value):
        return int(value)


@dataclass(frozen=True)
class ClockSpec(IntSpec):
    def frame_codes(self, values):
        return [*values[:2], 0]

    # Seconds are written as 00 and read back right away, so the minute can't
    # roll over before we check. Only compare hour and minute
    def matches(self, stored, wanted):
        return stored[:2] == wanted[:2]


@dataclass(frozen=True)
class BoolSpec(SettingSpec):
    def make_value(self, code):
        return RadioSettingValueBoolean(bool(code))

    def to_code(self, value):
        return int(bool(value))


@dataclass(frozen=True)
class ChoiceSpec(SettingSpec):
    labels: dict[int, str]
    write_codes: dict[int, int] = field(default_factory=dict)

    @property
    def options(self):
        return list(self.labels.values())

    def make_value(self, code):
        options = self.options
        # Radio can report codes not in the protocol, like CN54
        text = self.labels.get(code, UNKNOWN_OPTION % code)
        if text not in options:
            options.append(text)
        return RadioSettingValueList(options,
                                     current_index=options.index(text))

    def to_code(self, value):
        text = str(value)
        codes = {label: code for code, label in self.labels.items()}
        return codes[text] if text in codes else int(text.rsplit(' ', 1)[1])

    def write_code(self, code):
        return self.write_codes.get(code, code)


@dataclass(frozen=True)
class StatusSpec:
    name: str
    label: str
    read_frame: str
    render: Callable[[str], str]

    modes = None
    page = None
    min_firmware = None

    def build(self, reply):
        value = RadioSettingValueString(0, 32, self.render(reply),
                                        autopad=False)
        value.set_mutable(False)
        return RadioSetting(self.name, self.label, value)


def _indexed(options, start=0):
    return dict(enumerate(options, start))


def per_mode(spec_class, name, label, code, *args, **kwargs):
    return tuple(
        spec_class("%s_%s" % (name, group.lower()), label, code, *args,
                   modes=modes, page=group, **kwargs)
        for group, modes in MODE_GROUPS[code].items())


SETTING_GROUPS = (
    ("operating", "Operating", (
        IntSpec("vfo_a", "VFO A frequency (Hz)", "FA"),
        ChoiceSpec("rx_function", "Receive on", "FR",
                   _indexed(VFO_FUNCTIONS)),
        ChoiceSpec("tx_function", "Transmit on", "FT",
                   _indexed(VFO_FUNCTIONS),
                   doc="VFO B's frequency cannot be read on this radio."),
        ChoiceSpec("mode", "Mode", "MD",
                   _indexed(LAB599_MODES[1:], 1)),
        IntSpec("memory_channel", "Memory channel", "MC"),
        BoolSpec("lock", "Lock", "LK"),
        ClockSpec("clock_hour", "Hour", "TM", param=0, page="Clock",
                  min_firmware=CLOCK_MIN_FIRMWARE,
                  doc="Seconds restart at 00 when this changes."),
        ClockSpec("clock_minute", "Minute", "TM", param=1, page="Clock",
                  min_firmware=CLOCK_MIN_FIRMWARE,
                  doc="Seconds restart at 00 when this changes."),
    )),
    ("receiver", "Receiver", (
        IntSpec("af_gain", "AF gain", "AG"),
        *per_mode(ChoiceSpec, "rf_gain", "RF gain", "RG",
                  RF_GAIN_LABELS,
                  write_codes=RF_GAIN_LEVELS),
        IntSpec("squelch_ssb_am", "Squelch (all modes except FM)", "SQ",
                modes=MODE_GROUPS['SQ']['SSB/AM']),
        IntSpec("squelch_fm", "Squelch", "SQ",
                modes=MODE_GROUPS['SQ']['FM'], page='FM'),
        BoolSpec("preamp", "Preamplifier", "PA"),
        BoolSpec("attenuator", "Attenuator", "RA"),
        *per_mode(IntSpec, "agc", "AGC speed", "GT",
                  doc="1 is slow, 10 is fast."),
        ChoiceSpec("rx_filter", "RX filter", "FL",
                   _indexed(RX_FILTERS),
                   param=0),
        BoolSpec("dif", "DIF", "IS"),
    )),
    ("noise", "Noise", (
        BoolSpec("nb", "Noise blanker", "NB"),
        IntSpec("nb_level", "Noise blanker level", "NL"),
        BoolSpec("nr", "Noise reduction", "NR"),
        IntSpec("nr_level", "Noise reduction level", "RL"),
        BoolSpec("notch", "Auto notch", "NT"),
        ChoiceSpec("notch_type", "Notch type", "AL",
                   _indexed(NOTCH_TYPES)),
    )),
    ("transmit", "Transmit", (
        IntSpec("power", "Output power (%)", "PC"),
        ChoiceSpec("tx_filter", "TX filter", "FL",
                   _indexed(TX_FILTERS),
                   param=1),
        IntSpec("tune_power", "Tune power", "TP"),
        StatusSpec("carrier", "Carrier level (follows tune power)", "CG;",
                   lambda r: r[2:-1].lstrip("0") or "0"),
        BoolSpec("atu", "Antenna tuner", "AC",
                 doc="Enables the tuner. CHIRP never starts a tuning cycle."),
        ChoiceSpec("meter", "Meter", "RM",
                   _indexed(METER_FUNCTIONS)),
    )),
    ("audio", "Audio", (
        IntSpec("mic_gain", "Mic gain", "MG"),
        IntSpec("dig_gain", "DIG gain", "MA"),
        BoolSpec("compressor", "Speech compressor", "PR"),
        IntSpec("compressor_level", "Compressor level", "PL"),
        BoolSpec("monitor_mute", "TX monitor mute", "MO"),
        IntSpec("monitor_level", "TX monitor level", "ML"),
    )),
    ("cw_vox", "CW & VOX", (
        IntSpec("keyer_speed", "Keyer speed (CPM)", "KS"),
        *per_mode(BoolSpec, "vox", "VOX", "VX", warning=VOX_WARNING,
                  safe_value=False),
        *per_mode(IntSpec, "vox_gain", "VOX gain", "VG"),
        *per_mode(IntSpec, "vox_delay", "VOX delay (ms)", "VD"),
    )),
    ("tones", "Tones", (
        BoolSpec("tone", "Tone", "TO"),
        BoolSpec("ctcss", "CTCSS", "CT"),
        ChoiceSpec("ctcss_tone", "CTCSS tone", "CN",
                   _indexed(f"{tone:.1f} Hz"
                            for tone in CTCSS_TONES)),
    )),
    ("status", "Status", (
        StatusSpec("voltage", "Supply voltage", "VL;",
                   lambda r: "%s V" % r[2:-1].strip()),
        StatusSpec("s_meter", "S-meter (0-30)", "SM0;",
                   lambda r: r[3:-1].lstrip("0") or "0"),
        StatusSpec("busy", "Busy", "BY;",
                   lambda r: "Yes" if r[2:3] == "1" else "No"),
        StatusSpec("ptt", "PTT", "PT;",
                   lambda r: "Transmit" if r == "PT1;" else "Receive"),
    )),
)

SPECS_BY_NAME = {spec.name: spec for _name, _label, specs in SETTING_GROUPS
                 for spec in specs}


class Lab599Protocol:
    """Newest firmware, v1.31.02"""

    def __init__(self, link):
        self.link = link

    def query(self, frame):
        return self.link.query(frame)

    def write_setting(self, frame):
        self.link.write_setting(frame)

    def is_transmitting(self):
        return self.link.is_transmitting()

    def read(self, command):
        if command.code == 'SQ':
            return self.read_squelch()
        if command.code == 'TM':
            return self.read_clock()
        return self.query(command.read)

    def read_squelch(self):
        return self.query(SQUELCH_READ)

    def read_clock(self):
        return self.query('TM;')


class Lab599ProtocolV130(Lab599Protocol):
    """v1.29.01 to v1.31.01"""

    def read_squelch(self):
        return self.query(SQUELCH_READ_V130)


class Lab599ProtocolV128(Lab599ProtocolV130):
    """Older than v1.29.01, which added the clock"""

    def read_clock(self):
        return None


def detect_protocol(link):
    # CAT can't read the firmware version, guess from responses
    if link.probe(SQUELCH_READ_V130) == TERMINATOR:
        return Lab599Protocol(link)
    if link.probe('TM;') in ('TM;', ERROR_SYNTAX):
        return Lab599ProtocolV128(link)
    return Lab599ProtocolV130(link)


class ModeVisit:
    def __init__(self, link):
        self._link = link
        self._command = SETTING_COMMANDS['MD']
        self._vox = SETTING_COMMANDS['VX']
        self.home = None
        self._here = None
        self._held_vox = {}

    def __enter__(self):
        self.home = self._here = self._read()
        return self

    def __exit__(self, *_exc):
        try:
            self._restore_vox()
        finally:
            self._switch(self.home)

    def _read(self):
        code = self._command.parse(self._link.query(self._command.read))[0]
        return LAB599_MODES[code]

    @staticmethod
    def _vox_group(mode):
        return next((name for name, modes
                     in MODE_GROUPS['VX'].items() if mode in modes),
                    None)

    @property
    def holds_vox(self):
        return self._vox_group(self._here) in self._held_vox

    def set_held_vox(self, value):
        self._held_vox[self._vox_group(self._here)] = value

    def read(self, command):
        if command is self._vox and self.holds_vox:
            group = self._vox_group(self._here)
            return self._vox.set_frame(self._held_vox[group])
        return self._link.read(command)

    def go(self, mode):
        self._switch(mode)
        group = self._vox_group(mode)
        if mode == self.home or group in self._held_vox:
            return
        # VOX could key the radio, so keep it off until we're done
        if self._link.query(self._vox.read) == self._vox.set_frame(1):
            self._held_vox[group] = 1
            self._write_vox(0)

    def _write_vox(self, value):
        frame = self._vox.set_frame(value)
        self._link.write_setting(frame)
        if self._link.query(self._vox.read) != frame:
            raise errors.RadioError("Radio did not turn VOX %s" % (
                "on" if value else "off"))

    def _restore_vox(self):
        vox_modes = MODE_GROUPS['VX']
        failed = []
        for group in sorted(self._held_vox,
                            key=lambda name: self.home in vox_modes[name]):
            if not self._held_vox[group]:
                continue
            try:
                if self._link.is_transmitting():
                    raise errors.RadioError("Radio is transmitting")
                self._switch(self.home if self.home in vox_modes[group]
                             else vox_modes[group][0])
                self._write_vox(1)
            except errors.RadioError as e:
                LOG.error("Could not restore VOX for %s: %s", group, e)
                failed.append(group)
        if failed:
            raise errors.RadioError("VOX was left off for %s" %
                                    ", ".join(failed))

    def _switch(self, mode):
        if mode == self._here:
            return
        frame = self._command.set_frame(LAB599_MODES.index(mode))
        for _attempt in range(MODE_ATTEMPTS):
            self._link.write_setting(frame)
            time.sleep(MODE_SETTLE)
            if self._read() == mode:
                self._here = mode
                return
        raise errors.RadioError("Radio did not change to %s" % mode)


class SettingsPanel:
    def __init__(self, link):
        self._link = link
        self._protocol = None
        self._known = {}

    @property
    def protocol(self):
        if self._protocol is None:
            self._protocol = detect_protocol(self._link)
        return self._protocol

    def read(self):
        self._known = {}
        per_mode = self._read_per_mode()
        replies = {}
        groups = []
        for name, label, specs in SETTING_GROUPS:
            group = RadioSettingGroup(name, label)
            pages = {}
            for spec in specs:
                setting = self._read_one(spec, per_mode, replies)
                if spec.page:
                    page = pages.setdefault(spec.page, RadioSettingSubGroup(
                        f"{name}_{spec.page.lower()}", spec.page))
                    page.append(setting)
                else:
                    group.append(setting)
            for page in pages.values():
                group.append(page)
            groups.append(group)
        return RadioSettings(*groups)

    def _read_one(self, spec, per_mode, replies):
        if spec.modes:
            setting = per_mode[spec.name]
        else:
            frame = spec.read_frame
            if frame not in replies:
                replies[frame] = self._read_reply(spec)
            if replies[frame]:
                setting = spec.build(replies[frame])
            else:
                setting = spec.build_unread(
                    NEEDS_FIRMWARE % spec.min_firmware)
        if setting.value.get_mutable():
            self._known[spec.name] = spec.to_code(setting.value)
        return setting

    def _read_reply(self, spec):
        if isinstance(spec, StatusSpec):
            return self._link.query(spec.read_frame)
        return self.protocol.read(spec.command)

    def _read_per_mode(self):
        settings = {}
        with ModeVisit(self.protocol) as visit:
            blocked = self._switch_blocker()
            for mode, specs in self._stops(visit.home):
                if mode != visit.home:
                    if blocked:
                        settings.update((spec.name, spec.build_unread(blocked))
                                        for spec in specs)
                        continue
                    self._refuse_if_transmitting("change modes")
                    visit.go(mode)
                settings.update(
                    (spec.name, spec.build(visit.read(spec.command)))
                    for spec in specs)
        return settings

    @staticmethod
    def _stops(home):
        stops = {home: []}
        for spec in SPECS_BY_NAME.values():
            if spec.modes:
                stop = home if home in spec.modes else spec.modes[0]
                stops.setdefault(stop, []).append(spec)
        return stops.items()

    def _refuse_if_transmitting(self, action="change settings"):
        if self._link.is_transmitting():
            raise errors.RadioError("Refusing to %s while transmitting" %
                                    action)

    def _switch_blocker(self):
        if self._link.is_transmitting():
            return BLOCKED_BY_TX
        function = SETTING_COMMANDS['FR']
        current = function.parse(self._link.query(function.read))[0]
        if current == VFO_FUNCTIONS.index('Memory'):
            return BLOCKED_BY_MEMORY
        return None

    def apply(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.apply(element)
            elif element.changed() and element.value.get_mutable():
                spec = SPECS_BY_NAME[element.get_name()]
                code = spec.to_code(element.value)
                if not self._already_applied(spec, code):
                    self._apply_one(spec, element)
                    self._known[spec.name] = code

    def _already_applied(self, spec, code):
        return self._known.get(spec.name) == code

    def _apply_one(self, spec, setting):
        self._refuse_if_transmitting()
        if not spec.modes:
            self._change(spec, setting)
            return
        with ModeVisit(self.protocol) as visit:
            if visit.home not in spec.modes:
                self._enter_mode(visit, spec)
            if spec.code == 'VX' and visit.holds_vox:
                visit.set_held_vox(spec.to_code(setting.value))
            else:
                self._change(spec, setting)

    def _enter_mode(self, visit, spec):
        blocked = self._switch_blocker()
        if blocked:
            raise errors.RadioError("Cannot change %s: %s" % (spec.label,
                                                              blocked))
        visit.go(spec.modes[0])

    def _change(self, spec, setting):
        command = spec.command
        before = command.parse(self.protocol.read(command))
        after = list(before)
        after[spec.param] = spec.to_code(setting.value)
        if after == before or self._store(spec, after):
            return

        LOG.error("%s: radio did not accept %r", spec.name, after)
        try:
            self._store(spec, before)
        except errors.RadioError as e:
            LOG.error("%s: could not restore: %s", spec.name, e)
        raise errors.RadioError("Radio did not accept %s" % spec.label)

    def _store(self, spec, values):
        command = spec.command
        self._link.write_setting(command.set_frame(*spec.frame_codes(values)))
        return spec.matches(command.parse(self.protocol.read(command)),
                            values)


NOCACHE = "CHIRP_NOCACHE" in os.environ
REPLY_TIMEOUT = 0.4
# As of v1.31.02, the radio stalls on every 11th memory write and drops what
# it is sent, so retry
REPLY_ATTEMPTS = 8
WRITE_SETTLE = 0.1
RF_PATH_SETTING = "rf_path"


class CommandRefused(errors.RadioError):
    pass


class CommandGate:
    def check_read(self, frame):
        if (frame not in READ_FRAMES and
                not MEMORY_READ.accepts(frame)):
            raise CommandRefused('Refused to send %r' % frame)

    def check_set(self, frame):
        if not any(command.accepts(frame)
                   for command in SETTING_COMMANDS.values()):
            raise CommandRefused('Refused to set %r' % frame)

    def check_write(self, frame):
        if not MEMORY_WRITE_PATTERN.fullmatch(frame):
            raise CommandRefused('Refused to write %r' % frame)


class Lab599Cat:
    def __init__(self, pipe):
        self.pipe = pipe
        self.pipe.timeout = REPLY_TIMEOUT
        self._gate = CommandGate()
        self._lock = threading.Lock()

    def query(self, frame):
        self._gate.check_read(frame)
        reply = ''
        with self._lock:
            for _attempt in range(REPLY_ATTEMPTS):
                reply = self._exchange(frame)
                if reply in ERROR_REPLIES:
                    error = (CommandRejected
                             if reply == ERROR_SYNTAX
                             else errors.RadioError)
                    raise error('%s: %s' % (ERROR_REPLIES[reply],
                                            frame))
                if reply.startswith(frame[:-1]) and reply.endswith(';'):
                    return reply
        if reply:
            raise errors.RadioError('Unexpected reply to %s: %r' % (frame,
                                                                    reply))
        raise errors.RadioNoResponse()

    def probe(self, frame):
        """Return the first answer to a read, even an error or a bare ;"""
        self._gate.check_read(frame)
        with self._lock:
            for _attempt in range(REPLY_ATTEMPTS):
                reply = self._exchange(frame)
                if reply:
                    return reply
        raise errors.RadioNoResponse()

    def _exchange(self, frame):
        self.pipe.reset_input_buffer()
        self._send(frame)
        return self._receive()

    def write_memory(self, frame):
        self._gate.check_write(frame)
        self._send_unanswered(frame)

    def write_setting(self, frame):
        self._gate.check_set(frame)
        self._send_unanswered(frame)

    def _send_unanswered(self, frame):
        with self._lock:
            self.pipe.reset_input_buffer()
            self._send(frame)
            time.sleep(WRITE_SETTLE)

    def identify(self):
        return self.query('ID;')[2:-1]

    def require_id(self, expected):
        radio_id = self.identify()
        if radio_id == expected:
            return
        if radio_id == ID_TS2000:
            raise errors.RadioError('Radio is in TS-2000 CAT mode. Select '
                                    'the LAB599 CAT protocol on the radio.')
        raise errors.RadioError('Radio reports ID %s (expected %s)' % (
            radio_id, expected))

    def is_transmitting(self):
        reply = self.query('PT;')
        if reply not in ('PT0;', 'PT1;'):
            raise errors.RadioError('Unexpected PTT state: %r' % reply)
        return reply == 'PT1;'

    def _send(self, frame):
        self.pipe.write(frame.encode('ascii'))

    def _receive(self):
        reply = self.pipe.read_until(TERMINATOR.encode('ascii'))
        return reply.decode('ascii', 'replace')


@dataclass(frozen=True)
class MemoryRecord:
    _p1: str = '0'
    _p2: str = '0'
    _p3: str = '00'
    _p4: str = '0' * 11
    _p5: str = str(EMPTY_MEMORY_MODE)
    _p6: str = '0'
    _p7: str = '0'
    _p8: str = '00'
    _p9: str = '00'
    _p10: str = '000'
    _p11: str = '0'
    _p12: str = '0'
    _p13: str = '0' * 9
    _p14: str = '00'
    _p15: str = '0'
    _p16: str = ' ' * 8

    @classmethod
    def _new(cls, number, freq=0, mode=EMPTY_MEMORY_MODE, rf_path=0):
        return cls(_p3=f'{number:02d}', _p4=f'{freq:011d}', _p5=str(mode),
                   _p6=str(rf_path))

    @classmethod
    def empty(cls, number):
        return cls._new(number)

    @classmethod
    def from_spec(cls, spec):
        if (len(spec) != MEMORY_RECORD_LENGTH or
                spec[:2] not in ('MR', 'MW') or not spec.endswith(';')):
            raise errors.RadioError(f'Malformed memory record: {spec!r}')
        values = {}
        start = 2
        for part in fields(cls):
            end = start + len(part.default)
            values[part.name] = spec[start:end]
            start = end
        record = cls(**values)
        numeric = record._p3 + record._p4 + record._p5 + record._p6
        if not (numeric.isascii() and numeric.isdigit()):
            raise errors.RadioError(f'Malformed memory record: {spec!r}')
        return record

    @classmethod
    def from_memory(cls, mem):
        if mem.empty:
            return cls.empty(mem.number)
        if mem.mode not in LAB599_MODES[1:]:
            raise errors.RadioError('Mode %s is not supported' % mem.mode)
        return cls._new(mem.number, mem.freq, LAB599_MODES.index(mem.mode),
                        cls._rf_path_of(mem))

    @staticmethod
    def _rf_path_of(mem):
        for setting in mem.extra:
            if setting.get_name() == RF_PATH_SETTING:
                return LAB599_RF_PATHS.index(str(setting.value))
        return 0

    @property
    def number(self):
        return int(self._p3)

    @property
    def freq(self):
        return int(self._p4)

    @property
    def is_empty(self):
        return self.freq == 0

    @property
    def mode(self):
        code = int(self._p5)
        if not 1 <= code < len(LAB599_MODES):
            raise errors.RadioError('Unknown mode %i in channel %i' % (
                code, self.number))
        return LAB599_MODES[code]

    @property
    def rf_path(self):
        code = int(self._p6)
        if code >= len(LAB599_RF_PATHS):
            raise errors.RadioError('Unknown RF path %i in channel %i' % (
                code, self.number))
        return LAB599_RF_PATHS[code]

    def to_spec(self):
        # Everything after the 00 and channel number
        return ''.join(astuple(self)[3:])

    def to_memory(self):
        mem = chirp_common.Memory()
        mem.number = self.number
        path = 0 if self.is_empty else LAB599_RF_PATHS.index(self.rf_path)
        mem.extra = RadioSettingGroup("extra", "Extra")
        mem.extra.append(RadioSetting(
            RF_PATH_SETTING, "RF Path",
            RadioSettingValueList(LAB599_RF_PATHS, current_index=path)))
        if self.is_empty:
            mem.empty = True
            return mem
        mem.freq = self.freq
        mem.mode = self.mode
        return mem

    def matches(self, other):
        if self.number != other.number:
            return False
        if self.is_empty or other.is_empty:
            return self.is_empty and other.is_empty
        return (self.freq, self._p5, self._p6) == (other.freq, other._p5,
                                                   other._p6)


class Lab599Radio(chirp_common.LiveRadio):
    VENDOR = "Lab599"
    BAUD_RATE = 9600
    HARDWARE_FLOW = False
    # These lines can key the transmitter on some interfaces
    WANTS_DTR = False
    WANTS_RTS = False

    _radio_id = ""
    _upper = 99
    _valid_bands = [(FREQ_MIN_HZ, FREQ_MAX_HZ + 1)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memcache = {}
        self._cat_link = None
        self._settings_panel = None
        if self.pipe:
            self._connect()

    def _connect(self):
        if self.pipe is None:
            raise errors.RadioError("Radio is not connected")
        if self._cat_link is None or self._cat_link.pipe is not self.pipe:
            link = Lab599Cat(self.pipe)
            link.require_id(self._radio_id)
            self._cat_link = link
            self._settings_panel = SettingsPanel(link)
            self._memcache.clear()
        return self._cat_link

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_name = False
        rf.has_ctone = False
        rf.has_cross = False
        rf.has_dtcs = False
        rf.has_rx_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_offset = False
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.has_settings = True
        rf.has_comment = False
        rf.valid_modes = LAB599_MODES[1:]
        rf.valid_tmodes = []
        rf.valid_tones = []
        rf.valid_duplexes = []
        rf.valid_skips = []
        rf.valid_name_length = 0
        rf.valid_bands = list(self._valid_bands)
        rf.memory_bounds = (0, self._upper)
        return rf

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs
        for attr, label in (('tmode', 'Tone mode'), ('duplex', 'Duplex'),
                            ('skip', 'Skip')):
            if getattr(mem, attr):
                msgs.append(chirp_common.ValidationError(
                    "%s %s not supported" % (label, getattr(mem, attr))))
        return msgs

    def _cmd_get_memory(self, number):
        return "MR00%02i;" % number

    def _cmd_set_memory(self, number, spec):
        return "MW00%02i%s;" % (number, spec)

    def _cmd_erase_memory(self, number):
        return self._cmd_set_memory(number,
                                    MemoryRecord.empty(number).to_spec())

    def _check_number(self, number):
        if not 0 <= number <= self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)

    def get_raw_memory(self, number):
        self._check_number(number)
        return self._connect().query(self._cmd_get_memory(number))

    def get_memory(self, number):
        self._check_number(number)
        link = self._connect()
        if number not in self._memcache or NOCACHE:
            spec = link.query(self._cmd_get_memory(number))
            self._memcache[number] = self._parse_mem_spec(spec, number)
        return self._memcache[number].dupe()

    def _check_freq(self, freq):
        # Radio clears the channel if it rejects the frequency
        if not any(lo <= freq < hi for lo, hi in self._valid_bands):
            raise errors.RadioError(
                "Frequency %s is outside the radio's range" %
                chirp_common.format_freq(freq))

    def set_memory(self, memory):
        self._check_number(memory.number)
        if not memory.empty:
            self._check_freq(memory.freq)
        record = MemoryRecord.from_memory(memory)
        self._store(record, self._cmd_set_memory(record.number,
                                                 self._make_mem_spec(memory)))

    def erase_memory(self, number):
        self._check_number(number)
        self._store(MemoryRecord.empty(number),
                    self._cmd_erase_memory(number))

    def _store(self, record, frame):
        link = self._connect()
        if link.is_transmitting():
            raise errors.RadioError("Refusing to write while transmitting")

        read_frame = self._cmd_get_memory(record.number)
        previous = MemoryRecord.from_spec(link.query(read_frame))
        self._memcache.pop(record.number, None)
        link.write_memory(frame)
        spec = link.query(read_frame)
        stored = MemoryRecord.from_spec(spec)
        if stored.matches(record):
            self._memcache[record.number] = stored.to_memory()
            return

        LOG.error("Wrote %s but radio holds %s", frame, spec)
        link.write_memory(self._cmd_set_memory(previous.number,
                                               previous.to_spec()))
        restored = MemoryRecord.from_spec(link.query(read_frame))
        outcome = ("previous contents restored" if restored.matches(previous)
                   else "previous contents could not be restored")
        raise errors.RadioError("Radio did not store channel %i as written; "
                                "%s" % (record.number, outcome))

    def _parse_mem_spec(self, spec, number):
        record = MemoryRecord.from_spec(spec)
        if record.number != number:
            raise errors.RadioError("Asked for channel %i, got %i" % (
                number, record.number))
        return record.to_memory()

    def _make_mem_spec(self, mem):
        return MemoryRecord.from_memory(mem).to_spec()

    def get_settings(self):
        self._connect()
        return self._settings_panel.read()

    def set_settings(self, settings):
        self._connect()
        self._settings_panel.apply(settings)


@directory.register
class TX500Radio(Lab599Radio):
    MODEL = "TX-500"

    _radio_id = ID_TX500


@directory.register
class TX500MPRadio(Lab599Radio):
    MODEL = "TX-500MP"

    _radio_id = ID_TX500MP
