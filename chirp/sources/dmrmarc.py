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

import logging
import requests
from chirp import chirp_common
from chirp.sources import base
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList

LOG = logging.getLogger(__name__)


def list_filter(haystack, attr, needles):
    if not needles or not needles[0]:
        return haystack
    return [x for x in haystack if x[attr] in needles]


class DMRMARCRadio(base.NetworkResultRadio):
    """DMR-MARC data source"""
    VENDOR = "DMR-MARC"

    def get_label(self):
        return 'DMR-MARC'

    def do_fetch(self, status, params):
        status.send_status('Querying', 10)
        try:
            r = requests.get('https://radioid.net/api/dmr/repeater/',
                             headers=base.HEADERS,
                             params={'city': params['city'],
                                     'state': params['state'],
                                     'country': params['country']})
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            LOG.error('Failed to query DMR-MARC: %s' % e)
            status.send_fail('Unable to query DMR-MARC')
            return
        status.send_status('Parsing', 20)
        self._repeaters = r.json()['results']
        self._memories = [self.make_memory(i)
                          for i in range(0, len(self._repeaters))]
        status.send_end()

    def get_raw_memory(self, number):
        return repr(self._repeaters[number])

    def make_memory(self, number):
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
        mem.comment = repeater.get('details')

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting(
            "color_code", "Color Code", RadioSettingValueList(
                range(16), int(repeater.get('color_code', 0))))
        mem.extra.append(rs)

        return mem


def main():
    import argparse
    from pprint import PrettyPrinter

    parser = argparse.ArgumentParser(
        description=("Fetch DMR-MARC repeater "
                     "database and filter by city, state, and/or country. "
                     "Multiple items combined with a , will be filtered with "
                     "logical OR."))
    parser.add_argument(
        "-c", "--city",
        help="Comma-separated list of cities to include in output.")
    parser.add_argument(
        "-s", "--state",
        help="Comma-separated list of states to include in output.")
    parser.add_argument(
        "--country",
        help="Comma-separated list of countries to include in output.")
    args = parser.parse_args()

    dmrmarc = DMRMARCRadio(None)
    dmrmarc.set_params(**vars(args))
    dmrmarc.do_fetch()
    pp = PrettyPrinter(indent=2)
    pp.pprint(dmrmarc._repeaters)


if __name__ == "__main__":
    main()
