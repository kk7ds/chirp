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
import re

LOG = logging.getLogger(__name__)

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings
from textwrap import dedent

MEM_FORMAT = """
#seekto 0x0200;
struct {
  u8  unknown1;
  u8  volume;
  u8  unknown2[2];
  u8  wtled;
  u8  rxled;
  u8  txled;
  u8  ledsw;
  u8  beep;
  u8  ring;
  u8  bcl;
  u8  tot;
} settings;

struct vfo {
  u8  unknown1[2];
  u32 rxfreq;
  u8  unknown2[8];
  u8  power;
  u8  unknown3[3];
  u24 offset;
  u32 step;
  u8  sql;
};

#seekto 0x0300;
struct {
  struct vfo vfoa;
} upper;

#seekto 0x0380;
struct {
  struct vfo vfob;
} lower;

struct mem {
  u32 rxfreq;
  u16 is_rxdigtone:1,
      rxdtcs_pol:1,
      rxtone:14;
  u8  recvmode;
  u32 txfreq;
  u16 is_txdigtone:1,
      txdtcs_pol:1,
      txtone:14;
  u8  botsignal;
  u8  eotsignal;
  u8  power:1,
      wide:1,
      compandor:1
      scrambler:1
      unknown:4;
  u8  namelen;
  u8  name[6];
  u8  unused;
};

#seekto 0x0400;
struct mem upper_memory[128];

#seekto 0x1000;
struct mem lower_memory[128];

"""

MEM_SIZE = 0x1C00
BLOCK_SIZE = 0x40
STIMEOUT = 2

LIST_RECVMODE = ["", "QT/DQT", "QT/DQT + Signaling"]
LIST_SIGNAL = ["Off"] + ["DTMF%s" % x for x in range(1, 9)] + \
              ["DTMF%s + Identity" % x for x in range(1, 9)] + \
              ["Identity code"]
LIST_POWER = ["Low", "Mid", "High"]
LIST_COLOR = ["Off", "Orange", "Blue", "Purple"]
LIST_LEDSW = ["Auto", "On"]
LIST_RING = ["Off"] + ["%s seconds" % x for x in range(1, 10)]
LIST_TIMEOUT = ["Off"] + ["%s seconds" % x for x in range(30, 630, 30)]


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        Log.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        _exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        _exit_program_mode(radio)
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
    """Pack the info in the headder format"""
    frame = struct.pack(">4sHH", cmd, addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length):
    """Get data from the radio """

    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(data))

    return data


def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    #  set the serial discipline
    radio.pipe.baudrate = 19200
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # flush input buffer
    _clean_buffer(radio)

    magic = "PROM_LIN"

    _rawsend(radio, magic)

    ack = _rawrecv(radio, 1)
    if ack != "\x06":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    return True


def _exit_program_mode(radio):
    endframe = "EXIT"
    _rawsend(radio, endframe)


def _download(radio):
    """Get the memory map"""

    # put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_frame("READ", addr, BLOCK_SIZE)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug(util.hexprint(frame))

        # sending the read request
        _rawsend(radio, frame)

        # now we read
        d = _recv(radio, addr, BLOCK_SIZE)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)

    data += "LT-725UV"

    return data


