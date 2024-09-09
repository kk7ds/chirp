# Copyright 2014 Tom Hayward <tom@tomh.us>
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

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0184;
struct {
  u8 unknown1:4,
     sql:4;              // squelch level
  u8 unknown2;
  u8 obeep:1,            // open beep
     dw_off:1,           // dual watch (inverted)
     kbeep:1,            // key beep
     rbeep:1,            // roger beep
     unknown3:2,
     ctdcsb:1,           // ct/dcs busy lock
     unknown4:1;
  u8 alarm:1,            // alarm key
     unknown5:1,
     aliasen_off:1,      // alias enable (inverted)
     save:1,             // battery save
     unknown6:2,
     mrcha:1,            // mr/cha
     vfomr:1;            // vfo/mr
  u8 keylock_off:1,      // key lock (inverted)
     txstop_off:1,       // tx stop (inverted)
     scanm:1,            // scan key/mode
     vir:1,              // vox inhibit on receive
     keylockm:2,         // key lock mode
     lamp:2;             // backlight
  u8 opendis:2,          // open display
     fmen_off:1,         // fm enable (inverted)
     unknown7:1,
     fmscan_off:1,       // fm scan (inverted)
     fmdw:1,             // fm dual watch
     unknown8:2;
  u8 step:4,             // step
     vol:4;              // volume
  u8 apo:4,              // auto power off
     tot:4;              // time out timer
  u8 unknown9;
  u8 voxdt:4,            // vox delay time
     voxgain:4;          // vox gain
  u8 unknown10;
  u8 unknown11;
  u8 unknown12:3,
     lptime:5;           // long press time
  u8 keyp2long:4,        // p2 key long press
     keyp2short:4;       // p2 key short press
  u8 keyp1long:4,        // p1 key long press
     keyp1short:4;       // p1 key short press
  u8 keyp3long:4,        // p3 key long press
     keyp3short:4;       // p3 key short press
  u8 unknown13;
  u8 menuen:1,           // menu enable
     absel:1,            // a/b select
     unknown14:2,
     keymshort:4;        // m key short press
  u8 unknown15:4,
     dtmfst:1,           // dtmf sidetone
     ackdecode:1,        // ack decode
     monitor:2;          // monitor
  u8 unknown16:3,
     reset:1,            // reset enable
     unknown17:1,
     keypadmic_off:1,    // keypad mic (inverted)
     unknown18:2;
  u8 unknown19;
  u8 unknown20:3,
     dtmftime:5;         // dtmf digit time
  u8 unknown21:3,
     dtmfspace:5;        // dtmf digit space time
  u8 unknown22:2,
     dtmfdelay:6;        // dtmf first digit delay
  u8 unknown23:1,
     dtmfpretime:7;      // dtmf pretime
  u8 unknown24:2,
     dtmfdelay2:6;       // dtmf * and # digit delay
  u8 unknown25:3,
     smfont_off:1,       // small font (inverted)
     unknown26:4;
} settings;

#seekto 0x01cd;
struct {
  u8 rssi136;            // squelch base level (vhf)
  u8 unknown0x01ce;
  u8 rssi400;            // squelch base level (uhf)
} service;

#seekto 0x0900;
struct {
  char user1[7];         // user message 1
  char unknown0x0907;
  char unknown0x0908[8];
  char unknown0x0910[8];
  char system[7];        // system message
  char unknown0x091F;
  char user2[7];         // user message 2
  char unknown0x0927;
} messages;

struct channel {
  bbcd rx_freq[4];
  bbcd tx_freq[4];
  u8 rx_tone;
  u8 rx_tmode_extra:6,
     rx_tmode:2;
  u8 tx_tone;
  u8 tx_tmode_extra:6,
     tx_tmode:2;
  u8 unknown5;
  u8 pttidoff:1,
     dtmfoff:1,
     %(unknownormode)s,
     tailcut:1,
     aliasop:1,
     talkaroundoff:1,
     voxoff:1,
     skip:1;
  u8 %(modeorpower)s,
     reverseoff:1,
     blckoff:1,
     unknown7:1,
     apro:3;
  u8 unknown8;
};

struct name {
    char name[7];
    u8 pad;
};

#seekto 0x%(chanstart)x;
struct channel default[%(defaults)i];
struct channel memory[199];

