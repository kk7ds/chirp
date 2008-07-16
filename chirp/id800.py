#!/usr/bin/python

import chirp_common
import errors
import util

import id800_ll

class ID800v2Radio(chirp_common.IcomMmapRadio):
    BAUD_RATE = 9600

    _model = "\x27\x88\x02\x00"

    _mmap = None
    _memories = []

    def load_mmap(self, filename):
        f = file(filename, "rb")
        self._mmap = f.read()
        f.close()

        self._memories = id800_ll.parse_map_for_memory(self._mmap)

    def save_mmap(self, filename):
        f = file(filename, "wb")
        f.write(self._mmap)
        f.close()

    def _fetch_mmap(self):
        self._mmap = id800_ll.get_memory_map(self.pipe)
        self._memories = id800_ll.parse_map_for_memory(self._mmap)

    def get_memory(self, number, vfo=None):
        if not self._mmap:
            self._fetch_mmap()
        
        return self._memories[number]

    def get_memories(self, vfo=None):
        if not self._mmap:
            self._fetch_mmap()

        return self._memories

    def sync_in(self):
        self._fetch_mmap()

    def sync_out(self):
        id800_ll.clone_to_radio(self.pipe, self._model, self._mmap)

if __name__ == "__main__":
    import serial

    s = serial.Serial(port="/dev/ttyUSB1",
                      baudrate=9600,
                      timeout=1)

    r = ID800v2Radio(s)
    r.get_memories()

    f = file("id800.mmap", "wb")
    f.write(r._mmap)
    f.close()
