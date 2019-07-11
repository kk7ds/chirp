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

from chirp import util


class MemoryMap:
    """
    A pythonic memory map interface
    """

    def __init__(self, data):
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
        if start == -1:
            return "".join(self._data[start:])
        else:
            return "".join(self._data[start:start+length])

    def set(self, pos, value):
        """Set a chunk of memory at @pos to @value"""
        if isinstance(value, int):
            self._data[pos] = chr(value)
        elif isinstance(value, str):
            for byte in value:
                self._data[pos] = byte
                pos += 1
        else:
            raise ValueError("Unsupported type %s for value" %
                             type(value).__name__)

    def get_packed(self):
        """Return the entire memory map as raw data"""
        return "".join(self._data)

    def __len__(self):
        return len(self._data)

    def __getslice__(self, start, end):
        return self.get(start, end-start)

    def __getitem__(self, pos):
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


# Py3 branch compatibility
class MemoryMapBytes(MemoryMap):
    def __init__(self, data):
        # Expects data is a newbytes
        MemoryMap.__init__(self, ''.join(chr(b) for b in data))
