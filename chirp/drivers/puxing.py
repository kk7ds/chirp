# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

"""Puxing radios management module"""

import time
import logging

from chirp import util, chirp_common, bitwise, errors, directory
from chirp.drivers.wouxun import wipe_memory, do_download, do_upload

LOG = logging.getLogger(__name__)


def _puxing_prep(radio):
    radio.pipe.write(b"\x02PROGRA")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise Exception("Radio did not ACK first command")

    radio.pipe.write(b"M\x02")
    ident = radio.pipe.read(8)
    if len(ident) != 8:
        LOG.debug(util.hexprint(ident))
        raise Exception("Radio did not send identification")

    radio.pipe.write(b"\x06")
    if radio.pipe.read(1) != b"\x06":
        raise Exception("Radio did not ACK ident")


def puxing_prep(radio):
    """Do the Puxing PX-777 identification dance"""
    ex = None
    for _i in range(0, 10):
        try:
            return _puxing_prep(radio)
        except Exception as e:
            time.sleep(1)
            ex = e

    raise ex


def puxing_download(radio):
    """Talk to a Puxing PX-777 and do a download"""
    try:
        puxing_prep(radio)
        return do_download(radio, 0x0000, 0x0C60, 0x0008)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)


def puxing_upload(radio):
    """Talk to a Puxing PX-777 and do an upload"""
    try:
        puxing_prep(radio)
        return do_upload(radio, 0x0000, 0x0C40, 0x0008)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)


POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                chirp_common.PowerLevel("Low", watts=1.00)]

PUXING_CHARSET = list("0123456789") + \
    [chr(x + ord("A")) for x in range(0, 26)] + \
    list("-                       ")

PUXING_MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 _3_unknown_1;
  u8 _2_unknown_1:2,
     power_high:1,
     iswide:1,
     skip:1,
     bclo:2,
     _2_unknown_2:1;
  u8 _4_unknown1:7,
     pttid:1;
  u8 unknown;
} memory[128];

#seekto 0x080A;
struct {
  u8 limits;
  u8 model;
} model[1];

