# Copyright 2026 Deniz Sincar <denizsincar29@gmail.com>
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
"""Screen reader accessibility helpers for wx.grid.Grid and
wx.propgrid.PropertyGrid.

Both controls paint their own rows/cells instead of using one native
child window per item, so under MSAA/IAccessible they expose a single
ROLE_SYSTEM_CLIENT/PANE object for the whole control with no children:
arrow-key navigation between rows is otherwise completely silent for
screen reader users.

An earlier version of this fix (see PR #1597) spoke each row directly
through prismatoid (ethindp/prism) whenever the row changed. That
worked, but it bypassed the OS accessibility layer entirely, so it
fought with the narration wx already produces natively for the
surrounding UI (tab control, panel labels, etc) -- two voices talking
over each other -- and, on macOS, spoke constantly for every user
regardless of whether a screen reader was even running, since nothing
gated it on assistive technology actually being active.

This version does the same job the way any native control does: by
implementing wx.Accessible so the grid answers IAccessible queries
(name/value/role/state/focused child) truthfully, and by calling
wx.Accessible.NotifyEvent() when the focused row/cell changes so
Windows re-queries it. No screen-reader-specific package or manual
speech call is involved anywhere in this module -- wx.Accessible and
NotifyEvent are both part of wxPython itself.

Caveat: wx.Accessible is only implemented for MSW (see the wxWidgets
docs for wx.Accessible -- "Availability: Only available for MSW").
On other platforms attach_grid_accessible()/attach_propgrid_accessible()
still set a plain accessible name (which GTK/Cocoa do surface) but
install no per-row bridging, so this specifically fixes Windows/NVDA
and does not attempt -- and does not risk regressing anything -- on
Linux or macOS. That matches the double/forced-narration report in
PR #1597, which was on macOS, a platform this module now does nothing
extra on.
"""

import logging

import wx

from chirp.wxui import config

LOG = logging.getLogger(__name__)

CONF = config.get()


def _accessible_supported():
    """Probe whether wx.Accessible actually works on this platform.

    wx.Accessible exists as a class attribute on every platform (it's
    part of the Phoenix bindings), but it's only *implemented* for
    MSW: on GTK/Cocoa builds ``wx.Accessible()`` raises
    NotImplementedError from the underlying C++ the moment you try to
    construct one, even though ``hasattr(wx, 'Accessible')`` is True
    there too. So we have to actually try instantiating it rather than
    checking for the attribute.
    """
    if CONF.get_bool('disable_accessibility', 'state', default=False):
        return False
    accessible_cls = getattr(wx, 'Accessible', None)
    if accessible_cls is None:
        return False
    try:
        accessible_cls()
    except NotImplementedError:
        return False
    return True


# Real per-row screen reader support (wx.Accessible) only works on
# Windows builds of wxWidgets/wxPython; see _accessible_supported().
HAS_ACCESSIBLE = _accessible_supported()


def _acc_state(*names):
    """OR together wx.ACC_STATE_SYSTEM_<NAME> flags looked up by name.

    Looked up defensively (rather than hardcoded as integers) since
    only a handful of these are documented for wxPython and the exact
    set available can vary by version; a name that isn't present in
    this build is simply skipped instead of raising.
    """
    value = 0
    for name in names:
        value |= getattr(wx, 'ACC_STATE_SYSTEM_' + name, 0)
    return value


def _notify(event_name, window, child_id):
    """Tell the OS a virtual child's focus/selection/value changed.

    This is the piece that makes screen readers re-query our
    wx.Accessible object on their own, instead of us pushing speech
    ourselves. No-op if wx.Accessible isn't available on this platform
    or this wxPython build doesn't expose the named event constant.
    """
    if not HAS_ACCESSIBLE:
        return
    event_type = getattr(wx, event_name, None)
    if event_type is None:
        LOG.debug('wx.%s not available in this wxPython build', event_name)
        return
    try:
        wx.Accessible.NotifyEvent(event_type, window,
                                  wx.OBJID_CLIENT, child_id)
    except Exception:
        LOG.debug('NotifyEvent failed', exc_info=True)


def _notify_focus(window, child_id):
    _notify('ACC_EVENT_OBJECT_FOCUS', window, child_id)
    _notify('ACC_EVENT_OBJECT_SELECTION', window, child_id)


def _notify_value_change(window, child_id):
    _notify('ACC_EVENT_OBJECT_VALUECHANGE', window, child_id)


