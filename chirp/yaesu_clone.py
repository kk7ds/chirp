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

def clone_in(radio):
    pipe = radio.pipe

    block1 = ""
    block2 = ""
    block3 = ""

    for i in range(0, 60):
        block1 += pipe.read(10 - len(block1))
        #print "Got %i:\n%s" % (len(block1), util.hexprint(block1))
        if len(block1) == 10:
            break
    if len(block1) != 10:
        raise Exception("Timeout waiting for clone start")
    #print "Got first block"

    pipe.write(chr(CMD_ACK))
    pipe.read(1) # Chew the ack

    for i in range(0, 10):
        block2 += pipe.read(8 - len(block2))
        #print "Got %i:\n%s" % (len(block2), util.hexprint(block2))
        if len(block2) == 8:
            break
    if len(block2) != 8:
        raise Exception("Timeout waiting for second block")
    #print "Got second block"

    pipe.write(chr(CMD_ACK))
    pipe.read(1) # Chew the ack

    total = 16193
    count = 0
    while count < total:
        chunk = pipe.read(32)
        #print "Got %i: %s" % (len(chunk), util.hexprint(chunk))
        block3 += chunk
        count += len(chunk)

        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = total
        status.cur = count
        radio.status_fn(status)

    return memmap.MemoryMap(block1 + block2 + block3)

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

    pipe.write(radio._mmap[:l[0]])
    pipe.read(l[0]) # Chew the first block

    ack = pipe.read(1)
    print "Ack1: %02x" % ord(ack)
    if ord(ack) != CMD_ACK:
        raise Exception("Radio did not respond (1)")
    total_written += l[0]
    status()

    pipe.write(radio._mmap[l[0]:l[0]+l[1]])
    pipe.read(l[1]) # Chew the second block
               
    ack = pipe.read(1)
    print "Ack2: %02x" % ord(ack)
    if ord(ack) != CMD_ACK:
        raise Exception("Radio did not respond (2)")
    total_written += l[1]
    status()

    base = l[0] + l[1]
    block = 8
    for i in range(0, l[2], block):
        chunk = radio._mmap[base+i:base+i+block]
        #print "Writing (%i@%i):\n%s" % (len(chunk), base+i,
        #                                util.hexprint(chunk))
        time.sleep(0.01) # Sucks, but we have no flow control!
        pipe.write(chunk)
        pipe.flush()
        crap = pipe.read(block)
        total_written += block
        status()
