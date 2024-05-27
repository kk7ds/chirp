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
import tempfile
import threading
import urllib

import wx
import wx.adv

from chirp import bandplan
from chirp.sources import base
from chirp.sources import dmrmarc
from chirp.sources import radioreference
from chirp.sources import repeaterbook
from chirp.sources import przemienniki
from chirp.wxui import common
from chirp.wxui import config

_ = wx.GetTranslation
CONF = config.get()
LOG = logging.getLogger(__name__)
QueryThreadEvent, EVT_QUERY_THREAD = wx.lib.newevent.NewCommandEvent()


class NumberValidator(wx.Validator):
    THING = _('Number')
    MIN = 0
    MAX = 1
    OPTIONAL = True

    def Validate(self, window):
        textctrl = self.GetWindow()
        strvalue = textctrl.GetValue()
        if not strvalue and self.OPTIONAL:
            return True
        try:
            v = float(strvalue)
            assert v >= self.MIN and v <= self.MAX
            textctrl.SetBackgroundColour(
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            return True
        except ValueError:
            msg = _('Invalid %(value)s (use decimal degrees)')
        except AssertionError:
            msg = _('%(value)s must be between %(min)i and %(max)i')
        textctrl.SetFocus()
        textctrl.SetBackgroundColour('pink')
        catalog = {'value': self.THING,
                   'min': self.MIN,
                   'max': self.MAX}
        wx.MessageBox(msg % catalog, _('Invalid Entry'))
        return False

    def Clone(self):
        return self.__class__()

    def TransferToWindow(self):
        return True

    def SetWindow(self, win):
        super().SetWindow(win)
        # Clear the validation failure background color as soon as the value
        # changes to avoid asking them to click OK on a dialog with a warning
        # sign.
        win.Bind(wx.EVT_TEXT, self._colorchange)

    def _colorchange(self, event):
        self.GetWindow().SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))


class LatValidator(NumberValidator):
    THING = _('Latitude')
    MIN = -90
    MAX = 90


class LonValidator(NumberValidator):
    THING = _('Longitude')
    MIN = -180
    MAX = 180


class DistValidator(NumberValidator):
    THING = _('Distance')
    MIN = 0
    MAX = 7000


class ZipValidator(wx.Validator):
    def Validate(self, window):
        textctrl = self.GetWindow()
        strvalue = textctrl.GetValue()
        if len(strvalue) == 5 and strvalue.isdigit():
            return True
        wx.MessageBox(_('Invalid ZIP code'), 'Invalid Entry')
        return False

    def Clone(self):
        return self.__class__()

    def TransferToWindow(self):
        return True


