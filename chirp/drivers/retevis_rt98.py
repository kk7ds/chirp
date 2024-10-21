# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
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

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings, \
    RadioSettingValueList, RadioSettingValueString, RadioSettingValueBoolean, \
    RadioSettingValueInteger

LOG = logging.getLogger(__name__)

#
#  Chirp Driver for Retevis RT98 models: RT98V (136-174 MHz)
#                                        RT98U (400-490 MHz)
#                                        RT98W (66-88 MHz)
#
#
#
# Global Parameters
#
TONES = [62.5] + list(chirp_common.TONES)
TMODES = ['', 'Tone', 'DTCS']
DUPLEXES = ['', '+', '-']

TXPOWER_LOW = 0x00
TXPOWER_MED = 0x01
TXPOWER_HIGH = 0x02

DUPLEX_NOSPLIT = 0x00
DUPLEX_POSSPLIT = 0x01
DUPLEX_NEGSPLIT = 0x02

CHANNEL_WIDTH_12d5kHz = 0x00
CHANNEL_WIDTH_20kHz = 0x01
CHANNEL_WIDTH_25kHz = 0x02

TUNING_STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 30.0, 50.0]

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("Mid", watts=10),
                chirp_common.PowerLevel("High", watts=15)]

PMR_POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.5), ]

FREENET_POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1), ]

PMR_FREQS = [446006250, 446018750, 446031250, 446043750,
             446056250, 446068750, 446081250, 446093750,
             446106250, 446118750, 446131250, 446143750,
             446156250, 446168750, 446181250, 446193750]

FREENET_FREQS = [149025000, 149037500, 149050000,
                 149087500, 149100000, 149112500]

CROSS_MODES = ["Tone->Tone", "DTCS->", "->DTCS", "Tone->DTCS", "DTCS->Tone",
               "->Tone", "DTCS->DTCS"]

LIST_STEP = [str(x) for x in TUNING_STEPS]
LIST_TIMEOUT = ["Off"] + ["%s min" % x for x in range(1, 31)]
LIST_APO = ["Off", "30 min", "1 hr", "2 hrs"]
LIST_SQUELCH = ["Off"] + ["Level %s" % x for x in range(1, 10)]
LIST_DISPLAY_MODE = ["Channel", "Frequency", "Name"]
LIST_AOP = ["Manual", "Auto"]
LIST_STE_TYPE = ["Off", "Silent", "120 Degree", "180 Degree", "240 Degree"]
LIST_STE_FREQ = ["Off", "55.2 Hz", "259.2 Hz"]
LIST_VFOMR = ["MR", "VFO"]
LIST_SCAN = ["TO", "CO", "SE"]

LIST_PRIORITY_CH = ["Off", "Priority Channel 1", "Priority Channel 2",
                    "Priority Channel 1 + Priority Channel 2"]

LIST_REVERT_CH = ["Selected", "Selected + TalkBack", "Priority Channel 1",
                  "Priority Channel 2", "Last Called", "Last Used",
                  "Priority Channel 1 + TalkBack",
                  "Priority Channel 2 + TalkBack"]

LIST_TIME50 = ["0.1", "0.2", "0.3", "0.4", "0.5",
               "0.6", "0.7", "0.8", "0.9", "1.0",
               "1.1", "1.2", "1.3", "1.4", "1.5",
               "1.6", "1.7", "1.8", "1.9", "2.0",
               "2.1", "3.2", "2.3", "2.4", "2.5",
               "2.6", "2.7", "2.8", "2.9", "3.0",
               "3.1", "3.2", "3.3", "3.4", "3.5",
               "3.6", "3.7", "3.8", "3.9", "4.0",
               "4.1", "4.2", "4.3", "4.4", "4.5",
               "4.6", "4.7", "4.8", "4.9", "5.0"]
LIST_TIME46 = LIST_TIME50[4:]

LIST_RT98V_MODES = ["FreeNet", "COM", "COMII"]
LIST_RT98U_MODES = ["PMR", "COM", "COMII"]
LIST_RT98W_MODES = ["", "", "", "", "", "", "COM"]

LIST_RT98V_FREQS = ["Rx(149 - 149.2 MHz) Tx(149 - 149.2 MHz)",
                    "Rx(136 - 174 MHz) Tx(136 - 174 MHz)",
                    "Rx(147 - 174 MHz) Tx(147 - 174 MHz)"]

LIST_RT98U_FREQS = ["Rx(446 - 446.2 MHz) Tx(446 - 446.2 MHz)",
                    "Rx(400 - 470 MHz) Tx(400 - 470 MHz)",
                    "Rx(450 - 470 MHz) Tx(450 - 470 MHz)"]

LIST_RT98W_FREQS = ["",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "Rx(66 - 88 MHz) Tx(66 - 88 MHz)"]

