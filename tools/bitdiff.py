#!/usr/bin/env python
#
# Copyright 2013 Jens Jensen AF5MI <kd4tjx@yahoo.com>

import sys
import os
import argparse
import time


def printDiff(pos, byte1, byte2, args):
    bits1 = '{0:08b}'.format(byte1)
    bits2 = '{0:08b}'.format(byte2)
    print "@%04Xh" % pos
    print "1:%02Xh, %sb" % (byte1, bits1)
    print "2:%02Xh, %sb" % (byte2, bits2)
    if args.csv:
        writeDiffCSV(pos, byte1, byte2, args)


def writeDiffCSV(pos, byte1, byte2, args):
    bits1 = '{0:08b}'.format(byte1)
    bits2 = '{0:08b}'.format(byte2)
    csvline = '%s, %s, %04X, %02X, %s, %02X, %s, %s, %s' % \
        (args.file1, args.file2, pos, byte1, bits1,
         byte2, bits2, args.setting, args.value)
    if not os.path.isfile(args.csv):
        fh = open(args.csv, "w")
        header = "filename1, filename2, byte_offset, byte1, " \
            "bits1, byte2, bits2, item_msg, value_msg"
        fh.write(header + os.linesep)
    else:
        fh = open(args.csv, "a")
    fh.write(csvline + os.linesep)
    fh.close()


def compareFiles(args):
    f1 = open(args.file1, "rb")
    f1.seek(args.offset)
    f2 = open(args.file2, "rb")
    f2.seek(args.offset)

    while True:
        pos = f1.tell() - args.offset
        c1 = f1.read(1)
        c2 = f2.read(1)
        if not (c1 and c2):
            break
        b1 = ord(c1)
        b2 = ord(c2)
        if b1 != b2:
            printDiff(pos, b1, b2, args)

    pos = f1.tell() - args.offset
    print "bytes read: %02d" % pos
    f1.close()
    f2.close()


def compareFilesDat(args):
    f1 = open(args.file1, "r")
    f1contents = f1.read()
    f1.close()
    f2 = open(args.file2, "r")
    f2contents = f2.read()
    f2.close()

    f1strlist = f1contents.split()
    f1intlist = map(int, f1strlist)
    f2strlist = f2contents.split()
    f2intlist = map(int, f2strlist)
    f1bytes = bytearray(f1intlist)
    f2bytes = bytearray(f2intlist)

    length = len(f1intlist)
    for i in range(length):
        b1 = f1bytes[i]
        b2 = f2bytes[i]
        pos = i
        if b1 != b2:
            printDiff(pos, b1, b2, args)

    pos = length
    print "bytes read: %02d" % pos


def convertFileToBin(args):
    f1 = open(args.file1, "r")
    f1contents = f1.read()
    f1.close()
    f1strlist = f1contents.split()
    f1intlist = map(int, f1strlist)
    f1bytes = bytearray(f1intlist)
    f2 = open(args.file2, "wb")
    f2.write(f1bytes)
    f2.close


def convertFileToDat(args):
    f1 = open(args.file1, "rb")
    f1contents = f1.read()
    f1.close()
    f2 = open(args.file2, "w")
    for i in range(0, len(f1contents)):
        f2.write(" %d " % (ord(f1contents[i]), ))
        if i % 16 == 15:
            f2.write("\r\n")
    f2.close


# main

ap = argparse.ArgumentParser(description="byte-/bit- comparison of two files")
ap.add_argument("file1", help="first (reference) file to parse")
ap.add_argument("file2", help="second file to parse")

mutexgrp1 = ap.add_mutually_exclusive_group()
mutexgrp1.add_argument("-o", "--offset", default=0,
                       help="offset (hex) to start comparison")
mutexgrp1.add_argument("-d", "--dat", action="store_true",
                       help="process input files from .DAT/.ADJ format "
                            "(from 'jujumao' oem programming software "
                            "for chinese radios)")
mutexgrp1.add_argument("--convert2bin", action="store_true",
                       help="convert file1 from .dat/.adj to "
                       "binary image file2")
mutexgrp1.add_argument("--convert2dat", action="store_true",
                       help="convert file1 from bin to .dat/.adj file2")

ap.add_argument("-w", "--watch", action="store_true",
                help="'watch' changes. runs in a loop")

csvgrp = ap.add_argument_group("csv output")
csvgrp.add_argument("-c", "--csv",
                    help="file to append csv results. format: filename1, "
                         "filename2, byte_offset, byte1, bits1, byte2, "
                         "bits2, item_msg, value_msg")
csvgrp.add_argument("-s", "--setting",
                    help="user-meaningful field indicating setting/item "
                         "modified, e.g. 'beep' or 'txtone'")
csvgrp.add_argument("-v", "--value",
                    help="user-meaningful field indicating values "
                         "changed, e.g. 'true->false' or '110.9->100.0'")

args = ap.parse_args()
if args.offset:
    args.offset = int(args.offset, 16)

print "f1:", args.file1, " f2:", args.file2
if args.setting or args.value:
    print "setting:", args.setting, "- value:", args.value

while True:
    if (args.dat):
        compareFilesDat(args)
    elif (args.convert2bin):
        convertFileToBin(args)
    elif (args.convert2dat):
        convertFileToDat(args)
    else:
        compareFiles(args)
    if not args.watch:
        break
    print "------"
    time.sleep(delay)
