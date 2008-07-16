class IcomFrame:
    pass

class Memory:
    freq = 0.0
    number = 0
    name = ""
    vfo = 0

    def __str__(self):
        return "Memory %i: %.2f (%s) [VFO=%i]" % (self.number,
                                                  self.freq,
                                                  self.name,
                                                  self.vfo)

class Bank:
    name = "BANK"
    vfo = 0

class IcomRadio:
    BAUD_RATE = 9600

    def __init__(self, pipe):
        self.pipe = pipe

    def get_memory(self, number, vfo=None):
        pass

    def get_memories(self, vfo=None):
        pass

    def set_memory(self, memory):
        pass

    def set_memories(self, memories):
        pass

    def get_banks(self, vfo=None):
        pass

    def set_banks(self, vfo=None):
        pass

    
class IcomMmapRadio(IcomRadio):
    def load_mmap(self, filename):
        pass

    def save_mmap(self, filename):
        pass

    def sync_in(self):
        pass

    def sync_out(self):
        pass
