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
from chirp.pyPEG import keyword, parseLine

TYPES = ["u8", "u16", "ul16", "u24", "ul24", "u32", "ul32", "char",
         "lbcd", "bbcd"]
DIRECTIVES = ["seekto", "seek", "printoffset"]

def string():
    return re.compile(r"\"[^\"]*\"")

def symbol():
    return re.compile(r"\w+")

def count():
    return re.compile(r"([1-9][0-9]*|0x[0-9a-fA-F]+)")

def bitdef():
    return symbol, ":", count, -1

def _bitdeflist():
    return bitdef, -1, (",", bitdef)

def bitfield():
    return -2, _bitdeflist

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
    return -2, [definition, struct, directive]

def _block():
    return "{", _block_inner, "}"

def struct_defn():
    return symbol, _block

def struct_decl():
    return [symbol, _block], [array, symbol]

def struct():
    return keyword("struct"), [struct_defn, struct_decl], ";"

def _language():
    return _block_inner

def parse(data):
    return parseLine(data, _language, resultSoFar=[]) 
