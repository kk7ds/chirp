#!/usr/bin/python

import util

class MemoryMap:
    """
    A pythonic memory map interface
    """

    def __init__(self, data):
        self._data = list(data)

    def printable(self, start=None, end=None, printToStdio=True):
        if not start:
            start = 0

        if not end:
            end = len(self._data)

        s = util.hexprint(self._data[start:end])

        if printToStdio:
            print s

        return s

    def get(self, start, length=1):
        if start == -1:
            return "".join(self._data[start:])
        else:
            return "".join(self._data[start:start+length])

    def set(self, pos, value):
        if isinstance(value, int):
            self._data[pos] = chr(value)
        elif isinstance(value, str):
            for byte in value:
                self._data[pos] = byte
                pos += 1
        else:
            raise ValueError("Unsupported type %s for value" % \
                                 type(value).__name__)

    def get_packed(self):
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
        return self.printable(printToStdio=False)

if __name__ == "__main__":
    m = MemoryMap("\x00" * 32)

    m.printable()

    m[8] = "\x21\x22\x23"

    m.printable()

    print util.hexprint(m[8:11])

    print util.hexprint(m.get_packed())

    m[-4] = "abcd"

    m.printable()

    print m[-4:]

    print util.hexprint(m[-2:])
