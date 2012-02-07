# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import struct

def hexprint(data):
    line_sz = 8

    lines = len(data) / line_sz
    
    if (len(data) % line_sz) != 0:
        lines += 1
        data += "\x00" * ((lines * line_sz) - len(data))

    out = ""
        
    for i in range(0, (len(data)/line_sz)):
        out += "%03i: " % (i * line_sz)

        left = len(data) - (i * line_sz)
        if left < line_sz:
            limit = left
        else:
            limit = line_sz
            
        for j in range(0, limit):
            out += "%02x " % ord(data[(i * line_sz) + j])

        out += "  "

        for j in range(0, limit):
            char = data[(i * line_sz) + j]

            if ord(char) > 0x20 and ord(char) < 0x7E:
                out += "%s" % char
            else:
                out += "."

        out += "\n"

    return out

def write_in_place(mem, start, data):
    return mem[:start] + data + mem[start+len(data):]

def bcd_encode(val, bigendian=True, width=None):
    digits = []
    while val != 0:
        digits.append(val % 10)
        val /= 10

    result = ""

    if len(digits) % 2 != 0:
        digits.append(0)

    while width and width > len(digits):
        digits.append(0)

    for i in range(0, len(digits), 2):
        newval = struct.pack("B", (digits[i+1] << 4) | digits[i])
        if bigendian:
            result =  newval + result
        else:
            result = result + newval
    
    return result

def get_dict_rev(dict, key):
    _dict = {}
    for k,v in dict.items():
        _dict[v] = k
    return _dict[key]
