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
import queue
import requests
import sys
import tempfile
import threading

import wx

from chirp import CHIRP_VERSION
from chirp.ui import config
from chirp.ui import fips

CONF = config.get()
LOG = logging.getLogger(__name__)
QueryThreadEvent, EVT_QUERY_THREAD = wx.lib.newevent.NewCommandEvent()
HEADERS = {
    'User-Agent': 'chirp/%s Python %i.%i.%i %s' % (
        CHIRP_VERSION,
        sys.version_info.major, sys.version_info.minor, sys.version_info.micro,
        sys.platform),
}


class QueryThread(threading.Thread):
    END_SENTINEL = object()

    def __init__(self, *a, **k):
        self.query_dialog = a[0]
        super(QueryThread, self).__init__(*a[1:], **k)
        self.status_queue = queue.Queue()

    def run(self):
        try:
            self.do_query()
        except Exception as e:
            self.send_fail('Failed: %s' % str(e))

    def send_status(self, status, percent):
        self.query_dialog.status(status, percent)

    def send_end(self):
        self.query_dialog.end()

    def send_fail(self, reason):
        self.query_dialog.fail(reason)


class QuerySourceDialog(wx.Dialog):
    NAME = 'NetworkSource'

    def __init__(self, *a, **k):
        super(QuerySourceDialog, self).__init__(*a, **k)
        vbox = self.build()
        self.Center()

        self.gauge = wx.Gauge(self)
        self.gauge.SetRange(100)
        vbox.Add(self.gauge, 0, wx.EXPAND)

        self.statusmsg = wx.StaticText(
            self, label='',
            style=(wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ST_ELLIPSIZE_END))
        vbox.Add(self.statusmsg, 0, wx.EXPAND)

        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(bs)
        self.Bind(wx.EVT_BUTTON, self._button)

        self.Bind(EVT_QUERY_THREAD, self._got_status)

        self.result_file = tempfile.NamedTemporaryFile(
            prefix='%s-' % self.NAME,
            suffix='.csv').name

    def _button(self, event):
        id = event.GetEventObject().GetId()

        if id == wx.ID_OK:
            self.FindWindowById(wx.ID_OK).Disable()
            self.do_query()
            return

        self.EndModal(id)

    def build(self):
        pass

    def do_query(self):
        pass

    def status(self, status, percent):
        wx.PostEvent(self, QueryThreadEvent(self.GetId(),
                                            status=status, percent=percent))

    def end(self):
        self.status(None, 100)

    def fail(self, reason):
        self.status(reason, 100)

    def _got_status(self, event):
        self.gauge.SetValue(event.percent)
        if event.status is None:
            self.EndModal(wx.ID_OK)
        else:
            self.statusmsg.SetLabel(event.status)
        if event.percent == 100:
            self.FindWindowById(wx.ID_OK).Enable()


