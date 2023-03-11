# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import csv
import logging

from chirp import chirp_common, errors, directory
from chirp.drivers import generic_csv

LOG = logging.getLogger(__name__)


class OmittedHeaderError(Exception):
    """An internal exception to indicate that a header was omitted"""
    pass


@directory.register
class ITMRadio(generic_csv.CSVRadio):
    """Kenwood ITM format"""
    VENDOR = "Kenwood"
    MODEL = "ITM"
    FILE_EXTENSION = "itm"

    ATTR_MAP = {
        "CH":            (int,  "number"),
        "RXF":           (chirp_common.parse_freq, "freq"),
        "NAME":          (str,  "name"),
        }

    def _clean_duplex(self, headers, line, mem):
        try:
            txfreq = chirp_common.parse_freq(
                        generic_csv.get_datum_by_header(headers, line, "TXF"))
        except ValueError:
            mem.duplex = "off"
            return mem

        if mem.freq == txfreq:
            mem.duplex = ""
        elif txfreq:
            mem.duplex = "split"
            mem.offset = txfreq

        return mem

    def _clean_number(self, headers, line, mem):
        zone = int(generic_csv.get_datum_by_header(headers, line, "ZN"))
        mem.number = zone * 100 + mem.number
        return mem

    def _clean_tmode(self, headers, line, mem):
        rtone = eval(generic_csv.get_datum_by_header(headers, line, "TXSIG"))
        ctone = eval(generic_csv.get_datum_by_header(headers, line, "RXSIG"))

        if rtone:
            mem.tmode = "Tone"
        if ctone:
            mem.tmode = "TSQL"

        mem.rtone = rtone or 88.5
        mem.ctone = ctone or mem.rtone

        return mem

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()

        f = open(self._filename, "r")
        for line in f:
            if line.strip() == "// Conventional Data":
                break

        reader = csv.reader(f, delimiter=chirp_common.SEPCHAR, quotechar='"')

        good = 0
        lineno = 0
        for line in reader:
            lineno += 1
            if lineno == 1:
                header = line
                continue

            if len(line) == 0:
                # End of channel data
                break

            if len(header) > len(line):
                LOG.error("Line %i has %i columns, expected %i" %
                          (lineno, len(line), len(header)))
                self.errors.append("Column number mismatch on line %i" %
                                   lineno)
                continue

            # fix EU decimal
            line = [i.replace(',', '.') for i in line]

            try:
                mem = self._parse_csv_data_line(header, line)
                if mem.number is None:
                    raise Exception("Invalid Location field" % lineno)
            except Exception as e:
                LOG.error("Line %i: %s" % (lineno, e))
                self.errors.append("Line %i: %s" % (lineno, e))
                continue

            self._grow(mem.number)
            self.memories[mem.number] = mem
            good += 1

        if not good:
            for e in errors:
                LOG.error("kenwood_itm: %s", e)
            raise errors.InvalidDataError("No channels found")

    @classmethod
    def match_model(cls, filedata, filename):
        return filename.lower().endswith("." + cls.FILE_EXTENSION)
