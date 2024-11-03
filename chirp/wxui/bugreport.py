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
import platform
import subprocess
import tempfile
import threading
import time

import requests
import wx
import wx.adv

from chirp import CHIRP_VERSION
from chirp import chirp_common
from chirp import logger
from chirp import platform as chirp_platform
from chirp.wxui import common
from chirp.wxui import config

_ = wx.GetTranslation
CONF = config.get()
BASE = CONF.get('baseurl', 'chirpmyradio') or 'https://www.chirpmyradio.com'
LOG = logging.getLogger(__name__)
ReportThreadEvent, EVT_REPORT_THREAD = wx.lib.newevent.NewCommandEvent()


def get_chirp_platform():
    """Get the proper platform name for the chirp site's field"""
    p = platform.system()
    return 'MacOS' if p == 'Darwin' else p


def get_macos_system_info(manifest):
    try:
        sp = subprocess.check_output(
            'system_profiler SPSoftwareDataType SPUSBDataType',
            shell=True)
    except Exception as e:
        sp = 'Error getting system_profiler data: %s' % e
    manifest['files']['macos_system_info.txt'] = sp


def get_linux_system_info(manifest):
    try:
        sp = subprocess.check_output('lsusb',
                                     shell=True)
    except Exception as e:
        sp = 'Error getting system data: %s' % e
    manifest['files']['linux_system_info.txt'] = sp


def get_windows_system_info(manifest):
    try:
        sp = subprocess.check_output('pnputil /enum-devices /connected',
                                     shell=True)
    except Exception as e:
        sp = 'Error getting system data: %s' % e
    manifest['files']['win_system_info.txt'] = sp


@common.error_proof()
def prepare_report(chirpmain):
    manifest = {'files': {}}

    # Copy and clean/redact config
    config._CONFIG.save()
    conf_fn = chirp_platform.get_platform().config_file('chirp.config')
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
    manifest['files']['config.txt'] = '\n'.join(clean_lines)

    # Attach the currently-open file
    editor = chirpmain.current_editorset
    if editor and isinstance(editor._radio, chirp_common.FileBackedRadio):
        tmpf = tempfile.mktemp('-capture.img', 'chirp')
        LOG.debug('Capturing focused open file %s from %s',
                  editor.filename, editor._radio)
        editor._radio.save(tmpf)
        with open(tmpf, 'rb') as f:
            manifest['files'][os.path.basename(editor.filename)] = f.read()

    # Gather system details, if available
    system = platform.system()
    if system == 'Darwin':
        LOG.debug('Capturing macOS system_profiler data')
        get_macos_system_info(manifest)
    elif system == 'Linux':
        LOG.debug('Capturing linux system info')
        get_linux_system_info(manifest)
    elif system == 'Windows':
        LOG.debug('Capturing windows system info')
        get_windows_system_info(manifest)
    else:
        LOG.debug('No system info support for %s', system)

    # Snapshot debug log last
    if logger.Logger.instance.has_debug_log_file:
        tmp = common.temporary_debug_log()
        with open(tmp) as f:
            manifest['files']['debug_log.txt'] = f.read()
        tmpf = tempfile.mktemp('.config', 'chirp')

    return manifest


class BugReportContext:
    def __init__(self, wizard, chirpmain):
        self.wizard = wizard
        self.chirpmain = chirpmain
        self.editor = chirpmain.current_editorset
        self.session = requests.Session()
        self.session.headers = {
            'User-Agent': 'CHIRP/%s' % CHIRP_VERSION,
        }

    def get_page(self, name, cls):
        if not hasattr(self, 'page_%s' % name):
            LOG.debug('Created page %s', name)
            setattr(self, 'page_%s' % name, cls(self))
        return getattr(self, 'page_%s' % name)


class BugReportPage(wx.adv.WizardPage):
    INST = ''

    def __init__(self, context):
        super().__init__(context.wizard)
        self.context = context
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        inst = wx.StaticText(self, label=self.INST,
                             style=wx.TE_CENTER)
        inst.Wrap(self.wrap_width)
        vbox.Add(inst, 0, border=20, flag=wx.EXPAND | wx.ALL)

        self._build(vbox)

    @property
    def wrap_width(self):
        return 500

    def _validate_next(self):
        return True

    def validate_next(self, *a):
        self.FindWindowById(wx.ID_FORWARD).Enable(self._validate_next())

    def validate_success(self, event):
        pass