class QueryThread(threading.Thread, base.QueryStatus):
    END_SENTINEL = object()

    def __init__(self, *a, **k):
        self.query_dialog = a[0]
        self.radio = a[1]
        super(QueryThread, self).__init__(*a[2:], **k)
        self.status_queue = queue.Queue()

    def run(self):
        try:
            self.radio.do_fetch(self, self.query_dialog.get_params())
        except Exception as e:
            LOG.exception('Failed to execute query: %s' % e)
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
        self.result_radio = None

        vbox = self.build()
        self.Center()

        self.statusmsg = wx.StaticText(
            self, label='',
            style=(wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ST_ELLIPSIZE_END))
        vbox.Add(self.statusmsg, proportion=0, border=5,
                 flag=wx.EXPAND | wx.BOTTOM)

        self.gauge = wx.Gauge(self)
        self.gauge.SetRange(100)
        vbox.Add(self.gauge, proportion=0, border=10,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT)

        link_label = urllib.parse.urlparse(self.get_link()).netloc
        link = wx.adv.HyperlinkCtrl(vbox.GetContainingWindow(),
                                    label=link_label, url=self.get_link(),
                                    style=wx.adv.HL_ALIGN_CENTRE)
        vbox.Insert(0, link, proportion=0, border=10,
                    flag=(wx.LEFT | wx.RIGHT | wx.BOTTOM |
                          wx.ALIGN_CENTER_HORIZONTAL))
        info = wx.StaticText(vbox.GetContainingWindow(),
                             style=wx.ALIGN_CENTER_HORIZONTAL)
        info.SetLabelMarkup(self.get_info())
        vbox.Insert(0, info, proportion=0, border=10,
                    flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP)

        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(bs, border=10, flag=wx.ALL)
        self.Bind(wx.EVT_BUTTON, self._button)

        self.Bind(EVT_QUERY_THREAD, self._got_status)

        self.SetMinSize((400, 200))
        self.Fit()
        wx.CallAfter(self.Center)

        vbox.GetContainingWindow().InitDialog()

        self.result_file = tempfile.NamedTemporaryFile(
            prefix='%s-' % self.NAME,
            suffix='.csv').name

    def _call_validations(self, parent):
        for child in parent.GetChildren():
            if not child.Validate():
                return False
            self._call_validations(child)
        return True

    def _button(self, event):
        id = event.GetEventObject().GetId()

        if id == wx.ID_OK:
            if not self._call_validations(self):
                return
            self.FindWindowById(wx.ID_OK).Disable()
            self.do_query()
            return

        self.EndModal(id)

    def build(self):
        pass

    def do_query(self):
        LOG.info('Starting QueryThread for %s' % self.result_radio)
        LOG.debug('Query Parameters: %s' % self.get_params())
        QueryThread(self, self.result_radio).start()

    def get_params(self):
        pass

    def get_info(self):
        return ''

    def get_link(self):
        return ''

    def status(self, status, percent):
        wx.PostEvent(self, QueryThreadEvent(self.GetId(),
                                            status=status, percent=percent))

    def end(self):
        self.status(None, 100)

    def fail(self, reason):
        self.status(reason, 100)

    def _got_status(self, event):
        self.gauge.SetValue(int(event.percent))
        if event.status is None:
            self.EndModal(wx.ID_OK)
        else:
            self.statusmsg.SetLabel(event.status)
        if event.percent == 100:
            self.FindWindowById(wx.ID_OK).Enable()


