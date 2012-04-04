# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

CMD_ACK = 0x06

from chirp import chirp_common, util, memmap, errors
import time, os

def safe_read(pipe, count, times=60):
    buf = ""
    first = True
    for i in range(0, 60):
        buf += pipe.read(count - len(buf))
        #print "safe_read: %i/%i\n" % (len(buf), count)
        if buf:
            if first and buf[0] == chr(CMD_ACK):
                #print "Chewed an ack"
                buf = buf[1:] # Chew an echo'd ack if using a 2-pin cable
            first = False
        if len(buf) == count:
            break
    print util.hexprint(buf)
    return buf

def chunk_read(pipe, count, status_fn):
    block = 32
    data = ""
    first = True
    for i in range(0, count, block):
        data += pipe.read(block)
        if data:
            if data[0] == chr(CMD_ACK):
                data = data[1:] # Chew an echo'd ack if using a 2-pin cable
                #print "Chewed an ack"
            first = False
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = count
        status.cur = len(data)
        status_fn(status)
        if os.getenv("CHIRP_DEBUG"):
            print "Read %i/%i" % (len(data), count)
    return data        

def _clone_in(radio):
    pipe = radio.pipe

    start = time.time()

    data = ""
    blocks = 0
    for block in radio._block_lengths:
        blocks += 1
        if blocks == len(radio._block_lengths):
            chunk = chunk_read(pipe, block, radio.status_fn)
        else:
            chunk = safe_read(pipe, block)
            pipe.write(chr(CMD_ACK))
        if not chunk:
            raise errors.RadioError("No response from radio")
        data += chunk

    if len(data) != radio._memsize:
        raise errors.RadioError("Received incomplete image from radio")

    print "Clone completed in %i seconds" % (time.time() - start)

    return memmap.MemoryMap(data)

def clone_in(radio):
    try:
        return _clone_in(radio)
    except Exception, e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)

def chunk_write(pipe, data, status_fn, block):
    delay = 0.03
    count = 0
    for i in range(0, len(data), block):
        chunk = data[i:i+block]
        pipe.write(chunk)
        count += len(chunk)
        #print "Count is %i" % count
        time.sleep(delay)

        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = len(data)
        status.cur = count
        status_fn(status)
        
def _clone_out(radio):
    pipe = radio.pipe
    l = radio._block_lengths
    total_written = 0

    def status():
        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = l[0] + l[1] + l[2]
        status.cur = total_written
        radio.status_fn(status)

    start = time.time()

    blocks = 0
    pos = 0
    for block in radio._block_lengths:
        blocks += 1
        if blocks != len(radio._block_lengths):
            #print "Sending %i-%i" % (pos, pos+block)
            pipe.write(radio._mmap[pos:pos+block])
            buf = pipe.read(1)
            if buf and buf[0] != chr(CMD_ACK):
                buf = pipe.read(block)
            if not buf or buf[-1] != chr(CMD_ACK):
                raise Exception("Radio did not ack block %i" % blocks)
        else:
            chunk_write(pipe, radio._mmap[pos:],
                        radio.status_fn, radio._block_size)
        pos += block

    pipe.read(pos) # Chew the echo if using a 2-pin cable

    print "Clone completed in %i seconds" % (time.time() - start)

def clone_out(radio):
    try:
        return _clone_out(radio)
    except Exception, e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)

class YaesuChecksum:
    def __init__(self, start, stop, address=None):
        self._start = start
        self._stop = stop
        if address:
            self._address = address
        else:
            self._address = stop + 1

    def get_existing(self, mmap):
        """Return the existing checksum in mmap"""
        return ord(mmap[self._address])

    def get_calculated(self, mmap):
        cs = 0
        for i in range(self._start, self._stop+1):
            cs += ord(mmap[i])
        return cs % 256

    def update(self, mmap):
        mmap[self._address] = self.get_calculated(mmap)

    def __str__(self):
        return "%04X-%04X (@%04X)" % (self._start,
                                      self._stop,
                                      self._address)

class YaesuCloneModeRadio(chirp_common.CloneModeRadio):
    _block_lengths = [8, 65536]
    _block_size = 8

    VENDOR = "Yaesu"
    _model = "ABCDE"

    def _checksums(self):
        """Return a list of checksum objects that need to be calculated"""
        return []

    def update_checksums(self):
        for checksum in self._checksums():
            checksum.update(self._mmap)

    def check_checksums(self):
        for checksum in self._checksums():
            if checksum.get_existing(self._mmap) != \
                    checksum.get_calculated(self._mmap):
                raise errors.RadioError("Checksum Failed [%s]" % checksum)
            print "Checksum %s: OK" % checksum

    def sync_in(self):
        self._mmap = clone_in(self)
        self.check_checksums()
        self.process_mmap()

    def sync_out(self):
        self.update_checksums()
        clone_out(self)

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata[:5] == cls._model

    def _wipe_memory_banks(self, mem):
        """Remove @mem from all the banks it is currently in"""
        bm = self.get_bank_model()
        for bank in bm.get_memory_banks(mem):
            bm.remove_memory_from_bank(mem, bank)


if __name__ == "__main__":
    import sys, serial
    s = serial.Serial(port=sys.argv[1], baudrate=19200, timeout=5)

    d = s.read(20)
    print util.hexprint(d)

    s.write(chr(0x06))

    d = ""
    while True:
        c = s.read(32)
        if not c:
            break
        d += c

    print len(d)

    
