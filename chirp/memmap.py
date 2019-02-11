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

from builtins import bytes

import six

from chirp import util


class MemoryMapBytes(object):
    """
    This is the proper way for MemoryMap to work, which is
    in terms of bytes always.
    """

    def __init__(self, data):
        assert isinstance(data, bytes)

        self._data = list(data)

    def printable(self, start=None, end=None):
        """Return a printable representation of the memory map"""
        if not start:
            start = 0

        if not end:
            end = len(self._data)

        string = util.hexprint(self._data[start:end])

        return string

    def get(self, start, length=1):
        """Return a chunk of memory of @length bytes from @start"""
        if length == -1:
            return bytes(self._data[start:])
        else:
            end = start + length
            d = self._data[start:end]
            return bytes(d)

    def set(self, pos, value):
        """Set a chunk of memory at @pos to @value"""

        pos = int(pos)

        if isinstance(value, int):
            self._data[pos] = value & 0xFF
        elif isinstance(value, bytes):
            for byte in bytes(value):
                self._data[pos] = byte
                pos += 1
        elif isinstance(value, str):
            if six.PY3:
                value = value.encode()
            for byte in value:
                self._data[pos] = ord(byte)
                pos += 1
        else:
            raise ValueError("Unsupported type %s for value" %
                             type(value).__name__)

    def get_packed(self):
        """Return the entire memory map as raw data"""
        return bytes(self._data)

    def __len__(self):
        return len(self._data)

    def __getslice__(self, start, end):
        return self.get(start, end-start)

    def __getitem__(self, pos):
        if isinstance(pos, slice):
            if pos.stop is None:
                return self.get(pos.start, -1)

            return self.get(pos.start, pos.stop - pos.start)
        else:
            return self.get(pos)

    def __setitem__(self, pos, value):
        """
        NB: Setting a value of more than one character overwrites
        len(value) bytes of the map, unlike a typical array!
        """
        self.set(pos, value)

    def __str__(self):
        return self.get_packed()

    def __repr__(self):
        return self.printable(printit=False)

    def truncate(self, size):
        """Truncate the memory map to @size"""
        self._data = self._data[:size]

    def get_byte_compatible(self):
        return self


class MemoryMap(MemoryMapBytes):
    """Compatibility version of MemoryMapBytes

    This deals in strings for compatibility with drivers that do.
    """
    def __init__(self, data):
        # Fix circular dependency
        from chirp import bitwise
        self._bitwise = bitwise

        if six.PY3 and isinstance(data, bytes):
            # Be graceful if py3-enabled code uses this,
            # just don't encode it
            encode = lambda d: d
        else:
            encode = self._bitwise.string_straight_encode
        super(MemoryMap, self).__init__(encode(data))

    def get(self, pos, length=1):
        return self._bitwise.string_straight_decode(
            super(MemoryMap, self).get(pos, length=length))

    def set(self, pos, value):
        if isinstance(value, int):
            # Apparently this is a thing that drivers do, so
            # be compatible here
            value = chr(value)
        super(MemoryMap, self).set(
            pos, self._bitwise.string_straight_encode(value))

    def get_packed(self):
        return self._bitwise.string_straight_decode(
            super(MemoryMap, self).get_packed())

    def get_byte_compatible(self):
        mmb = MemoryMapBytes(bytes(self._data))
        self._data = mmb._data
        return mmb
