# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

import urllib
import hashlib

from chirp import chirp_common, CHIRP_VERSION

SCHEMA = [
    "ID",
    "TRUSTEE",
    "OUTFREQUENCY",
    "CITY",
    "STATE",
    "COUNTRY",
    "LATITUDE",
    "LONGITUDE",
    "CLUB",
    "DESCRIPTION",
    "NOTES",
    "RANGE",
    "OFFSETSIGN",
    "OFFSETFREQ",
    "PL",
    "DCS",
    "REPEATERTYPE",
    "BAND",
    "IRLP",
    "ECHOLINK",
    "DOC_ID",
    ]

class RFinderParser:
    def __init__(self):
        self.__memories = []
        self.__cheat = {}

    def fetch_data(self, lat, lon, email, passwd):
        args = {
            "lat"   : "%7.5f" % lat,
            "lon"   : "%8.5f" % lon,
            "email" : urllib.quote_plus(email),
            "pass"  : hashlib.md5(passwd).hexdigest(),
            "vers"  : "CH%s" % CHIRP_VERSION,
            }

        url = "http://sync.rfinder.net/radio/repeaters.nsf/getlocal?openagent&%s"\
            % "&".join(["%s=%s" % (k,v) for k,v in args.items()])

        f = urllib.urlopen(url)
        data = f.read()
        f.close()

        return data

    def parse_line(self, line):
        mem = chirp_common.Memory()

        _vals = line.split("|")

        vals = {}
        for i in range(0, len(SCHEMA)):
            vals[SCHEMA[i]] = _vals[i]
        self.__cheat = vals

        mem.name = vals["TRUSTEE"]
        mem.freq = chirp_common.parse_freq(vals["OUTFREQUENCY"])
        if vals["OFFSETSIGN"] != "X":
            mem.duplex = vals["OFFSETSIGN"]
        if vals["OFFSETFREQ"]:
            mem.offset = chirp_common.format_freq(vals["OFFSETFREQ"])

        if vals["PL"] and vals["PL"] != "0":
            mem.rtone = float(vals["PL"])
            mem.tmode = "Tone"
        elif vals["DCS"] and vals["DCS"] != "0":
            mem.dtcs = int(vals["DCS"])
            mem.tmode = "DTCS"

        return mem

    def parse_data(self, data):
        number = 1
        for line in data.split("\n"):
            if line.startswith("<"):
                continue
            elif not line.strip():
                continue
            try:
                mem = self.parse_line(line)
                mem.number = number
                number += 1
                self.__memories.append(mem)
            except Exception, e:
                print "Error in record %s:" % self.__cheat["DOC_ID"]
                print e
                print self.__cheat
                print "\n\n"

    def get_memories(self):
        return self.__memories

class RFinderRadio(chirp_common.Radio):
    VENDOR = "ITWeRKS"
    MODEL = "RFinder"

    def __init__(self, *args, **kwargs):
        chirp_common.Radio.__init__(self, *args, **kwargs)
       
        self._lat = 0
        self._lon = 0
        self._call = ""
        self._email = ""
 
        self._rfp = None

    def set_params(self, lat, lon, call, email):
        self._lat = lat
        self._lon = lon
        self._call = call
        self._email = email

    def do_fetch(self):
        self._rfp = RFinderParser()
        self._rfp.parse_data(self._rfp.fetch_data(self._lat, self._lon, self._call, self._email))
        
    def get_features(self):
        if not self._rfp:
            self.do_fetch()

        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, len(self._rfp.get_memories()))
        return rf

    def get_memory(self, number):
        if not self._rfp:
            self.do_fetch()

        return self._rfp.get_memories()[number-1]

if __name__ == "__main__":
    import sys

    rfp = RFinderParser()
    data = rfp.fetch_data(45.525, -122.9164, "KK7DS", "dsmith@danplanet.com")
    rfp.parse_data(data)

    for m in rfp.get_memories():
        print m
