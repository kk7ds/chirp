#!/usr/bin/python

import serial
import sys
from optparse import OptionParser

from chirp import ic9x, id800, chirp_common, errors

RADIOS = { "ic9x"  : ic9x.IC9xRadio,
           "id800" : id800.ID800v2Radio,
}

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
parser.add_option("-r", "--radio", dest="radio",
                  default=None,
                  help="Radio model (one of %s)" % ",".join(RADIOS.keys()))

(options, args) = parser.parse_args()

if not options.radio:
    print "Must specify a radio model"
    sys.exit(1)
else:
    rclass = RADIOS[options.radio]

s = serial.Serial(port=options.serial, baudrate=rclass.BAUD_RATE, timeout=0.5)

radio = rclass(s)

if options.set_mem_name or options.set_mem_freq:
    try:
        mem = radio.get_memory(int(args[0]), options.vfo)
    except errors.InvalidMemoryLocation:
        mem = chirp_common.Memory()
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

