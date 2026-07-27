# Copyright 2026
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

"""Lets the user hide individual menu items (top menu bar and the memory
list's right-click menu) via Help > Customize Menus...

Items opt in to being hideable by being tagged with a stable string key
via tag(item, key), which stashes the key in the item's (otherwise
unused, by us) help-text field. That's what makes an item show up in the
customize dialog and be subject to filter_hidden() -- untagged items
(and separators) are never touched.

Deliberately not used for Undo/Redo: their labels change at runtime
("Undo Paste memories") and other code looks them up by stock ID
after the menu is built, so hiding them isn't worth the edge cases.
"""

import logging

import wx

from chirp.wxui import config

CONF = config.get()
LOG = logging.getLogger(__name__)

_CONF_KEY = 'hidden_menu_items'
_CONF_SECTION = 'state'


def get_hidden_items():
    """Return the set of currently-hidden item keys."""
    raw = CONF.get(_CONF_KEY, _CONF_SECTION) or ''
    return set(x for x in raw.split('\n') if x)


def set_hidden_items(hidden):
    """Persist the set of hidden item keys."""
    CONF.set(_CONF_KEY, '\n'.join(sorted(hidden)), _CONF_SECTION)


# Stock-ID items (e.g. wx.ID_UNDO) can carry a platform-provided default
# help string even when we never call SetHelp() ourselves, so a bare
# "is GetHelp() non-empty" check isn't enough to know an item was
# deliberately tagged. Prefixing our own keys and requiring an exact
# prefix match keeps the two from colliding.
_TAG_PREFIX = 'chirp-hide:'


def tag(item, key):
    """Mark @item as hideable under @key. Returns @item for chaining."""
    item.SetHelp(_TAG_PREFIX + key)
    return item


def _get_tag(item):
    """Return @item's hide key, or None if it was never tag()ed."""
    help_text = item.GetHelp()
    if help_text.startswith(_TAG_PREFIX):
        return help_text[len(_TAG_PREFIX):]
    return None


def _walk(menu, path):
    """Yield (key, path, label) for every tagged item in @menu."""
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        label = item.GetItemLabelText()
        submenu = item.GetSubMenu()
        key = _get_tag(item)
        if key:
            # Plain strings only, deliberately not the wx.MenuItem itself:
            # this is called on the menu bar's one real build, before
            # filter_hidden() may destroy some of these items, and the
            # result gets cached for the customize dialog to read later.
            yield key, path, label
        if submenu:
            yield from _walk(submenu, path + (label,))


def collect_menu_bar_items(menu_bar):
    """Collect all tagged items across every top-level menu in @menu_bar.

    Call this on a menu bar BEFORE filter_hidden() runs on it, so
    currently-hidden items are still included (and can be re-shown from
    the customize dialog).
    """
    results = []
    for i in range(menu_bar.GetMenuCount()):
        menu = menu_bar.GetMenu(i)
        top_label = menu_bar.GetMenuLabelText(i)
        results.extend(_walk(menu, (top_label,)))
    return results


def collect_menu_items(menu, top_label):
    """Collect all tagged items in a standalone (e.g. context) menu."""
    return list(_walk(menu, (top_label,)))


def _cleanup_separators(menu):
    """Drop leading/trailing/duplicate separators left behind by pruning."""
    items = list(menu.GetMenuItems())
    while items and items[0].IsSeparator():
        menu.Delete(items.pop(0))
    while items and items[-1].IsSeparator():
        menu.Delete(items.pop())
    prev_was_sep = False
    for item in items:
        if item.IsSeparator():
            if prev_was_sep:
                menu.Delete(item)
            prev_was_sep = True
        else:
            prev_was_sep = False


def _prune(menu, hidden):
    for item in list(menu.GetMenuItems()):
        submenu = item.GetSubMenu()
        if submenu:
            _prune(submenu, hidden)
        key = _get_tag(item)
        if key and key in hidden:
            # Delete() both removes @item from @menu AND destroys it (as
            # opposed to Remove(), which only detaches it, leaving the
            # caller responsible for destroying it). Menu.Destroy() is a
            # different method entirely (from wx.Object) that destroys
            # the *menu itself*, not a specific item -- it takes no
            # arguments, and passing one raises TypeError.
            menu.Delete(item)
    _cleanup_separators(menu)


def filter_hidden(menu_or_bar):
    """Remove any tagged item in @menu_or_bar whose key is hidden.

    @menu_or_bar may be a wx.MenuBar (all top-level menus) or a single
    wx.Menu (e.g. a context menu built just before showing it).
    """
    hidden = get_hidden_items()
    if not hidden:
        return

    if isinstance(menu_or_bar, wx.MenuBar):
        for i in range(menu_or_bar.GetMenuCount()):
            _prune(menu_or_bar.GetMenu(i), hidden)
    else:
        _prune(menu_or_bar, hidden)


class MenuCustomizeDialog(wx.Dialog):
    """Lets the user check/uncheck individual menu items to show/hide."""

    def __init__(self, parent, menu_bar_entries, context_menu_entries):
        """@menu_bar_entries and @context_menu_entries are both lists of
        (key, path, label), as returned by collect_menu_bar_items() /
        collect_menu_items() -- plain data, not live wx.MenuItem objects,
        since some of the former may have already been hidden/destroyed
        by the time this dialog is shown.
        """
        super().__init__(
            parent, title=_('Customize Menus'),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetSize((520, 520))
        self.SetMinSize((400, 300))

        hidden = get_hidden_items()

        groups = {}
        for key, path, label in menu_bar_entries:
            display = ' > '.join(path[1:] + (label,))
            groups.setdefault(path[0], []).append((key, display))
        if context_menu_entries:
            groups[_('Memory list (right-click)')] = [
                (key, ' > '.join(path[1:] + (label,)))
                for key, path, label in context_menu_entries]

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        help_label = wx.StaticText(
            self, label=_('Uncheck any items you want to hide from their '
                          'menu. Takes effect immediately.'))
        vbox.Add(help_label, 0, wx.ALL, 10)

        notebook = wx.Notebook(self)
        vbox.Add(notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self._checklists = []
        for group_name, entries in groups.items():
            panel = wx.Panel(notebook)
            pbox = wx.BoxSizer(wx.VERTICAL)
            panel.SetSizer(pbox)
            clb = wx.CheckListBox(panel,
                                  choices=[label for _key, label in entries])
            for i, (key, label) in enumerate(entries):
                clb.Check(i, key not in hidden)
            pbox.Add(clb, 1, wx.EXPAND | wx.ALL, 5)
            self._checklists.append((clb, entries))
            notebook.AddPage(panel, group_name)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        show_all = wx.Button(self, label=_('Show All'))
        show_all.Bind(wx.EVT_BUTTON, self._on_show_all)
        btn_row.Add(show_all, 0, wx.RIGHT, 10)
        btn_row.AddStretchSpacer()
        btn_row.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL))
        vbox.Add(btn_row, 0, wx.EXPAND | wx.ALL, 10)

        self.CenterOnParent()

    def _on_show_all(self, event):
        for clb, entries in self._checklists:
            for i in range(len(entries)):
                clb.Check(i, True)

    def get_hidden_items(self):
        hidden = set()
        for clb, entries in self._checklists:
            for i, (key, label) in enumerate(entries):
                if not clb.IsChecked(i):
                    hidden.add(key)
        return hidden
