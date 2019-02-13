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

import six
import struct


def hexprint(data, addrfmt=None):
    """Return a hexdump-like encoding of @data"""
    if addrfmt is None:
        addrfmt = '%(addr)03i'

    block_size = 8

    lines = len(data) // block_size

    if six.PY3 and isinstance(data, bytes):
        pad = bytes([0])
    else:
        pad = '\x00'

    if (len(data) % block_size) != 0:
        lines += 1
        data += pad * ((lines * block_size) - len(data))

    out = ""

    if six.PY3 and isinstance(data, bytes):
        byte_to_int = lambda b: b
    else:
        byte_to_int = ord

    for block in range(0, (len(data) // block_size)):
        addr = block * block_size
        try:
            out += addrfmt % locals()
        except (OverflowError, ValueError, TypeError, KeyError):
            out += "%03i" % addr
        out += ': '

        left = len(data) - (block * block_size)
        if left < block_size:
            limit = left
        else:
            limit = block_size

        for j in range(0, limit):
            byte = data[(block * block_size) + j]
            if isinstance(byte, str):
                byte = ord(byte)
            out += "%02x " % byte

        out += "  "

        for j in range(0, limit):
            byte = data[(block * block_size) + j]
            if isinstance(byte, str):
                byte = ord(byte)
            if byte > 0x20 and byte < 0x7E:
                out += "%s" % chr(byte)
            else:
                out += "."

        out += "\n"

    return out


def bcd_encode(val, bigendian=True, width=None):
    """This is really old and shouldn't be used anymore"""
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
        newval = struct.pack("B", (digits[i + 1] << 4) | digits[i])
        if bigendian:
            result = newval + result
        else:
            result = result + newval

    return result


def get_dict_rev(thedict, value):
    """Return the first matching key for a given @value in @dict"""
    _dict = {}
    for k, v in thedict.items():
        _dict[v] = k
    return _dict[value]


def safe_charset_string(indexes, charset, safechar=" "):
    """Return a string from an array of charset indexes,
    replaces out of charset values with safechar"""
    assert safechar in charset
    _string = ""
    for i in indexes:
        try:
            _string += charset[i]
        except IndexError:
            _string += safechar
    return _string


class StringStruct(object):
    """String-compatible struct module."""
    @staticmethod
    def pack(*args):
        from chirp import bitwise
        fmt = args[0]
        # Encode any string arguments to bytes
        newargs = (bitwise.string_straight_encode(x) if isinstance(x, str)
                   else x
                   for x in args[1:])
        return bitwise.string_straight_decode(struct.pack(fmt, *newargs))

    @staticmethod
    def unpack(fmt, data):
        from chirp import bitwise
        result = struct.unpack(fmt, bitwise.string_straight_encode(data))
        # Decode any string results
        return tuple(bitwise.string_straight_decode(x) if isinstance(x, bytes)
                     else x
                     for x in result)