#seekto 0x0850;
struct {
  u8 name[6];
  u8 pad[2];
} names[128];
"""

# Limits
#   67- 72: 0xEE
#  136-174: 0xEF
#  240-260: 0xF0
#  350-390: 0xF1
#  400-430: 0xF2
#  430-450: 0xF3
#  450-470: 0xF4
#  470-490: 0xF5
#  400-470: 0xF6
#  460-520: 0xF7

PUXING_MODELS = {
    328: 0x38,
    338: 0x39,
    777: 0x3A,
}

PUXING_777_BANDS = [
    (67000000,  72000000),
    (136000000, 174000000),
    (240000000, 260000000),
    (350000000, 390000000),
    (400000000, 430000000),
    (430000000, 450000000),
    (450000000, 470000000),
    (470000000, 490000000),
    (400000000, 470000000),
    (460000000, 520000000),
]


@directory.register
class Puxing777Radio(chirp_common.CloneModeRadio):
    """Puxing PX-777"""
    VENDOR = "Puxing"
    MODEL = "PX-777"

    def sync_in(self):
        self._mmap = puxing_download(self)
        self.process_mmap()

    def sync_out(self):
        puxing_upload(self)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = ''.join(set(PUXING_CHARSET))
        rf.valid_name_length = 6
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0,
                                 25.0, 30.0, 50.0, 100.0]
        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.memory_bounds = (1, 128)

        if not hasattr(self, "_memobj") or self._memobj is None:
            rf.valid_bands = [PUXING_777_BANDS[1]]
        elif self._memobj.model.model == PUXING_MODELS[777]:
            limit_idx = self._memobj.model.limits - 0xEE
            try:
                rf.valid_bands = [PUXING_777_BANDS[limit_idx]]
            except IndexError:
                LOG.error("Invalid band index %i (0x%02x)" %
                          (limit_idx, self._memobj.model.limits))
                rf.valid_bands = [PUXING_777_BANDS[1]]
        elif self._memobj.model.model == PUXING_MODELS[328]:
            # There are PX-777 that says to be model 328 ...
            # for them we only know this freq limits till now
            if self._memobj.model.limits in (0xEE, 0xEF):
                rf.valid_bands = [PUXING_777_BANDS[1]]
            else:
                raise Exception("Unsupported band limits 0x%02x for PX-777" %
                                (self._memobj.model.limits) + " submodel 328"
                                " - PLEASE REPORT THIS ERROR TO DEVELOPERS!!")

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(PUXING_MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1]) + "\r\n" + \
            repr(self._memobj.names[number - 1])

    @classmethod
    def match_model(cls, filedata, filename):
        # There are PX-777 that says to be model 328 ...
        return (len(filedata) == 3168 and
                (util.byte_to_int(filedata[0x080B]) == PUXING_MODELS[777] or
                (util.byte_to_int(filedata[0x080B]) == PUXING_MODELS[328] and
                 util.byte_to_int(filedata[0x080A]) == 0xEE)))

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        def _is_empty():
            for i in range(0, 4):
                if _mem.rx_freq[i].get_raw(asbytes=False) != "\xFF":
                    return False
            return True

        def _is_no_tone(field):
            return field.get_raw(asbytes=False) in ["\x00\x00", "\xFF\xFF"]

        def _get_dtcs(value):
            # Upper nibble 0x80 -> DCS, 0xC0 -> Inv. DCS
            if value > 12000:
                return "R", value - 12000
            elif value > 8000:
                return "N", value - 8000
            else:
                raise Exception("Unable to convert DCS value")

        def _do_dtcs(mem, txfield, rxfield):
            if int(txfield) < 8000 or int(rxfield) < 8000:
                raise Exception("Split tone not supported")

            if txfield[0].get_raw(asbytes=False) == "\xFF":
                tp, tx = "N", None
            else:
                tp, tx = _get_dtcs(int(txfield))

            if rxfield[0].get_raw(asbytes=False) == "\xFF":
                rp, rx = "N", None
            else:
                rp, rx = _get_dtcs(int(rxfield))

            if not rx:
                rx = tx
            if not tx:
                tx = rx

            if tx != rx:
                raise Exception("Different RX and TX DCS codes not supported")

            mem.dtcs = tx
            mem.dtcs_polarity = "%s%s" % (tp, rp)

        mem = chirp_common.Memory()
        mem.number = number

        if _is_empty():
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        mem.offset = (int(_mem.tx_freq) * 10) - mem.freq
        if mem.offset < 0:
            mem.duplex = "-"
        elif mem.offset:
            mem.duplex = "+"
        mem.offset = abs(mem.offset)
        if not _mem.skip:
            mem.skip = "S"
        if not _mem.iswide:
            mem.mode = "NFM"

        if _is_no_tone(_mem.tx_tone):
            pass  # No tone
        elif int(_mem.tx_tone) > 8000 or \
                (not _is_no_tone(_mem.rx_tone) and int(_mem.rx_tone) > 8000):
            mem.tmode = "DTCS"
            _do_dtcs(mem, _mem.tx_tone, _mem.rx_tone)
        else:
            mem.rtone = int(_mem.tx_tone) / 10.0
            mem.tmode = _is_no_tone(_mem.rx_tone) and "Tone" or "TSQL"

        mem.power = POWER_LEVELS[not _mem.power_high]

        for i in _nam.name:
            if i == 0xFF:
                break
            mem.name += PUXING_CHARSET[i]
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            wipe_memory(_mem, "\xFF")
            return

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq / 10) + (mem.offset / 10)
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq / 10) - (mem.offset / 10)
        else:
            _mem.tx_freq = (mem.freq / 10)
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"

        _mem.rx_tone[0].set_raw("\xFF")
        _mem.rx_tone[1].set_raw("\xFF")
        _mem.tx_tone[0].set_raw("\xFF")
        _mem.tx_tone[1].set_raw("\xFF")

        if mem.tmode == "DTCS":
            _mem.tx_tone = int("%x" % int("%i" % (mem.dtcs), 16))
            _mem.rx_tone = int("%x" % int("%i" % (mem.dtcs), 16))

            # Argh.  Set the high order two bits to signal DCS or Inv. DCS
            txm = mem.dtcs_polarity[0] == "N" and 0x80 or 0xC0
            rxm = mem.dtcs_polarity[1] == "N" and 0x80 or 0xC0
            _mem.tx_tone[1].set_raw(
                chr(ord(_mem.tx_tone[1].get_raw(asbytes=False)) | txm))
            _mem.rx_tone[1].set_raw(
                chr(ord(_mem.rx_tone[1].get_raw(asbytes=False)) | rxm))

        elif mem.tmode:
            _mem.tx_tone = int(mem.rtone * 10)
            if mem.tmode == "TSQL":
                _mem.rx_tone = int(_mem.tx_tone)

        if mem.power:
            _mem.power_high = not POWER_LEVELS.index(mem.power)
        else:
            _mem.power_high = True

        # Default to disabling the busy channel lockout
        # 00 == Close
        # 01 == Carrier
        # 10 == QT/DQT
        _mem.bclo = 0

        _nam.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _nam.name[i] = PUXING_CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")


def puxing_2r_prep(radio):
    """Do the Puxing 2R identification dance"""
    radio.pipe.timeout = 0.2
    radio.pipe.write(b"PROGRAM\x02")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise Exception("Radio is not responding")

    radio.pipe.write(ack)
    ident = radio.pipe.read(16)
    LOG.info("Radio ident: %s (%i)" % (repr(ident), len(ident)))


def puxing_2r_download(radio):
    """Talk to a Puxing 2R and do a download"""
    try:
        puxing_2r_prep(radio)
        return do_download(radio, 0x0000, 0x0FE0, 0x0010)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)


def puxing_2r_upload(radio):
    """Talk to a Puxing 2R and do an upload"""
    try:
        puxing_2r_prep(radio)
        return do_upload(radio, 0x0000, 0x0FE0, 0x0010)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)


PUXING_2R_MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd freq[4];
  lbcd offset[4];
  u8 rx_tone;
  u8 tx_tone;
  u8 duplex:2,
     txdtcsinv:1,
     rxdtcsinv:1,
     simplex:1,
     unknown2:1,
     iswide:1,
     ishigh:1;
  u8 name[5];
} memory[128];
"""