class GridAccessible(wx.Accessible):
    """wx.Accessible for a wx.grid.Grid's grid window.

    Exposes one virtual child per cell (1-based childId, row-major, as
    IAccessible requires) whose name is built from the column header
    and current cell text, so a screen reader reads it the same way it
    would any other table/list control.
    """

    def __init__(self, grid):
        super().__init__()
        self.grid = grid  # the wx.grid.Grid, not GetGridWindow()

    def _row_col(self, child_id):
        cols = self.grid.GetNumberCols()
        if child_id < 1 or cols <= 0:
            return None
        row, col = divmod(child_id - 1, cols)
        if row >= self.grid.GetNumberRows():
            return None
        return row, col

    def GetChildCount(self):
        return (wx.ACC_OK,
                self.grid.GetNumberRows() * self.grid.GetNumberCols())

    def GetChild(self, childId):
        if childId == 0:
            return wx.ACC_OK, self
        # A plain int childId with no wx.Accessible of its own is a
        # "simple element" per the wx.Accessible docs.
        return wx.ACC_OK, None

    def GetName(self, childId):
        if childId == 0:
            return wx.ACC_OK, self.grid.GetGridWindow().GetName()
        cell = self._row_col(childId)
        if not cell:
            return wx.ACC_FAIL, ''
        row, col = cell
        header = self.grid.GetColLabelValue(col)
        value = self.grid.GetCellValue(row, col) or _('empty')
        return wx.ACC_OK, _('%s %s, row %d') % (header, value, row + 1)

    def GetValue(self, childId):
        cell = self._row_col(childId)
        if not cell:
            return wx.ACC_OK, ''
        row, col = cell
        return wx.ACC_OK, self.grid.GetCellValue(row, col)

    def GetRole(self, childId):
        if childId == 0:
            return wx.ACC_OK, wx.ROLE_SYSTEM_TABLE
        return wx.ACC_OK, wx.ROLE_SYSTEM_CELL

    def GetState(self, childId):
        state = _acc_state('FOCUSABLE', 'SELECTABLE')
        if childId == 0:
            return wx.ACC_OK, state
        cell = self._row_col(childId)
        if not cell:
            return wx.ACC_FAIL, 0
        if cell == (self.grid.GetGridCursorRow(),
                    self.grid.GetGridCursorCol()):
            state |= _acc_state('FOCUSED', 'SELECTED')
        return wx.ACC_OK, state

    def GetFocus(self):
        row = self.grid.GetGridCursorRow()
        col = self.grid.GetGridCursorCol()
        cols = self.grid.GetNumberCols()
        if row < 0 or col < 0 or cols <= 0:
            return wx.ACC_OK, self
        return wx.ACC_OK, row * cols + col + 1

    def GetLocation(self, elementId):
        window = self.grid.GetGridWindow()
        if elementId == 0:
            return wx.ACC_OK, window.GetScreenRect()
        cell = self._row_col(elementId)
        if not cell:
            return wx.ACC_FAIL, wx.Rect()
        row, col = cell
        rect = self.grid.CellToRect(row, col)
        rect.SetPosition(window.ClientToScreen(rect.GetTopLeft()))
        return wx.ACC_OK, rect


def attach_grid_accessible(grid, name=None):
    """Give a wx.grid.Grid a real per-cell accessible tree.

    Binds EVT_GRID_SELECT_CELL to notify Windows of the new focused
    cell so screen readers announce cell navigation on their own --
    no speech is pushed by this code.
    """
    window = grid.GetGridWindow()
    if name:
        window.SetName(name)
    if not HAS_ACCESSIBLE:
        return None

    try:
        accessible = GridAccessible(grid)
    except NotImplementedError:
        # Belt-and-suspenders: _accessible_supported() already probed
        # this at import time, but if it's ever wrong for some build
        # we still shouldn't crash grid construction over it.
        return None
    window.SetAccessible(accessible)

    def _on_select_cell(event):
        event.Skip()
        cols = grid.GetNumberCols()
        if cols <= 0:
            return
        child_id = event.GetRow() * cols + event.GetCol() + 1
        _notify_focus(window, child_id)

    grid.Bind(wx.grid.EVT_GRID_SELECT_CELL, _on_select_cell)
    return accessible


