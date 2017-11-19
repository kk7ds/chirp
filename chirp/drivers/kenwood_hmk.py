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
class HMKRadio(generic_csv.CSVRadio):
    """Kenwood HMK format"""
    VENDOR = "Kenwood"
    MODEL = "HMK"
    FILE_EXTENSION = "hmk"

    DUPLEX_MAP = {
        " ":    "",
        "S":    "split",
        "+":    "+",
        "-":    "-",
    }

    SKIP_MAP = {
        "Off":  "",
        "On":   "S",
        }

    TMODE_MAP = {
        "Off":  "",
        "T":    "Tone",
        "CT":   "TSQL",
        "DCS":  "DTCS",
        "":     "Cross",
        }

    ATTR_MAP = {
        "!!Ch":          (int,   "number"),
        "M.Name":        (str,   "name"),
        "Rx Freq.":      (chirp_common.parse_freq, "freq"),
        "Shift/Split":   (lambda v: HMKRadio.DUPLEX_MAP[v], "duplex"),
        "Offset":        (chirp_common.parse_freq, "offset"),
        "T/CT/DCS":      (lambda v: HMKRadio.TMODE_MAP[v], "tmode"),
        "TO Freq.":      (float, "rtone"),
        "CT Freq.":      (float, "ctone"),
        "DCS Code":      (int,   "dtcs"),
        "Mode":          (str,   "mode"),
        "Rx Step":       (float, "tuning_step"),
        "L.Out":         (lambda v: HMKRadio.SKIP_MAP[v], "skip"),
        }

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()

        f = file(self._filename, "r")
        for line in f:
            if line.strip() == "// Memory Channels":
                break

        reader = csv.reader(f, delimiter=chirp_common.SEPCHAR, quotechar='"')

        good = 0
        lineno = 0
        for line in reader:
            lineno += 1
            if lineno == 1:
                header = line
                continue

            if len(header) > len(line):
                LOG.debug("Line %i has %i columns, expected %i" %
                          (lineno, len(line), len(header)))
                self.errors.append("Column number mismatch on line %i" %
                                   lineno)
                continue

            # hmk stores Tx Freq. in its own field, but Chirp expects the Tx
            # Freq. for odd-split channels to be in the Offset field.
            # If channel is odd-split, copy Tx Freq. field to Offset field.
            if line[header.index('Shift/Split')] == "S":
                line[header.index('Offset')] = line[header.index('Tx Freq.')]

            # fix EU decimal
            line = [i.replace(',', '.') for i in line]

            try:
                mem = self._parse_csv_data_line(header, line)
                if mem.number is None:
                    raise Exception("Invalid Location field" % lineno)
            except Exception, e:
                LOG.error("Line %i: %s" % (lineno, e))
                self.errors.append("Line %i: %s" % (lineno, e))
                continue

            self._grow(mem.number)
            self.memories[mem.number] = mem
            good += 1

        if not good:
            for e in errors:
                LOG.error("kenwood_hmk: %s", e)
            raise errors.InvalidDataError("No channels found")

    @classmethod
    def match_model(cls, filedata, filename):
        """Match files ending in .hmk"""
        return filename.lower().endswith("." + cls.FILE_EXTENSION)