PX2R_DUPLEX = ["", "+", "-", ""]
PX2R_POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.0),
                     chirp_common.PowerLevel("High", watts=2.0)]
PX2R_CHARSET = "0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZ +"


@directory.register
class Puxing2RRadio(chirp_common.CloneModeRadio):
    """Puxing PX-2R"""
    VENDOR = "Puxing"
    MODEL = "PX-2R"
    NEEDS_COMPAT_SERIAL = True
    _memsize = 0x0FE0

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = PX2R_POWER_LEVELS
        rf.valid_bands = [(400000000, 500000000)]
        rf.valid_characters = PX2R_CHARSET
        rf.valid_name_length = 5
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_skips = []
        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.memory_bounds = (1, 128)
        rf.can_odd_split = False
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return (len(filedata) == cls._memsize) and \
            filedata[-16:] not in ("IcomCloneFormat3",
                                   b'IcomCloneFormat3')

    def sync_in(self):
        self._mmap = puxing_2r_download(self)
        self.process_mmap()

    def sync_out(self):
        puxing_2r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(PUXING_2R_MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        if _mem.get_raw(asbytes=False)[0:4] == "\xff\xff\xff\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10
        mem.mode = _mem.iswide and "FM" or "NFM"
        mem.duplex = PX2R_DUPLEX[_mem.duplex]
        mem.power = PX2R_POWER_LEVELS[_mem.ishigh]

        if _mem.tx_tone >= 0x33:
            mem.dtcs = chirp_common.DTCS_CODES[_mem.tx_tone - 0x33]
            mem.tmode = "DTCS"
            mem.dtcs_polarity = \
                (_mem.txdtcsinv and "R" or "N") + \
                (_mem.rxdtcsinv and "R" or "N")
        elif _mem.tx_tone:
            mem.rtone = chirp_common.TONES[_mem.tx_tone - 1]
            mem.tmode = _mem.rx_tone and "TSQL" or "Tone"

        count = 0
        for i in _mem.name:
            if i == 0xFF:
                break
            try:
                mem.name += PX2R_CHARSET[i]
            except Exception:
                LOG.error("Unknown name char %i: 0x%02x (mem %i)" %
                          (count, i, number))
                mem.name += " "
            count += 1
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            return

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10
        _mem.iswide = mem.mode == "FM"
        _mem.duplex = PX2R_DUPLEX.index(mem.duplex)
        _mem.ishigh = mem.power == PX2R_POWER_LEVELS[1]

        if mem.tmode == "DTCS":
            _mem.tx_tone = chirp_common.DTCS_CODES.index(mem.dtcs) + 0x33
            _mem.rx_tone = chirp_common.DTCS_CODES.index(mem.dtcs) + 0x33
            _mem.txdtcsinv = mem.dtcs_polarity[0] == "R"
            _mem.rxdtcsinv = mem.dtcs_polarity[1] == "R"
        elif mem.tmode in ["Tone", "TSQL"]:
            _mem.tx_tone = chirp_common.TONES.index(mem.rtone) + 1
            _mem.rx_tone = mem.tmode == "TSQL" and int(_mem.tx_tone) or 0
        else:
            _mem.tx_tone = 0
            _mem.rx_tone = 0

        for i in range(0, 5):
            try:
                _mem.name[i] = PX2R_CHARSET.index(mem.name[i])
            except IndexError:
                _mem.name[i] = 0xFF

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])
