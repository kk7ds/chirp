# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
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
from chirp.sources import repeaterbook

LOG = logging.getLogger(__name__)


class MyGMRS(base.NetworkResultRadio):
    VENDOR = 'myGMRS'


    def get_label(self):
        return 'myGMRS'

    @staticmethod
    def parse_tone(tone):
        return float(tone.split(' ', 1)[0])

    @staticmethod
    def parse_dpl(dpl):
        return int(dpl.split(' ', 1)[0])

    def decode_tone(self, result, m):
        txmode = rxmode = tx = rx = None
        if 'Hz' in result['PL In']:
            tx = self.parse_tone(result['PL In'])
            txmode = 'Tone'
        elif 'DPL' in result['PL In']:
            tx = self.parse_dpl(result['PL In'])
            txmode = 'DTCS'
        if 'Hz' in result['PL Out']:
            rx = self.parse_tone(result['PL Out'])
            rxmode = 'Tone'
        elif 'DPL' in result['PL Out']:
            rx = self.parse_dpl(result['PL Out'])
            rxmode = 'DTCS'

        chirp_common.split_tone_decode(m,
                                       (txmode, tx, 'N'),
                                       (rxmode, rx, 'N'))

    def do_fetch(self, status, params):
        lat = float(params.pop('lat') or 0)
        lon = float(params.pop('lon') or 0)
        params.update({'limit': 50,
                       'skip': 0,
                       'sort': 'Modified',
                       'descending': 'true'})
        username = params.pop('username')
        password = params.pop('password')

        s = requests.Session()
        s.headers.update(base.HEADERS)
        if username and password:
            status.send_status('Logging in', 5)
            r = s.post('https://api.mygmrs.com/login',
                       json={'username': username,
                             'password': password})
            if r.status_code != 200:
                status.send_fail('Login rejected')
                return

        status.send_status('Querying', 10)

        results = []
        total = 0
        while True:
            r = s.get('https://api.mygmrs.com/repeaters',
                      params=params)
            if r.status_code != 200:
                status.send_fail('Got error code %i from server' % (
                    r.status_code))
                return
            resp = r.json()
            if not resp['success']:
                status.send_fail('MyGMRS reported failure')
                return
            if not results:
                if resp['info']['total'] == 0:
                    status.send_fail('No results!')
                    return
                else:
                    total = resp['info']['total']
            results.extend(resp['items'])
            LOG.debug('Got %i items in this page', len(resp['items']))
            if len(results) == total:
                status.send_status('Processing results', 90)
                break
            elif len(resp['items']) == 0:
                LOG.error('Got a page of zero results; exiting for safety!')
                break
            else:
                params['skip'] = len(results)
                status.send_status('Downloading %i results' % len(results),
                                   int(len(results) / total * 80))

        def sorter(item):
            if lat and lon:
                return repeaterbook.distance(lat, lon,
                                             item['Latitude'],
                                             item['Longitude'])
            else:
                return 0

        i = 0
        for result in sorted(results, key=sorter):
            if result['Status'] != 'Online':
                LOG.debug('Skipping non-online result %s' % result.get('ID'))
                continue
            m = chirp_common.Memory()
            m.number = i
            m.freq = chirp_common.parse_freq(result['Frequency'])
            m.name = result['Name']
            m.offset = chirp_common.to_MHz(5)
            m.duplex = '+'
            try:
                self.decode_tone(result, m)
            except Exception:
                LOG.exception('Failed to decode tone from %r' % result)
                raise
            m.comment = '%s, %s (%s)' % (result['Location'],
                                         result['State'],
                                         result['Type'])
            self._memories.append(m)
            i += 1

        if i > 0:
            status.send_end()
        else:
            status.send_fail('No results!')
