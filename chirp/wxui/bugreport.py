# Copyright 2024 Dan Smith <chirp@f.danplanet.com>
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

import datetime
import logging
import os
import tempfile
import threading

import requests
import wx

from chirp import CHIRP_VERSION
from chirp import chirp_common
from chirp import logger
from chirp import platform
from chirp.wxui import common
from chirp.wxui import config

CONF = config.get()
BASE = 'https://www.chirpmyradio.com'
LOG = logging.getLogger(__name__)
ReportThreadEvent, EVT_REPORT_THREAD = wx.lib.newevent.NewCommandEvent()


class BugReportDialog(wx.Dialog):
    def _add_grid_label(self, grid, label, thing):
        grid.Add(wx.StaticText(thing.GetParent(), label=label))
        grid.Add(thing, flag=wx.EXPAND)

    def __init__(self, parent):
        super().__init__(parent, title=_('Send bug details'))
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        instructions = _(
            'This tool will upload details about your system to an existing '
            'issue on the CHIRP tracker. It requires your username and '
            'password for chirpmyradio.com in order to work. Information '
            'about your system, including your debug log, config file, and '
            'any open image files will be uploaded. An attempt will '
            'be made to redact any personal information before it leaves '
            'your system.'
            )
        inst = wx.StaticText(self, label=instructions)
        inst.Wrap(400)
        vbox.Add(inst, border=10, flag=wx.EXPAND | wx.ALL)

        panel = wx.Panel(self)
        vbox.Add(panel, proportion=0, border=10, flag=wx.EXPAND | wx.ALL)
        grid = wx.FlexGridSizer(2, 5, 5)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        self.user = wx.TextCtrl(panel, value=CONF.get('chirp_user',
                                                      'chirpmyradio') or '')
        self._add_grid_label(grid, _('Username'), self.user)
        self.password = wx.TextCtrl(panel, style=wx.TE_PASSWORD,
                                    value=CONF.get_password(
                                        'chirp_password',
                                        'chirpmyradio') or '')
        self._add_grid_label(grid, _('Password'), self.password)
        self.issue = wx.TextCtrl(panel)
        self.issue.SetHint('12345')
        self.issue.SetToolTip(_('This is the ticket number for an '
                                'already-created issue on the '
                                'chirpmyradio.com website'))
        self._add_grid_label(grid, _('Issue Number'), self.issue)
        self.desc = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        self.desc.SetHint('Optional notes...')
        self._add_grid_label(grid, _('Notes'), self.desc)

        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(bs, border=10, flag=wx.ALL)
        self.Bind(wx.EVT_BUTTON, self.action)
        self.Bind(EVT_REPORT_THREAD, self._finished)
        self.report_thread = None
        self.cancel_event = threading.Event()
        self.Fit()
        if not logger.Logger.instance.has_debug_log_file:
            wx.MessageDialog(
                self,
                _('The debug log file is not available when CHIRP is run '
                  'interactively from the command-line. Thus, this tool will '
                  'not upload what you expect. It is recomended that you '
                  'quit now and run CHIRP non-interactively (or with stdin '
                  'redirected to /dev/null)'),
                _('Warning'),
                style=wx.OK | wx.ICON_WARNING).ShowModal()

    def action(self, event):
        CONF.set('chirp_user', self.user.GetValue(), 'chirpmyradio')
        CONF.set_password('chirp_password', self.password.GetValue(),
                          'chirpmyradio')
        if event.GetEventObject().GetId() == wx.ID_CANCEL:
            LOG.info('User Canceled')
            if self.report_thread:
                self.cancel_event.set()
            self.Hide()
            return

        try:
            int(self.issue.GetValue())
        except ValueError:
            wx.MessageDialog(self, _('Issue must be a number!'),
                             _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()
            event.StopPropagation()
            return

        if not (self.user.GetValue().strip() and
                self.password.GetValue().strip()):
            wx.MessageDialog(self, _('Username and password are required!'),
                             _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()
            event.StopPropagation()
            return

        self.FindWindowById(wx.ID_OK).Disable()
        manifest = self.prepare_report()
        self.report_thread = threading.Thread(target=self.send_report,
                                              args=(manifest,))
        self.report_thread.start()
        LOG.debug('Started report thread')

    @common.error_proof()
    def prepare_report(self):
        manifest = {
            'username': self.user.GetValue(),
            'password': self.password.GetValue(),
            'issue': self.issue.GetValue(),
            'desc': self.desc.GetValue(),
        }

        # Copy and clean/redact config
        config._CONFIG.save()
        conf_fn = platform.get_platform().config_file('chirp.config')
        LOG.debug('Capturing config file %s stamped %s', conf_fn,
                  datetime.datetime.fromtimestamp(
                      os.stat(conf_fn).st_mtime).isoformat())
        with open(conf_fn) as f:
            config_lines = f.readlines()
        clean_lines = []
        for line in list(config_lines):
            if 'password' in line:
                key, value = line.split('=', 1)
                value = '***REDACTED***'
                line = '%s = %s' % (key.strip(), value)
            clean_lines.append(line.strip())
        manifest['config.txt'] = '\n'.join(clean_lines)

        editor = self.GetParent().current_editorset
        if editor and isinstance(editor._radio, chirp_common.FileBackedRadio):
            tmpf = tempfile.mktemp('-capture.img', 'chirp')
            LOG.debug('Capturing focused open file %s from %s',
                      editor.filename, editor._radio)
            editor._radio.save(tmpf)
            with open(tmpf, 'rb') as f:
                manifest['image'] = f.read()
            manifest['image_fn'] = editor.filename

        if logger.Logger.instance.has_debug_log_file:
            # Snapshot debug log last
            tmp = common.temporary_debug_log()
            with open(tmp) as f:
                manifest['debug_log.txt'] = f.read()
            tmpf = tempfile.mktemp('.config', 'chirp')

        return manifest

    def send_report(self, manifest):
        LOG.info('Report thread running for issue %s', manifest['issue'])
        try:
            result = self._send_report(manifest)
        except Exception as e:
            LOG.exception('Failed to report: %s', e)
            result = str(e)
        wx.PostEvent(self, ReportThreadEvent(self.GetId(), result=result))

    def _send_report(self, manifest):
        auth = requests.auth.HTTPBasicAuth(manifest['username'],
                                           manifest['password'])
        session = requests.Session()
        session.headers = {'User-Agent': 'CHIRP/%s' % CHIRP_VERSION}
        r = session.get(BASE + '/my/account.json', auth=auth)
        if r.status_code != 200:
            LOG.error('Login auth check failed: %s', r.reason)
            raise Exception('Login failed (check user/password)')

        r = session.get(BASE + '/issues/%s.json' % manifest['issue'],
                        auth=auth)
        if r.status_code != 200:
            LOG.error('Failed to access issue %s: %i %s',
                      manifest['issue'], r.status_code, r.reason)
            raise Exception('Issue not found')

        tokens = []
        for fn in ('config.txt', 'debug_log.txt', 'image'):
            if fn not in manifest:
                LOG.warning('No %s in manifest to upload', fn)
                continue
            LOG.debug('Uploading %s', fn)
            r = session.post(BASE + '/uploads.json',
                             params={'filename': fn},
                             data=manifest[fn],
                             headers={
                                 'Content-Type': 'application/octet-stream'},
                             auth=auth)
            if r.status_code != 201:
                LOG.error('Failed to upload %s: %s %s',
                          fn, r.status_code, r.reason)
                raise Exception('Failed to upload file')
            if fn == 'image':
                fn = manifest['image_fn']
                ct = 'application/octet-stream'
            else:
                ct = 'text/plain'
            tokens.append({'token': r.json()['upload']['token'],
                           'filename': fn,
                           'content_type': ct})
        LOG.debug('File tokens: %s', tokens)

        header = '[Uploaded from CHIRP %s]\n\n' % CHIRP_VERSION
        r = session.put(BASE + '/issues/%s.json' % manifest['issue'],
                        json={'issue': {
                                'notes': (header + manifest['desc']),
                                'uploads': tokens,
                            }},
                        auth=auth)
        if r.status_code != 204:
            LOG.error('Failed to update issue %s with tokens %s: %s %s',
                      manifest['issue'], tokens, r.status_code, r.reason)
            raise Exception('Failed to update issue')

        return 'success'

    def _finished(self, event):
        self.report_thread = None
        if self.cancel_event.is_set():
            LOG.warning('Thread finished but was canceled (%s)', event.result)
            return
        LOG.info('Report done: %s' % event.result)
        if event.result == 'success':
            wx.MessageDialog(self, _('Details successfully uploaded'),
                             _('Success'),
                             style=wx.OK | wx.ICON_INFORMATION).ShowModal()
            self.Hide()
        else:
            wx.MessageDialog(self,
                             _('Failed to upload details: %s') % event.result,
                             _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()
            self.FindWindowById(wx.ID_OK).Enable()

    @staticmethod
    def do_report(mainwindow, event):
        logging.getLogger('requests').setLevel(logging.DEBUG)
        brd = BugReportDialog(mainwindow)
        brd.Center()
        brd.Show()
