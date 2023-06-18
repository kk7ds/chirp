# Copyright 2010 Dan Smith <dsmith@danplanet.com>
# Portions Copyright 2017 Wade Simmons <wade@wades.im>
# Copyright 2017 Declan Rieb <darieb@comcast.net>
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

import logging

from chirp.drivers import ft1d
from chirp import chirp_common, directory
from chirp import errors
from chirp import memmap
from chirp.settings import RadioSetting
from chirp.settings import RadioSettingValueString
from chirp import util

# Differences from Yaesu FT1D
#  Text in memory and memory bank structures is ASCII encoded
#  Expanded modes
#  Slightly different clone-mode instructions

LOG = logging.getLogger(__name__)

TMODES = ["", "Tone", "TSQL", "DTCS", "RTone", "JRfrq", "PRSQL", "Pager"]


class FT2Bank(chirp_common.NamedBank):  # Like FT1D except for name in ASCII
    def get_name(self):
        _bank = self._model._radio._memobj.bank_info[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xff:
                break
            name += chr(i & 0xFF)
        return name.rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank.name = [ord(x) for x in name.ljust(16, chr(0xFF))[:16]]


class FT2BankModel(ft1d.FT1BankModel):  # Just need this one to launch FT2Bank
    """A FT1D bank model"""
    def __init__(self, radio, name='Banks'):
        super(FT2BankModel, self).__init__(radio, name)

        _banks = self._radio._memobj.bank_info
        self._bank_mappings = []
        for index, _bank in enumerate(_banks):
            bank = FT2Bank(self, "%i" % index, "BANK-%i" % index)
            bank.index = index
            self._bank_mappings.append(bank)


@directory.register
class FT2D(ft1d.FT1Radio):
    """Yaesu FT-2D"""
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "FT2D"  # Yaesu doesn't use a hyphen in its documents
    VARIANT = "R"

    _model = b"AH60M"  # Get this from chirp .img file after saving once
    _has_vibrate = True
    MAX_MEM_SLOTS = 900
    _mem_params = {
         "memnum": 900,            # size of memories array
         "flgnum": 900,            # size of flags array
         "dtmadd": 0x94A,          # address of DTMF strings
         }
    _adms_ext = '.ft2d'
    _APRS_HIGH_SPEED_MAX = 90
    FORMATS = [directory.register_format('FT2D ADMS-8', '*.ft2d')]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to DATA terminal.\n"
            "3. Press and hold [DISP] key while turning on radio\n"
            "     (\"CLONE\" will appear on the display).\n"
            "4. <b>After clicking OK here in chirp</b>,\n"
            "     press the [Send] screen button.\n")
        rp.pre_upload = _(
            " 1. Turn radio off.\n"
            " 2. Connect cable to DATA terminal.\n"
            " 3. Press and hold in [DISP] key while turning on radio\n"
            "      (\"CLONE\" will appear on radio LCD).\n"
            " 4. Press [RECEIVE] screen button\n"
            "      (\"-WAIT-\" will appear on radio LCD).\n"
            "5. Finally, press OK button below.\n")
        return rp

    def get_features(self):  # AFAICT only TMODES & memory bounds are different
        rf = super(FT2D, self).get_features()
        rf.valid_tmodes = list(TMODES)
        rf.memory_bounds = (1, self.MAX_MEM_SLOTS)
        return rf

    def get_bank_model(self):   # here only to launch the bank model
        return FT2BankModel(self)

    def _decode_label(self, mem):
        return str(mem.label).rstrip("\xFF")

    def _encode_label(self, mem):
        label = mem.name.rstrip().encode('ascii', 'ignore')
        return self._add_ff_pad(label, 16)

    def _decode_opening_message(self, opening_message):
        msg = ""
        for i in opening_message.message.padded_yaesu:
            if i == 0xFF:
                break
            msg += chr(int(i))
        val = RadioSettingValueString(0, 16, msg)
        rs = RadioSetting("opening_message.message.padded_yaesu",
                          "Opening Message", val)
        rs.set_apply_callback(self._apply_opening_message,
                              opening_message.message.padded_yaesu)
        return rs

    def _apply_opening_message(self, setting, obj):
        data = self._add_ff_pad(setting.value.get_value().rstrip(), 16)
        val = []
        for i in data:
            val.append(ord(i))
        self._memobj.opening_message.message.padded_yaesu = val


@directory.register
class FT2Dv2(FT2D):
    """Yaesu FT-2D v2 firmware"""
    VARIANT = "Rv2"

    _model = b"AH60G"


@directory.register
class FT3D(FT2D):
    """Yaesu FT-3D"""
    MODEL = "FT3D"
    VARIANT = "R"

    _model = b"AH72M"
    FORMATS = [directory.register_format('FT3D ADMS-11', '*.ft3d')]

    def load_mmap(self, filename):
        if filename.lower().endswith('.ft3d'):
            with open(filename, 'rb') as f:
                self._adms_header = f.read(0x18C)
                if b'ADMS11, Version=1.0.0.0' not in self._adms_header:
                    raise errors.ImageDetectFailed(
                        'Unsupported version found in ADMS file')
                LOG.debug('ADMS Header:\n%s',
                          util.hexprint(self._adms_header))
                self._mmap = memmap.MemoryMapBytes(f.read())
                LOG.info('Loaded ADMS-11 file at offset 0x18C')
            self.process_mmap()
        else:
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.ft3d'):
            if not hasattr(self, '_adms_header'):
                raise Exception('Unable to save .img to .ft3d')
            with open(filename, 'wb') as f:
                f.write(self._adms_header)
                f.write(self._mmap.get_packed())
                LOG.info('Wrote ADMS-11 file')
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    @classmethod
    def match_model(cls, filedata, filename):
        if filename.endswith('.ft3d'):
            return True
        else:
            return super().match_model(filedata, filename)
