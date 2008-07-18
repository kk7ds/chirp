#!/usr/bin/python

import chirp_common
import errors
import util
import icf

import ic2820_ll

class IC2820Radio(chirp_common.IcomMmapRadio):
    _model = "\x29\x70\x00\x01"
    _memsize = 44224
    _endframe = "Icom Inc\x2e68"

    _memories = []

    _ranges = [(0x0000, 0x6960, 32),
               (0x6960, 0x6980, 16),
               (0x6980, 0x7160, 32),
               (0x7160, 0x7180, 16),
               (0x7180, 0xACC0, 32),]

    def process_mmap(self):
        self._memories = ic2820_ll.parse_map_for_memory(self._mmap)

    def get_memory(self, number, vfo=None):
        if not self._mmap:
            self.sync_in()
        
        return self._memories[number]

    def get_memories(self, vfo=None):
        if not self._mmap:
            self.sync_in()

        return self._memories

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        self._mmap = ic2820_ll.set_memory(self._mmap, memory)

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)
        self.process_mmap()

    def sync_out(self):
        return icf.clone_to_radio(self)