#  RT98  memory map
#  section: 1  Channel Bank
#         description of channel bank (199 channels , range 1-199)
#         Each 32 Byte (0x20 hex)  record:
#  bytes:bit  type                 description
#  ---------------------------------------------------------------------------
#  4          bbcd freq[4]         receive frequency in packed binary coded
#                                  decimal
#  4          bbcd offset[4]       transceive offset in packed binary coded
#                                  decimal (note: +/- direction set by
#                                  'duplex' field)
#  1          u8 unknown0
#  1          u8
#   :1        reverse:1            reverse flag, 0=off, 1=on (reverses
#                                  transmit and receive frequencies)
#   :1        txoff:1              transmitt off flag, 0=transmit, 1=do not
#                                  transmit
#   :2        power:2              transmit power setting, value range 0-2,
#                                  0=low, 1=middle, 2=high
#   :2        duplex:2             duplex settings, 0=simplex, 1=plus (+)
#                                  offset, 2=minus(-) offset (see offset field)
#   :2        channel_width:2      channel spacing, 0=12.5kHz, 1=20kHz, 2=25kHz
#  1          u8
#   :2        unknown1:2
#   :1        talkaround:1         talkaround flag, 0=off, 1=on
#                                  (bypasses repeater)
#   :1        squelch_mode:1       squelch mode flag, 0=carrier, 1=ctcss/dcs
#   :1        rxdcsextra:1         use with rxcode for index of rx DCS to use
#   :1        rxinv:1              inverse DCS rx polarity flag, 0=N, 1=I
#   :1        txdcsextra:1         use with txcode for index of tx DCS to use
#   :1        txinv:1              inverse DCS tx polarity flag, 0=N, 1=I
#  1          u8
#   :4        unknown2:4
#   :2        rxtmode:2            rx tone mode, value range 0-2, 0=none,
#                                  1=CTCSS, 2=DCS  (ctcss tone in field rxtone)
#   :2        txtmode:2            tx tone mode, value range 0-2, 0=none,
#                                  1=CTCSS, 3=DCS  (ctcss tone in field txtone)
#  1          u8
#   :2        unknown3:2
#   :6        txtone:6             tx ctcss tone, menu index
#  1          u8
#   :2        unknown4:2
#   :6        rxtone:6             rx ctcss tone, menu index
#  1          u8 txcode            ?, not used for ctcss
#  1          u8 rxcode            ?, not used for ctcss
#  1          u8
#   :6        unknown5:6
#   :1        busychannellockout:1 busy channel lockout flag, 0=off, 1=enabled
#   :1        unknown6:1
#  6          char name[6]         6 byte char string for channel name
#  9          u8 unknown7[9]
#
MEM_FORMAT = """
// #seekto 0x0000;
struct {
  bbcd freq[4];
  bbcd offset[4];
  u8 unknown0;
  u8 reverse:1,
     tx_off:1,
     txpower:2,
     duplex:2,
     channel_width:2;
  u8 unknown1:2,
     talkaround:1,
     squelch_mode:1,
     rxdcsextra:1,
     rxinv:1,
     txdcsextra:1,
     txinv:1;
  u8 unknown2:4,
     rxtmode:2,
     txtmode:2;
  u8 unknown3:2,
     txtone:6;
  u8 unknown4:2,
     rxtone:6;
  u8 txcode;
  u8 rxcode;
  u8 unknown5:6,
     busychannellockout:1,
     unknown6:1;
  char name[6];
  u8 unknown7[9];
} memory[199];
"""

#  RT98  memory map
#  section: 2 and 3  Channel Set/Skip Flags
#
#    Channel Set (starts 0x3240) : Channel Set  bit is value 0 if a memory
#                                  location in the channel bank is active.
#    Channel Skip (starts 0x3260): Channel Skip bit is value 0 if a memory
#                                  location in the channel bank is active.
#
#    Both flag maps are a total 24 bytes in length, aligned on 32 byte records.
#    bit = 0 channel not set/skip,  1 is channel set/no skip
#
#    to index a channel:
#        cbyte = channel / 8 ;
#        cbit  = channel % 8 ;
#        setflag  = csetflag[cbyte].c[cbit] ;
#        skipflag = cskipflag[cbyte].c[cbit] ;
#
#    channel range is 1-199, range is 32 bytes (last 7 unknown)
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3240;
struct {
   bit c[8];
} csetflag[32];

// #seekto 0x3260;
struct {
   bit c[8];
} cskipflag[32];

"""

#  RT98  memory map
#  section: 4  Startup Label
#
#  bytes:bit  type                 description
#  ---------------------------------------------------------------------------
#  6          char start_label[6]  label displayed at startup (usually
#                                  your call sign)
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3300;
struct {
    char startname[6];
} slabel;
"""