class Start(BugReportPage):
    INST = _(
        'This tool will upload details about your system to an existing '
        'issue on the CHIRP tracker. It requires your username and '
        'password for chirpmyradio.com in order to work. Information '
        'about your system, including your debug log, config file, and '
        'any open image files will be uploaded. An attempt will '
        'be made to redact any personal information before it leaves '
        'your system.'
        )

    def _build(self, vbox):
        self.context.is_new = None
        choices = wx.Panel(self)
        cvbox = wx.BoxSizer(wx.VERTICAL)
        choices.SetSizer(cvbox)

        self.newbug = wx.RadioButton(choices, label=_('File a new bug'),
                                     style=wx.RB_GROUP)
        self.newbug.Bind(wx.EVT_RADIOBUTTON, self.validate_next)
        cvbox.Add(self.newbug, flag=wx.ALIGN_LEFT)

        self.existbug = wx.RadioButton(choices,
                                       label=_('Update an existing bug'))
        self.existbug.Bind(wx.EVT_RADIOBUTTON, self.validate_next)
        cvbox.Add(self.existbug, flag=wx.ALIGN_LEFT)

        vbox.Add(choices, 1, flag=wx.ALIGN_CENTER)

        self.validate_next()

        if not logger.Logger.instance.has_debug_log_file:
            wx.MessageDialog(
                self,
                _('The debug log file is not available when CHIRP is run '
                  'interactively from the command-line. Thus, this tool will '
                  'not upload what you expect. It is recommended that you '
                  'quit now and run CHIRP non-interactively (or with stdin '
                  'redirected to /dev/null)'),
                _('Warning'),
                style=wx.OK | wx.ICON_WARNING).ShowModal()

    def GetNext(self):
        return self.context.get_page('creds', GetCreds)

    def _validate_next(self):
        return self.newbug.GetValue() or self.existbug.GetValue()

    def validate_success(self, event):
        self.context.is_new = self.newbug.GetValue()


