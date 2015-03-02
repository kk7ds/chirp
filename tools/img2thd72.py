#!/usr/bin/env python
# coding=utf-8
# ex: set tabstop=4 expandtab shiftwidth=4 softtabstop=4:
#
# © Copyright Vernon Mauery <vernon@mauery.com>, 2010.  All Rights Reserved
#
# This is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as  published
# by the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# This sofware is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public
# License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.


import sys
import getopt
from PIL import Image as im


def die(msg):
    print msg
    sys.exit(1)


def thd72bitmap(fname, invert):
    img = im.open(ifname)
    if img.size != (120, 48):
        die("Image has wrong dimensions: must be 120x48")

    colors = img.getcolors()
    if len(colors) != 2:
        die("Image must be 1 bits per pixel (black and white)")

    if ('-i', '') in opts:
        c, black = colors[0]
        c, white = colors[1]
    else:
        c, white = colors[0]
        c, black = colors[1]

    colors = {black: 1, white: 0}
    data = img.getdata()
    buf = ''
    for y in range(6):
        for x in range(120):
            b = 0
            for i in range(8):
                b |= colors[data[x + 120 * (y * 8 + i)]] << i
            buf += chr(b)
    return buf


def display_thd72(buf):
    dots = {0: '*', 1: ' '}
    lines = []
    for y in range(48):
        line = ''
        for x in range(120):
            byte = y/8*120 + x
            line += dots[(ord(buf[byte]) >> (y % 8)) & 0x01]
        lines.append(line)
    for l in lines:
        print l


def usage():
    print "\nUsage: %s <-s|-g> [-i] [-d] " \
          "<image-file> <thd72-nvram-file>" % sys.argv[0]
    print "\nThis program will modify whatever nvram file provided or will"
    print "create a new one if the file does not exist.  After using this to"
    print "modify the image, you can use that file to upload all or part of"
    print "it to your radio"
    print "\nOption explanations:"
    print "  -s     Save as the startup image"
    print "  -g     Save as the GPS logger image"
    print "  -i     Invert colors (black for white)"
    print "         Depending on the file format the bits may be inverted."
    print "         If your bitmap file turns out to be inverted, use -i."
    print "  -d     Display the bitmap as dots (for confirmation)"
    print "         Each black pixel is '*' and each white pixel is ' '"
    print "         This will print up to 120 dots wide, so beware your"
    print "         terminal size."
    sys.exit(1)

if __name__ == "__main__":
    opts, args = getopt.getopt(sys.argv[1:], "idgs")
    if len(args) != 2:
        usage()
    ifname = args[0]
    ofname = args[1]
    invert = ('-i', '') in opts
    gps = ('-g', '') in opts
    startup = ('-s', '') in opts
    if (gps and startup) or not (gps or startup):
        usage()
    if gps:
        imgpos = 0xe800
        tagpos = 18
    else:
        imgpos = 0xe500
        tagpos = 17

    buf = thd72bitmap(ifname, invert)
    imgfname = ifname + '\xff' * (48-len(ifname))
    of = file(ofname, "rb+")
    of.seek(tagpos)
    of.write('\x01')
    of.seek(imgpos)
    of.write(buf)
    of.write(imgfname)
    of.seek(65536)
    of.close()

    if ('-d', '') in opts:
        display_thd72(buf)

    blocks = [0, ]
    blocks.append(imgpos/256)
    blocks.append(1+imgpos/256)
    blocks.append(2+imgpos/256)
    print "Modified block list:", blocks
