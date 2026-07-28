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

"""File > Open Recent list management.

The list itself is read from and written to config as plain data, with
no wx dependency, so it can be unit tested directly. RemoveRecentFilesDialog
at the bottom is the only wx-dependent piece, used to let the user pick
which entries to remove.
"""

import logging

import wx

LOG = logging.getLogger(__name__)

KEEP_RECENT = 8


def load(conf, keep=KEEP_RECENT):
    """Return the persisted recent-files list, most recent first."""
    return [conf.get('recent%i' % i, 'state')
            for i in range(keep)
            if conf.get('recent%i' % i, 'state')]


def _write(conf, recent, keep=KEEP_RECENT):
    """Persist @recent (most recent first), truncated to @keep entries."""
    recent = recent[:keep]
    for i in range(keep):
        try:
            conf.set('recent%i' % i, recent[i], 'state')
        except IndexError:
            # Clean higher-order entries if they exist
            if conf.is_defined('recent%i' % i, 'state'):
                conf.remove_option('recent%i' % i, 'state')
    return recent


def add(conf, filename, keep=KEEP_RECENT):
    """Move @filename to the front of the recent list, deduped."""
    recent = load(conf, keep)
    while filename in recent:
        # The old algorithm could have dupes, so keep looking and
        # cleaning until they're gone
        recent.remove(filename)
    recent.insert(0, filename)
    return _write(conf, recent, keep)


def remove(conf, filenames, keep=KEEP_RECENT):
    """Remove each of @filenames from the recent list."""
    filenames = set(filenames)
    recent = [fn for fn in load(conf, keep) if fn not in filenames]
    return _write(conf, recent, keep)


def clear(conf, keep=KEEP_RECENT):
    """Remove all entries from the recent list."""
    return _write(conf, [], keep)


class RemoveRecentFilesDialog(wx.Dialog):
    """Lets the user pick recent-file entries to remove."""

    def __init__(self, parent, recent):
        super().__init__(
            parent, title=_('Remove from Recent Files'),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        label = wx.StaticText(
            self, label=_('Select entries to remove from Open Recent:'))
        vbox.Add(label, 0, wx.ALL, 10)

        self._clb = wx.CheckListBox(self, choices=recent)
        vbox.Add(self._clb, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL))
        vbox.Add(btn_row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSize((520, 360))
        self.CenterOnParent()

    def get_selected(self):
        """Return the list of checked filenames."""
        return list(self._clb.GetCheckedStrings())
