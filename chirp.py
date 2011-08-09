#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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


import serial
import sys
from optparse import OptionParser
import optparse

from chirp import util
from chirp import ic9x, id800, ic2820, ic2200, icx8x, id880, vx3, vx7, vx8
from chirp import tmv71
from chirp import chirp_common, errors, idrp, directory

def fail_unsupported():
    print "Operation not supported by selected radio"
    sys.exit(1)

def fail_missing_mmap():
    print "mmap-only operation requires specification of an mmap file"
    sys.exit(1)

RADIOS = directory.DRV_TO_RADIO

def store_tone(option, opt, value, parser):
    if value in chirp_common.TONES:
        setattr(parser.values, option.dest, value)
    else:
        raise optparse.OptionValueError("Invalid tone value: %.1f" % value)

def store_dtcs(option, opt, value, parser):
    try:
        value = int(value, 10)
    except ValueError:
        raise optparse.OptionValueError("Invalid DTCS value: %s" % value)

    if value in chirp_common.DTCS_CODES:
        setattr(parser.values, option.dest, value)
    else:
        raise optparse.OptionValueError("Invalid DTCS value: %03i" % value)

def store_dtcspol(option, opt, value, parser):
    if value not in ["NN", "RN", "NR", "RR"]:
        raise optparse.OptionValueError("Invaid DTCS polarity: %s" % value)

    setattr(parser.values, option.dest, value)