class RepeaterBookQueryDialog(QuerySourceDialog):
    NAME = 'Repeaterbook'

    def get_info(self):
        return _(
            "RepeaterBook is Amateur Radio's most comprehensive,\n"
            "worldwide, FREE repeater directory.")

    def get_link(self):
        return 'https://repeaterbook.com'

    def build(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, proportion=1, border=10,
                 flag=wx.EXPAND | wx.BOTTOM)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        self._country = wx.Choice(panel, choices=repeaterbook.COUNTRIES)
        prev = CONF.get('country', 'repeaterbook')
        if prev and prev in repeaterbook.COUNTRIES:
            self._country.SetStringSelection(prev)
        else:
            self._country.SetStringSelection(repeaterbook.NA_COUNTRIES[0])
        self._country.Bind(wx.EVT_CHOICE, self._state_selected)
        self._add_grid(grid, _('Country'), self._country)

        self._service = wx.Choice(panel, choices=[_('Amateur'),
                                                  _('GMRS')])
        self._service.Bind(wx.EVT_CHOICE, self._service_selected)
        self._add_grid(grid, _('Service'), self._service)

        self._state = wx.Choice(panel, choices=[])
        self._add_grid(grid, _('State/Province'), self._state)

        self._lat = wx.TextCtrl(panel,
                                value=CONF.get('lat', 'repeaterbook') or '',
                                validator=LatValidator())
        self._lat.SetHint(_('Optional: 45.0000'))
        self._lat.SetToolTip(_('If set, sort results by distance from '
                               'these coordinates'))
        self._lon = wx.TextCtrl(panel,
                                value=CONF.get('lon', 'repeaterbook') or '',
                                validator=LonValidator())
        self._lon.SetHint(_('Optional: -122.0000'))
        self._lon.SetToolTip(_('If set, sort results by distance from '
                               'these coordinates'))
        self._add_grid(grid, _('Latitude'), self._lat)
        self._add_grid(grid, _('Longitude'), self._lon)

        self._dist = wx.TextCtrl(panel,
                                 value=CONF.get('dist', 'repeaterbook') or '',
                                 validator=DistValidator())
        self._dist.SetHint(_('Optional: 100'))
        self._dist.SetToolTip(_('Limit results to this distance (km) from '
                                'coordinates'))
        self._add_grid(grid, _('Distance'), self._dist)

        self._search = wx.TextCtrl(panel)
        self._search.SetHint(_('Optional: County, Hospital, etc.'))
        self._search.SetToolTip(_('Filter results with location matching '
                                  'this string'))
        self._add_grid(grid, _('Filter'), self._search)

        self._bands = bandplan.BandPlans(CONF).get_repeater_bands()
        self._limit_bands = []
        self._bandfilter = wx.CheckBox(panel, label=_('Only certain bands'))
        self.Bind(wx.EVT_CHECKBOX, self._select_bands, self._bandfilter)
        self._add_grid(grid, _('Limit Bands'), self._bandfilter)

        self._limit_modes = list(repeaterbook.MODES)
        self._modefilter = wx.CheckBox(panel, label=_('Only certain modes'))
        self.Bind(wx.EVT_CHECKBOX, self._select_modes, self._modefilter)
        self._add_grid(grid, _('Limit Modes'), self._modefilter)

        self._openonly = wx.CheckBox(panel, label=_('Open repeaters only'))
        self._openonly.SetValue(CONF.get_bool('openonly', 'repeaterbook'))
        self._openonly.SetToolTip(_('Exclude private and closed repeaters'))
        self._add_grid(grid, _('Limit use'), self._openonly)

        self._fmconv = wx.CheckBox(panel, label=_('Convert to FM'))
        self._fmconv.SetValue(CONF.get_bool('fmconv', 'repeaterbook'))
        self._fmconv.SetToolTip(_('Dual-mode digital repeaters that support '
                                  'analog will be shown as FM'))
        self._add_grid(grid, _('Digital Modes'), self._fmconv)

        self._state_selected(None)
        self._service_selected(None)

        self.Layout()
        return vbox

    def _service_selected(self, event):
        is_gmrs = _('GMRS') in self._service.GetStringSelection()
        self._bandfilter.Enable(not is_gmrs)
        self._modefilter.Enable(not is_gmrs)

    def _state_selected(self, event):
        country = self._country.GetStringSelection()
        if country == 'United States':
            self._service.Enable(True)
            self._service.SetStringSelection(
                CONF.get('service', 'repeaterbook') or _('Amateur'))
        else:
            self._service.Enable(False)
            self._service.SetSelection(0)

        try:
            states = repeaterbook.STATES[country]
        except KeyError:
            self._state.SetItems([_('All')])
            self._state.Enable(False)
            return
        self._state.SetItems(states)
        self._state.Enable(True)
        prev = CONF.get('state', 'repeaterbook')
        if prev and prev in states:
            self._state.SetStringSelection(prev)
        else:
            self._state.SetStringSelection(states[0])

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def _select_bands(self, event):
        if not self._bandfilter.IsChecked():
            self._limit_bands = []
            return

        band_names = [x.name for x in self._bands]
        d = wx.MultiChoiceDialog(self, _('Select Bands'), _('Bands'),
                                 choices=band_names)
        prev = CONF.get('bands', 'repeaterbook') or ''
        d.SetSelections([i for i, band in enumerate(self._bands)
                         if band.name in prev.split(',')])
        r = d.ShowModal()
        if r == wx.ID_CANCEL or not d.GetSelections():
            self._bandfilter.SetValue(False)
            self._limit_bands = []
        else:
            self._limit_bands = [self._bands[i].limits
                                 for i in d.GetSelections()]
            CONF.set('bands', ','.join(self._bands[i].name
                                       for i in d.GetSelections()),
                     'repeaterbook')

    def _select_modes(self, event):
        if not self._modefilter.IsChecked():
            self._limit_modes = []
            return

        d = wx.MultiChoiceDialog(self, _('Select Modes'), _('Modes'),
                                 choices=repeaterbook.MODES)
        r = d.ShowModal()
        if r == wx.ID_CANCEL or not d.GetSelections():
            self._modefilter.SetValue(False)
            self._limit_modes = []
        else:
            self._limit_modes = [repeaterbook.MODES[i]
                                 for i in d.GetSelections()]

    def do_query(self):
        CONF.set('lat', self._lat.GetValue(), 'repeaterbook')
        CONF.set('lon', self._lon.GetValue(), 'repeaterbook')
        CONF.set('dist', self._dist.GetValue(), 'repeaterbook')
        CONF.set('state', self._state.GetStringSelection(), 'repeaterbook')
        CONF.set('country', self._country.GetStringSelection(), 'repeaterbook')
        CONF.set('service', self._service.GetStringSelection(), 'repeaterbook')
        CONF.set_bool('fmconv', self._fmconv.IsChecked(), 'repeaterbook')
        CONF.set_bool('openonly', self._openonly.IsChecked(), 'repeaterbook')
        self.result_radio = repeaterbook.RepeaterBook()
        super().do_query()

    def get_params(self):
        service = self._service.GetStringSelection()
        return {
            'country': self._country.GetStringSelection(),
            'state': self._state.GetStringSelection(),
            'lat': self._lat.GetValue(),
            'lon': self._lon.GetValue(),
            'dist': self._dist.GetValue(),
            'filter': self._search.GetValue(),
            'bands': self._limit_bands,
            'modes': self._limit_modes,
            'service': 'gmrs' if service == _('GMRS') else '',
            'service_display': self._service.GetStringSelection(),
            'fmconv': self._fmconv.IsChecked(),
            'openonly': self._openonly.IsChecked(),
        }


