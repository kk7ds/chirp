#!/usr/bin/env python
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
import os
import sys
import argparse
import logging

from chirp import logger
from chirp import chirp_common, errors, directory, util

directory.import_drivers()

LOG = logging.getLogger("chirpc")
RADIOS = directory.DRV_TO_RADIO


def fail_unsupported():
    LOG.error("Operation not supported by selected radio")
    sys.exit(1)


def fail_missing_mmap():
    LOG.error("mmap-only operation requires specification of an mmap file")
    sys.exit(1)


class ToneAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        value = values[0]
        if value not in chirp_common.TONES:
            raise argparse.ArgumentError(
                self, "Invalid tone value: %.1f" % value)
        setattr(namespace, self.dest, value)


class DTCSAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        value = values[0]
        if value not in chirp_common.DTCS_CODES:
            raise argparse.ArgumentError(
                self, "Invalid DTCS value: %03i" % value)
        setattr(namespace, self.dest, value)


class DTCSPolarityAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        value = values[0]
        if value not in ["NN", "RN", "NR", "RR"]:
            raise argparse.ArgumentError(
                self, "Invalid DTCS polarity: %s" % value)
        setattr(namespace, self.dest, value)


def parse_memory_number(radio, args):
    if len(args) < 1:
        LOG.error("You must provide an argument specifying the memory number.")
        sys.exit(1)

    try:
        memnum = int(args[0])
    except ValueError:
        memnum = args[0]

    rf = radio.get_features()
    start, end = rf.memory_bounds
    if not (start <= memnum <= end or memnum in rf.valid_special_chans):
        if len(rf.valid_special_chans) > 0:
            LOG.error(
                "memory number must be between %d and %d or one of %s"
                " (got %s)",
                start, end, ", ".join(rf.valid_special_chans), memnum)
        else:
            LOG.error("memory number must be between %d and %d (got %s)",
                      start, end, memnum)
        sys.exit(1)
    return memnum


