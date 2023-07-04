# Copyright 2023 Dan Smith <chirp@f.danplanet.com>
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

from chirp.drivers import generic_csv
from chirp import errors
from chirp.sources import base

LOG = logging.getLogger(__name__)


class Przemienniki(base.NetworkResultRadio):
    VENDOR = 'przemienniki.net'

    def get_label(self):
        return 'przemienniki.net'

    def do_fetch(self, status, params):
        status.send_status('Querying', 10)
        if not params['range'] or int(params['range']) == 0:
            params.pop('range')
        LOG.debug('query params: %s' % str(params))
        try:
            r = requests.get('http://przemienniki.net/export/chirp.csv',
                             headers=base.HEADERS,
                             params=params,
                             stream=True)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            LOG.error('Failed to query przemienniki: %s' % e)
            status.send_fail(_('Unable to query'))
            return
        status.send_status(_('Parsing'), 20)
        try:
            csv = generic_csv.CSVRadio(None)
            csv._load(x.decode() for x in r.iter_lines())
        except errors.InvalidDataError:
            status.send_fail(_('No results'))
            return
        except Exception as e:
            LOG.error('Error parsing result: %s' % e)
            status.send_fail(_('Failed to parse result'))
            return

        status.send_status(_('Sorting'), 80)

        self._memories = [csv.get_memory(x) for x in range(1, 999)
                          if not csv.get_memory(x).empty]
        if not any([params['latitude'], params['longitude']]):
            LOG.debug('Sorting memories by name')
            self._memories.sort(key=lambda m: m.name)
            # Now renumber them
            for i, mem in enumerate(self._memories):
                mem.number = i + 1

        return status.send_end()