#  RT98  memory map
#  section: 5, 6 and 7  Radio Options
#        used to set a number of radio options
#
# description of function setup options, starting at 0x3310 (settings3)
#
#  bytes:bit  type                 description
#  ---------------------------------------------------------------------------
#  1          u8
#   :6        unknown:6
#   :2        bandlimit_3310:2     frequency ranges, range 0-2,
#                                  0=freenet(vhf) or pmr(uhf), 1=com, 2=comii
#                   rt98v - 00 FreeNet Rx(149 - 149.2 MHz) Tx(149 - 149.2 MHz)
#                           01 COM     Rx(136 - 174 MHz) Tx(136 - 174 MHz)
#                           02 COMII   Rx(147 - 174 MHz) Tx(147 - 174 MHz)
#                   rt98u - 00 PMR     Rx(446 - 446.2 MHz) Tx(446 - 446.2 MHz)
#                           01 COM     Rx(400 - 470 MHz) Tx(400 - 470 MHz)
#                           02 COMII   Rx(450 - 470 MHz) Tx(450 - 470 MHz)
#  1          u8 ch_number;        channel number, range 1-199
#  1          u8
#   :7        unknown_3312:7
#   :1        vfomr:1              vfo/mr mode, range 0-1, 0=mr, 1=vfo
#                                  only S/N:1907***********
#
# description of function setup options, starting at 0x3340 (settings)
#
#  bytes:bit  type                   description
#  ---------------------------------------------------------------------------
#  1          u8
#   :4        unknown_3340:4
#   :4        tuning_step:4          tuning step, menu index value from 0-8
#                                    2.5, 5, 6.25, 10, 12.5, 20, 25, 30, 50
#  1          u8
#   :7        unknown_3341:7
#   :1        beep:1                 beep mode, range 0-1, 0=off, 1=on
#  1           u8
#   :3        unknown_3342:3
#   :5        timeout_timer:5        timeout timer, range off (no timeout),
#                                    1-30 minutes
#  1          u8
#   :6        unknown_3343:6
#   :2        auto_power_off:2       auto power off, range 0-3, off, 30min,
#                                    1hr, 2hr
#  1          u8
#   :4        unknown_3344:4
#   :4        squelch:4              squelch level, range off, 1-9
#  1          u8
#   :3        unknown_3345:3
#   :5        volume:5               volume level, range 1-30 (no zero)
#  1          u8
#   :6        unknown_3346:6
#   :2        scan_revive:2          scan revive method, range 0-2, 0=to,
#                                    1=co, 2=se
#                                    only S/N:1907***********
#  1          u8 unknown_3347
#  1          u8   0x3348 [12]
#   :6        unknown_3348:6
#   :2        display_mode           display mode, range 0-2, 0=channel,
#                                    1=frequency, 2=name
#  1           u8
#   :7        unknown_3349:7
#   :1        auto_power_on:1        auto power on, range 0-1, 0=manual,
#                                    1=auto
#  1          u8
#   :3        unknown_334A:3
#   :5        mic_gain:5             mic gain, range 1-30 (no zero)
#  1          u8
#   :5        unknown_334C:5
#   :3        ste_type:3             ste type, range 0-4, 0=off, 1=silent,
#                                    2=120degree, 3=180degree, 4=240degree
#  1          u8
#   :7        unknown_334D:7
#   :1        ste_frequency:1        ste frequency, range 0-2, 0=off,
#                                    1=55.2Hz, 2=259.2Hz
#  1          u8
#   :2        unknown_0x334E:2
#   :1        forbid_setting:1       forbid setting(optional function),
#                                    range 0-1, 0=disabled, 1=enabled
#   :1        forbid_initialize:1    forbid initialize operate, range 0-1,
#                                    0=enabled, 1=disabled (inverted)
#   :1        save_chan_param:1      save channel parameters, range 0-1,
#                                    0=disabled, 1=enabled
#   :1        forbid_chan_menu:1     forbid channel menu, range 0-1,
#                                    0=disabled, 1=enabled
#   :1        sql_key_function:1     sql key function, range 0-1,
#                                    0=squelch off momentary, 1=squelch off
#   :1        unknown:1
#
# description of function setup options, starting at 0x3380 (settings2)
#
#  bytes:bit  type                   description
#  ---------------------------------------------------------------------------
#  1          u8
#   :7        unknown_3380:7
#   :1        scan_mode:1            scan mode, range 0-1, 0=off, 1=on
#  1          u8
#   :6        unknown_3381:6
#   :2        priority_ch:2          priority channel, range 0-3, 0=off,
#                                    1=priority channel 1,
#                                    2=priority channel 2,
#                                    3=priority channel 1 + priority channel 2
#  1          u8 priority_ch1        priority channel 1 number, range 1-199
#  1          u8 priority_ch2        priority channel 2 number, range 1-199
#  1          u8
#   :4        unknown_3384:4
#   :4        revert_ch:4            revert channel, range 0-3, 0=selected,
#                                    1=selected + talkback, 2=last called,
#                                    3=last used
#  1          u8 look_back_time_a    look back time a, range 0-45
#  1          u8 look_back_time_b    look back time b, range 0-45
#  1          u8 dropout_delay_time  dropout delay time, range 0-49
#  1          u8 dwell_time          dwell time, range 0-49
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3310;
struct {
    u8 bandlimit;
    u8 ch_number;
    u8 unknown_3312:7,
       vfomr:1;
} settings3;
"""

MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3340;
struct {
  u8 unknown_3340:4,
     tuning_step:4;
  u8 unknown_3341:7,
     beep:1;
  u8 unknown_3342:3,
     timeout_timer:5;
  u8 unknown_3343:6,
     auto_power_off:2;
  u8 unknown_3344:4,
     squelch:4;
  u8 unknown_3345:3,
     volume:5;
  u8 unknown_3346:6,
     scan_resume:2;
  u8 unknown_3347;
  u8 unknown_3348:6,
     display_mode:2;
  u8 unknown_3349:7,
     auto_power_on:1;
  u8 unknown_334A:3,
     mic_gain:5;
  u8 unknown_334B;
  u8 unknown_334C:5,
     ste_type:3;
  u8 unknown_334D:6,
     ste_frequency:2;
  u8 unknown_334E:1,
     forbid_setting:1,
     unknown1:1,
     forbid_initialize:1,
     save_chan_param:1,
     forbid_chan_menu:1,
     sql_key_function:1,
     unknown2:1;
} settings;
"""

MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3380;
struct {
  u8 unknown_3380:7,
     scan_mode:1;
  u8 unknown_3381:6,
     priority_ch:2;
  u8 priority_ch1;
  u8 priority_ch2;
  u8 unknown_3384:4,
     revert_ch:4;
  u8 look_back_time_a;
  u8 look_back_time_b;
  u8 dropout_delay_time;
  u8 dwell_time;
} settings2;
"""

#  RT98  memory map
#  section: 8  Embedded Messages
#
#  bytes:bit  type                 description
#  ---------------------------------------------------------------------------
#  6          char radio_type[5]   radio type, vhf=rt98v, uhf=rt98u
#  2          u8 unknown1[2]
#  4          char mcu_version[4]  mcu version, [x.xx]
#  2          u8 unknown2[2]
#  1          u8 mode              rt98u mode: 0=pmr, 1=com, 2=comii
#                                  rt98v mode: 0=freenet, 1=com, 2=comii
#  1          u8 unknown3
#  10         u8 unused1[10]
#  4          u8 unknown4[4]
#  3          u8 unused2[3]
#  16         u8 unknown5[16]
#  10         char date_mfg[16]    date manufactured, [yyyy-mm-dd]
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x3D00;
struct {
char radio_type[7];
char mcu_version[4];
u8 unknown2[2];
u8 mode;
u8 unknown3;
u8 unused1[10];
u8 unknown4[4];
u8 unused2[3];
u8 unknown5[16];
char date_mfg[10];
} embedded_msg;
"""


# Format for the version messages returned by the radio
VER_FORMAT = '''
u8 hdr;
char model[7];
u8 bandlimit;
char version[6];
u8 ack;
'''