def main(args=None):
    parser = argparse.ArgumentParser()
    logger.add_version_argument(parser)
    parser.add_argument("-s", "--serial", dest="serial",
                        default="mmap",
                        help="Serial port (default: mmap)")

    parser.add_argument("--list-settings", action="store_true",
                        help="List settings")

    parser.add_argument("-i", "--id", dest="id",
                        default=False,
                        action="store_true",
                        help="Request radio ID string")

    memarg = parser.add_argument_group("Memory/Channel Options")
    memarg.add_argument("--list-mem", action="store_true",
                        help="List all memory locations")

    memarg.add_argument("--list-special-mem", action="store_true",
                        help="List all special memory locations")

    memarg.add_argument("--raw", action="store_true",
                        help="Dump raw memory location")

    memarg.add_argument("--get-mem", action="store_true",
                        help="Get and print memory location")
    memarg.add_argument("--copy-mem", action="store_true",
                        help="Copy memory location")
    memarg.add_argument("--clear-mem", action="store_true",
                        help="Clear memory location")

    memarg.add_argument("--set-mem-name", help="Set memory name")
    memarg.add_argument("--set-mem-freq", type=float,
                        help="Set memory frequency")

    memarg.add_argument("--set-mem-tencon", action="store_true",
                        help="Set tone encode enabled flag")
    memarg.add_argument("--set-mem-tencoff", action="store_true",
                        help="Set tone decode disabled flag")
    memarg.add_argument("--set-mem-tsqlon", action="store_true",
                        help="Set tone squelch enabled flag")
    memarg.add_argument("--set-mem-tsqloff", action="store_true",
                        help="Set tone squelch disabled flag")
    memarg.add_argument("--set-mem-dtcson", action="store_true",
                        help="Set DTCS enabled flag")
    memarg.add_argument("--set-mem-dtcsoff", action="store_true",
                        help="Set DTCS disabled flag")

    memarg.add_argument("--set-mem-tenc",
                        type=float, action=ToneAction, nargs=1,
                        help="Set memory encode tone")
    memarg.add_argument("--set-mem-tsql",
                        type=float, action=ToneAction, nargs=1,
                        help="Set memory squelch tone")

    memarg.add_argument("--set-mem-dtcs",
                        type=int, action=DTCSAction, nargs=1,
                        help="Set memory DTCS code")
    memarg.add_argument("--set-mem-dtcspol",
                        action=DTCSPolarityAction, nargs=1,
                        help="Set memory DTCS polarity (NN, NR, RN, RR)")

    memarg.add_argument("--set-mem-dup",
                        help="Set memory duplex (+,-, or blank)")
    memarg.add_argument("--set-mem-offset", type=float,
                        help="Set memory duplex offset (in MHz)")

    memarg.add_argument("--set-mem-mode",
                        help="Set mode (%s)" % ",".join(chirp_common.MODES))

    parser.add_argument("-r", "--radio", dest="radio",
                        default=None,
                        help="Radio model (see --list-radios)")
    parser.add_argument("--list-radios", action="store_true",
                        help="List radio models")
    parser.add_argument("--mmap", dest="mmap",
                        default=None,
                        help="Radio memory map file location")
    parser.add_argument("--download-mmap", dest="download_mmap",
                        action="store_true",
                        default=False,
                        help="Download memory map from radio")
    parser.add_argument("--upload-mmap", dest="upload_mmap",
                        action="store_true",
                        default=False,
                        help="Upload memory map to radio")
    logger.add_arguments(parser)
    parser.add_argument("args", metavar="arg", nargs='*',
                        help="Some commands require additional arguments")

    if len(sys.argv) <= 1:
        parser.print_help()
        sys.exit(0)

    options = parser.parse_args(args)
    args = options.args

    logger.handle_options(options)

    if options.list_radios:
        print("Supported Radios:\n\t", "\n\t".join(sorted(RADIOS.keys())))
        sys.exit(0)

    if options.id:
        from chirp import detect
        md = detect.detect_icom_radio(options.serial)
        print("Model:\n%s" % md.MODEL)
        sys.exit(0)

    if not options.radio:
        if options.mmap:
            rclass = directory.get_radio_by_image(options.mmap).__class__
        else:
            print("You must specify a radio model.  See --list-radios.")
            sys.exit(1)
    else:
        rclass = directory.get_radio(options.radio)

    if options.serial == "mmap":
        if options.mmap:
            s = options.mmap
        else:
            s = options.radio + ".img"
        if not os.path.exists(s):
            LOG.error("Image file '%s' does not exist" % s)
            sys.exit(1)
    else:
        LOG.info("opening %s at %i" % (options.serial, rclass.BAUD_RATE))
        if '://' in options.serial:
            s = serial.serial_for_url(options.serial, do_not_open=True)
            s.timeout = 0.5
            s.open()
        else:
            s = serial.Serial(port=options.serial, timeout=0.5)

    radio = rclass(s)

    if options.list_settings:
        print(radio.get_settings())
        sys.exit(0)

    if options.list_mem:
        rf = radio.get_features()
        start, end = rf.memory_bounds
        for i in range(start, end + 1):
            mem = radio.get_memory(i)
            if mem.empty and not logger.is_visible(logging.INFO):
                continue
            print(mem)
        sys.exit(0)

    if options.list_special_mem:
        rf = radio.get_features()
        for i in sorted(rf.valid_special_chans):
            mem = radio.get_memory(i)
            if mem.empty and not logger.is_visible(logging.INFO):
                continue
            print(mem)
        sys.exit(0)

    if options.copy_mem:
        src = parse_memory_number(radio, args)
        dst = parse_memory_number(radio, args[1:])
        try:
            mem = radio.get_memory(src)
        except errors.InvalidMemoryLocation as e:
            LOG.exception(e)
            sys.exit(1)
        LOG.info("copying memory %s to %s", src, dst)
        mem.number = dst
        radio.set_memory(mem)

    if options.clear_mem:
        memnum = parse_memory_number(radio, args)
        try:
            mem = radio.get_memory(memnum)
        except errors.InvalidMemoryLocation as e:
            LOG.exception(e)
            sys.exit(1)
        if mem.empty:
            LOG.warn("memory %s is already empty, deleting again", memnum)
        mem.empty = True
        radio.set_memory(mem)

    if options.raw:
        memnum = parse_memory_number(radio, args)
        data = radio.get_raw_memory(memnum)
        for i in data:
            if ord(i) > 0x7F:
                print("Memory location %s (%i):\n%s" %
                      (memnum, len(data), util.hexprint(data)))
                sys.exit(0)
        print(data)
        sys.exit(0)

    if options.set_mem_dup is not None:
        if options.set_mem_dup != "+" and \
                options.set_mem_dup != "-" and \
                options.set_mem_dup != "":
            LOG.error("Invalid duplex value `%s'" % options.set_mem_dup)
            LOG.error("Valid values are: '+', '-', ''")
            sys.exit(1)
        else:
            _dup = options.set_mem_dup
    else:
        _dup = None

    if options.set_mem_mode:
        LOG.info("Set mode: %s" % options.set_mem_mode)
        if options.set_mem_mode not in chirp_common.MODES:
            LOG.error("Invalid mode `%s'")
            sys.exit(1)
        else:
            _mode = options.set_mem_mode
    else:
        _mode = None

    if options.set_mem_name or options.set_mem_freq or \
            options.set_mem_tencon or options.set_mem_tencoff or \
            options.set_mem_tsqlon or options.set_mem_tsqloff or \
            options.set_mem_dtcson or options.set_mem_dtcsoff or \
            options.set_mem_tenc or options.set_mem_tsql or \
            options.set_mem_dtcs or options.set_mem_dup is not None or \
            options.set_mem_mode or options.set_mem_dtcspol or\
            options.set_mem_offset:
        memnum = parse_memory_number(radio, args)
        try:
            mem = radio.get_memory(memnum)
        except errors.InvalidMemoryLocation as e:
            LOG.exception(e)
            sys.exit(1)

        if mem.empty:
            LOG.info("creating new memory (#%s)", memnum)
            mem = chirp_common.Memory()
            mem.number = memnum

        mem.name = options.set_mem_name or mem.name
        mem.freq = options.set_mem_freq or mem.freq
        mem.rtone = options.set_mem_tenc or mem.rtone
        mem.ctone = options.set_mem_tsql or mem.ctone
        mem.dtcs = options.set_mem_dtcs or mem.dtcs
        mem.dtcs_polarity = options.set_mem_dtcspol or mem.dtcs_polarity
        if _dup is not None:
            mem.duplex = _dup
        mem.offset = options.set_mem_offset or mem.offset
        mem.mode = _mode or mem.mode

        if options.set_mem_tencon:
            mem.tmode = "Tone"
        elif options.set_mem_tencoff:
            mem.tmode = ""

        if options.set_mem_tsqlon:
            mem.tmode = "TSQL"
        elif options.set_mem_tsqloff:
            mem.tmode = ""

        if options.set_mem_dtcson:
            mem.tmode = "DTCS"
        elif options.set_mem_dtcsoff:
            mem.tmode = ""

        radio.set_memory(mem)

    if options.get_mem:
        pos = parse_memory_number(radio, args)
        try:
            mem = radio.get_memory(pos)
        except errors.InvalidMemoryLocation:
            mem = chirp_common.Memory()
            mem.number = pos

        print(mem)
        sys.exit(0)

    if options.download_mmap:
        if not issubclass(rclass, chirp_common.CloneModeRadio):
            LOG.error("%s is not a clone mode radio" % options.radio)
            sys.exit(1)
        if not options.mmap:
            LOG.error("You must specify the destination file name with --mmap")
            sys.exit(1)
        try:
            radio.sync_in()
            radio.save_mmap(options.mmap)
        except Exception as e:
            LOG.exception(e)
        sys.exit(1)

    if options.upload_mmap:
        if not issubclass(rclass, chirp_common.CloneModeRadio):
            LOG.error("%s is not a clone mode radio" % options.radio)
            sys.exit(1)
        if not options.mmap:
            LOG.error("You must specify the source file name with --mmap")
            sys.exit(1)
        try:
            radio.load_mmap(options.mmap)
            radio.sync_out()
            print("Upload successful")
        except Exception as e:
            LOG.exception(e)
        sys.exit(1)

    if options.mmap and isinstance(radio, chirp_common.CloneModeRadio):
        radio.save_mmap(options.mmap)
