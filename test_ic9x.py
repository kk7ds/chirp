#!/usr/bin/python

import serial
import sys
from optparse import OptionParser

from repidr import ic9x, repidr_common, errors

parser = OptionParser()
parser.add_option("-s", "--serial", dest="serial",
                  default="/dev/ttyUSB0",
                  help="Serial port (default: /dev/ttyUSB0)")
parser.add_option("", "--vfo", dest="vfo",
                  default=1,
                  type="int",
                  help="VFO index (default: 1)")
parser.add_option("", "--get-mem", dest="get_mem",
                  default=False,
                  action="store_true",
                  help="Get and print memory location")
parser.add_option("", "--set-mem-name", dest="set_mem_name",
                  default=None,
                  help="Set memory name")
parser.add_option("", "--set-mem-freq", dest="set_mem_freq",
                  type="float",
                  default=None,
                  help="Set memory frequency")

(options, args) = parser.parse_args()

s = serial.Serial(port=options.serial, baudrate=38400, timeout=0.5)

radio = ic9x.IC9xRadio(s)

if options.set_mem_name or options.set_mem_freq:
    try:
        mem = radio.get_memory(int(args[0]), options.vfo)
    except errors.InvalidMemoryLocation:
        mem = repidr_common.Memory()
        mem.vfo = options.vfo
        mem.number = int(args[0])

    mem.name = options.set_mem_name or mem.name
    mem.freq = options.set_mem_freq or mem.freq
    radio.set_memory(mem)

if options.get_mem:
    try:
        mem = radio.get_memory(int(args[0]), options.vfo)
    except errors.InvalidMemoryLocation:
        mem = repidr_common.Memory()
        mem.number = int(args[0])
        mem.vfo = options.vfo
        
    print mem