# Radio supports upper case and symbols
CHARSET_ASCII_PLUS = chirp_common.CHARSET_UPPER_NUMERIC + '- '

# Band limits as defined by the band byte in ver_response, defined in Hz, for
# VHF and UHF, used for RX and TX.
RT98V_BAND_LIMITS = {0x00: [(149000000, 149200000)],
                     0x01: [(136000000, 174000000)],
                     0x02: [(147000000, 174000000)]}

RT98U_BAND_LIMITS = {0x00: [(446000000, 446200000)],
                     0x01: [(400000000, 470000000)],
                     0x02: [(450000000, 470000000)]}

RT98W_BAND_LIMITS = {0x00: [(66000000, 88000000)],
                     0x01: [(66000000, 88000000)],
                     0x02: [(66000000, 88000000)],
                     0x03: [(66000000, 88000000)],
                     0x04: [(66000000, 88000000)],
                     0x05: [(66000000, 88000000)],
                     0x06: [(66000000, 88000000)]}


# Get band limits from a band limit value
def get_band_limits_Hz(radio_type, limit_value):
    if str(radio_type).rstrip("\00") in ["RT98U", "AT-779U"]:
        if limit_value not in RT98U_BAND_LIMITS:
            limit_value = 0x01
            LOG.warning('Unknown band limit value 0x%02x, default to 0x01')
        bandlimitfrequencies = RT98U_BAND_LIMITS[limit_value]
    elif str(radio_type).rstrip("\00") in ["RT98V", "AT-779V"]:
        if limit_value not in RT98V_BAND_LIMITS:
            limit_value = 0x01
            LOG.warning('Unknown band limit value 0x%02x, default to 0x01')
        bandlimitfrequencies = RT98V_BAND_LIMITS[limit_value]
    elif str(radio_type).rstrip("\00") in ["RT98W", "AT-779W"]:
        if limit_value not in RT98W_BAND_LIMITS:
            limit_value = 0x06
            LOG.warning('Unknown band limit value 0x%02x, default to 0x06')
        bandlimitfrequencies = RT98W_BAND_LIMITS[limit_value]
    return bandlimitfrequencies


def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
        radio.pipe.read(len(data))
    except Exception as e:
        LOG.error("Error writing to radio: %s" % e)
        raise errors.RadioError("Unable to write to radio")


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception as e:
        _finish(radio)
        LOG.error("Error reading from radio: %s" % e)
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        _finish(radio)
        LOG.error("Short read from radio (%i, expected %i)" %
                  (len(data), length))
        LOG.debug(util.hexprint(data))
        raise errors.RadioError("Short read from radio")
    return data


# strip trailing 0x00 to convert a string returned by bitwise.parse into a
# python string
def cstring_to_py_string(cstring):
    return "".join(c for c in cstring if c != '\x00')


# Check the radio version reported to see if it's one we support,
# returns bool version supported, and the band index
def check_ver(ver_response, allowed_types):
    ''' Check the returned radio version is one we approve of '''

    LOG.debug('ver_response = ')
    LOG.debug(util.hexprint(ver_response))

    resp = bitwise.parse(VER_FORMAT, ver_response)
    verok = False

    if resp.hdr == 0x49 and resp.ack == 0x06:
        model, version = [cstring_to_py_string(bitwise.get_string(s)).strip()
                          for s in (resp.model, resp.version)]
        LOG.debug('radio model: \'%s\' version: \'%s\'' %
                  (model, version))
        LOG.debug('allowed_types = %s' % allowed_types)

        if model in allowed_types:
            LOG.debug('model in allowed_types')

            if version in allowed_types[model]:
                LOG.debug('version in allowed_types[model]')
                verok = True
    else:
        _finish(radio)
        raise errors.RadioError('Failed to parse version response')

    return verok, str(resp.model), int(resp.bandlimit)


def _ident(radio):
    radio.pipe.timeout = 1
    _echo_write(radio, b"PROGRAM")
    response = radio.pipe.read(3)
    if response != b"QX\06":
        _finish(radio)
        LOG.debug("Response was :\n%s" % util.hexprint(response))
        raise errors.RadioError("Radio did not respond. Check connection.")
    _echo_write(radio, b"\x02")
    ver_response = radio.pipe.read(16)
    LOG.debug(util.hexprint(ver_response))

    verok, model, bandlimit = check_ver(ver_response,
                                        radio.ALLOWED_RADIO_TYPES)
    if not verok:
        _finish(radio)
        raise errors.RadioError(
            'Radio version not in allowed list for %s-%s: %s' %
            (radio.VENDOR, radio.MODEL, util.hexprint(ver_response)))

    return model, bandlimit


def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += bytes([_checksum(frame[1:])])
        frame += b"\x06"
    _echo_write(radio, frame)
    LOG.debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != b"\x06":
            _finish(radio)
            LOG.debug("Ack was: %s" % repr(result))
            raise errors.RadioError("Radio did not accept block at %04x"
                                    % addr)
        return
    result = _read(radio, length + 6)
    LOG.debug("Got:\n%s" % util.hexprint(result))
    header = result[:4]
    data = result[4:-2]
    ack = result[-1:]
    if ack != b"\x06":
        _finish(radio)
        LOG.debug("Ack was: %s" % repr(ack))
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        _finish(radio)
        LOG.debug("Expected/Received:")
        LOG.debug(" Length: %02x/%02x" % (length, _length))
        LOG.debug(" Addr: %04x/%04x" % (addr, _addr))
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != result[-2]:
        _finish(radio)
        LOG.debug("Calculated: %02x" % cs)
        LOG.debug("Actual:     %02x" % result[-2])
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data


def _finish(radio):
    endframe = b"\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    if result != b"\x06":
        LOG.error("Got:\n%s" % util.hexprint(result))
        raise errors.RadioError("Radio did not finish cleanly")