class DMRMARCQueryDialog(QuerySourceDialog):
    NAME = 'DMR-MARC'

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, 1, flag=wx.EXPAND | wx.ALL, border=20)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        self._city = wx.TextCtrl(panel,
                                 value=CONF.get('city', 'dmrmarc') or '')
        self._add_grid(grid, _('City'), self._city)
        self._state = wx.TextCtrl(panel,
                                  value=CONF.get('state', 'dmrmarc') or '')
        self._add_grid(grid, _('State'), self._state)
        self._country = wx.TextCtrl(panel,
                                    value=CONF.get('country', 'dmrmarc') or '')
        self._add_grid(grid, _('Country'), self._country)

        return vbox

    def get_info(self):
        return _('The DMR-MARC Worldwide Network')

    def get_link(self):
        return 'https://www.dmr-marc.net'

    def do_query(self):
        CONF.set('city', self._city.GetValue(), 'dmrmarc')
        CONF.set('state', self._state.GetValue(), 'dmrmarc')
        CONF.set('country', self._country.GetValue(), 'dmrmarc')
        self.result_radio = dmrmarc.DMRMARCRadio()
        super().do_query()

    def get_params(self):
        return {'city': CONF.get('city', 'dmrmarc'),
                'state': CONF.get('state', 'dmrmarc'),
                'country': CONF.get('country', 'dmrmarc')}


