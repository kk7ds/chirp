# Copyright 2016:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
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

import time
import struct
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown1:2,
     dtmf:1,          // DTMF
     unknown2:1,
     bcl:1,           // Busy Channel Lockout
     unknown3:3;
  u8 unknown4:1,
     scan:1,          // Scan Add
     highpower:1,     // TX Power Level
     wide:1,          // BandWidth
     unknown5:4;
  u8 unknown6[2];
} memory[128];

#seekto 0x0E17;
struct {
  u8 displayab:1,  // Selected Display
     unknown1:6,
     unknown2:1;
} settings1;

#seekto 0x0E22;
struct {
  u8 squelcha;      // menu 02a Squelch Level              0xe22
  u8 unknown1;
  u8 tdrab;         //          TDR A/B                    0xe24
  u8 roger;         // menu 20  Roger Beep                 0xe25
  u8 timeout;       // menu 16  TOT                        0xe26
  u8 vox;           // menu 05  VOX                        0xe27
  u8 unknown2;
  u8 mdfb;          // menu 27b Memory Display Format B    0xe37
  u8 dw;            // menu 37  DW                         0xe2a
  u8 tdr;           // menu 29  Dual Watch                 0xe2b
  u8 voice;         // menu 03  Voice Prompts              0xe2c
  u8 beep;          // menu 01  Key Beep                   0xe2d
  u8 ani;           // menu 30  ANI                        0xe2e
  u8 unknown3[4];
  u8 pttdly;        // menu 31  PTT-ID Delay               0xe33
  u8 unknown4;
  u8 dtmfst;        // menu 33  DTMF Side Tone             0xe35
  u8 toa;           // menu 15  TOT Pre-Alert              0xe36
  u8 mdfa;          // menu 27a Memory Display Format A    0xe37
  u8 screv;         // menu 09  Scan Resume Method         0xe38
  u8 pttid;         // menu 32  PTT-ID Enable              0xe39
  u8 ponmsg;        // menu 36  Power-on Message           0xe3a
  u8 pf1;           // menu 28  Programmable Function Key  0xe3b
  u8 unknown5;
  u8 wtled;         // menu 17  Standby LED Color          0xe3d
  u8 rxled;         // menu 18  RX LED Color               0xe3e
  u8 txled;         // menu 19  TX LED Color               0xe3f
  u8 unknown6;
  u8 autolk;        // menu 06  Auto Key Lock              0xe41
  u8 squelchb;      // menu 02b Squelch Level              0xe42
  u8 control;       //          Control Code               0xe43
  u8 unknown7;
  u8 ach;           //          Selected A channel Number  0xe45
  u8 unknown8[4];
  u8 password[6];   //          Control Password           0xe4a-0xe4f
  u8 unknown9[7];
  u8 code[3];       //          PTT ID Code                0xe57-0xe59
  u8 vfomr;         //          Frequency/Channel Modevel  0xe5a
  u8 keylk;         //          Key Lock                   0xe5b
  u8 unknown10[2];
  u8 prioritych;    //          Priority Channel           0xe5e
  u8 bch;           //          Selected B channel Number  0xe5f
} settings;

struct vfo {
  u8 unknown0[8];
  u8 freq[8];
  u8 offset[6];
  ul16 rxtone;
  ul16 txtone;
  u8 unused0:7,
     band:1;
  u8 unknown3;
  u8 unknown4:2,
     sftd:2,
     scode:4;
  u8 unknown5;
  u8 unknown6:1,
     step:3,
     unknown7:4;
  u8 txpower:1,
     widenarr:1,
     unknown8:6;
};

#seekto 0x0F10;
struct {
  struct vfo a;
  struct vfo b;
} vfo;

#seekto 0x1010;
struct {
  u8 name[6];
  u8 unknown[10];
} names[128];