if __name__ == "__main__":
	parser = OptionParser()
	parser.add_option("-s", "--serial", dest="serial",
			  default="mmap",
			  help="Serial port (default: mmap)")

	parser.add_option("-i", "--id", dest="id",
			  default=False,
			  action="store_true",
			  help="Request radio ID string")
	parser.add_option("", "--raw", dest="raw",
			  default=False,
			  action="store_true",
			  help="Dump raw memory location")

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

	parser.add_option("", "--set-mem-tencon", dest="set_mem_tencon",
			  default=False,
			  action="store_true",
			  help="Set tone encode enabled flag")
	parser.add_option("", "--set-mem-tencoff", dest="set_mem_tencoff",
			  default=False,
			  action="store_true",
			  help="Set tone decode disabled flag")
	parser.add_option("", "--set-mem-tsqlon", dest="set_mem_tsqlon",
			  default=False,
			  action="store_true",
			  help="Set tone squelch enabled flag")
	parser.add_option("", "--set-mem-tsqloff", dest="set_mem_tsqloff",
			  default=False,
			  action="store_true",
			  help="Set tone squelch disabled flag")
	parser.add_option("", "--set-mem-dtcson", dest="set_mem_dtcson",
			  default=False,
			  action="store_true",
			  help="Set DTCS enabled flag")
	parser.add_option("", "--set-mem-dtcsoff", dest="set_mem_dtcsoff",
			  default=False,
			  action="store_true",
			  help="Set DTCS disabled flag")

	parser.add_option("", "--set-mem-tenc", dest="set_mem_tenc",
			  type="float",
			  action="callback", callback=store_tone, nargs=1,
			  help="Set memory encode tone")
	parser.add_option("", "--set-mem-tsql", dest="set_mem_tsql",
			  type="float",
			  action="callback", callback=store_tone, nargs=1,
			  help="Set memory squelch tone")
	parser.add_option("", "--set-mem-dtcs", dest="set_mem_dtcs",
			  type="string",
			  action="callback", callback=store_dtcs, nargs=1,
			  help="Set memory DTCS code")

	parser.add_option("", "--set-mem-dtcspol", dest="set_mem_dtcspol",
			  type="string",
			  action="callback", callback=store_dtcspol, nargs=1,
			  help="Set memory DTCS polarity (NN, NR, RN, RR)")

	parser.add_option("", "--set-mem-dup", dest="set_mem_dup",
			  help="Set memory duplex (+,-, or blank)")
	parser.add_option("", "--set-mem-offset", dest="set_mem_offset",
			  type="float",
			  help="Set memory duplex offset (in MHz)")

	parser.add_option("", "--set-mem-mode", dest="set_mem_mode",
			  default=None,
			  help="Set mode (%s)" % ",".join(chirp_common.MODES))
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
	if len(sys.argv) <= 1:
		parser.print_help()
		sys.exit(0)
	(options, args) = parser.parse_args()

	if options.id:
	    from chirp import icf

	    s = serial.Serial(port=options.serial,
			      baudrate=9600,
			      timeout=0.5)

	    md = icf.get_model_data(s)

	    print "Model:\n%s" % util.hexprint(md)

	    sys.exit(0)

	if not options.radio:
            if options.mmap:
                rclass = directory.get_radio_by_image(options.mmap).__class__
            else:
                print "Must specify a radio model"
                sys.exit(1)
	else:
	    rclass = RADIOS[options.radio]

	if options.serial == "mmap":
	    if options.mmap:
		s = options.mmap
	    else:
		s = options.radio + ".img"
	else:
	    print "opening %s at %i" % (options.serial, rclass.BAUD_RATE)
	    s = serial.Serial(port=options.serial,
			      baudrate=rclass.BAUD_RATE,
			      timeout=0.5)

	radio = rclass(s)

	if options.raw:
	    data = radio.get_raw_memory(int(args[0]))
            for i in data:
                if ord(i) > 0x7F:
                    print "Memory location %i (%i):\n%s" % (int(args[0]),
                                                            len(data),
                                                            util.hexprint(data))
                    sys.exit(0)
            print data
            sys.exit(0)

	if options.set_mem_dup is not None:
	    if options.set_mem_dup != "+" and \
		    options.set_mem_dup != "-" and \
		    options.set_mem_dup != "":
		print "Invalid duplex value `%s'" % options.set_mem_dup
		print "Valid values are: '+', '-', ''"
		sys.exit(1)
	    else:
		_dup = options.set_mem_dup
	else:
	    _dup = None

	if options.set_mem_mode:
	    print "Set mode: %s" % options.set_mem_mode
	    if options.set_mem_mode not in chirp_common.MODES:
		print "Invalid mode `%s'"
		sys.exit(1)
	    else:
		_mode = options.set_mem_mode
	else:
	    _mode = None

	if options.set_mem_name or options.set_mem_freq or \
		options.set_mem_tencon or options.set_mem_tencoff or \
		options.set_mem_tsqlon or options.set_mem_tsqloff or \
		options.set_mem_dtcson or options.set_mem_dtcsoff or \
		options.set_mem_tenc or options.set_mem_tsql or options.set_mem_dtcs or\
		options.set_mem_dup is not None or \
		options.set_mem_mode or options.set_mem_dtcspol or\
		options.set_mem_offset:
	    try:
		mem = radio.get_memory(int(args[0]))
	    except errors.InvalidMemoryLocation:
		mem = chirp_common.Memory()
		mem.number = int(args[0])

	    mem.name   = options.set_mem_name or mem.name
	    mem.freq   = options.set_mem_freq or mem.freq
	    mem.rtone  = options.set_mem_tenc or mem.rtone
	    mem.ctone  = options.set_mem_tsql or mem.ctone
	    mem.dtcs   = options.set_mem_dtcs or mem.dtcs
	    mem.dtcs_polarity = options.set_mem_dtcspol or mem.dtcs_polarity
	    if _dup is not None:
		mem.duplex = _dup
	    mem.offset = options.set_mem_offset or mem.offset
	    mem.mode   = _mode or mem.mode

	    if options.set_mem_tencon:
		mem.tencEnabled = True
	    elif options.set_mem_tencoff:
		mem.tencEnabled = False

	    if options.set_mem_tsqlon:
		mem.tsqlEnabled = True
	    elif options.set_mem_tsqloff:
		mem.tsqlEnabled = False

	    if options.set_mem_dtcson:
		mem.dtcsEnabled = True
	    elif options.set_mem_dtcsoff:
		mem.dtcsEnabled = False

	    radio.set_memory(mem)

	if options.get_mem:
	    try:
		pos = int(args[0])
	    except ValueError:
		pos = args[0]

	    try:
		mem = radio.get_memory(pos)
	    except errors.InvalidMemoryLocation, e:
		mem = chirp_common.Memory()
		mem.number = pos
		
	    print mem

	if options.download_mmap:
	    #isinstance(radio, chirp_common.IcomMmapRadio) or fail_unsupported()
	    radio.sync_in()
	    radio.save_mmap(options.mmap)

	if options.upload_mmap:
	    #isinstance(radio, chirp_common.IcomMmapRadio) or fail_unsupported()
	    radio.load_mmap(options.mmap)
	    if radio.sync_out():
		print "Clone successful"
	    else:
		print "Clone failed"

	if options.mmap and isinstance(radio, chirp_common.CloneModeRadio):
	    radio.save_mmap(options.mmap)
	    
