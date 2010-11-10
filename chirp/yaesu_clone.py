#!/usr/bin/python
#
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

from chirp import chirp_common, util, memmap
import time

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
    return data        

def clone_in(radio):
    pipe = radio.pipe

    start = time.time()

    data = ""
    blocks = 0
    for block in radio._block_lengths:
        blocks += 1
        if blocks == len(radio._block_lengths):
            data += chunk_read(pipe, block, radio.status_fn)
        else:
            data += safe_read(pipe, block)
            pipe.write(chr(CMD_ACK))

    print "Clone completed in %i seconds" % (time.time() - start)

    return memmap.MemoryMap(data)

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
        
def clone_out(radio):
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

class YaesuCloneModeRadio(chirp_common.CloneModeRadio):
    _block_lengths = [8, 65536]
    _block_size = 8

    def _update_checksum(self):
        pass

    def sync_in(self):
        self._mmap = clone_in(self)
        self.process_mmap()

    def sync_out(self):
        self._update_checksum()
        clone_out(self)

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

    