class PrzemiennikiQueryDialog(QuerySourceDialog):
    NAME = 'przemienniki.net'
    _section = 'przemienniki'
    _countries = sorted(
        ['at', 'bg', 'by', 'ch', 'cz', 'de', 'dk', 'es', 'fi',
         'fr', 'hu', 'is', 'it', 'lt', 'lv', 'no', 'nl', 'pl',
         'ro', 'ru', 'se', 'si', 'sk', 'ua', 'uk'])
    _bands = ['10m', '4m', '6m', '2m', '70cm',
              '23cm', '13cm', '3cm']
    _modes = ['FM', 'MOTOTRBO', 'DSTAR', 'C4FM', 'ECHOLINK',
              'FMLINK', 'APCO25', 'ATV']

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, 1, flag=wx.EXPAND | wx.ALL, border=20)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        # Mode
        self._mode = wx.Choice(panel, choices=self._modes)
        prev = CONF.get('mode', self._section)

        if prev and prev in self._modes:
            self._mode.SetStringSelection(prev)
        else:
            self._mode.SetStringSelection(self._modes[0])
        self._add_grid(grid, _('Mode'), self._mode)

        # Band selection
        if CONF.is_defined('band', self._section):
            CONF.remove_option('band', self._section)

        self._bandfilter = wx.CheckBox(panel, label=_('Only certain bands'))
        self.Bind(wx.EVT_CHECKBOX, self._select_bands, self._bandfilter)
        self._add_grid(grid, _('Limit Bands'), self._bandfilter)

        # Only working
        if CONF.is_defined('workingstatus', self._section):
            self._limit_onlyworking = CONF.get_bool('workingstatus',
                                                    self._section)
        else:
            self._limit_onlyworking = True
        self._onlyworkingfilter = wx.CheckBox(panel,
                                              label=_('Only working repeaters')
                                              )
        self._onlyworkingfilter.SetValue(self._limit_onlyworking)
        CONF.set_bool('workingstatus', self._limit_onlyworking, self._section)
        self.Bind(wx.EVT_CHECKBOX, self._select_workingstatus,
                  self._onlyworkingfilter)
        self._add_grid(grid, _('Limit Status'), self._onlyworkingfilter)

        # Country
        self._country = wx.Choice(panel, choices=self._countries)
        prev = CONF.get('country', self._section)

        if prev and prev in self._countries:
            self._country.SetStringSelection(prev)
        else:
            self._country.SetStringSelection('pl')
        self._add_grid(grid, _('Country'), self._country)

        # Coordinates
        self._lat = wx.TextCtrl(panel,
                                value=CONF.get('lat', 'repeaterbook') or '',
                                validator=LatValidator())
        self._lat.SetHint(_('Optional: 45.0000'))
        self._lat.SetToolTip(_('If set, sort results by distance from '
                               'these coordinates'))
        self._lon = wx.TextCtrl(panel,
                                value=CONF.get('lon', 'repeaterbook') or '',
                                validator=LonValidator())
        self._lon.SetHint(_('Optional: -122.0000'))
        self._lon.SetToolTip(_('If set, sort results by distance from '
                               'these coordinates'))
        self._add_grid(grid, _('Latitude'), self._lat)
        self._add_grid(grid, _('Longitude'), self._lon)
        self._dist = wx.TextCtrl(panel,
                                 value=CONF.get('dist', 'repeaterbook') or '',
                                 validator=DistValidator())
        self._dist.SetHint(_('Optional: 100'))
        self._dist.SetToolTip(_('Limit results to this distance (km) from '
                                'coordinates'))
        self._add_grid(grid, _('Distance'), self._dist)

        return vbox

    def _select_workingstatus(self, event):
        if not self._onlyworkingfilter.IsChecked():
            self._limit_onlyworking = False
        else:
            self._limit_onlyworking = True
        CONF.set_bool('workingstatus', self._limit_onlyworking, self._section)
        return

    def _select_bands(self, event):
        if not self._bandfilter.IsChecked():
            CONF.set('band', '', self._section)
            return

        band_names = [x for x in self._bands]
        d = wx.MultiChoiceDialog(self, _('Select Bands'), _('Bands'),
                                 choices=band_names)

        d.SetSelections([i for i, band in enumerate(self._bands)
                         if band in ['2m', '70cm']])
        r = d.ShowModal()
        if r == wx.ID_CANCEL or not d.GetSelections():
            self._bandfilter.SetValue(False)
        else:
            CONF.set('band', ','.join(self._bands[i]
                     for i in d.GetSelections()),
                     self._section)

    def get_info(self):
        return _('FREE repeater database, which provides most up-to-date\n'
                 'information about repeaters in Europe. No account is\n'
                 'required.')

    def get_link(self):
        return 'https://przemienniki.net'

    def do_query(self):
        CONF.set('country', self._country.GetStringSelection(), self._section)
        CONF.set('mode', self._mode.GetStringSelection(), self._section)
        CONF.set('lat', self._lat.GetValue(), 'repeaterbook')
        CONF.set('lon', self._lon.GetValue(), 'repeaterbook')
        CONF.set('dist', self._dist.GetValue(), 'repeaterbook')
        self.result_radio = przemienniki.Przemienniki()
        super().do_query()

    def get_params(self):
        params = {
            'country': CONF.get('country', self._section),
            'band': CONF.get('band', self._section),
            'mode': CONF.get('mode', self._section).lower(),
            'latitude': CONF.get('lat', 'repeaterbook'),
            'longitude': CONF.get('lon', 'repeaterbook'),
            'range': CONF.get('dist', 'repeaterbook'),
        }

        if CONF.get_bool('workingstatus', self._section):
            params['onlyworking'] = 'Yes'

        return params


