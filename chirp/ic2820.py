#!/usr/bin/python

import chirp_common
import errors
import util

import ic2820_ll

class IC2820Radio(chirp_common.IcomMmapRadio):
    _model = "\x29\x70\x00\x01"
    _memsize = 44224

    _memories = []

    def process_mmap(self):
        self._memories = ic2820_ll.parse_map_for_memory(self._mmap)

    def _fetch_mmap(self):
        self._mmap = ic2820_ll.get_memory_map(self)
        self.process_mmap()

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
        return ic2820_ll.clone_to_radio(self)
