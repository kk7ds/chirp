# Copyright 2026 CHIRP Development Team
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

"""Help > Install Linux Launcher... GUI handler.

This module only gathers user choices, asks for confirmation, and
presents results -- all of the actual filesystem/permission work lives
in chirp.linux_desktop, which has no wx dependency and is unit tested
directly.
"""

import logging

import wx

from chirp import linux_desktop
from chirp.wxui import common

_ = wx.GetTranslation
LOG = logging.getLogger(__name__)


class LinuxLauncherDialog(wx.Dialog):
    """Confirms which launcher(s) to install for a detected AppImage."""

    def __init__(self, parent, status):
        super().__init__(
            parent, title=_('Install Linux Launcher'),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        executable_desc = (_('It is executable.') if status.is_executable
                           else _('It is NOT currently executable.'))
        desktop_dir = linux_desktop.desktop_dir()
        if desktop_dir is None:
            desktop_dir_desc = _('(no Desktop directory could be found)')
        else:
            desktop_dir_desc = str(desktop_dir)
        info = wx.StaticText(self, label='\n'.join([
            _('Detected AppImage:'),
            str(status.path),
            executable_desc,
            '',
            _('CHIRP will create launcher file(s) only in your personal '
              'profile; no administrator access is used:'),
            '  %s' % linux_desktop.applications_dir(),
            '  %s' % desktop_dir_desc,
        ]))
        info.Wrap(480)
        vbox.Add(info, 0, wx.ALL, 10)

        self._menu_cb = wx.CheckBox(
            self, label=_('Add CHIRP to the application menu'))
        self._menu_cb.SetValue(True)
        vbox.Add(self._menu_cb, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._desktop_cb = wx.CheckBox(
            self, label=_('Create a launcher on the desktop'))
        self._desktop_cb.SetValue(False)
        vbox.Add(self._desktop_cb, 0, wx.ALL, 10)

        note = wx.StaticText(self, label=_(
            'Note: some desktop environments require newly-created '
            'desktop launchers to be manually marked as trusted (e.g. '
            'right-click > Allow Launching) before they can be run.'))
        note.Wrap(480)
        vbox.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL))
        vbox.Add(btn_row, 0, wx.EXPAND | wx.ALL, 10)

        self.Fit()
        self.CenterOnParent()

    @property
    def install_menu(self):
        return self._menu_cb.GetValue()

    @property
    def install_desktop_icon(self):
        return self._desktop_cb.GetValue()


def _describe_target(label, result):
    if result is None:
        return None
    path, status = result
    if status == 'unsupported':
        return _('%s: skipped (could not determine a safe location)') % (
            label,)
    return _('%(label)s %(status)s: %(path)s') % {
        'label': label, 'status': status, 'path': path}


def _report_outcome(parent, outcome):
    lines = []
    menu_line = _describe_target(_('Application menu launcher'),
                                 outcome.menu)
    if menu_line:
        lines.append(menu_line)

    desktop_line = _describe_target(_('Desktop launcher'), outcome.desktop)
    if desktop_line:
        lines.append(desktop_line)
        if outcome.desktop and outcome.desktop[1] != 'unsupported':
            lines.append(_(
                'Some desktop environments require you to mark the new '
                'desktop icon as trusted before it will run.'))

    if outcome.validation_warning:
        lines.append(_('The generated launcher may not be fully valid:'))
        lines.append(outcome.validation_warning)

    message = '\n\n'.join(lines) if lines else _('Nothing was installed.')

    if outcome.errors:
        wx.MessageBox('\n\n'.join(outcome.errors + [message]),
                      _('Launcher installation failed'),
                      wx.ICON_ERROR | wx.OK, parent)
    elif outcome.validation_warning:
        wx.MessageBox(message, _('Launcher installed with warnings'),
                      wx.ICON_WARNING | wx.OK, parent)
    else:
        wx.MessageBox(message, _('Launcher installed'),
                      wx.ICON_INFORMATION | wx.OK, parent)


def do_install_linux_launcher(parent, event):
    if not linux_desktop.is_supported_platform():
        return

    status = linux_desktop.get_appimage_status()
    if status.path is None:
        wx.MessageBox(
            _('This installs a desktop launcher for a running CHIRP '
              'AppImage. CHIRP does not appear to be running from an '
              'AppImage right now, so there is nothing to install a '
              'launcher for. Download and run the CHIRP AppImage to use '
              'this feature.'),
            _('Not running as an AppImage'),
            wx.ICON_INFORMATION | wx.OK, parent)
        return

    if not status.usable:
        wx.MessageBox(
            _('The detected AppImage path does not exist or is not a '
              'regular file:') + '\n%s' % status.path,
            _('AppImage not found'),
            wx.ICON_ERROR | wx.OK, parent)
        return

    if not status.is_executable:
        r = wx.MessageBox(
            _('The running AppImage at %s does not have execute '
              'permission set, so a launcher would not be able to start '
              'it.\n\nAdd execute permission for your user now?') %
            status.path,
            _('AppImage is not executable'),
            wx.ICON_WARNING | wx.YES_NO, parent)
        if r != wx.YES:
            return
        try:
            status = linux_desktop.grant_execute_permission(status.path)
        except linux_desktop.LinuxDesktopError as e:
            common.error_proof.show_error(e, parent=parent)
            return
        if not status.is_executable:
            common.error_proof.show_error(
                _('Failed to make the AppImage executable for an unknown '
                  'reason.'), parent=parent)
            return

    d = LinuxLauncherDialog(parent, status)
    try:
        if d.ShowModal() != wx.ID_OK:
            return
        install_menu = d.install_menu
        install_desktop_icon = d.install_desktop_icon
    finally:
        d.Destroy()

    if not install_menu and not install_desktop_icon:
        return

    outcome = linux_desktop.install_launchers(
        status.path, install_menu=install_menu,
        install_desktop_icon=install_desktop_icon)

    _report_outcome(parent, outcome)