#seekto 0x%(namestart)x;
struct name defaultname[%(defaults)i];
struct name name[199];
"""


APO_LIST = ["OFF", "10M", "20M", "30M", "40M", "50M", "60M", "90M",
            "2H", "4H", "6H", "8H", "10H", "12H", "14H", "16H"]
SQL_LIST = ["%s" % x for x in range(0, 10)]
SCANM_LIST = ["CO", "TO"]
TOT_LIST = ["OFF"] + ["%s seconds" % x for x in range(10, 130, 10)]
_STEP_LIST = [2.5, 5., 6.25, 10., 12.5, 25.]
STEP_LIST = ["{} kHz".format(x) for x in _STEP_LIST]
MONITOR_LIST = ["CTC/DCS", "DTMF", "CTC/DCS and DTMF", "CTC/DCS or DTMF"]
VFOMR_LIST = ["MR", "VFO"]
MRCHA_LIST = ["MR CHA", "Freq. MR"]
VOL_LIST = ["OFF"] + ["%s" % x for x in range(1, 16)]
OPENDIS_LIST = ["All", "Lease Time", "User-defined", "Leixen"]
LAMP_LIST = ["OFF", "KEY", "CONT"]
KEYLOCKM_LIST = ["K+S", "PTT", "KEY", "ALL"]
ABSEL_LIST = ["B Channel",  "A Channel"]
VOXGAIN_LIST = ["%s" % x for x in range(1, 9)]
VOXDT_LIST = ["%s seconds" % x for x in range(1, 5)]
DTMFTIME_LIST = ["%i milliseconds" % x for x in range(50, 210, 10)]
DTMFDELAY_LIST = ["%i milliseconds" % x for x in range(0, 550, 50)]
DTMFPRETIME_LIST = ["%i milliseconds" % x for x in range(100, 1100, 100)]
DTMFDELAY2_LIST = ["%i milliseconds" % x for x in range(0, 450, 50)]

LPTIME_LIST = ["%i milliseconds" % x for x in range(500, 2600, 100)]
PFKEYLONG_LIST = ["OFF",
                  "FM",
                  "Monitor Momentary",
                  "Monitor Lock",
                  "SQ Off Momentary",
                  "Mute",
                  "SCAN",
                  "TX Power",
                  "EMG",
                  "VFO/MR",
                  "DTMF",
                  "CALL",
                  "Transmit 1750 Hz",
                  "A/B",
                  "Talk Around",
                  "Reverse"
                  ]

PFKEYSHORT_LIST = ["OFF",
                   "FM",
                   "BandChange",
                   "Time",
                   "Monitor Lock",
                   "Mute",
                   "SCAN",
                   "TX Power",
                   "EMG",
                   "VFO/MR",
                   "DTMF",
                   "CALL",
                   "Transmit 1750 Hz",
                   "A/B",
                   "Talk Around",
                   "Reverse"
                   ]

MODES = ["NFM", "FM"]
WTFTONES = tuple(float(x) for x in range(56, 64))
TONES = tuple(sorted(WTFTONES + chirp_common.TONES))
DTCS_CODES = tuple(sorted((17, 50, 645) + chirp_common.DTCS_CODES))
TMODES = ["", "Tone", "DTCS", "DTCS"]


def _image_ident_from_data(data):
    return data[0x168:0x178]


def _image_ident_from_image(radio):
    return _image_ident_from_data(radio.get_mmap())


def checksum(frame):
    x = 0
    for b in frame:
        x ^= b
    return x & 0xFF


def make_frame(cmd, addr, data=b""):
    payload = struct.pack(">H", addr) + data
    header = struct.pack(">cB", cmd, len(payload))
    frame = header + payload
    return frame + bytes([checksum(frame)])


def send(radio, frame):
    # LOG.debug("%04i P>R: %s" %
    #           (len(frame),
    #            util.hexprint(frame).replace("\n", "\n          ")))
    try:
        radio.pipe.write(frame)
    except Exception as e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)


def recv(radio, readdata=True):
    hdr = radio.pipe.read(4)
    # LOG.debug("%04i P<R: %s" %
    #           (len(hdr), util.hexprint(hdr).replace("\n", "\n          ")))
    if hdr == b"\x09\x00\x09":
        raise errors.RadioError("Radio rejected command.")
    cmd, length, addr = struct.unpack(">BBH", hdr)
    length -= 2
    if readdata:
        data = radio.pipe.read(length)
        # LOG.debug("     P<R: %s" %
        #           util.hexprint(hdr + data).replace("\n", "\n          "))
        if len(data) != length:
            raise errors.RadioError("Radio sent %i bytes (expected %i)" % (
                len(data), length))
        chk = radio.pipe.read(1)
    else:
        data = b""
    return addr, data


def do_ident(radio):
    send(radio, b"\x02\x06LEIXEN\x17")
    ident = radio.pipe.read(9)
    LOG.debug("     P<R: %s" %
              util.hexprint(ident).replace("\n", "\n          "))
    if ident != b"\x06\x06leixen\x13":
        raise errors.RadioError("Radio refused program mode")
    radio.pipe.write(b"\x06\x00\x06")
    ack = radio.pipe.read(3)
    if ack != b"\x06\x00\x06":
        raise errors.RadioError("Radio did not ack.")


def do_download(radio):
    # Ident should have already been done by the detect_from_serial()

    data = b""
    data += b"\xFF" * (0 - len(data))
    for addr in range(0, radio._memsize, 0x10):
        send(radio, make_frame(b"R", addr, b'\x10'))
        _addr, _data = recv(radio)
        if _addr != addr:
            raise errors.RadioError("Radio sent unexpected address")
        data += _data

        status = chirp_common.Status()
        status.cur = addr
        status.max = radio._memsize
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    finish(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    _ranges = [(0x0d00, 0x2000)]

    image_ident = _image_ident_from_image(radio)
    if image_ident.startswith(radio._file_ident) and \
       radio._model_ident in image_ident:
        _ranges = radio._ranges

    do_ident(radio)

    for start, end in _ranges:
        LOG.debug('Uploading range 0x%04X - 0x%04X' % (start, end))
        for addr in range(start, end, 0x10):
            frame = make_frame(b"W", addr, radio._mmap[addr:addr + 0x10])
            send(radio, frame)
            # LOG.debug("     P<R: %s" %
            #           util.hexprint(frame).replace("\n", "\n          "))
            radio.pipe.write(b"\x06\x00\x06")
            ack = radio.pipe.read(3)
            if ack != b"\x06\x00\x06":
                raise errors.RadioError("Radio refused block at %04x" % addr)

            status = chirp_common.Status()
            status.cur = addr
            status.max = radio._memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    finish(radio)


def finish(radio):
    send(radio, b"\x64\x01\x6F\x0A")
    ack = radio.pipe.read(8)


@directory.register
class LeixenVV898Radio(chirp_common.CloneModeRadio):

    """Leixen VV-898"""
    VENDOR = "Leixen"
    MODEL = "VV-898"
    BAUD_RATE = 9600

    _file_ident = b"Leixen"
    _model_ident = b'LX-\x89\x85\x63'

    _memsize = 0x2000
    _ranges = [
        (0x0000, 0x013f),
        (0x0148, 0x0167),
        (0x0184, 0x018f),
        (0x0190, 0x01cf),
        (0x0900, 0x090f),
        (0x0920, 0x0927),
        (0x0d00, 0x2000),
    ]

    _mem_formatter = {'unknownormode': 'unknown6:1',
                      'modeorpower': 'mode:1, power:1',
                      'chanstart': 0x0D00,
                      'namestart': 0x19B0,
                      'defaults': 3}
    _power_levels = [chirp_common.PowerLevel("Low", watts=4),
                     chirp_common.PowerLevel("High", watts=10)]

    @classmethod
    def detect_from_serial(cls, pipe):
        radio = cls(pipe)
        do_ident(radio)
        send(radio, make_frame(b"R", 0x0168, b'\x10'))
        _addr, _data = recv(radio)
        ident = _data[8:14]
        LOG.debug('Got ident from radio:\n%s' % util.hexprint(ident))
        for rclass in cls.detected_models():
            if ident == rclass._model_ident:
                return rclass
        # Reset the radio if we didn't find a match
        finish(radio)
        raise errors.RadioError('Unable to detect a supported model')

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_modes = MODES
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 7
        rf.valid_power_levels = self._power_levels
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = _STEP_LIST
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 480000000)]
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.memory_bounds = (1, 199)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except Exception as e:
            finish(self)
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(
            MEM_FORMAT % self._mem_formatter, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            finish(self)
            raise
        except Exception as e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def get_raw_memory(self, number):
        name, mem = self._get_memobjs(number)
        return repr(name) + repr(mem)

    def _get_tone(self, mem, _mem):
        rx_tone = tx_tone = None

        tx_tmode = TMODES[_mem.tx_tmode]
        rx_tmode = TMODES[_mem.rx_tmode]

        if tx_tmode == "Tone":
            tx_tone = TONES[_mem.tx_tone - 1]
        elif tx_tmode == "DTCS":
            tx_tone = DTCS_CODES[_mem.tx_tone - 1]

        if rx_tmode == "Tone":
            rx_tone = TONES[_mem.rx_tone - 1]
        elif rx_tmode == "DTCS":
            rx_tone = DTCS_CODES[_mem.rx_tone - 1]

        tx_pol = _mem.tx_tmode == 0x03 and "R" or "N"
        rx_pol = _mem.rx_tmode == 0x03 and "R" or "N"

        chirp_common.split_tone_decode(mem, (tx_tmode, tx_tone, tx_pol),
                                       (rx_tmode, rx_tone, rx_pol))

    def _is_txinh(self, _mem):
        raw_tx = b""
        for i in range(0, 4):
            raw_tx += _mem.tx_freq[i].get_raw()
        return raw_tx == b"\xFF\xFF\xFF\xFF"

    def _get_memobjs(self, number):
        _mem = self._memobj.memory[number - 1]
        _name = self._memobj.name[number - 1]
        return _mem, _name

    def get_memory(self, number):
        _mem, _name = self._get_memobjs(number)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:4] == b"\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rx_freq) == int(_mem.tx_freq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rx_freq) * 10 - int(_mem.tx_freq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.tx_freq) * 10
        else:
            mem.duplex = int(_mem.rx_freq) > int(_mem.tx_freq) and "-" or "+"
            mem.offset = abs(int(_mem.rx_freq) - int(_mem.tx_freq)) * 10

        mem.name = str(_name.name).rstrip()

        self._get_tone(mem, _mem)
        mem.mode = MODES[_mem.mode]
        powerindex = _mem.power if _mem.power < len(self._power_levels) else -1
        mem.power = self._power_levels[powerindex]
        mem.skip = _mem.skip and "S" or ""

        mem.extra = RadioSettingGroup("Extra", "extra")

        opts = ["On", "Off"]
        rs = RadioSetting("blckoff", "Busy Channel Lockout",
                          RadioSettingValueList(
                              opts, current_index=_mem.blckoff))
        mem.extra.append(rs)
        opts = ["Off", "On"]
        rs = RadioSetting("tailcut", "Squelch Tail Elimination",
                          RadioSettingValueList(
                              opts, current_index=_mem.tailcut))
        mem.extra.append(rs)
        apro = _mem.apro if _mem.apro < 0x5 else 0
        opts = ["Off", "Compander", "Scrambler", "TX Scrambler",
                "RX Scrambler"]
        rs = RadioSetting("apro", "Audio Processing",
                          RadioSettingValueList(
                              opts, current_index=apro))
        mem.extra.append(rs)
        opts = ["On", "Off"]
        rs = RadioSetting("voxoff", "VOX",
                          RadioSettingValueList(
                              opts, current_index=_mem.voxoff))
        mem.extra.append(rs)
        opts = ["On", "Off"]
        rs = RadioSetting("pttidoff", "PTT ID",
                          RadioSettingValueList(
                              opts, current_index=_mem.pttidoff))
        mem.extra.append(rs)
        opts = ["On", "Off"]
        rs = RadioSetting("dtmfoff", "DTMF",
                          RadioSettingValueList(
                              opts, current_index=_mem.dtmfoff))
        mem.extra.append(rs)
        opts = ["Name", "Frequency"]
        aliasop = RadioSetting("aliasop", "Display",
                               RadioSettingValueList(
                                   opts, current_index=_mem.aliasop))
        mem.extra.append(aliasop)
        opts = ["On", "Off"]
        rs = RadioSetting("reverseoff", "Reverse Frequency",
                          RadioSettingValueList(
                              opts, current_index=_mem.reverseoff))
        mem.extra.append(rs)
        opts = ["On", "Off"]
        rs = RadioSetting("talkaroundoff", "Talk Around",
                          RadioSettingValueList(
                              opts, current_index=_mem.talkaroundoff))
        mem.extra.append(rs)

        return mem

    def _set_tone(self, mem, _mem):
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.tx_tmode = TMODES.index(txmode)
        _mem.rx_tmode = TMODES.index(rxmode)
        if txmode == "Tone":
            _mem.tx_tone = TONES.index(txtone) + 1
        elif txmode == "DTCS":
            _mem.tx_tmode = txpol == "R" and 0x03 or 0x02
            _mem.tx_tone = DTCS_CODES.index(txtone) + 1
        if rxmode == "Tone":
            _mem.rx_tone = TONES.index(rxtone) + 1
        elif rxmode == "DTCS":
            _mem.rx_tmode = rxpol == "R" and 0x03 or 0x02
            _mem.rx_tone = DTCS_CODES.index(rxtone) + 1

    def set_memory(self, mem):
        _mem, _name = self._get_memobjs(mem.number)

        if mem.empty:
            _mem.set_raw(b"\xFF" * 16)
            return
        elif _mem.get_raw() == (b"\xFF" * 16):
            _mem.set_raw(b"\xFF" * 8 + b"\xFF\x00\xFF\x00\xFF\xFE\xF0\xFC")

        _mem.rx_freq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        self._set_tone(mem, _mem)

        _mem.power = mem.power and self._power_levels.index(mem.power) or 0
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = mem.skip == "S"
        _name.name = mem.name.ljust(7)

        # autoset display to name if filled, else show frequency
        if mem.extra:
            # mem.extra only seems to be populated when called from edit panel
            aliasop = mem.extra["aliasop"]
        else:
            aliasop = None
        if mem.name:
            _mem.aliasop = False
        else:
            _mem.aliasop = True

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _get_settings(self):
        _settings = self._memobj.settings
        _service = self._memobj.service
        _msg = self._memobj.messages
        cfg_grp = RadioSettingGroup("cfg_grp", "Basic Settings")
        adv_grp = RadioSettingGroup("adv_grp", "Advanced Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Assignment")
        group = RadioSettings(cfg_grp, adv_grp, key_grp)

        #
        # Basic Settings
        #
        rs = RadioSetting("apo", "Auto Power Off",
                          RadioSettingValueList(
                              APO_LIST, current_index=_settings.apo))
        cfg_grp.append(rs)
        rs = RadioSetting("sql", "Squelch Level",
                          RadioSettingValueList(
                              SQL_LIST, current_index=_settings.sql))
        cfg_grp.append(rs)
        rs = RadioSetting("scanm", "Scan Mode",
                          RadioSettingValueList(
                              SCANM_LIST, current_index=_settings.scanm))
        cfg_grp.append(rs)
        rs = RadioSetting("tot", "Time Out Timer",
                          RadioSettingValueList(
                              TOT_LIST, current_index=_settings.tot))
        cfg_grp.append(rs)
        rs = RadioSetting("step", "Step",
                          RadioSettingValueList(
                              STEP_LIST, current_index=_settings.step))
        cfg_grp.append(rs)
        rs = RadioSetting("monitor", "Monitor",
                          RadioSettingValueList(
                              MONITOR_LIST, current_index=_settings.monitor))
        cfg_grp.append(rs)
        rs = RadioSetting("vfomr", "VFO/MR",
                          RadioSettingValueList(
                              VFOMR_LIST, current_index=_settings.vfomr))
        cfg_grp.append(rs)
        rs = RadioSetting("mrcha", "MR/CHA",
                          RadioSettingValueList(
                              MRCHA_LIST, current_index=_settings.mrcha))
        cfg_grp.append(rs)
        rs = RadioSetting("vol", "Volume",
                          RadioSettingValueList(
                              VOL_LIST, current_index=_settings.vol))
        cfg_grp.append(rs)
        rs = RadioSetting("opendis", "Open Display",
                          RadioSettingValueList(
                              OPENDIS_LIST, current_index=_settings.opendis))
        cfg_grp.append(rs)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            LOG.debug("Filtered: %s" % filtered)
            return filtered

        rs = RadioSetting("messages.user1", "User-defined Message 1",
                          RadioSettingValueString(0, 7, _filter(_msg.user1)))
        cfg_grp.append(rs)
        rs = RadioSetting("messages.user2", "User-defined Message 2",
                          RadioSettingValueString(0, 7, _filter(_msg.user2)))
        cfg_grp.append(rs)

        val = RadioSettingValueString(0, 7, _filter(_msg.system))
        val.set_mutable(False)
        rs = RadioSetting("messages.system", "System Message", val)
        cfg_grp.append(rs)

        rs = RadioSetting("lamp", "Backlight",
                          RadioSettingValueList(
                              LAMP_LIST, current_index=_settings.lamp))
        cfg_grp.append(rs)
        rs = RadioSetting("keylockm", "Key Lock Mode",
                          RadioSettingValueList(
                              KEYLOCKM_LIST,
                              current_index=_settings.keylockm))
        cfg_grp.append(rs)
        rs = RadioSetting("absel", "A/B Select",
                          RadioSettingValueList(ABSEL_LIST,
                                                current_index=_settings.absel))
        cfg_grp.append(rs)

        rs = RadioSetting("obeep", "Open Beep",
                          RadioSettingValueBoolean(_settings.obeep))
        cfg_grp.append(rs)
        rs = RadioSetting("rbeep", "Roger Beep",
                          RadioSettingValueBoolean(_settings.rbeep))
        cfg_grp.append(rs)
        rs = RadioSetting("keylock_off", "Key Lock",
                          RadioSettingValueBoolean(not _settings.keylock_off))
        cfg_grp.append(rs)
        rs = RadioSetting("ctdcsb", "CT/DCS Busy Lock",
                          RadioSettingValueBoolean(_settings.ctdcsb))
        cfg_grp.append(rs)
        rs = RadioSetting("alarm", "Alarm Key",
                          RadioSettingValueBoolean(_settings.alarm))
        cfg_grp.append(rs)
        rs = RadioSetting("save", "Battery Save",
                          RadioSettingValueBoolean(_settings.save))
        cfg_grp.append(rs)
        rs = RadioSetting("kbeep", "Key Beep",
                          RadioSettingValueBoolean(_settings.kbeep))
        cfg_grp.append(rs)
        rs = RadioSetting("reset", "Reset Enable",
                          RadioSettingValueBoolean(_settings.reset))
        cfg_grp.append(rs)
        rs = RadioSetting("smfont_off", "Small Font",
                          RadioSettingValueBoolean(not _settings.smfont_off))
        cfg_grp.append(rs)
        rs = RadioSetting("aliasen_off", "Alias Enable",
                          RadioSettingValueBoolean(not _settings.aliasen_off))
        cfg_grp.append(rs)
        rs = RadioSetting("txstop_off", "TX Stop",
                          RadioSettingValueBoolean(not _settings.txstop_off))
        cfg_grp.append(rs)
        rs = RadioSetting("dw_off", "Dual Watch",
                          RadioSettingValueBoolean(not _settings.dw_off))
        cfg_grp.append(rs)
        rs = RadioSetting("fmen_off", "FM Enable",
                          RadioSettingValueBoolean(not _settings.fmen_off))
        cfg_grp.append(rs)
        rs = RadioSetting("fmdw", "FM Dual Watch",
                          RadioSettingValueBoolean(_settings.fmdw))
        cfg_grp.append(rs)
        rs = RadioSetting("fmscan_off", "FM Scan",
                          RadioSettingValueBoolean(
                              not _settings.fmscan_off))
        cfg_grp.append(rs)
        rs = RadioSetting("keypadmic_off", "Keypad MIC",
                          RadioSettingValueBoolean(
                              not _settings.keypadmic_off))
        cfg_grp.append(rs)
        rs = RadioSetting("voxgain", "VOX Gain",
                          RadioSettingValueList(
                              VOXGAIN_LIST, current_index=_settings.voxgain))
        cfg_grp.append(rs)
        rs = RadioSetting("voxdt", "VOX Delay Time",
                          RadioSettingValueList(
                              VOXDT_LIST, current_index=_settings.voxdt))
        cfg_grp.append(rs)
        rs = RadioSetting("vir", "VOX Inhibit on Receive",
                          RadioSettingValueBoolean(_settings.vir))
        cfg_grp.append(rs)

        #
        # Advanced Settings
        #
        val = (_settings.dtmftime) - 5
        rs = RadioSetting("dtmftime", "DTMF Digit Time",
                          RadioSettingValueList(
                              DTMFTIME_LIST, current_index=val))
        adv_grp.append(rs)
        val = (_settings.dtmfspace) - 5
        rs = RadioSetting("dtmfspace", "DTMF Digit Space Time",
                          RadioSettingValueList(
                              DTMFTIME_LIST, current_index=val))
        adv_grp.append(rs)
        val = (_settings.dtmfdelay) // 5
        rs = RadioSetting("dtmfdelay", "DTMF 1st Digit Delay",
                          RadioSettingValueList(
                              DTMFDELAY_LIST, current_index=val))
        adv_grp.append(rs)
        val = (_settings.dtmfpretime) // 10 - 1
        rs = RadioSetting("dtmfpretime", "DTMF Pretime",
                          RadioSettingValueList(
                              DTMFPRETIME_LIST, current_index=val))
        adv_grp.append(rs)
        val = (_settings.dtmfdelay2) // 5
        rs = RadioSetting("dtmfdelay2", "DTMF * and # Digit Delay",
                          RadioSettingValueList(
                              DTMFDELAY2_LIST, current_index=val))
        adv_grp.append(rs)
        rs = RadioSetting("ackdecode", "ACK Decode",
                          RadioSettingValueBoolean(_settings.ackdecode))
        adv_grp.append(rs)
        rs = RadioSetting("dtmfst", "DTMF Sidetone",
                          RadioSettingValueBoolean(_settings.dtmfst))
        adv_grp.append(rs)

        rs = RadioSetting("service.rssi400", "Squelch Base Level (UHF)",
                          RadioSettingValueInteger(0, 255, _service.rssi400))
        adv_grp.append(rs)
        rs = RadioSetting("service.rssi136", "Squelch Base Level (VHF)",
                          RadioSettingValueInteger(0, 255, _service.rssi136))
        adv_grp.append(rs)

        #
        # Key Settings
        #
        val = (_settings.lptime) - 5
        rs = RadioSetting("lptime", "Long Press Time",
                          RadioSettingValueList(
                              LPTIME_LIST, current_index=val))
        key_grp.append(rs)
        rs = RadioSetting("keyp1long", "P1 Long Key",
                          RadioSettingValueList(
                              PFKEYLONG_LIST,
                              current_index=_settings.keyp1long))
        key_grp.append(rs)
        rs = RadioSetting("keyp1short", "P1 Short Key",
                          RadioSettingValueList(
                              PFKEYSHORT_LIST,
                              current_index=_settings.keyp1short))
        key_grp.append(rs)
        rs = RadioSetting("keyp2long", "P2 Long Key",
                          RadioSettingValueList(
                              PFKEYLONG_LIST,
                              current_index=_settings.keyp2long))
        key_grp.append(rs)
        rs = RadioSetting("keyp2short", "P2 Short Key",
                          RadioSettingValueList(
                              PFKEYSHORT_LIST,
                              current_index=_settings.keyp2short))
        key_grp.append(rs)
        rs = RadioSetting("keyp3long", "P3 Long Key",
                          RadioSettingValueList(
                              PFKEYLONG_LIST,
                              current_index=_settings.keyp3long))
        key_grp.append(rs)
        rs = RadioSetting("keyp3short", "P3 Short Key",
                          RadioSettingValueList(
                              PFKEYSHORT_LIST,
                              current_index=_settings.keyp3short))
        key_grp.append(rs)

        val = RadioSettingValueList(PFKEYSHORT_LIST,
                                    current_index=_settings.keymshort)
        val.set_mutable(_settings.menuen == 0)
        rs = RadioSetting("keymshort", "M Short Key", val)
        key_grp.append(rs)
        val = RadioSettingValueBoolean(_settings.menuen)
        rs = RadioSetting("menuen", "Menu Enable", val)
        key_grp.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "keylock_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "smfont_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "aliasen_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "txstop_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "dw_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "fmen_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "fmscan_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "keypadmic_off":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "dtmftime":
                        setattr(obj, setting, int(element.value) + 5)
                    elif setting == "dtmfspace":
                        setattr(obj, setting, int(element.value) + 5)
                    elif setting == "dtmfdelay":
                        setattr(obj, setting, int(element.value) * 5)
                    elif setting == "dtmfpretime":
                        setattr(obj, setting, (int(element.value) + 1) * 10)
                    elif setting == "dtmfdelay2":
                        setattr(obj, setting, int(element.value) * 5)
                    elif setting == "lptime":
                        setattr(obj, setting, int(element.value) + 5)
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        if filedata[0x168:0x170].startswith(cls._file_ident) and \
           filedata[0x170:0x178].startswith(cls._model_ident):
            return True
        else:
            return False


@directory.register
class JetstreamJT270MRadio(LeixenVV898Radio):

    """Jetstream JT270M"""
    VENDOR = "Jetstream"
    MODEL = "JT270M"
    ALIASES = []

    _file_ident = b"JET"
    _model_ident = b'LX-\x89\x85\x53'


class LT898UV(LeixenVV898Radio):
    VENDOR = "LUITON"
    MODEL = "LT-898UV"

    @classmethod
    def match_model(cls, filedata, filename):
        return False


@directory.register
class JetstreamJT270MHRadio(LeixenVV898Radio):

    """Jetstream JT270MH"""
    VENDOR = "Jetstream"
    MODEL = "JT270MH"

    _file_ident = b"Leixen"
    _model_ident = b'LX-\x89\x85\x85'
    _ranges = [(0x0C00, 0x2000)]
    _mem_formatter = {'unknownormode': 'mode:1',
                      'modeorpower': 'power:2',
                      'chanstart': 0x0C00,
                      'namestart': 0x1900,
                      'defaults': 6}
    _power_levels = [chirp_common.PowerLevel("Low", watts=5),
                     chirp_common.PowerLevel("Mid", watts=10),
                     chirp_common.PowerLevel("High", watts=25)]
    # Base radio has offset zero to distinguish from sub devices
    _offset = 0

    def get_features(self):
        rf = super(JetstreamJT270MHRadio, self).get_features()
        rf.has_sub_devices = self._offset == 0
        rf.memory_bounds = (1, 99)
        return rf

    def get_sub_devices(self):
        return [JetstreamJT270MHRadioA(self._mmap),
                JetstreamJT270MHRadioB(self._mmap)]

    def _get_memobjs(self, number):
        number = number * 2 - self._offset
        _mem = self._memobj.memory[number]
        _name = self._memobj.name[number]
        return _mem, _name


class JetstreamJT270MHRadioA(JetstreamJT270MHRadio):
    VARIANT = 'A Band'
    _offset = 1


class JetstreamJT270MHRadioB(JetstreamJT270MHRadio):
    VARIANT = 'B Band'
    _offset = 2


@directory.register
class LeixenVV898SRadio(LeixenVV898Radio):

    """Leixen VV-898S, also VV-898E which is identical"""
    VENDOR = "Leixen"
    MODEL = "VV-898S"

    _model_ident = b'LX-\x89\x85\x75'
    _mem_formatter = {'unknownormode': 'mode:1',
                      'modeorpower': 'power:2',
                      'chanstart': 0x0D00,
                      'namestart': 0x19B0,
                      'defaults': 3}
    _power_levels = [chirp_common.PowerLevel("Low", watts=5),
                     chirp_common.PowerLevel("Med", watts=10),
                     chirp_common.PowerLevel("High", watts=25)]


@directory.register
class VV898E(LeixenVV898SRadio):
    '''Leixen has called this radio both 898E and S historically, ident is
    identical'''
    VENDOR = "Leixen"
    MODEL = "VV-898E"

    @classmethod
    def match_model(cls, filedata, filename):
        return False


@directory.register
@directory.detected_by(LeixenVV898SRadio)
class VV898SDualBank(JetstreamJT270MHRadio):
    '''Newer VV898S 1.06+ firmware that features dual memory banks'''
    VENDOR = "Leixen"
    MODEL = "VV-898S"
    VARIANT = "Dual Bank"

    @classmethod
    def match_model(cls, filedata, filename):
        return False


@directory.register
@directory.detected_by(VV898E)
class VV898EDualBank(JetstreamJT270MHRadio):
    '''Newer VV898E 1.06+ firmware that features dual memory banks'''
    VENDOR = "Leixen"
    MODEL = "VV-898E"
    VARIANT = "Dual Bank"

    @classmethod
    def match_model(cls, filedata, filename):
        return False