def do_download(radio):

    _ident(radio)

    _memobj = None
    data = b""

    for addr in range(0, radio._memsize, 0x10):
        block = _send(radio, b'R', addr, 0x10)
        data += block
        status = chirp_common.Status()
        status.cur = len(data)
        status.max = radio._memsize
        status.msg = "Downloading from radio"
        radio.status_fn(status)

    _finish(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    model, bandlimit = _ident(radio)
    _embedded = radio._memobj.embedded_msg

    if model != str(_embedded.radio_type):
        LOG.warning('radio and image model types differ')
        LOG.warning('model type (radio): %s' % str(model))
        LOG.warning('model type (image): %s' % str(_embedded.radio_type))

        _finish(radio)

        msg = ("The upload was stopped because the radio type "
               "of the image (%s) does not match that "
               "of the radio (%s).")
        raise errors.RadioError(msg % (str(_embedded.radio_type), str(model)))

    if bandlimit != int(_embedded.mode):
        if str(_embedded.radio_type).rstrip("\00") in ["RT98U", "AT-779U"]:
            image_band_limits = LIST_RT98U_FREQS[int(_embedded.mode)]
        if str(_embedded.radio_type).rstrip("\00") in ["RT98V", "AT-779V"]:
            image_band_limits = LIST_RT98V_FREQS[int(_embedded.mode)]
        if str(_embedded.radio_type).rstrip("\00") in ["RT98W", "AT-779W"]:
            image_band_limits = LIST_RT98W_FREQS[int(_embedded.mode)]
        if str(model).rstrip("\00") in ["RT98U", "AT-779U"]:
            radio_band_limits = LIST_RT98U_FREQS[int(bandlimit)]
        if str(model).rstrip("\00") in ["RT98V", "AT-779V"]:
            radio_band_limits = LIST_RT98V_FREQS[int(bandlimit)]
        if str(model).rstrip("\00") in ["RT98W", "AT-779W"]:
            radio_band_limits = LIST_RT98W_FREQS[int(bandlimit)]

        LOG.warning('radio and image band limits differ')
        LOG.warning('image band limits: %s' % image_band_limits)
        LOG.warning('radio band limits: %s' % radio_band_limits)

        _finish(radio)

        msg = ("The upload was stopped because the band limits "
               "of the image (%s) does not match that "
               "of the radio (%s).")
        raise errors.RadioError(msg % (image_band_limits, radio_band_limits))

    try:
        for start, end in radio._ranges:
            for addr in range(start, end, 0x10):
                block = radio._mmap[addr:addr+0x10]
                _send(radio, b'W', addr, len(block), block)
                status = chirp_common.Status()
                status.cur = addr
                status.max = end
                status.msg = "Uploading to Radio"
                radio.status_fn(status)
        _finish(radio)
    except errors.RadioError:
        raise
    except Exception as e:
        _finish(radio)
        raise errors.RadioError('Failed to upload to radio: %s' % e)


#
# The base class, extended for use with other models
#
class Rt98BaseRadio(chirp_common.CloneModeRadio,
                    chirp_common.ExperimentalRadio):
    """Retevis RT98 Base"""
    VENDOR = "Retevis"
    MODEL = "RT98 Base"
    BAUD_RATE = 9600

    _memsize = 0x3E00
    _ranges = [(0x0000, 0x3310),
               (0x3320, 0x3390)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The Retevis RT98 driver is an beta version."
                           "Proceed with Caution and backup your data")
        return rp

    def get_features(self):
        class FakeEmbedded(object):
            mode = 0
            radio_type = 'RT98U'

        if self._memobj:
            _embedded = self._memobj.embedded_msg
        else:
            # If we have no memory object, take defaults for unit
            # test, make_supported, etc
            _embedded = FakeEmbedded()
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.can_odd_split = True
        rf.has_name = True
        if _embedded.mode == 0:  # PMR or FreeNet
            rf.has_offset = False
        else:
            rf.has_offset = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_skips = ["", "S"]
        rf.memory_bounds = (1, 199)
        rf.valid_name_length = 6
        if _embedded.mode == 0:  # PMR or FreeNet
            rf.valid_duplexes = ['', 'off']
        else:
            rf.valid_duplexes = DUPLEXES + ['split', 'off']
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "- "
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = CROSS_MODES
        if _embedded.mode == 0:  # PMR or FreeNet
            if str(_embedded.radio_type).rstrip("\00") == "RT98U":
                rf.valid_power_levels = PMR_POWER_LEVELS
            if str(_embedded.radio_type).rstrip("\00") == "RT98V":
                rf.valid_power_levels = FREENET_POWER_LEVELS
        else:
            rf.valid_power_levels = POWER_LEVELS
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES

        try:
            rf.valid_bands = get_band_limits_Hz(
                str(_embedded.radio_type),
                int(_embedded.mode))
        except TypeError:
            # If we're asked without memory loaded, assume the most permissive
            rf.valid_bands = get_band_limits_Hz(str(_embedded.radio_type), 1)
        except Exception as e:
            LOG.error('Failed to get band limits for RT98: %s' % e)
            rf.valid_bands = get_band_limits_Hz(str(_embedded.radio_type), 1)

        rf.valid_tuning_steps = TUNING_STEPS
        return rf

    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_dcs_index(self, _mem, which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)

    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        _embedded = self._memobj.embedded_msg
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[number - 1]

        # get flag info
        cbyte = (number - 1) / 8
        cbit = 7 - ((number - 1) % 8)
        setflag = self._memobj.csetflag[cbyte].c[cbit]
        skipflag = self._memobj.cskipflag[cbyte].c[cbit]

        mem = chirp_common.Memory()

        mem.number = number  # Set the memory number

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if _mem.freq == 0:
            mem.empty = True
            return mem

        if setflag == 0:
            mem.empty = True
            return mem

        if _mem.get_raw()[0] == b"\xFF":
            mem.empty = True
            return mem

        # set the name
        mem.name = str(_mem.name).rstrip()  # Set the alpha tag

        # Convert your low-level frequency and offset to Hertz
        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10

        # Set the duplex flags
        if _mem.tx_off:  # handle tx off
            mem.duplex = 'off'
        elif _mem.duplex == DUPLEX_POSSPLIT:
            mem.duplex = '+'
        elif _mem.duplex == DUPLEX_NEGSPLIT:
            mem.duplex = '-'
        elif _mem.duplex == DUPLEX_NOSPLIT:
            mem.duplex = ''
        elif _mem.duplex == DUPLEX_ODDSPLIT:
            mem.duplex = 'split'
        else:
            LOG.error('%s: get_mem: unhandled duplex: %02x' %
                      (mem.name, _mem.duplex))

        # Set the channel width
        if _mem.channel_width == CHANNEL_WIDTH_12d5kHz:
            mem.mode = 'NFM'
        elif _embedded.mode == 0:  # PMR or FreeNet
            LOG.info('PMR and FreeNet channels must be Channel Width 12.5 kHz')
            mem.mode = 'NFM'
        elif _mem.channel_width == CHANNEL_WIDTH_25kHz:
            mem.mode = 'FM'
        elif _mem.channel_width == CHANNEL_WIDTH_20kHz:
            LOG.info(
                '%s: get_mem: promoting 20 kHz channel width to 25 kHz' %
                mem.name)
            mem.mode = 'FM'
        else:
            LOG.error('%s: get_mem: unhandled channel width: 0x%02x' %
                      (mem.name, _mem.channel_width))

        # set the power level
        if _embedded.mode == 0:  # PMR or FreeNet
            if str(_embedded.radio_type).rstrip("\00") == "RT98U":
                LOG.info('using PMR power levels')
                _levels = PMR_POWER_LEVELS
            if str(_embedded.radio_type).rstrip("\00") == "RT98V":
                LOG.info('using FreeNet power levels')
                _levels = FREENET_POWER_LEVELS
        else:  # COM or COMII
            LOG.info('using general power levels')
            _levels = POWER_LEVELS

        if _mem.txpower == TXPOWER_LOW:
            mem.power = _levels[0]
        elif _embedded.mode == 0:  # PMR or FreeNet
            LOG.info('FreeNet or PMR channel is not set to TX Power Low')
            LOG.info('Setting channel to TX Power Low')
            mem.power = _levels[0]
        elif _mem.txpower == TXPOWER_MED:
            mem.power = _levels[1]
        elif _mem.txpower == TXPOWER_HIGH:
            mem.power = _levels[2]
        else:
            LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                      (mem.name, _mem.txpower))

        # CTCSS Tones and DTCS Codes
        rxtone = txtone = None

        rxmode = TMODES[_mem.rxtmode]
        txmode = TMODES[_mem.txtmode]

        if rxmode == "Tone":
            rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(
                                                 _mem, 'rx')]

        if txmode == "Tone":
            txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(
                                                 _mem, 'tx')]

        rxpol = _mem.rxinv and "R" or "N"
        txpol = _mem.txinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        # Check if this memory is in the scan enabled list
        mem.skip = "S" if skipflag == 0 else ""

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        rs = RadioSettingValueBoolean(bool(_mem.busychannellockout))
        rset = RadioSetting("busychannellockout", "Busy channel lockout", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(bool(_mem.reverse))
        rset = RadioSetting("reverse", "Reverse", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(bool(_mem.talkaround))
        rset = RadioSetting("talkaround", "Talk around", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(bool(_mem.squelch_mode))
        rset = RadioSetting("squelch_mode", "Squelch mode", rs)
        rset.set_doc(_('Honor the CTCSS/DCS receive squelch configuration '
                       'when enabled, else only carrier squelch'))
        mem.extra.append(rset)

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        _embedded = self._memobj.embedded_msg
        # Get a low-level memory object mapped to the image

        _mem = self._memobj.memory[mem.number - 1]

        cbyte = (mem.number - 1) / 8
        cbit = 7 - ((mem.number - 1) % 8)

        if mem.empty:
            self._memobj.csetflag[cbyte].c[cbit] = 0
            self._memobj.cskipflag[cbyte].c[cbit] = 0
            _mem.set_raw("\xff" * 32)
            return

        _mem.set_raw("\x00" * 32)

        # FreeNet and PMR radio types
        if _embedded.mode == 0:  # PMR or FreeNet

            mem.mode = 'NFM'
            mem.offset = 0

            # FreeNet
            if str(_embedded.radio_type).rstrip("\00") == "RT98V":
                if mem.number >= 1 and mem.number <= 6:
                    FREENET_FREQ = FREENET_FREQS[mem.number - 1]
                    mem.freq = FREENET_FREQ
                else:
                    _mem.tx_off = 1
                    mem.duplex = 'off'

            # PMR
            if str(_embedded.radio_type).rstrip("\00") == "RT98U":
                if mem.number >= 1 and mem.number <= 16:
                    PMR_FREQ = PMR_FREQS[mem.number - 1]
                    mem.freq = PMR_FREQ
                else:
                    _mem.tx_off = 1
                    mem.duplex = 'off'

        # set the occupied bitfield
        self._memobj.csetflag[cbyte].c[cbit] = 1
        # set the scan add bitfield
        self._memobj.cskipflag[cbyte].c[cbit] = 0 if (mem.skip == "S") else 1

        _mem.freq = mem.freq / 10             # Convert to low-level frequency
        _mem.offset = mem.offset / 10         # Convert to low-level frequency

        # Store the alpha tag
        _mem.name = mem.name.ljust(6)[:6]  # Store the alpha tag

        # Set duplex bitfields
        _mem.tx_off = 0
        if mem.duplex == 'off':  # handle tx off
            _mem.tx_off = 1
        elif mem.duplex == '+':
            _mem.duplex = DUPLEX_POSSPLIT
        elif mem.duplex == '-':
            _mem.duplex = DUPLEX_NEGSPLIT
        elif mem.duplex == '':
            _mem.duplex = DUPLEX_NOSPLIT
        elif mem.duplex == 'split':
            diff = mem.offset - mem.freq
            _mem.duplex = DUPLEXES.index("-") \
                if diff < 0 else DUPLEXES.index("+")
            _mem.offset = abs(diff) / 10
        else:
            LOG.error('%s: set_mem: unhandled duplex: %s' %
                      (mem.name, mem.duplex))

        # Set the channel width - remember we promote 20 kHz channels to FM
        # on import, so don't handle them here
        if mem.mode == 'FM':
            _mem.channel_width = CHANNEL_WIDTH_25kHz
        elif mem.mode == 'NFM':
            _mem.channel_width = CHANNEL_WIDTH_12d5kHz
        else:
            LOG.error('%s: set_mem: unhandled mode: %s' % (
                mem.name, mem.mode))

        # CTCSS Tones and DTCS Codes
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = TMODES.index(txmode)

        _mem.rxtmode = TMODES.index(rxmode)

        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem, 'tx',
                                chirp_common.ALL_DTCS_CODES.index(txtone))

        _mem.squelch_mode = False
        if rxmode == "Tone":
            _mem.rxtone = TONES.index(rxtone)
            _mem.squelch_mode = True
        elif rxmode == "DTCS":
            self._set_dcs_index(_mem, 'rx',
                                chirp_common.ALL_DTCS_CODES.index(rxtone))
            _mem.squelch_mode = True

        _mem.txinv = txpol == "R"
        _mem.rxinv = rxpol == "R"

        # set the power level
        if _embedded.mode == 0:  # PMR or FreeNet
            if str(_embedded.radio_type).rstrip("\00") == "RT98U":
                LOG.info('using PMR power levels')
                _levels = PMR_POWER_LEVELS
            if str(_embedded.radio_type).rstrip("\00") == "RT98V":
                LOG.info('using FreeNet power levels')
                _levels = FREENET_POWER_LEVELS
        else:  # COM or COMII
            LOG.info('using general power levels')
            _levels = POWER_LEVELS

        if mem.power is None:
            _mem.txpower = TXPOWER_HIGH
        elif mem.power == _levels[0]:
            _mem.txpower = TXPOWER_LOW
        elif _embedded.mode == 0:  # PMR or FreeNet
            LOG.info('FreeNet or PMR channel is not set to TX Power Low')
            LOG.info('Setting channel to TX Power Low')
            _mem.txpower = TXPOWER_LOW
        elif mem.power == _levels[1]:
            _mem.txpower = TXPOWER_MED
        elif mem.power == _levels[2]:
            _mem.txpower = TXPOWER_HIGH
        else:
            LOG.error('%s: set_mem: unhandled power level: %s' %
                      (mem.name, mem.power))

        # extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _get_settings(self):
        _embedded = self._memobj.embedded_msg
        _settings = self._memobj.settings
        _settings2 = self._memobj.settings2
        _settings3 = self._memobj.settings3
        _slabel = self._memobj.slabel

        function = RadioSettingGroup("function", "Function Setup")
        group = RadioSettings(function)

        # Function Setup
        # MODE SET
        rs = RadioSettingValueList(LIST_DISPLAY_MODE,
                                   current_index=_settings.display_mode)
        rset = RadioSetting("display_mode", "Display Mode", rs)
        function.append(rset)

        if "AT-779" in str(_embedded.radio_type):
            rs = RadioSettingValueList(LIST_VFOMR,
                                       current_index=_settings3.vfomr)
            rset = RadioSetting("settings3.vfomr", "VFO/MR", rs)
            function.append(rset)

        rs = RadioSettingValueInteger(1, 199, _settings3.ch_number + 1)
        rset = RadioSetting("settings3.ch_number", "Channel Number", rs)
        function.append(rset)

        # DISPLAY SET
        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        val = RadioSettingValueString(0, 6, _filter(_slabel.startname))
        rs = RadioSetting("slabel.startname", "Startup Label", val)
        function.append(rs)

        # VOL SET
        rs = RadioSettingValueBoolean(bool(_settings.beep))
        rset = RadioSetting("beep", "Beep Prompt", rs)
        function.append(rset)

        rs = RadioSettingValueInteger(1, 30, _settings.volume)
        rset = RadioSetting("volume", "Volume Level", rs)
        function.append(rset)

        rs = RadioSettingValueInteger(1, 16, _settings.mic_gain)
        rset = RadioSetting("mic_gain", "Mic Gain", rs)
        function.append(rset)

        # ON/OFF SET
        rs = RadioSettingValueList(LIST_APO,
                                   current_index=_settings.auto_power_off)
        rset = RadioSetting("auto_power_off", "Auto Power Off", rs)
        function.append(rset)

        rs = RadioSettingValueList(
            LIST_AOP, current_index=_settings.auto_power_on)
        rset = RadioSetting("auto_power_on", "Power On Method", rs)
        function.append(rset)

        # STE SET
        rs = RadioSettingValueList(LIST_STE_FREQ,
                                   current_index=_settings.ste_frequency)
        rset = RadioSetting("ste_frequency", "STE Frequency", rs)
        rset.set_doc(_('Recommend using 55.2'))
        function.append(rset)

        rs = RadioSettingValueList(LIST_STE_TYPE,
                                   current_index=_settings.ste_type)
        rset = RadioSetting("ste_type", "STE Type", rs)
        function.append(rset)

        # FUNCTION SET
        rs = RadioSettingValueList(
            LIST_STEP, current_index=_settings.tuning_step)
        rset = RadioSetting("tuning_step", "Tuning Step", rs)
        function.append(rset)

        rs = RadioSettingValueList(LIST_SQUELCH,
                                   current_index=_settings.squelch)
        rset = RadioSetting("squelch", "Squelch Level", rs)
        function.append(rset)

        if "AT-779" in str(_embedded.radio_type):
            rs = RadioSettingValueList(LIST_SCAN,
                                       current_index=_settings.scan_resume)
            rset = RadioSetting("scan_resume", "Frequency Scan", rs)
            function.append(rset)

        rs = RadioSettingValueBoolean(bool(_settings.sql_key_function))
        rset = RadioSetting("sql_key_function", "SQL Key Function", rs)
        function.append(rset)

        rs = RadioSettingValueList(LIST_TIMEOUT,
                                   current_index=_settings.timeout_timer)
        rset = RadioSetting("timeout_timer", "Timeout Timer", rs)
        function.append(rset)

        # uncategorized
        rs = RadioSettingValueBoolean(bool(_settings.save_chan_param))
        rset = RadioSetting("save_chan_param", "Save Channel Parameters", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(bool(_settings.forbid_chan_menu))
        rset = RadioSetting("forbid_chan_menu", "Forbid Channel Menu", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(bool(not _settings.forbid_initialize))
        rset = RadioSetting("forbid_initialize", "Forbid Initialize", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(bool(_settings.forbid_setting))
        rset = RadioSetting("forbid_setting", "Forbid Setting", rs)
        function.append(rset)

        # Information Of Scanning Channel
        scanning = RadioSettingGroup("scanning", "Scanning Setup")
        group.append(scanning)

        rs = RadioSettingValueBoolean(bool(_settings2.scan_mode))
        rset = RadioSetting("settings2.scan_mode", "Scan Mode", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_PRIORITY_CH,
                                   current_index=_settings2.priority_ch)
        rset = RadioSetting("settings2.priority_ch", "Priority Channel", rs)
        scanning.append(rset)

        rs = RadioSettingValueInteger(1, 199, _settings2.priority_ch1 + 1)
        rset = RadioSetting("settings2.priority_ch1", "Priority Channel 1", rs)
        scanning.append(rset)

        rs = RadioSettingValueInteger(1, 199, _settings2.priority_ch2 + 1)
        rset = RadioSetting("settings2.priority_ch2", "Priority Channel 2", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_REVERT_CH,
                                   current_index=_settings2.revert_ch)
        rset = RadioSetting("settings2.revert_ch", "Revert Channel", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_TIME46,
                                   current_index=_settings2.look_back_time_a)
        rset = RadioSetting("settings2.look_back_time_a",
                            "Look Back Time A", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_TIME46,
                                   current_index=_settings2.look_back_time_b)
        rset = RadioSetting("settings2.look_back_time_b",
                            "Look Back Time B", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_TIME50,
                                   current_index=_settings2.dropout_delay_time)
        rset = RadioSetting("settings2.dropout_delay_time",
                            "Dropout Delay Time", rs)
        scanning.append(rset)

        rs = RadioSettingValueList(LIST_TIME50,
                                   current_index=_settings2.dwell_time)
        rset = RadioSetting("settings2.dwell_time", "Dwell Time", rs)
        scanning.append(rset)

        # Embedded Message
        embedded = RadioSettingGroup("embedded", "Embedded Message")
        group.append(embedded)

        rs = RadioSettingValueString(0, 7, _filter(_embedded.radio_type))
        rs.set_mutable(False)
        rset = RadioSetting("embedded_msg.radio_type", "Radio Type", rs)
        embedded.append(rset)

        if str(_embedded.radio_type).rstrip("\00") in ["RT98V", "AT-779V"]:
            options = LIST_RT98V_MODES
        elif str(_embedded.radio_type).rstrip("\00") in ["RT98W", "AT-779W"]:
            options = LIST_RT98W_MODES
        else:
            options = LIST_RT98U_MODES
        rs = RadioSettingValueList(options, current_index=_embedded.mode)
        rs.set_mutable(False)
        rset = RadioSetting("embedded_msg.mode", "Mode", rs)
        embedded.append(rset)

        # frequency
        if str(_embedded.radio_type).rstrip("\00") in ["RT98V", "AT-779V"]:
            options = LIST_RT98V_FREQS
        elif str(_embedded.radio_type).rstrip("\00") in ["RT98W", "AT-779W"]:
            options = LIST_RT98W_FREQS
        else:
            options = LIST_RT98U_FREQS
        rs = RadioSettingValueList(options, current_index=_settings3.bandlimit)
        rs.set_mutable(False)
        rset = RadioSetting("settings3.bandlimit", "Frequency", rs)
        embedded.append(rset)

        rs = RadioSettingValueString(0, 10, _filter(_embedded.date_mfg))
        rs.set_mutable(False)
        rset = RadioSetting("embedded_msg.date_mfg", "Production Date", rs)
        embedded.append(rset)

        rs = RadioSettingValueString(0, 4, _filter(_embedded.mcu_version))
        rs.set_mutable(False)
        rset = RadioSetting("embedded_msg.mcu_version", "MCU Version", rs)
        embedded.append(rset)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("failed to parse settings")
            traceback.print_exc()
            return None

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("using apply callback")
                        element.run_apply_callback()
                    elif setting == "ch_number":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "forbid_initialize":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "priority_ch1":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "priority_ch2":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class Rt98Radio(Rt98BaseRadio):
    """Retevis RT98"""
    VENDOR = "Retevis"
    MODEL = "RT98"
    # Allowed radio types is a dict keyed by model of a list of version
    # strings
    ALLOWED_RADIO_TYPES = {'RT98V': ['V100', 'V101'],
                           'RT98U': ['V100', 'V101'],
                           'RT98W': ['V100'],
                           'AT-779V': ['V100'],
                           'AT-779U': ['V100'],
                           'AT-779W': ['V100'],
                           }
