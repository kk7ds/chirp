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

def console_status(status):
    import sys

    sys.stderr.write("\r%s" % status)
    

class IcomRadio:
    BAUD_RATE = 9600

    status_fn = lambda x,y: console_status(y)

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
    BAUDRATE = 9600

    _model = "\x00\x00\x00\x00"
    _memsize = 0
    _mmap = None

    def __init__(self, pipe):

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        else:
            IcomRadio.__init__(self, pipe)

    def load_mmap(self, filename):
        f = file(filename, "rb")
        self._mmap = f.read()
        f.close()

        self.process_mmap()

    def save_mmap(self, filename):
        f = file(filename, "wb")
        f.write(self._mmap)
        f.close()

    def sync_in(self):
        pass

    def sync_out(self):
        pass

    def process_mmap(self):
        pass

class Status:
    name = "Job"
    msg = "Unknown"
    max = 100
    cur = 0

    def __str__(self):
        try:
            pct = (self.cur / float(self.max)) * 100
            nticks = int(pct) / 10
            ticks = "=" * nticks
        except ValueError:
            pct = 0.0
            ticks = "?" * 10

        return "|%-10s| %2.1f%% %s" % (ticks, pct, self.msg)

if __name__ == "__main__":
    s = Status()
    s.msg = "Cloning"
    s.max = 1234
    s.cur = 172

    print s