class PropertyGridAccessible(wx.Accessible):
    """wx.Accessible for a wx.propgrid.PropertyGrid.

    Exposes one virtual child per visible row (1-based childId, in
    display order) so screen readers get a real name/value/role/state
    for each property instead of the single opaque pane
    wx.propgrid.PropertyGrid otherwise reports.

    speech_fn(prop) -> str, if given, overrides the default
    "<label> <value>" rendering (e.g. to add type/locked/unspecified
    wording); it is only used for GetName(), the accessible name is
    what screen readers read on focus.
    """

    def __init__(self, pg, speech_fn=None):
        super().__init__()
        self.pg = pg
        self.speech_fn = speech_fn

    def _visible_props(self):
        it = self.pg.GetIterator()
        props = []
        while not it.AtEnd():
            props.append(it.GetProperty())
            it.Next()
        return props

    def _prop_for_child(self, childId):
        if childId < 1:
            return None
        props = self._visible_props()
        if childId > len(props):
            return None
        return props[childId - 1]

    def GetChildCount(self):
        return wx.ACC_OK, len(self._visible_props())

    def GetChild(self, childId):
        if childId == 0:
            return wx.ACC_OK, self
        return wx.ACC_OK, None

    def GetName(self, childId):
        if childId == 0:
            return wx.ACC_OK, self.pg.GetName()
        prop = self._prop_for_child(childId)
        if prop is None:
            return wx.ACC_FAIL, ''
        if self.speech_fn:
            return wx.ACC_OK, self.speech_fn(prop)
        if prop.IsCategory():
            return wx.ACC_OK, _('Group: %s') % prop.GetLabel()
        label = prop.GetLabel() or prop.GetName()
        return wx.ACC_OK, '%s %s' % (label, prop.GetValueAsString())

    def GetValue(self, childId):
        prop = self._prop_for_child(childId)
        if prop is None or prop.IsCategory():
            return wx.ACC_OK, ''
        return wx.ACC_OK, prop.GetValueAsString()

    def GetRole(self, childId):
        if childId == 0:
            return wx.ACC_OK, wx.ROLE_SYSTEM_LIST
        prop = self._prop_for_child(childId)
        if prop is not None and prop.IsCategory():
            return wx.ACC_OK, wx.ROLE_SYSTEM_GROUPING
        if isinstance(prop, wx.propgrid.BoolProperty):
            return wx.ACC_OK, wx.ROLE_SYSTEM_CHECKBUTTON
        if isinstance(prop, wx.propgrid.EnumProperty):
            return wx.ACC_OK, wx.ROLE_SYSTEM_COMBOBOX
        return wx.ACC_OK, wx.ROLE_SYSTEM_LISTITEM

    def GetState(self, childId):
        state = _acc_state('FOCUSABLE', 'SELECTABLE')
        if childId == 0:
            return wx.ACC_OK, state
        prop = self._prop_for_child(childId)
        if prop is None:
            return wx.ACC_FAIL, 0
        if prop is self.pg.GetSelectedProperty():
            state |= _acc_state('FOCUSED', 'SELECTED')
        if isinstance(prop, wx.propgrid.BoolProperty) and prop.GetValue():
            state |= _acc_state('CHECKED')
        if not prop.IsEnabled():
            state |= _acc_state('UNAVAILABLE')
        return wx.ACC_OK, state

    def GetFocus(self):
        prop = self.pg.GetSelectedProperty()
        if prop is None:
            return wx.ACC_OK, self
        props = self._visible_props()
        try:
            return wx.ACC_OK, props.index(prop) + 1
        except ValueError:
            return wx.ACC_OK, self

    def GetDescription(self, childId):
        """Exposed via the OS accessibility layer (e.g. NVDA's "report
        object description" command) instead of being pushed as speech
        on a hijacked F1 key press."""
        prop = self._prop_for_child(childId) if childId else None
        if prop is None:
            return wx.ACC_OK, ''
        return wx.ACC_OK, prop.GetHelpString() or ''


def attach_propgrid_accessible(pg, name, speech_fn=None):
    """Give a wx.propgrid.PropertyGrid a real per-row accessible tree.

    Binds EVT_PG_SELECTED to notify Windows of the newly focused row
    so screen readers announce it on their own.
    """
    pg.SetName(name)
    if not HAS_ACCESSIBLE:
        return None

    try:
        accessible = PropertyGridAccessible(pg, speech_fn=speech_fn)
    except NotImplementedError:
        return None
    pg.SetAccessible(accessible)

    def _on_selected(event):
        event.Skip()
        prop = event.GetProperty()
        if prop is None:
            return
        props = accessible._visible_props()
        try:
            child_id = props.index(prop) + 1
        except ValueError:
            return
        _notify_focus(pg, child_id)

    pg.Bind(wx.propgrid.EVT_PG_SELECTED, _on_selected)
    return accessible


def notify_propgrid_value_change(pg, accessible, prop):
    """Tell Windows a property's value changed mid-edit (e.g. arrowing
    through an open EnumProperty combo box, or toggling a checkbox),
    so screen readers pick up the pending value the same way they'd
    pick up a committed one. No-op if accessible attachment failed."""
    if accessible is None:
        return
    props = accessible._visible_props()
    try:
        child_id = props.index(prop) + 1
    except ValueError:
        return
    _notify_value_change(pg, child_id)


# Screen reader accessibility for wx.propgrid.PropertyGrid lives in
# chirp/wxui/accessibility.py (wx.Accessible-based; see that module's
# docstring for why it replaced an earlier prismatoid-based approach).
# enable_propgrid_a11y() is kept as a thin compatibility wrapper since
# radioinfo.py's read-only PropertyGrid pages don't have RadioSetting
# objects backing them the way ChirpSettingGrid's pages do.
def enable_propgrid_a11y(pg, accessible_name):
    """Give a wx.propgrid.PropertyGrid basic screen reader feedback.

    For grids backed by RadioSetting objects, see ChirpSettingGrid,
    which passes a richer speech_fn (type/locked/unspecified wording,
    in-progress edit announcements, F1 description lookup) to
    accessibility.attach_propgrid_accessible() directly instead of
    going through this wrapper.
    """
    return attach_propgrid_accessible(pg, accessible_name)
