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
import re
import logging

from math import pi, cos, acos, sin, atan2
from chirp import chirp_common, CHIRP_VERSION

LOG = logging.getLogger(__name__)

EARTH_RADIUS = 3963.1

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


def deg2rad(deg):
    """Convert degrees to radians"""
    return deg * (pi / 180)


def rad2deg(rad):
    """Convert radians to degrees"""
    return rad / (pi / 180)


def dm2deg(degrees, minutes):
    """Convert degrees and minutes to decimal degrees"""
    return degrees + (minutes / 60.0)


def deg2dm(decdeg):
    """Convert decimal degrees to degrees and minutes"""
    degrees = int(decdeg)
    minutes = (decdeg - degrees) * 60.0

    return degrees, minutes


def nmea2deg(nmea, direction="N"):
    """Convert NMEA-encoded value to float"""
    deg = int(nmea) / 100
    try:
        minutes = nmea % (deg * 100)
    except ZeroDivisionError:
        minutes = int(nmea)

    if direction == "S" or direction == "W":
        sign = -1
    else:
        sign = 1

    return dm2deg(deg, minutes) * sign


def deg2nmea(deg):
    """Convert degrees to a NMEA-encoded value"""
    degrees, minutes = deg2dm(deg)

    return (degrees * 100) + minutes


def meters2feet(meters):
    """Convert meters to feet"""
    return meters * 3.2808399


def feet2meters(feet):
    """Convert feet to meters"""
    return feet * 0.3048


def distance(lat_a, lon_a, lat_b, lon_b):
    """Calculate the distance between two points"""
    lat_a = deg2rad(lat_a)
    lon_a = deg2rad(lon_a)

    lat_b = deg2rad(lat_b)
    lon_b = deg2rad(lon_b)

    earth_radius = EARTH_RADIUS

    tmp = (cos(lat_a) * cos(lon_a) * cos(lat_b) * cos(lon_b)) + \
          (cos(lat_a) * sin(lon_a) * cos(lat_b) * sin(lon_b)) + \
          (sin(lat_a) * sin(lat_b))

    # Correct round-off error (which is just *silly*)
    if tmp > 1:
        tmp = 1
    elif tmp < -1:
        tmp = -1

    dist = acos(tmp)

    return dist * earth_radius


def bearing(lat_a, lon_a, lat_b, lon_b):
    """Calculate the bearing between two points"""
    lat_me = deg2rad(lat_a)
    lat_u = deg2rad(lat_b)
    lon_d = deg2rad(lon_b - lon_a)

    posy = sin(lon_d) * cos(lat_u)
    posx = cos(lat_me) * sin(lat_u) - \
        sin(lat_me) * cos(lat_u) * cos(lon_d)

    bear = rad2deg(atan2(posy, posx))

    return (bear + 360) % 360


def fuzzy_to(lat_a, lon_a, lat_b, lon_b):
    """Calculate a fuzzy distance to a point"""
    bear = bearing(lat_a, lon_a, lat_b, lon_b)

    dirs = ["N", "NNE", "NE", "ENE", "E",
            "ESE", "SE", "SSE", "S",
            "SSW", "SW", "WSW", "W",
            "WNW", "NW", "NNW"]

    delta = 22.5
    angle = 0

    direction = "?"
    for i in dirs:
        if bear > angle and bear < (angle + delta):
            direction = i
        angle += delta

    return direction


