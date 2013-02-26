# Copyright 2012 Tom Hayward <tom@tomh.us>
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

import UserDict
from chirp import chirp_common, directory, generic_csv

class TpeMap(UserDict.UserDict):
    """Pretend we're a dict"""
    def items(self):
        return [
            ("Sequence Number" , (int, "number")),
            ("Location"        , (str, "comment")),
            ("Call Sign"       , (str, "name")),
            ("Output Frequency", (chirp_common.parse_freq, "freq")),
            ("Input Frequency" , (str, "duplex")),
            ("CTCSS Tones"     , (lambda v: "Tone" 
                                  if float(v) in chirp_common.TONES
                                  else "", "tmode")),
            ("CTCSS Tones"     , (lambda v: float(v)
                                  if float(v) in chirp_common.TONES
                                  else 88.5, "rtone")),
            ("CTCSS Tones"     , (lambda v: float(v)
                                  if float(v) in chirp_common.TONES
                                  else 88.5, "ctone")),
        ]

@directory.register
class TpeRadio(generic_csv.CSVRadio):
    """Generic ARRL Travel Plus"""
    VENDOR = "ARRL"
    MODEL = "Travel Plus"
    FILE_EXTENSION = "tpe"

    ATTR_MAP = TpeMap()

    @classmethod
    def match_model(cls, filedata, filename):
        return filename.lower().endswith("." + cls.FILE_EXTENSION)