class RepeaterBookQueryThread(QueryThread):
    def do_query(self):
        self.send_status('Querying', 10)

        params = self.query_dialog.get_rb_params()
        r = requests.get('http://chirp.danplanet.com/%s' % params.pop('_url'),
                         params=params,
                         headers=HEADERS,
                         stream=True)
        if r.status_code != 200:
            self.send_fail('Got error code %i from server' % r.status_code)
            return

        self.send_status('Downloading', 20)

        size = 0
        chunks = 0
        LOG.debug('Writing to %s' % self.query_dialog.result_file)
        with open(self.query_dialog.result_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                size += len(chunk)
                chunks += 1
                self.send_status('Read %iKiB' % (size // 1024),
                                 20 + max(chunks * 10, 80))
                f.write(chunk)

        if size <= 105:
            self.send_fail('No results!')
            return

        self.send_end()


class RepeaterBookQueryDialog(QuerySourceDialog):
    NAME = 'Repeaterbook'
    RB_BANDS = {
        "--All--":                  0,
        "10 meters (29MHz)":        29,
        "6 meters (54MHz)":         5,
        "2 meters (144MHz)":        14,
        "1.25 meters (220MHz)":     22,
        "70 centimeters (440MHz)":  4,
        "33 centimeters (900MHz)":  9,
        "23 centimeters (1.2GHz)":  12,
    }

    def build(self):
        self.tabs = wx.Notebook(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        vbox.Add(self.tabs, 1, wx.EXPAND)

        self.tabs.InsertPage(0, self._build_political(self.tabs), 'Political')
        self.tabs.InsertPage(1, self._build_proximity(self.tabs), 'Proximity')
        self.Layout()
        return vbox

    def _build_band_choice(self, parent):
        return wx.Choice(parent, choices=list(self.RB_BANDS.keys()))

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def _build_political(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)

        self._state = wx.Choice(panel, choices=sorted(fips.FIPS_STATES.keys()))
        self.Bind(wx.EVT_CHOICE, self._selected_state, self._state)
        self._county = wx.Choice(panel, choices=['--All--'])
        self.Bind(wx.EVT_CHOICE, self._selected_county, self._county)
        self._pol_band = self._build_band_choice(panel)
        self.Bind(wx.EVT_CHOICE, self._selected_band, self._pol_band)

        self._fips_to_state = {str(v): k for k, v in fips.FIPS_STATES.items()}

        current_state = CONF.get('state', 'repeaterbook')
        current_county = CONF.get('county', 'repeaterbook')
        if not current_state:
            current_state = '1'
        self._state.SetSelection(
            self._state.FindString(self._fips_to_state[current_state]))
        self._selected_state_name(self._fips_to_state[current_state])

        try:
            _fips_to_county = {
                str(v): k
                for k, v in fips.FIPS_COUNTIES[int(current_state)].items()}
            self._county.SetSelection(
                self._county.FindString(_fips_to_county[current_county]))
        except Exception:
            if current_county:
                LOG.warning('Missing county code %r in state %r' % (
                    current_county,
                    current_state))

        self._add_grid(grid, 'State', self._state)
        self._add_grid(grid, 'County', self._county)
        self._add_grid(grid, 'Band', self._pol_band)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, proportion=0, flag=wx.EXPAND,
                 border=20)
        panel.SetSizer(vbox)
        return panel

    def _selected_state(self, event):
        self._selected_state_name(event.GetString())

    def _selected_state_name(self, state):
        counties = sorted(fips.FIPS_COUNTIES[fips.FIPS_STATES[state]].keys())
        self._county.Set(counties)
        CONF.set('state', str(fips.FIPS_STATES[state]), 'repeaterbook')
        self._selected_county_name(counties[0])

    def _selected_county(self, event):
        self._selected_county_name(event.GetString())

    def _selected_county_name(self, county):
        state = CONF.get('state', 'repeaterbook')
        try:
            state = int(state)
        except ValueError:
            pass
        county_code = str(fips.FIPS_COUNTIES[state][county])
        if county_code == '%':
            CONF.remove_option('county', 'repeaterbook')
        else:
            CONF.set('county', county_code, 'repeaterbook')

    def _build_proximity(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)

        self._location = wx.TextCtrl(panel)
        self._location.AppendText(CONF.get('location', 'repeaterbook') or '')
        self.Bind(wx.EVT_TEXT, self._selected_location, self._location)
        self._distance = wx.TextCtrl(panel)
        self._distance.AppendText(CONF.get('distance', 'repeaterbook') or '')
        self.Bind(wx.EVT_TEXT, self._selected_distance, self._distance)
        self._prox_band = self._build_band_choice(panel)
        self.Bind(wx.EVT_CHOICE, self._selected_band, self._prox_band)

        self._add_grid(grid, 'Location', self._location)
        self._add_grid(grid, 'Distance', self._distance)
        self._add_grid(grid, 'Band', self._prox_band)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, flag=wx.EXPAND,
                 border=20)
        panel.SetSizer(vbox)
        return panel

    def _selected_location(self, event):
        CONF.set('location', event.GetString(), 'repeaterbook')

    def _selected_distance(self, event):
        CONF.set('distance', event.GetString(), 'repeaterbook')

    def _selected_band(self, event):
        CONF.set('band', str(self.RB_BANDS[event.GetString()]), 'repeaterbook')

    def do_query(self):
        RepeaterBookQueryThread(self).start()

    def get_rb_params(self):
        page = self.tabs.GetSelection()
        if page == 0:
            # Political
            return {
                '_url': 'query/rb/1.0/chirp',
                'state_id': CONF.get('state', 'repeaterbook'),
                'county_id': CONF.get('county', 'repeaterbook') or '%',
                'func': 'default',
                'band': CONF.get('band', 'repeaterbook') or '%',
                'freq': '%',
                'band6': '%',
                'loc': '%',
                'status_id': '%',
                'features': '%',
                'coverage': '%',
                'use': '%',
            }
        elif page == 1:
            # Proximity
            try:
                return {
                    '_url': 'query/rb/1.0/app_direct',
                    'loc': CONF.get('location', 'repeaterbook'),
                    'dist': int(CONF.get('distance', 'repeaterbook')),
                    'band': CONF.get('band', 'repeaterbook') or '%',
                }
            except (TypeError, ValueError):
                raise Exception('Distance must be a number!')
