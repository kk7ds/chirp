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

"""A small, hideable color-swatch legend shown under the memory grid."""

import wx

from chirp.memcolors import categories

_ = wx.GetTranslation

_SWATCH_SIZE = (14, 14)


class ColorLegendPanel(wx.Panel):
    """Shows one swatch+label per enabled category/custom rule.

    Only shown when both color coding and "show legend" are on (see
    ChirpMemEdit._update_legend_visibility); refresh() is cheap enough
    to call on every profile change since the category list is tiny.
    """

    def __init__(self, parent, controller):
        super().__init__(parent)
        self._controller = controller
        self._sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.SetSizer(self._sizer)
        self.refresh()

    def refresh(self):
        self._sizer.Clear(delete_windows=True)
        profile = self._controller.profile

        for category_id, state in profile.enabled_categories():
            cat = categories.default_category(category_id)
            label = _(cat.label) if cat else category_id
            self._sizer.Add(self._make_swatch(state.bg, label, italic=False),
                            0, wx.ALL, 3)

        for rule in profile.custom_rules:
            if not rule.enabled:
                continue
            self._sizer.Add(self._make_swatch(rule.bg, rule.name,
                                              italic=True),
                            0, wx.ALL, 3)

        self.Layout()
        parent = self.GetParent()
        if parent:
            parent.Layout()

    def _make_swatch(self, bg_hex, label, italic):
        panel = wx.Panel(self)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        panel.SetSizer(hbox)

        swatch = wx.Panel(panel, size=_SWATCH_SIZE)
        swatch.SetMinSize(_SWATCH_SIZE)
        try:
            swatch.SetBackgroundColour(wx.Colour(bg_hex))
        except Exception:
            pass
        hbox.Add(swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        text = wx.StaticText(panel, label=label)
        if italic:
            font = text.GetFont()
            font.MakeItalic()
            text.SetFont(font)
            text.SetToolTip(_('Custom rule'))
        hbox.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)

        return panel