class RRQueryDialog(QuerySourceDialog):
    NAME = 'RadioReference'

    def get_info(self):
        return _(
            "RadioReference.com is the world's largest\n"
            "radio communications data provider\n"
            "<small>Premium account required</small>")

    def get_link(self):
        return (
            'https://support.radioreference.com/hc/en-us/articles/'
            '18860633200276-Programming-Using-the-RadioReference-Web-Service')

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        self.result_radio = radioreference.RadioReferenceRadio()
        self.tabs = wx.Notebook(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(3, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)
        vbox.Add(panel, proportion=0, flag=wx.EXPAND)

        # build the login elements
        self._rrusername = wx.TextCtrl(
            panel, value=CONF.get('username', 'radioreference') or '')
        self._add_grid(grid, 'Username', self._rrusername)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)

        self._rrpassword = wx.TextCtrl(
            panel, style=wx.TE_PASSWORD,
            value=CONF.get_password('password',
                                    'radioreference') or '')
        self._add_grid(grid, 'Password', self._rrpassword)

        vbox.Add(self.tabs, proportion=1, border=10,
                 flag=wx.EXPAND | wx.BOTTOM | wx.TOP)
        self.tabs.InsertPage(0, self.build_us(self.tabs), _('United States'))
        self.tabs.InsertPage(1, self.build_ca(self.tabs), _('Canada'))

        return vbox

    def _call_validations(self, parent):
        if parent == self:
            # If we're calling validations at the top-level, redirect that to
            # the start of our country-specific widgets, based on whatever tab
            # is selected. This avoids trying to validate US things when
            # Canada is selected and so on.
            parent = self.tabs.GetPage(self.tabs.GetSelection())
        return super()._call_validations(parent)

    def build_ca(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(3, 5, 0)
        grid.AddGrowableCol(1)

        # build a new login button
        self._loginbutton = wx.Button(panel, label='Log In')
        grid.Add(self._loginbutton)
        self._loginbutton.Bind(wx.EVT_BUTTON, self._populateca)

        # build a prov/county selector grid & add selectors
        self._provchoice = wx.Choice(panel, choices=['Log in First'])
        self.Bind(wx.EVT_CHOICE, self.selected_province, self._provchoice)
        self._add_grid(grid, 'Province', self._provchoice)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)

        self._countychoice = wx.Choice(panel, choices=['Log in First'])
        self._add_grid(grid, 'County', self._countychoice)
        self.Bind(wx.EVT_CHOICE, self.selected_county, self._countychoice)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)

        if radioreference.CA_PROVINCES:
            self.populateprov()

        panel.SetSizer(grid)
        return panel

    def build_us(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)
        self._uszip = wx.TextCtrl(
            panel,
            value=CONF.get('zipcode', 'radioreference') or '',
            validator=ZipValidator())
        self._add_grid(grid, 'ZIP Code', self._uszip)

        return panel

    def _populateca(self, event):
        button = event.GetEventObject()
        button.Disable()
        okay = self.FindWindowById(wx.ID_OK)
        okay.Disable()

        def cb(result):
            wx.CallAfter(okay.Enable)
            if isinstance(result, Exception):
                self.status('Failed: %s' % result, 0)
                wx.CallAfter(button.Enable)
            else:
                self.status('Logged in', 0)
                wx.CallAfter(self.populateprov)
        self.status('Attempting login...', 0)
        radioreference.RadioReferenceCAData(
            cb,
            self._rrusername.GetValue(),
            self._rrpassword.GetValue()).start()

    def populateprov(self):
        self._provchoice.SetItems([str(x) for x in
                                   radioreference.CA_PROVINCES.keys()])
        self.getconfdefaults()
        self._provchoice.SetStringSelection(self.default_prov)
        self._selected_province(self.default_prov)
        self._countychoice.SetStringSelection(self.default_county)
        self._selected_county(self.default_county)
        self._loginbutton.Enable(False)

    def getconfdefaults(self):
        code = CONF.get("province", "radioreference")
        for k, v in radioreference.CA_PROVINCES.items():
            if code == str(v):
                self.default_prov = k
                break
            else:
                self.default_prov = "BC"
        code = CONF.get("county", "radioreference")
        for row in radioreference.CA_COUNTIES:
            if code == str(row[2]):
                self.default_county = row[3]
                break
            else:
                self.default_county = 0
        LOG.debug('Default province=%r county=%r' % (self.default_prov,
                                                     self.default_county))

    def selected_province(self, event):
        self._selected_province(event.GetEventObject().GetStringSelection())

    def _selected_province(self, chosenprov):
        # if user alters the province dropdown, load the new counties into
        # the county dropdown choice
        for name, id in radioreference.CA_PROVINCES.items():
            if name == chosenprov:
                CONF.set_int('province', id, 'radioreference')
                LOG.debug('Province id %s for %s' % (id, name))
                break
        self._countychoice.Clear()
        for x in radioreference.CA_COUNTIES:
            if x[1] == chosenprov:
                self._countychoice.Append(x[3])
        self._selected_county(self._countychoice.GetItems()[0])

    def selected_county(self, event):
        self._selected_county(self._countychoice.GetStringSelection())

    def _selected_county(self, chosencounty):
        self._ca_county_id = 0
        for _u, _prov, cid, county in radioreference.CA_COUNTIES:
            if county == chosencounty:
                self._ca_county_id = cid
                break
        CONF.set_int('county', self._ca_county_id, 'radioreference')
        LOG.debug('County id %s for %s' % (self._ca_county_id, chosencounty))

    @common.error_proof()
    def do_query(self):
        CONF.set('username', self._rrusername.GetValue(), 'radioreference')
        CONF.set_password('password', self._rrpassword.GetValue(),
                          'radioreference')

        CONF.set('zipcode', self._uszip.GetValue(), 'radioreference')

        self.result_radio.set_auth(
            CONF.get('username', 'radioreference'),
            CONF.get_password('password', 'radioreference'))

        if self.tabs.GetSelection() == 1:
            # CA
            if not radioreference.CA_PROVINCES:
                raise Exception(_('RadioReference Canada requires a login '
                                  'before you can query'))

        super().do_query()

    def get_params(self):
        if self.tabs.GetSelection() == 0:
            # US
            return {'zipcounty': self._uszip.GetValue(),
                    'country': 'US'}
        else:
            # CA
            return {'zipcounty': '%s' % self._ca_county_id,
                    'country': 'CA'}