"""

# #### MAGICS #########################################################

# TDXone TD-Q8A magic string
MSTRING_TDQ8A = "\x02PYNCRAM"

LIST_DTMF = ["QT", "QT+DTMF"]
LIST_VOICE = ["Off", "Chinese", "English"]
LIST_OFF1TO9 = ["Off"] + list("123456789")
LIST_OFF1TO10 = LIST_OFF1TO9 + ["10"]
LIST_RESUME = ["Time Operated(TO)", "Carrier Operated(CO)", "Search(SE)"]
LIST_COLOR = ["Off", "Blue", "Orange", "Purple"]
LIST_MODE = ["Channel", "Frequency", "Name"]
LIST_PF1 = ["Off", "Scan", "Lamp", "FM Radio", "Alarm"]
LIST_OFF1TO30 = ["OFF"] + ["%s" % x for x in range(1, 31)]
LIST_DTMFST = ["Off", "DTMF Sidetone", "ANI Sidetone", "DTMF+ANI Sidetone"]
LIST_PONMSG = ["Full", "Welcome", "Battery Voltage"]
LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 615, 15)]
LIST_PTTID = ["BOT", "EOT", "Both"]
LIST_ROGER = ["Off"] + LIST_PTTID
LIST_PRIORITY = ["Off"] + ["%s" % x for x in range(1, 129)]
LIST_WORKMODE = ["Frequency", "Channel"]
LIST_AB = ["A", "B"]

LIST_ALMOD = ["Site", "Tone", "Code"]
LIST_BANDWIDTH = ["Wide", "Narrow"]
LIST_DELAYPROCTIME = ["%s ms" % x for x in range(100, 4100, 100)]
LIST_DTMFSPEED = ["%s ms" % x for x in range(50, 2010, 10)]
LIST_OFFAB = ["Off"] + LIST_AB
LIST_RESETTIME = ["%s ms" % x for x in range(100, 16100, 100)]
LIST_SCODE = ["%s" % x for x in range(1, 16)]
LIST_RPSTE = ["Off"] + ["%s" % x for x in range(1, 11)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SHIFTD = ["Off", "+", "-"]
LIST_STEDELAY = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
LIST_TXPOWER = ["High", "Low"]
LIST_DTMF_SPECIAL_DIGITS = ["*", "#", "A", "B", "C", "D"]
LIST_DTMF_SPECIAL_VALUES = [0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x00]

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ?+-*"
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Low", watts=1)]
VALID_BANDS = [(136000000, 174000000),
               (400000000, 520000000)]


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        msg = "Error reading data from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length):
    """Get data from the radio """
    # read 4 bytes of header
    hdr = _rawrecv(radio, 4)

    # read data
    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord("W"):
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _do_ident(radio, magic):
    """Put the radio in PROGRAM mode"""
    # set the serial discipline
    radio.pipe.baudrate = 9600

    # send request to enter program mode
    _rawsend(radio, magic)

    ack = _rawrecv(radio, 1)
    if ack != "\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    _rawsend(radio, "\x02")

    # Ok, get the response
    ident = _rawrecv(radio, radio._magic_response_length)

    # check if response is OK
    if not ident.startswith("P3107"):
        # bad response
        msg = "Unexpected response, got this:"
        msg += util.hexprint(ident)
        LOG.debug(msg)
        raise errors.RadioError("Unexpected response from radio.")

    # DEBUG
    LOG.info("Valid response, got this:")
    LOG.debug(util.hexprint(ident))

    _rawsend(radio, "\x06")
    ack = _rawrecv(radio, 1)
    if ack != "\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio refused clone")

    return ident


def _ident_radio(radio):
    for magic in radio._magic:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError as e:
            print(e)
            error = e
            time.sleep(2)
    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _download(radio):
    """Get the memory map"""
    # put radio in program mode
    ident = _ident_radio(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size / radio._recv_block_size
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in range(0, radio._mem_size, radio._recv_block_size):
        frame = _make_frame("R", addr, radio._recv_block_size)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug(util.hexprint(frame))

        # sending the read request
        _rawsend(radio, frame)

        # now we read
        d = _recv(radio, addr, radio._recv_block_size)

        time.sleep(0.05)

        _rawsend(radio, "\x06")

        ack = _rawrecv(radio, 1)
        if ack != "\x06":
            raise errors.RadioError(
                "Radio refused to send block 0x%04x" % addr)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr / radio._recv_block_size
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    data += radio.MODEL.ljust(8)

    return data


def _upload(radio):
    """Upload procedure"""
    # put radio in program mode
    _ident_radio(radio)

    addr = 0x0f80
    frame = _make_frame("R", addr, radio._recv_block_size)
    # DEBUG
    LOG.info("Request sent:")
    LOG.debug(util.hexprint(frame))

    # sending the read request
    _rawsend(radio, frame)

    # now we read
    d = _recv(radio, addr, radio._recv_block_size)

    time.sleep(0.05)

    _rawsend(radio, "\x06")

    ack = _rawrecv(radio, 1)
    if ack != "\x06":
        raise errors.RadioError(
            "Radio refused to send block 0x%04x" % addr)

    _ranges = radio._ranges

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size / radio._send_block_size
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    for start, end in _ranges:
        for addr in range(start, end, radio._send_block_size):
            # sending the data
            data = radio.get_mmap()[addr:addr + radio._send_block_size]

            frame = _make_frame("W", addr, radio._send_block_size, data)

            _rawsend(radio, frame)

            # receiving the response
            ack = _rawrecv(radio, 1)
            if ack != "\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = addr / radio._send_block_size
            status.msg = "Cloning to radio..."
            radio.status_fn(status)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == 0x2008:
        rid = data[0x2000:0x2008]
        return rid.startswith(cls._model)
    else:
        return False


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True


@directory.register
class TDXoneTDQ8A(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """TDXone TD-Q8A Radio"""
    VENDOR = "TDXone"
    MODEL = "TD-Q8A"
    NEEDS_COMPAT_SERIAL = True

    _model = b'TD-Q8A'
    _magic = [MSTRING_TDQ8A, MSTRING_TDQ8A, ]
    _magic_response_length = 8
    _fw_ver_start = 0x1EF0
    _recv_block_size = 0x40
    _mem_size = 0x2000

    _ranges = [(0x0010, 0x0810),
               (0x0E20, 0x0E60),
               (0x0F10, 0x0F30),
               (0x1010, 0x1810),
               (0x1F10, 0x1F30)]
    _send_block_size = 0x10

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The TDXone TD-Q8A driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def get_features(self):
        """Get the radio's features"""

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = False
        rf.has_rx_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "->Tone"]
        rf.valid_skips = ["", "S"]
        rf.memory_bounds = (1, 128)
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = STEPS
        rf.valid_bands = VALID_BANDS

        return rf

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw(asbytes=False)
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def _get_mem(self, number):
        return self._memobj.memory[number - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw(asbytes=False)[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(
                          _mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        if _nam.name:
            for char in _nam.name:
                try:
                    mem.name += CHARSET[char]
                except IndexError:
                    break
            mem.name = mem.name.rstrip()

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = POWER_LEVELS[1 - _mem.highpower]

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("dtmf", "DTMF",
                          RadioSettingValueList(LIST_DTMF,
                                                current_index=_mem.dtmf))
        mem.extra.append(rs)

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        return mem

    def _set_mem(self, number):
        return self._memobj.memory[number - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        _nam = self._get_nam(mem.number)

        if mem.empty:
            _mem.set_raw("\xff" * 12 + "\xbf" + "\xff" * 3)
            _nam.set_raw("\xff" * 16)
            return

        _mem.set_raw("\xff" * 12 + "\x9f" + "\xff" * 3)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        if _nam.name:
            for i in range(0, 6):
                try:
                    _nam.name[i] = CHARSET.index(mem.name[i])
                except IndexError:
                    _nam.name[i] = 0xFF

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"

        _mem.highpower = mem.power == POWER_LEVELS[0]

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        top = RadioSettings(basic, advanced, )

        # Basic settings
        rs = RadioSetting("settings.beep", "Beep",
                          RadioSettingValueBoolean(
                              _mem.settings.beep))
        basic.append(rs)

        if _mem.settings.squelcha > 0x09:
            val = 0x00
        else:
            val = _mem.settings.squelcha
        rs = RadioSetting("squelcha", "Squelch Level A",
                          RadioSettingValueInteger(
                              0, 9, _mem.settings.squelcha))
        basic.append(rs)

        if _mem.settings.squelchb > 0x09:
            val = 0x00
        else:
            val = _mem.settings.squelchb
        rs = RadioSetting("squelchb", "Squelch Level B",
                          RadioSettingValueInteger(
                              0, 9, _mem.settings.squelchb))
        basic.append(rs)

        if _mem.settings.voice > 0x02:
            val = 0x01
        else:
            val = _mem.settings.voice
        rs = RadioSetting("settings.voice", "Voice Prompt",
                          RadioSettingValueList(
                              LIST_VOICE, current_index=val))
        basic.append(rs)

        if _mem.settings.vox > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.vox
        rs = RadioSetting("settings.vox", "VOX",
                          RadioSettingValueList(
                              LIST_OFF1TO10, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.autolk", "Automatic Key Lock",
                          RadioSettingValueBoolean(_mem.settings.autolk))
        basic.append(rs)

        if _mem.settings.screv > 0x02:
            val = 0x01
        else:
            val = _mem.settings.screv
        rs = RadioSetting("settings.screv", "Scan Resume",
                          RadioSettingValueList(
                              LIST_RESUME, current_index=val))
        basic.append(rs)

        if _mem.settings.toa > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.toa
        rs = RadioSetting("settings.toa", "Time-out Pre-Alert",
                          RadioSettingValueList(
                              LIST_OFF1TO10, current_index=val))
        basic.append(rs)

        if _mem.settings.timeout > 0x28:
            val = 0x03
        else:
            val = _mem.settings.timeout
        rs = RadioSetting("settings.timeout", "Timeout Timer",
                          RadioSettingValueList(
                              LIST_TIMEOUT, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.wtled", "Standby LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.wtled))
        basic.append(rs)

        rs = RadioSetting("settings.rxled", "RX LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.rxled))
        basic.append(rs)

        rs = RadioSetting("settings.txled", "TX LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.txled))
        basic.append(rs)

        rs = RadioSetting(
            "settings.roger", "Roger Beep",
            RadioSettingValueList(
                LIST_ROGER, current_index=_mem.settings.roger))
        basic.append(rs)

        rs = RadioSetting(
            "settings.mdfa", "Display Mode (A)",
            RadioSettingValueList(
                LIST_MODE, current_index=_mem.settings.mdfa))
        basic.append(rs)

        rs = RadioSetting(
            "settings.mdfb", "Display Mode (B)",
            RadioSettingValueList(
                LIST_MODE, current_index=_mem.settings.mdfb))
        basic.append(rs)

        rs = RadioSetting(
            "settings.pf1", "PF1 Key Assignment",
            RadioSettingValueList(
                LIST_PF1, current_index=_mem.settings.pf1))
        basic.append(rs)

        rs = RadioSetting("settings.tdr", "Dual Watch(TDR)",
                          RadioSettingValueBoolean(_mem.settings.tdr))
        basic.append(rs)

        rs = RadioSetting("settings.ani", "ANI",
                          RadioSettingValueBoolean(_mem.settings.ani))
        basic.append(rs)

        if _mem.settings.pttdly > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.pttdly
        rs = RadioSetting("settings.pttdly", "PTT ID Delay",
                          RadioSettingValueList(
                              LIST_OFF1TO30, current_index=val))
        basic.append(rs)

        rs = RadioSetting(
            "settings.pttid", "When to send PTT ID",
            RadioSettingValueList(
                LIST_PTTID, current_index=_mem.settings.pttid))
        basic.append(rs)

        rs = RadioSetting(
            "settings.dtmfst", "DTMF Sidetone",
            RadioSettingValueList(
                LIST_DTMFST, current_index=_mem.settings.dtmfst))
        basic.append(rs)

        rs = RadioSetting(
            "settings.ponmsg", "Power-On Message",
            RadioSettingValueList(
                LIST_PONMSG, current_index=_mem.settings.ponmsg))
        basic.append(rs)

        rs = RadioSetting("settings.dw", "DW",
                          RadioSettingValueBoolean(_mem.settings.dw))
        basic.append(rs)

        # Advanced settings
        rs = RadioSetting(
            "settings.prioritych", "Priority Channel",
            RadioSettingValueList(
                LIST_PRIORITY, current_index=_mem.settings.prioritych))
        advanced.append(rs)

        rs = RadioSetting(
            "settings.vfomr", "Work Mode",
            RadioSettingValueList(
                LIST_WORKMODE, current_index=_mem.settings.vfomr))
        advanced.append(rs)

        dtmfchars = "0123456789"
        _codeobj = _mem.settings.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 3, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("settings.code", "PTT-ID Code", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 3):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, _mem.settings)
        advanced.append(rs)

        _codeobj = _mem.settings.password
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("settings.password", "Control Password", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 6):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.password = code
        rs.set_apply_callback(apply_code, _mem.settings)
        advanced.append(rs)

        if _mem.settings.tdrab > 0x01:
            val = 0x00
        else:
            val = _mem.settings.tdrab
        rs = RadioSetting("settings.tdrab", "Dual Watch TX Priority",
                          RadioSettingValueList(
                              LIST_AB, current_index=val))
        advanced.append(rs)

        rs = RadioSetting("settings.keylk", "Key Lock",
                          RadioSettingValueBoolean(_mem.settings.keylk))
        advanced.append(rs)

        rs = RadioSetting("settings.control", "Control Code",
                          RadioSettingValueBoolean(_mem.settings.control))
        advanced.append(rs)

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
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
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                if self._memobj.fm_presets <= 108.0 * 10 - 650:
                    value = int(val.get_value() * 10 - 650)
                else:
                    value = int(val.get_value() * 10)
                LOG.debug("Setting fm_presets = %s" % (value))
                self._memobj.fm_presets = value
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == 0x2008:
            match_size = True

        # testing the model fingerprint
        match_model = model_match(cls, filedata)

        # if match_size and match_model:
        if match_size and match_model:
            return True
        else:
            return False
