# Copyright 2016 Tom Hayward <tom@tomh.us>
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

import json
import logging
import tempfile
import urllib
from chirp import chirp_common, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
     RadioSettingValueList

LOG = logging.getLogger(__name__)


def list_filter(haystack, attr, needles):
    if not needles or not needles[0]:
        return haystack
    return [x for x in haystack if x[attr] in needles]


class DMRMARCRadio(chirp_common.NetworkSourceRadio):
    """DMR-MARC data source"""
    VENDOR = "DMR-MARC"
    MODEL = "Repeater database"

    URL = "http://www.dmr-marc.net/cgi-bin/trbo-database/datadump.cgi?" \
          "table=repeaters&format=json"

    def __init__(self, *args, **kwargs):
        chirp_common.NetworkSourceRadio.__init__(self, *args, **kwargs)
        self._repeaters = None

    def set_params(self, city, state, country):
        """Set the parameters to be used for a query"""
        self._city = city and [x.strip() for x in city.split(",")] or ['']
        self._state = state and [x.strip() for x in state.split(",")] or ['']
        self._country = country and [x.strip() for x in country.split(",")] \
            or ['']

    def do_fetch(self):
        fn = tempfile.mktemp(".json")
        filename, headers = urllib.urlretrieve(self.URL, fn)
        with open(fn, 'r') as f:
            try:
                self._repeaters = json.load(f)['repeaters']
            except AttributeError:
                raise errors.RadioError(
                    "Unexpected response from %s" % self.URL)
            except ValueError as e:
                raise errors.RadioError(
                    "Invalid JSON from %s. %s" % (self.URL, str(e)))

        self._repeaters = list_filter(self._repeaters, "city", self._city)
        self._repeaters = list_filter(self._repeaters, "state", self._state)
        self._repeaters = list_filter(self._repeaters, "country",
                                      self._country)

    def get_features(self):
        if not self._repeaters:
            self.do_fetch()

        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, len(self._repeaters)-1)
        rf.has_bank = False
        rf.has_comment = True
        rf.has_ctone = False
        rf.valid_tmodes = [""]
        return rf

    def get_raw_memory(self, number):
        return repr(self._repeaters[number])

    def get_memory(self, number):
        if not self._repeaters:
            self.do_fetch()

        repeater = self._repeaters[number]

        mem = chirp_common.Memory()
        mem.number = number

        mem.name = repeater.get('city')
        mem.freq = chirp_common.parse_freq(repeater.get('frequency'))
        offset = chirp_common.parse_freq(repeater.get('offset', '0'))
        if offset > 0:
            mem.duplex = "+"
        elif offset < 0:
            mem.duplex = "-"
        else:
            mem.duplex = ""
        mem.offset = abs(offset)
        mem.mode = 'DMR'
        mem.comment = repeater.get('map_info')

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting(
            "color_code", "Color Code", RadioSettingValueList(
                range(16), int(repeater.get('color_code', 0))))
        mem.extra.append(rs)

        return mem


def main():
    import argparse
    from pprint import PrettyPrinter

    parser = argparse.ArgumentParser(description="Fetch DMR-MARC repeater "
        "database and filter by city, state, and/or country. Multiple items "
        "combined with a , will be filtered with logical OR.")
    parser.add_argument("-c", "--city",
        help="Comma-separated list of cities to include in output.")
    parser.add_argument("-s", "--state",
        help="Comma-separated list of states to include in output.")
    parser.add_argument("--country",
        help="Comma-separated list of countries to include in output.")
    args = parser.parse_args()

    dmrmarc = DMRMARCRadio(None)
    dmrmarc.set_params(**vars(args))
    dmrmarc.do_fetch()
    pp = PrettyPrinter(indent=2)
    pp.pprint(dmrmarc._repeaters)

if __name__ == "__main__":
    main()
