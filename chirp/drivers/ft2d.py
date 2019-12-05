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
from textwrap import dedent

from chirp.drivers import yaesu_clone, ft1d
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSetting, RadioSettings
from chirp.settings import RadioSettingValueString

# Differences from Yaesu FT1D
#  999 memories, but 901-999 are only for skipping VFO frequencies
#  Text in memory and memory bank structures is ASCII encoded
#  Expanded modes
#  Slightly different clone-mode instructions

LOG = logging.getLogger(__name__)

TMODES = ["", "Tone", "TSQL", "DTCS", "RTone", "JRfrq", "PRSQL", "Pager"]

class FT2Bank(chirp_common.NamedBank): # Like FT1D except for name in ASCII
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

class FT2BankModel(ft1d.FT1BankModel): #just need this one to launch FT2Bank
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
    MODEL = "FT2D" # Yaesu doesn't use a hyphen in its documents
    VARIANT = "R"

    _model = "AH60M" # Get this from chirp .img file after saving once
    _has_vibrate = True
    _mem_params = (0x94a,         # Location of DTMF storage
                   999,            # size of memories array
                   999,            # size of flags array
                   0xFECA,         # APRS beacon metadata address.
                   60,             # Number of beacons stored.
                   0x1064A,        # APRS beacon content address.
                   134,            # Length of beacon data stored.
                   60)             # Number of beacons stored.
    _APRS_HIGH_SPEED_MAX = 90

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
         1. Turn radio off.
         2. Connect cable to DATA terminal.
         3. Press and hold [DISP] key while turning on radio
              ("CLONE" will appear on the display).
         4. <b>After clicking OK here in chirp</b>,
              press the [Send] screen button."""))
        rp.pre_upload = _(dedent("""\
         1. Turn radio off.
         2. Connect cable to DATA terminal.
         3. Press and hold in [DISP] key while turning on radio
              ("CLONE" will appear on radio LCD).
         4. Press [RECEIVE] screen button
              ("-WAIT-" will appear on radio LCD).
        5. Finally, press OK button below."""))
        return rp

    def get_features(self): # AFAICT only TMODES & memory bounds are different
        rf = super(FT2D, self).get_features()
        rf.valid_tmodes = list(TMODES)
        rf.memory_bounds = (1, 999)
        return rf

    def get_bank_model(self):   # here only to launch the bank model
        return FT2BankModel(self)

    def get_memory(self, number):
        mem = super(FT2D, self).get_memory(number)
        flag = self._memobj.flag[number - 1]
        if number >= 901 and number <= 999: # for FT2D; enforces skip
            mem.skip = "S"
            flag.skip = True
        return mem

    def _decode_label(self, mem):
        return str(mem.label).rstrip("\xFF").decode('ascii', 'replace')

    def _encode_label(self, mem):
        label = mem.name.rstrip().encode('ascii', 'ignore')
        return self._add_ff_pad(label, 16)

    def set_memory(self, mem):
        flag = self._memobj.flag[mem.number - 1]
        if mem.number >= 901 and mem.number <= 999: # for FT2D; enforces skip
            flag.skip = True
            mem.skip = "S"
        super(FT2D, self).set_memory(mem)

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
    """Yaesu FT-2D v2 firwmare"""
    VARIANT = "Rv2"

    _model = "AH60G"

@directory.register
class FT3D(FT2D):
    """Yaesu FT-3D"""
    MODEL = "FT3D"
    VARIANT = "R"

    _model = "AH72M"
