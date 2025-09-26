# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

import re
from chirp.pyPEG import keyword, parse as pypeg_parse

TYPES = ["bit", "lbit", "u8", "u16", "ul16", "u24", "ul24", "u32", "ul32",
         "i8", "i16", "il16", "i24", "il24", "i32", "il32", "char",
         "lbcd", "bbcd"]
DIRECTIVES = ["seekto", "seek", "printoffset"]


def string():
    return re.compile(r"\"[^\"]*\"")


def symbol():
    return re.compile(r"\w+")


def count():
    return re.compile(r"([1-9][0-9]*|0x[0-9a-fA-F]+)")


def bitdef():
    return symbol, ":", count


def _bitdeflist():
    return bitdef, -1, (",", bitdef)


def bitfield():
    return _bitdeflist


def array():
    return symbol, '[', count, ']'


def _typedef():
    return re.compile(r"(%s)" % "|".join(TYPES))


def definition():
    return _typedef, [array, bitfield, symbol], ";"


def seekto():
    return keyword("seekto"), count


def seek():
    return keyword("seek"), count


def printoffset():
    return keyword("printoffset"), string


def directive():
    return "#", [seekto, seek, printoffset], ";"


def _block_inner():
    return -2, [definition, struct, union, directive]


def _block():
    return "{", _block_inner, "}"


def struct_defn():
    return symbol, _block


def struct_decl():
    return [symbol, _block], [array, symbol]


def struct():
    return keyword("struct"), [struct_defn, struct_decl], ";"


def union():
    return keyword("union"), _block, [array, symbol], ";"


def _language():
    return _block_inner


def parse(data):
    lines = data.split("\n")
    for index, line in enumerate(lines):
        if '//' in line:
            lines[index] = line[:line.index('//')]

    class FakeFileInput(object):
        """Simulate line-by-line file reading from @data"""
        line = -1

        def isfirstline(self):
            return self.line == 0

        def filename(self):
            return "input"

        def lineno(self):
            return self.line

        def __iter__(self):
            return self

        def __next__(self):
            self.line += 1
            try:
                # Note, FileInput objects keep the newlines
                return lines[self.line] + "\n"
            except IndexError:
                raise StopIteration

    return pypeg_parse(_language, FakeFileInput())
