# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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

from chirp.drivers import id31
from chirp import directory, bitwise

MEM_FORMAT = """
struct {
  u24 freq;
  u16 offset;
  u16 rtone:6,
      ctone:6,
      unknown2:1,
      mode:3;
  u8 dtcs;
  u8 tune_step:4,
     dsql_mode:2,
     unknown5:2;
  u8 unknown4;
  u8 tmode:4,
     duplex:2,
     dtcs_polarity:2;
  char name[16];
  u8 digcode;
  u8 urcall[7];
  u8 rpt1call[7];
  u8 rpt2call[7];
} memory[500];

#seekto 0x6A40;
u8 used_flags[70];

#seekto 0x6A86;
u8 skip_flags[69];

#seekto 0x6ACB;
u8 pskp_flags[69];

#seekto 0x6B40;
struct {
  u8 bank;
  u8 index;
} banks[500];

#seekto 0x6FD0;
struct {
  char name[16];
} bank_names[26];

#seekto 0xA8C0;
struct {
  u24 freq;
  u16 offset;
  u8 unknown1[3];
  u8 call[7];
  char name[16];
  char subname[8];
  u8 unknown3[10];
} repeaters[750];

#seekto 0x1384E;
struct {
  u8 call[7];
} rptcall[750];

#seekto 0x14E60;
struct {
  char call[8];
  char tag[4];
} mycall[6];

#seekto 0x14EA8;
struct {
  char call[8];
} urcall[200];

"""
LOG = logging.getLogger(__name__)


@directory.register
class ID51Radio(id31.ID31Radio):
    """Icom ID-51"""
    MODEL = "ID-51"

    _memsize = 0x1FB40
    _model = "\x33\x90\x00\x01"
    _endframe = "Icom Inc\x2E\x44\x41"

    _ranges = [(0x00000, 0x1FB40, 32)]

    MODES = {0: "FM", 1: "NFM", 3: "AM", 5: "DV"}

    @classmethod
    def match_model(cls, filedata, filename):
        """Given contents of a stored file (@filedata), return True if
        this radio driver handles the represented model"""

        # The default check for ICOM is just to check memory size
        # Since the ID-51 and ID-51 Plus/Anniversary have exactly
        # the same memory size, we need to do a more detailed check.
        if len(filedata) == cls._memsize:
            snip = bytes(filedata[0x1AF40:0x1AF60])
            if snip == bytes(b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                             b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                             b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                             b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'):
                return True
        if filename.lower().endswith('.icf'):
            return super().match_model(filedata, filename)
        return False

    def get_features(self):
        rf = super(ID51Radio, self).get_features()
        rf.valid_bands = [(108000000, 174000000), (400000000, 479000000)]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
