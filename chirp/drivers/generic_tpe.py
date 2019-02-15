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

try:
    import UserDict
except ImportError:
    from collections import UserDict
from chirp import chirp_common, directory
from chirp.drivers import generic_csv


@directory.register
class TpeRadio(generic_csv.CSVRadio):
    """Generic ARRL Travel Plus"""
    VENDOR = "ARRL"
    MODEL = "Travel Plus"
    FILE_EXTENSION = "tpe"

    ATTR_MAP = {
        "Sequence Number":  (int, "number"),
        "Location":         (str, "comment"),
        "Call Sign":        (str, "name"),
        "Output Frequency": (chirp_common.parse_freq, "freq"),
        "Input Frequency":  (str, "duplex"),
        "CTCSS Tones":      (lambda v: float(v)
                             if v and float(v) in chirp_common.TONES
                             else 88.5, "rtone"),
        "Repeater Notes":   (str, "comment"),
    }

    def _clean_tmode(self, headers, line, mem):
        try:
            val = generic_csv.get_datum_by_header(headers, line, "CTCSS Tones")
            if val and float(val) in chirp_common.TONES:
                mem.tmode = "Tone"
        except generic_csv.OmittedHeaderError:
            pass

        return mem

    def _clean_ctone(self, headers, line, mem):
        # TPE only stores a single tone value
        mem.ctone = mem.rtone
        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        return filename.lower().endswith("." + cls.FILE_EXTENSION)
