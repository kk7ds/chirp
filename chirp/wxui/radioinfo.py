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

import wx
import wx.propgrid

from chirp.drivers import icf
from chirp import util
from chirp.wxui import common


class ChirpRadioInfo(common.ChirpEditor, common.ChirpSyncEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpRadioInfo, self).__init__(*a, **k)

        self._radio = radio
        self._features = radio.get_features()

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self._group_control = wx.Listbook(self, style=wx.LB_LEFT)
        sizer.Add(self._group_control, 1, wx.EXPAND)

        self._add_features_group()
        self._add_vendor()
        self._add_metadata()
        self._add_driver()

    def _add_features_group(self):
        pg = wx.propgrid.PropertyGrid(
            self, style=wx.propgrid.PG_SPLITTER_AUTO_CENTER)
        self._group_control.AddPage(pg, _('Features'))

        for key in self._features._valid_map.keys():
            value = getattr(self._features, key)
            if isinstance(value, list):
                value = ','.join(str(v) or _('(none)') for v in value)
            p = wx.propgrid.StringProperty(
                key, key,
                value=str(value))
            p.Enable(False)
            pg.Append(p)

        pg.Sort()

    def _add_driver(self):
        pg = wx.propgrid.PropertyGrid(
            self, style=wx.propgrid.PG_SPLITTER_AUTO_CENTER)
        self._group_control.AddPage(pg, _('Driver'))

        try:
            rclass = self._radio._orig_rclass
        except AttributeError:
            rclass = self._radio.__class__

        p = wx.propgrid.StringProperty('class', 'class',
                                       rclass.__name__)
        p.Enable(False)
        pg.Append(p)
        p = wx.propgrid.StringProperty('module', 'module',
                                       rclass.__module__)
        p.Enable(False)
        pg.Append(p)
        pg.Sort()

    def _add_vendor(self):
        # This should really be an interface on the radio, but there
        # is only one example for the moment, so just cheat.
        if not isinstance(self._radio, icf.IcomCloneModeRadio):
            return

        pg = wx.propgrid.PropertyGrid(
            self, style=wx.propgrid.PG_SPLITTER_AUTO_CENTER)
        self._group_control.AddPage(pg, 'Icom')

        attrs = dict(self._radio._icf_data)
        attrs.update({
            'modelid': ''.join('%02x' % util.byte_to_int(b)
                               for b in self._radio._model),
            'endframe': self._radio._endframe,
            'raw': self._radio._raw_frames,
            'memsize': '0x%X' % self._radio._memsize,
        })

        for key, value in attrs.items():
            p = wx.propgrid.StringProperty(
                key, key,
                value=str(value))
            p.Enable(False)
            pg.Append(p)

        pg.Sort()

    def _add_metadata(self):
        if not self._radio.metadata:
            return

        pg = wx.propgrid.PropertyGrid(
            self, style=wx.propgrid.PG_SPLITTER_AUTO_CENTER)
        self._group_control.AddPage(pg, 'Image Metadata')
        # Don't show the icom fields which are displayed elsewhere, and
        # don't dump the whole mem_extra blob in here
        exclude = ('modelid', 'endframe', 'raw', 'memsize',
                   'mem_extra')
        for key, value in self._radio.metadata.items():
            if key in exclude:
                continue
            p = wx.propgrid.StringProperty(key, key, value=str(value))
            p.Enable(False)
            pg.Append(p)

        pg.Sort()