def _upload(radio):
    """Upload procedure"""

    # put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun starts here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_frame("WRIE", addr, BLOCK_SIZE, data)

        _rawsend(radio, frame)

        # receiving the response
        ack = _rawrecv(radio, 1)
        if ack != "\x06":
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x1C00:0x1C08]

    if rid == cls.MODEL:
        return True

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
class LT725UV(chirp_common.CloneModeRadio,
              chirp_common.ExperimentalRadio):
    """LUITON LT-725UV Radio"""
    VENDOR = "LUITON"
    MODEL = "LT-725UV"
    MODES = ["NFM", "FM"]
    TONES = chirp_common.TONES
    DTCS_CODES = sorted(chirp_common.DTCS_CODES + [645])
    NAME_LENGTH = 6
    DTMF_CHARS = list("0123456789ABCD*#")

    VALID_BANDS = [(136000000, 176000000),
                   (400000000, 480000000)]

    # valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The LT725UV driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(dedent("""\
            Follow this instructions to download your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the download of your radio data
            """))
        rp.pre_upload = _(dedent("""\
            Follow this instructions to upload your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the upload of your radio data
            """))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_sub_devices = self.VARIANT == ""
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = []
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, 128)
        return rf

    def get_sub_devices(self):
        return [LT725UVUpper(self._mmap), LT725UVLower(self._mmap)]

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

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _memory_obj(self, suffix=""):
        return getattr(self._memobj, "%s_memory%s" % (self._vfo, suffix))

    def _get_dcs(self, val):
        return int(str(val)[2:-18])

    def _set_dcs(self, val):
        return int(str(val), 16)

    def get_memory(self, number):
        _mem = self._memory_obj()[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _split(self.get_features(), mem.freq, int(_mem.txfreq) * 10):
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _mem.name[:_mem.namelen]:
            mem.name += chr(char)

        dtcs_pol = ["N", "N"]

        if _mem.rxtone == 0x3FFF:
            rxmode = ""
        elif _mem.is_rxdigtone == 0:
            # ctcss
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            # digital
            rxmode = "DTCS"
            mem.rx_dtcs = self._get_dcs(_mem.rxtone)
            if _mem.rxdtcs_pol == 1:
                dtcs_pol[1] = "R"

        if _mem.txtone == 0x3FFF:
            txmode = ""
        elif _mem.is_txdigtone == 0:
            # ctcss
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # digital
            txmode = "DTCS"
            mem.dtcs = self._get_dcs(_mem.txtone)
            if _mem.txdtcs_pol == 1:
                dtcs_pol[0] = "R"

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        mem.mode = self.MODES[_mem.wide]

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        if _mem.recvmode == 0xFF:
            val = 0x00
        else:
            val = _mem.recvmode
        recvmode = RadioSetting("recvmode", "Receiving mode",
                                 RadioSettingValueList(LIST_RECVMODE,
                                     LIST_RECVMODE[val]))
        mem.extra.append(recvmode)

        if _mem.botsignal == 0xFF:
            val = 0x00
        else:
            val = _mem.botsignal
        botsignal = RadioSetting("botsignal", "Launch signaling",
                                 RadioSettingValueList(LIST_SIGNAL,
                                     LIST_SIGNAL[val]))
        mem.extra.append(botsignal)

        if _mem.eotsignal == 0xFF:
            val = 0x00
        else:
            val = _mem.eotsignal
        eotsignal = RadioSetting("eotsignal", "Transmit end signaling",
                                 RadioSettingValueList(LIST_SIGNAL,
                                     LIST_SIGNAL[val]))
        mem.extra.append(eotsignal)

        compandor = RadioSetting("compandor", "Compandor",
                                 RadioSettingValueBoolean(bool(_mem.compandor)))
        mem.extra.append(compandor)

        scrambler = RadioSetting("scrambler", "Scrambler",
                                 RadioSettingValueBoolean(bool(_mem.scrambler)))
        mem.extra.append(scrambler)

        return mem

    def set_memory(self, mem):
        _mem = self._memory_obj()[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * 24)
            _mem.namelen = 0
            return

        _mem.set_raw("\xFF" * 15 + "\x00\x00" + "\xFF" * 7)

        _mem.rxfreq = mem.freq / 10
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.namelen = len(mem.name)
        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _mem.name[i] = ord(mem.name[i])
            except IndexError:
                _mem.name[i] = 0xFF

        rxmode = ""
        txmode = ""

        if mem.tmode == "Tone":
            txmode = "Tone"
        elif mem.tmode == "TSQL":
            rxmode = "Tone"
            txmode = "TSQL"
        elif mem.tmode == "DTCS":
            rxmode = "DTCSSQL"
            txmode = "DTCS"
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

        if rxmode == "":
            _mem.rxdtcs_pol = 1
            _mem.is_rxdigtone = 1
            _mem.rxtone = 0x3FFF
        elif rxmode == "Tone":
            _mem.rxdtcs_pol = 0
            _mem.is_rxdigtone = 0
            _mem.rxtone = int(mem.ctone * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.dtcs)
        elif rxmode == "DTCS":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.rx_dtcs)

        if txmode == "":
            _mem.txdtcs_pol = 1
            _mem.is_txdigtone = 1
            _mem.txtone = 0x3FFF
        elif txmode == "Tone":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.rtone * 10)
        elif txmode == "TSQL":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.ctone * 10)
        elif txmode == "DTCS":
            _mem.txdtcs_pol = 1 if mem.dtcs_polarity[0] == "R" else 0
            _mem.is_txdigtone = 1
            _mem.txtone = self._set_dcs(mem.dtcs)

        _mem.wide = self.MODES.index(mem.mode)

        # extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        # Basic

        volume = RadioSetting("settings.volume", "Volume",
                              RadioSettingValueInteger(0, 20,
                                  _mem.settings.volume))
        basic.append(volume)

        powera = RadioSetting("upper.vfoa.power", "Power (Upper)",
                              RadioSettingValueList(LIST_POWER, LIST_POWER[
                                  _mem.upper.vfoa.power]))
        basic.append(powera)

        powerb = RadioSetting("lower.vfob.power", "Power (Lower)",
                              RadioSettingValueList(LIST_POWER, LIST_POWER[
                                  _mem.lower.vfob.power]))
        basic.append(powerb)

        wtled = RadioSetting("settings.wtled", "Standby LED Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.wtled]))
        basic.append(wtled)

        rxled = RadioSetting("settings.rxled", "RX LED Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.rxled]))
        basic.append(rxled)

        txled = RadioSetting("settings.txled", "TX LED Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.txled]))
        basic.append(txled)

        ledsw = RadioSetting("settings.ledsw", "Back light mode",
                             RadioSettingValueList(LIST_LEDSW, LIST_LEDSW[
                                 _mem.settings.ledsw]))
        basic.append(ledsw)

        beep = RadioSetting("settings.beep", "Beep",
                            RadioSettingValueBoolean(bool(_mem.settings.beep)))
        basic.append(beep)

        ring = RadioSetting("settings.ring", "Ring",
                            RadioSettingValueList(LIST_RING, LIST_RING[
                                _mem.settings.ring]))
        basic.append(ring)

        bcl = RadioSetting("settings.bcl", "Busy channel lockout",
                           RadioSettingValueBoolean(bool(_mem.settings.bcl)))
        basic.append(bcl)

        tot = RadioSetting("settings.tot", "Timeout Timer",
                           RadioSettingValueList(LIST_TIMEOUT, LIST_TIMEOUT[
                               _mem.settings.tot]))
        basic.append(tot)

        if _mem.upper.vfoa.sql == 0xFF:
            val = 0x04
        else:
            val = _mem.upper.vfoa.sql
        sqla = RadioSetting("upper.vfoa.sql", "Squelch (Upper)",
                            RadioSettingValueInteger(0, 9, val))
        basic.append(sqla)

        if _mem.lower.vfob.sql == 0xFF:
            val = 0x04
        else:
            val = _mem.lower.vfob.sql
        sqlb = RadioSetting("lower.vfob.sql", "Squelch (Lower)",
                            RadioSettingValueInteger(0, 9, val))
        basic.append(sqlb)

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
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
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise


    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == MEM_SIZE + 8:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False


class LT725UVUpper(LT725UV):
    VARIANT = "Upper"
    _vfo = "upper"


class LT725UVLower(LT725UV):
    VARIANT = "Lower"
    _vfo = "lower"