class RFinderParser:
    """Parser for RFinder's data format"""
    def __init__(self, lat, lon):
        self.__memories = []
        self.__cheat = {}
        self.__lat = lat
        self.__lon = lon

    def fetch_data(self, user, pw, coords, radius):
        """Fetches the data for a set of parameters"""
        LOG.debug(user)
        LOG.debug(pw)
        args = {
            "email": urllib.quote_plus(user),
            "pass": hashlib.new("md5", pw).hexdigest(),
            "lat": "%7.5f" % coords[0],
            "lon": "%7.5f" % coords[1],
            "radius": "%i" % radius,
            "vers": "CH%s" % CHIRP_VERSION,
            }

        _url = "https://www.rfinder.net/query.php?%s" % \
               ("&".join(["%s=%s" % (k, v) for k, v in args.items()]))

        LOG.debug("Query URL: %s" % _url)

        f = urllib.urlopen(_url)
        data = f.read()
        f.close()

        match = re.match("^/#SERVERMSG#/(.*)/#ENDMSG#/", data)
        if match:
            raise Exception(match.groups()[0])

        return data

    def _parse_line(self, line):
        mem = chirp_common.Memory()

        _vals = line.split("|")

        vals = {}
        for i in range(0, len(SCHEMA)):
            try:
                vals[SCHEMA[i]] = _vals[i]
            except IndexError:
                LOG.error("No such vals %s" % SCHEMA[i])
        self.__cheat = vals

        mem.name = vals["TRUSTEE"]
        mem.freq = chirp_common.parse_freq(vals["OUTFREQUENCY"])
        if vals["OFFSETSIGN"] != "X":
            mem.duplex = vals["OFFSETSIGN"]
        if vals["OFFSETFREQ"]:
            mem.offset = chirp_common.parse_freq(vals["OFFSETFREQ"])

        if vals["PL"] and float(vals["PL"]) != 0:
            mem.rtone = float(vals["PL"])
            mem.tmode = "Tone"
        elif vals["DCS"] and vals["DCS"] != "0":
            mem.dtcs = int(vals["DCS"])
            mem.tmode = "DTCS"

        if vals["NOTES"]:
            mem.comment = vals["NOTES"].strip()

        if vals["LATITUDE"] and vals["LONGITUDE"]:
            try:
                lat = float(vals["LATITUDE"])
                lon = float(vals["LONGITUDE"])
                dist = distance(self.__lat, self.__lon, lat, lon)
                bear = fuzzy_to(self.__lat, self.__lon, lat, lon)
                mem.comment = "(%imi %s) %s" % (dist, bear, mem.comment)
            except Exception, e:
                LOG.error("Failed to calculate distance: %s" % e)

        return mem

    def parse_data(self, data):
        """Parse the fetched data"""
        number = 1
        for line in data.split("\n"):
            if line.startswith("<"):
                continue
            elif not line.strip():
                continue
            try:
                mem = self._parse_line(line)
                mem.number = number
                number += 1
                self.__memories.append(mem)
            except Exception, e:
                import traceback
                LOG.error(traceback.format_exc())
                LOG.error("Error in received data, cannot continue")
                LOG.error("rfinder.parse_data: %s", e)
                LOG.error(self.__cheat)
                LOG.error(line)

    def get_memories(self):
        """Return the Memory objects associated with the fetched data"""
        return self.__memories


class RFinderRadio(chirp_common.NetworkSourceRadio):
    """A network source radio that supports the RFinder repeater directory"""
    VENDOR = "ITWeRKS"
    MODEL = "RFinder"

    def __init__(self, *args, **kwargs):
        chirp_common.NetworkSourceRadio.__init__(self, *args, **kwargs)

        self._lat = 0
        self._lon = 0
        self._user = ""
        self._pass = ""
        self._miles = 25

        self._rfp = None

    def set_params(self, (lat, lon), miles, email, password):
        """Sets the parameters to use for the query"""
        self._lat = lat
        self._lon = lon
        self._miles = miles
        self._user = email
        self._pass = password

    def do_fetch(self):
        self._rfp = RFinderParser(self._lat, self._lon)

        self._rfp.parse_data(self._rfp.fetch_data(self._user,
                                                  self._pass,
                                                  (self._lat, self._lon),
                                                  self._miles))

    def get_features(self):
        if not self._rfp:
            self.do_fetch()

        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, len(self._rfp.get_memories()))
        rf.has_bank = False
        rf.has_ctone = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["", "FM", "NFM", "AM", "NAM", "DV"]
        return rf

    def get_memory(self, number):
        if not self._rfp:
            self.do_fetch()

        return self._rfp.get_memories()[number-1]


def _test():
    rfp = RFinderParser()
    data = rfp.fetch_data("KK7DS", "dsmith@danplanet.com",
                          (45.5, -122.91), 25)
    rfp.parse_data(data)

    for mem in rfp.get_memories():
        LOG.debug(mem)

if __name__ == "__main__":
    _test()
