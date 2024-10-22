# Copyright 2014 Jens Jensen <af5mi@yahoo.com>
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

from chirp.drivers import yaesu_clone, ft7800
from chirp import chirp_common, directory, bitwise, errors

LOG = logging.getLogger(__name__)
MEM_FORMAT = """
char model[6];
#seekto 0x018A;
struct {
    u16 in_use;
} bank_used[24];

#seekto 0x0214;
u16  banksoff1;
#seekto 0x0294;
u16  banksoff2;

#seekto 0x097A;
struct {
  u8 name[6];
} bank_names[24];

#seekto 0x0C0A;
struct {
  u16 channels[100];
} banks[24];

#seekto 0x0168;
struct {
  u8 used:1,
     unknown1:1,
     mode:1,
     unknown2:2,
     duplex:3;
  bbcd freq[3];
  u8 clockshift:1,
     tune_step:3,
     unknown5:1,
     tmode:3;
  bbcd split[3];
  u8 power:2,
     tone:6;
  u8 unknown6:1,
     dtcs:7;
  u8 unknown7[2];
  u8 offset;
  u8 unknown9[3];
} memory [200];

#seekto 0x0F28;
struct {
  char name[6];
  u8 enabled:1,
     unknown1:7;
  u8 used:1,
     unknown2:7;
} names[200];

#seekto 0x1768;
struct {
  u8 skip3:2,
     skip2:2,
     skip1:2,
     skip0:2;
} flags[50];
"""


@directory.register
class VX170Radio(ft7800.FTx800Radio):
    """Yaesu VX-170"""
    MODEL = "VX-170"
    _model = "AH022$"
    _memsize = 6057
    _block_lengths = [8, 6048, 1]
    _block_size = 32

    POWER_LEVELS_VHF = [chirp_common.PowerLevel("Hi", watts=5.00),
                        chirp_common.PowerLevel("Med", watts=2.00),
                        chirp_common.PowerLevel("Lo", watts=0.50)]

    MODES = ["FM", "NFM"]
    TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to MIC/SP jack.\n"
            "3. Press and hold in the [moni] key while turning the radio"
            " on.\n"
            "4. Select CLONE in menu, then press F. Radio restarts in clone"
            " mode.\n"
            "     (\"CLONE\" will appear on the display).\n"
            "5. <b>After clicking OK</b>, briefly hold [PTT] key to send"
            " image.\n"
            "    (\"-TX-\" will appear on the LCD). \n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "3. Press and hold in the [moni] key while turning the radio"
            " on.\n"
            "4. Select CLONE in menu, then press F. Radio restarts in clone"
            " mode.\n"
            "     (\"CLONE\" will appear on the display).\n"
            "5. Press the [moni] key (\"-RX-\" will appear on the LCD).\n")
        return rp

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, self._memsize - 2)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        if str(self._memobj.model) != self._model:
            LOG.debug('Expected %r, found %r' % (self._model,
                                                 str(self._memobj.model)))
            raise errors.RadioError(
              'Invalid model - radio is not %s' % self.MODEL)

    def get_features(self):
        rf = super(VX170Radio, self).get_features()
        rf.has_bank = False
        rf.has_bank_names = False
        rf.valid_modes = self.MODES
        rf.memory_bounds = (1, 200)
        rf.valid_bands = [(137000000, 174000000)]
        return rf


@directory.register
class VX177Radio(VX170Radio):
    MODEL = 'VX-177'
    _model = 'AH022U'
    POWER_LEVELS_UHF = [chirp_common.PowerLevel("Hi", watts=5.00),
                        chirp_common.PowerLevel("Med", watts=2.00),
                        chirp_common.PowerLevel("Lo", watts=0.50)]

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(420000000, 470000000)]
        return rf
