import os

from chirp import chirp_common, errors

class CSVRadio(chirp_common.IcomFileBackedRadio):
    def __init__(self, pipe):
        chirp_common.IcomFileBackedRadio.__init__(self, None)

        self.memories = []

        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.load()
            
    def _parse_csv_line(self, line):
        line = line.replace("\n", "")
        line = line.replace("\r", "")

        mem = chirp_common.Memory.from_csv(line)
        if mem:
            self.memories.append(mem)

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self.memories = []
        f = file(self._filename, "rU")
        
        lines = f.readlines()

        i = 0
        for line in lines:
            i += 1
            try:
                self._parse_csv_line(line)
            except errors.InvalidMemoryLocation:
                print "Invalid memory location on line %i" % i

        f.close()
    
    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        f = file(self._filename, "w")

        for mem in self.memories:
            f.write(mem.to_csv() + os.linesep)

        f.close()

    def get_memories(self, lo=0, hi=999):
        return [x for x in self.memories if x.number >= low and x.number <= hi]

    def get_memory(self, number):
        for mem in self.memories:
            if mem.number == number:
                return mem

        raise errors.InvalidMemoryLocation("No such memory")

    def set_memory(self, newmem):
        self.erase_memory(newmem.number)
        self.memories.append(newmem)

    def erase_memory(self, number):
        newlist = []
        for mem in self.memories:
            if mem.number != number:
                newlist.append(mem)
        self.memories = newlist
        
