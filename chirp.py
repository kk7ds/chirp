#!/usr/bin/python

import serial
import sys
from optparse import OptionParser

from chirp import ic9x, id800, ic2820, chirp_common, errors

def fail_unsupported():
    print "Operation not supported by selected radio"
    sys.exit(1)

def fail_missing_mmap():
    print "mmap-only operation requires specification of an mmap file"
    sys.exit(1)

RADIOS = { "ic9x"  : ic9x.IC9xRadio,
           "id800" : id800.ID800v2Radio,
           "ic2820": ic2820.IC2820Radio,
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

parser.add_option("", "--mmap", dest="mmap",
                  default=None,
                  help="Radio memory map file location")
parser.add_option("", "--download-mmap", dest="download_mmap",
                  action="store_true",
                  default=False,
                  help="Download memory map from radio")
parser.add_option("", "--upload-mmap", dest="upload_mmap",
                  action="store_true",
                  default=False,
                  help="Upload memory map to radio")

(options, args) = parser.parse_args()

if not options.radio:
    print "Must specify a radio model"
    sys.exit(1)
else:
    rclass = RADIOS[options.radio]

if options.serial == "mmap":
    if options.mmap:
        s = options.mmap
    else:
        fail_missing_mmap()
else:
    s = serial.Serial(port=options.serial,
                      baudrate=rclass.BAUD_RATE,
                      timeout=0.5)

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
        mem = chirp_common.Memory()
        mem.number = int(args[0])
        mem.vfo = options.vfo
        
    print mem

if options.download_mmap:
    isinstance(radio, chirp_common.IcomMmapRadio) or fail_unsupported()
    radio.sync_in()
    radio.save_mmap(options.mmap)

if options.upload_mmap:
    isinstance(radio, chirp_common.IcomMmapRadio) or fail_unsupported()
    radio.load_mmap(options.mmap)
    if radio.sync_out():
        print "Clone successful"
    else:
        print "Clone failed"

if options.mmap and isinstance(radio, chirp_common.IcomMmapRadio):
    radio.save_mmap(options.mmap)
    