class GetCreds(BugReportPage):
    INST = _('Enter your username and password for chirpmyradio.com. '
             'If you do not have an account click below to create '
             'one before proceeding.')

    def _build(self, vbox):
        vbox.Add(
            wx.adv.HyperlinkCtrl(
                self, label=BASE + '/account/register',
                url=BASE + '/account/register'),
            0, border=20, flag=wx.ALIGN_CENTER)

        panel = wx.Panel(self)
        vbox.Add(panel, 1, border=20, flag=wx.EXPAND | wx.ALL)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(
            panel, label=_('Username')),
            border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        self.username = wx.TextCtrl(
            panel, value=CONF.get('chirp_user',
                                  'chirpmyradio') or '')
        self.username.Bind(wx.EVT_TEXT, self.validate_next)
        grid.Add(self.username, 1, border=20,
                 flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

        grid.Add(wx.StaticText(
            panel, label=_('Password')),
            border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)
        self.password = wx.TextCtrl(
            panel, style=wx.TE_PASSWORD,
            value=CONF.get_password('chirp_password',
                                    'chirpmyradio') or '')
        self.password.Bind(wx.EVT_TEXT, self.validate_next)
        grid.Add(self.password, 1, border=20,
                 flag=wx.EXPAND | wx.RIGHT | wx.LEFT)
        panel.SetSizer(grid)
        self.SetSizer(vbox)

        self.SetSize(480, 640)

    def _validate_next(self):
        return (len(self.username.GetValue()) > 2 and
                len(self.password.GetValue()) > 2)

    def _check_limit(self, uid):
        issue_limit = 3
        known_user = None

        try:
            start = datetime.datetime.now(datetime.timezone.utc)
            start.replace(microsecond=0)
            start -= datetime.timedelta(days=7)

            r = self.context.session.get(
                BASE + '/issues.json',
                params={'author_id': uid, 'limit': issue_limit,
                        'created_on': '>=%s' % start.date().isoformat()},
                auth=self.context.auth)
            open_issue_count = r.json()['total_count']

            # If they have open issues, check to see if they're known
            if open_issue_count > issue_limit:
                r = self.context.session.get(
                    BASE + '/users/%i.json' % uid,
                    params={'include': 'memberships'},
                    auth=self.context.auth)
                known_user = len(r.json()['user']['memberships']) > 0
        except Exception as e:
            LOG.exception('Failed to get known-user info: %s', e)
            return True

        if not known_user and open_issue_count > issue_limit:
            LOG.warning('User %i is not known and has %i open recent issues',
                        uid, open_issue_count)
            wx.MessageDialog(
                self,
                _('You have opened multiple issues within the last week. '
                  'CHIRP limits the number of issues you can open to avoid '
                  'abuse. If you really need to open another, please do so '
                  'via the website.'),
                style=wx.OK | wx.ICON_WARNING).ShowModal()
            return False
        return True

    def validate_success(self, event):
        self.context.auth = requests.auth.HTTPBasicAuth(
            self.username.GetValue(), self.password.GetValue())

        r = self.context.session.get(BASE + '/my/account.json',
                                     auth=self.context.auth)
        if r.status_code != 200:
            LOG.error('Login auth check failed: %s', r.reason)
            wx.MessageDialog(self,
                             _('Login failed: '
                               'Check your username and password'),
                             _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()
            event.Veto()
            return

        uid = r.json()['user']['id']
        LOG.debug('CHIRP login success as %i', uid)
        CONF.set('chirp_user', self.username.GetValue(), 'chirpmyradio')
        CONF.set_password('chirp_password', self.password.GetValue(),
                          'chirpmyradio')

        if self.context.is_new and not self._check_limit(uid):
            event.Veto()
            return

    def GetPrev(self):
        return self.context.page_start

    def GetNext(self):
        if self.context.is_new:
            return self.context.get_page('newbug', NewBugInfo)
        else:
            return self.context.get_page('existbug', ExistingBugInfo)


class NewBugInfo(BugReportPage):
    INST = _('Enter information about the bug including a short but '
             'meaningful subject and information about the radio model '
             '(if applicable) in question. In the next step you will have '
             'a chance to add more details about the problem.')

    def _build(self, vbox):
        self.context.bugsubj = self.context.bugmodel = None
        panel = wx.Panel(self)
        vbox.Add(panel, 1, border=20, flag=wx.EXPAND)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        grid.Add(wx.StaticText(
            panel, label=_('Bug subject:')),
            border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        self.subj = wx.TextCtrl(panel)
        self.subj.SetMaxLength(100)
        self.subj.Bind(wx.EVT_TEXT, self.validate_next)
        grid.Add(self.subj, 1, border=20,
                 flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

        grid.Add(wx.StaticText(
            panel, label=_('Radio model:')),
            border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        self.model = wx.TextCtrl(panel)
        grid.Add(self.model, 1, border=20,
                 flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

        if self.context.editor and self.context.editor._radio:
            self.model.SetValue('%s %s %s' % (
                self.context.editor._radio.VARIANT,
                self.context.editor._radio.VENDOR,
                self.context.editor._radio.MODEL))

    def _validate_next(self):
        return len(self.subj.GetValue()) > 10

    def validate_success(self, *a):
        self.context.bugsubj = self.subj.GetValue()
        self.context.bugmodel = self.model.GetValue()

    def GetPrev(self):
        return self.context.page_creds

    def GetNext(self):
        return self.context.get_page('update', BugUpdateInfo)


class ExistingBugInfo(BugReportPage):
    INST = _('Enter the bug number that should be updated')

    def _build(self, vbox):
        self.context.bugnum = None
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        panel = wx.Panel(self)
        panel.SetMinSize((self.wrap_width, -1))
        panel.SetSizer(hbox)

        hbox.Add(wx.StaticText(panel, label=_('Bug number:')),
                 0, border=20, flag=wx.LEFT | wx.RIGHT)
        self.bugnum = wx.TextCtrl(panel)
        self.bugnum.Bind(wx.EVT_TEXT, self.validate_next)
        self.bugnum.SetToolTip(
            _('This is the ticket number for an already-created issue on the '
              'chirpmyradio.com website'))
        hbox.Add(self.bugnum, 1, border=20, flag=wx.EXPAND)

        vbox.Add(panel, 0, border=20, flag=wx.ALIGN_CENTER)

    def _validate_next(self):
        return self.bugnum.GetValue().isdigit()

    def validate_success(self, event):
        self.context.bugnum = self.bugnum.GetValue()
        r = self.context.session.get(
            BASE + '/issues/%s.json' % self.context.bugnum,
            auth=self.context.auth)
        if r.status_code != 200:
            LOG.error('Failed to access issue %s: %i %s',
                      self.context.bugnum, r.status_code, r.reason)
            wx.MessageDialog(self,
                             _('Bug number not found'),
                             _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()
            event.Veto()
        else:
            LOG.debug('Validated issue %s', self.context.bugnum)

    def GetNext(self):
        return self.context.get_page('update', BugUpdateInfo)

    def GetPrev(self):
        return self.context.page_creds


class BugUpdateInfo(BugReportPage):
    INST = _('Enter details about this update. Be descriptive about what '
             'you were doing, what you expected to happen, and what '
             'actually happened.')

    def _build(self, vbox):
        self.context.bugdetails = None
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        try:
            self.details.SetHint(_('Enter information to add to the bug here'))
        except Exception:
            # Older wx doesn't allow this on multi-line fields (?)
            pass
        self.details.Bind(wx.EVT_TEXT, self.validate_next)
        vbox.Add(self.details, 1, border=20,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT)

    def _validate_next(self):
        if self.details.GetValue() == '' and self.context.is_new:
            self.details.SetValue('\n'.join([
                _('(Describe what you were doing)'),
                '',
                _('(Describe what you expected to happen)'),
                '',
                _('(Describe what actually happened instead)'),
                '',
                _('(Has this ever worked before? New radio? '
                  'Does it work with OEM software?)'),
            ]))

        return len(self.details.GetValue()) > 10

    def validate_success(self, *a):
        self.context.bugdetails = self.details.GetValue()

    def GetNext(self):
        # Always create a fresh one so it's updated
        return SubmitPage(self.context)

    def GetPrev(self):
        if self.context.is_new:
            return self.context.get_page('newbug', NewBugInfo)
        else:
            return self.context.get_page('existbug', ExistingBugInfo)


class SubmitPage(BugReportPage):
    INST = _('The following information will be submitted:')

    def _build(self, vbox):
        self.deets = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.deets, 1, border=20, flag=wx.EXPAND)

    def update(self):
        self.context.manifest = prepare_report(self.context.chirpmain)
        self.context.manifest['desc'] = self.context.bugdetails
        if self.context.is_new:
            self.context.manifest['bugsubj'] = self.context.bugsubj
            self.context.manifest['bugmodel'] = self.context.bugmodel
        else:
            self.context.manifest['issue'] = self.context.bugnum
        text = '\n'.join([
            _('Reporting a new bug: %r') % self.context.bugsubj if
            self.context.is_new else
            _('Updating bug %s') % self.context.bugnum,
            _('Files:') + ' ' + ','.join(
                self.context.manifest['files'].keys()),
            _('Detailed information') + ':\n',
            self.context.bugdetails or '',
            ])
        self.deets.SetValue(text)

    def _validate_next(self):
        self.update()
        return True

    def GetPrev(self):
        return self.context.page_update

    def GetNext(self):
        return ResultPage(self.context)


class ResultPage(BugReportPage):
    def _build(self, vbox):
        self.ran = False
        self.thread = None
        self.Bind(EVT_REPORT_THREAD, self.report_done)

        self.result = wx.StaticText(self, label='Sending report...',
                                    style=wx.TE_CENTER)
        vbox.Add(self.result, 0, border=20, flag=wx.EXPAND | wx.ALL)

        self.issuelink = wx.adv.HyperlinkCtrl(self, url=BASE)
        self.issuelink.Hide()
        vbox.Add(self.issuelink, 0, border=20, flag=wx.EXPAND | wx.ALL)

    def start_thread(self):
        self.ran = True
        LOG.debug('Preparing to submit report')

        self.thread = threading.Thread(target=self.send_report,
                                       args=(self.context.manifest,))
        self.thread.start()

    def _validate_next(self):
        if not self.ran:
            self.start_thread()
        return self.thread is None

    def send_report(self, manifest):
        LOG.info('Report thread running for issue %s',
                 manifest.get('issue', '(new)'))
        try:
            result = self._send_report(manifest)
            failed = False
        except Exception as e:
            LOG.exception('Failed to report: %s', e)
            result = str(e)
            failed = True
        wx.PostEvent(self, ReportThreadEvent(self.GetId(),
                                             result=result, failed=failed))

    def _create_bug(self, manifest):
        issue_data = {
            'issue': {
                'project_id': 1,
                'priority_id': 4,
                'subject': manifest['bugsubj'],
                'description': manifest['desc'],
                'custom_fields': [
                    {'id': 1, 'value': 'next'},
                    {'id': 2, 'value': manifest['bugmodel']},
                    {'id': 3, 'value': get_chirp_platform()},
                    {'id': 7, 'value': '1'},  # read instructions
                ]
            }
        }
        r = self.context.session.post(BASE + '/issues.json',
                                      json=issue_data,
                                      auth=self.context.auth)
        if r.status_code != 201:
            LOG.error('Failed to create issue: %i %s', r.status_code, r.reason)
            raise Exception('Failed to create new issue')
        manifest['issue'] = str(r.json()['issue']['id'])
        self.context.bugnum = manifest['issue']
        LOG.info('Created new issue %s', manifest['issue'])

    def _upload_file(self, manifest, fn):
        for i in range(3):
            LOG.debug('Uploading %s attempt %i', fn, i + 1)
            r = self.context.session.post(
                BASE + '/uploads.json',
                params={'filename': fn},
                data=manifest['files'][fn],
                headers={
                    'Content-Type': 'application/octet-stream'},
                auth=self.context.auth)
            if r.status_code >= 500:
                LOG.error('Failed to upload %s: %s %s',
                          fn, r.status_code, r.reason)
                time.sleep(2 + (2 * i))
            elif r.status_code != 201:
                LOG.error('Failed to upload %s: %s %s',
                          fn, r.status_code, r.reason)
                raise Exception('Failed to upload file')
            return r.json()['upload']['token']
        raise Exception('Failed to upload %s after multiple attempts', fn)

    def _send_report(self, manifest):
        if 'issue' not in manifest:
            self._create_bug(manifest)

        tokens = []
        for fn in manifest['files']:
            token = self._upload_file(manifest, fn)
            if fn.lower().endswith('.img'):
                ct = 'application/octet-stream'
            else:
                ct = 'text/plain'
            tokens.append({'token': token,
                           'filename': fn,
                           'content_type': ct})
        LOG.debug('File tokens: %s', tokens)

        notes = '[Uploaded from CHIRP %s]\n\n' % CHIRP_VERSION
        if not self.context.is_new:
            notes += manifest['desc']
        r = self.context.session.put(
            BASE + '/issues/%s.json' % manifest['issue'],
            json={'issue': {
                    'notes': notes,
                    'uploads': tokens,
                }},
            auth=self.context.auth)
        if r.status_code != 204:
            LOG.error('Failed to update issue %s with tokens %s: %s %s',
                      manifest['issue'], tokens, r.status_code, r.reason)
            raise Exception('Failed to update issue')

    def report_done(self, event):
        self.thread = None
        LOG.info('Report thread returned %s', event.result)
        if event.failed:
            self.result.SetLabel(
                _('Failed to send bug report:') + '\n' + event.result)
        else:
            self.result.SetLabel(
                _('Successfully sent bug report:'))
            self.FindWindowById(wx.ID_BACKWARD).Enable(False)
            link = BASE + '/issues/%s' % self.context.bugnum
            self.issuelink.SetLabel(link)
            self.issuelink.SetURL(link)
            self.issuelink.Show()
        self.validate_next()
        self.GetSizer().Layout()

    def GetNext(self):
        return None

    def GetPrev(self):
        return self.context.page_submit


def do_bugreport(parent, event):
    wizard = wx.adv.Wizard(parent)

    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED,
                lambda e: e.GetPage().validate_next())
    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGING,
                lambda e: (e.GetPage().validate_success(e)
                           if e.GetDirection() else None))

    wizard.SetPageSize((640, 400))
    context = BugReportContext(wizard, parent)
    start = context.get_page('start', Start)
    wizard.GetPageAreaSizer().Add(start)
    wizard.RunWizard(start)
    wizard.Destroy()
