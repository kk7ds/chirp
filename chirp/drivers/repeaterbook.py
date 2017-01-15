# Copyright 2016 Tom Hayward <tom@tomh.us>
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

from chirp import chirp_common
from chirp.drivers import generic_csv


class RBRadio(generic_csv.CSVRadio, chirp_common.NetworkSourceRadio):
    VENDOR = "RepeaterBook"
    MODEL = ""

    def _clean_comment(self, headers, line, mem):
        "Converts iso-8859-1 encoded comments to unicode for pyGTK."
        mem.comment = unicode(mem.comment, 'iso-8859-1')
        return mem

    def _clean_name(self, headers, line, mem):
        "Converts iso-8859-1 encoded names to unicode for pyGTK."
        mem.name = unicode(mem.name, 'iso-8859-1')
        return mem
