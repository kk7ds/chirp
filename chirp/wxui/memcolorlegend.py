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

# Translated category display names/descriptions, keyed by the stable
# (untranslated) category id. This is the one place these literal
# strings get translated -- the extraction tool can only find literal
# string arguments, not ones read off an attribute at runtime, so
# category.label is deliberately never translated directly anywhere
# else in the UI code; everything looks it up here instead.
CATEGORY_LABELS = {
    categories.INVALID: _('Invalid'),
    categories.DISABLED: _('Disabled / Skipped'),
    categories.EMERGENCY: _('Emergency'),
    categories.CALLING: _('Calling'),
    categories.RECEIVE_ONLY: _('Receive-only'),
    categories.HAM_REPEATER: _('Ham: Repeater'),
    categories.HAM_SIMPLEX: _('Ham: Simplex'),
    categories.HAM_CALLING: _('Ham: Calling'),
    categories.HAM_SATELLITE: _('Ham: Satellite'),
    categories.HAM_APRS_DATA: _('Ham: APRS/Data'),
    categories.HAM_DIGITAL_VOICE: _('Ham: Digital Voice'),
    categories.HAM_BEACON_SPECIALTY: _('Ham: Beacon/Specialty'),
    categories.HAM_RECEIVE_ONLY: _('Ham: Receive-only'),
    categories.HAM_GENERAL: _('Ham: General'),
    categories.AVIATION_EMERGENCY: _('Aviation Emergency'),
    categories.AVIATION: _('Aviation'),
    categories.GMRS: _('GMRS'),
    categories.FRS: _('FRS'),
    categories.MURS: _('MURS'),
    categories.MARINE: _('Marine'),
    categories.RAILROAD: _('Railroad'),
    categories.PUBLIC_SAFETY: _('Public Safety'),
    categories.BUSINESS: _('Business/Industrial'),
    categories.WEATHER: _('NOAA/Weather'),
    categories.UNKNOWN: _('Unknown'),
}

CATEGORY_DESCRIPTIONS = {
    categories.INVALID:
        _('Fails radio validation (opt-in visual override).'),
    categories.DISABLED: _('Empty or skipped memory slot.'),
    categories.EMERGENCY: _('Known emergency/distress frequency.'),
    categories.CALLING:
        _('Commonly-used calling channel (operational aid, not '
          'exclusive or regulatory).'),
    categories.RECEIVE_ONLY: _('No transmit frequency configured.'),
    categories.HAM_REPEATER: _('Amateur repeater (duplex + offset).'),
    categories.HAM_SIMPLEX: _('Amateur simplex (no offset/split).'),
    categories.HAM_CALLING: _('Well-known amateur calling frequency.'),
    categories.HAM_SATELLITE:
        _('Amateur satellite uplink/downlink band.'),
    categories.HAM_APRS_DATA: _('APRS or other amateur data frequency.'),
    categories.HAM_DIGITAL_VOICE:
        _('DMR/D-STAR/System Fusion/P25 mode.'),
    categories.HAM_BEACON_SPECIALTY:
        _('Propagation beacon or weak-signal specialty sub-band.'),
    categories.HAM_RECEIVE_ONLY: _('Amateur memory with no transmit.'),
    categories.HAM_GENERAL:
        _('Amateur allocation, no specific subtype.'),
    categories.AVIATION_EMERGENCY:
        _('Civil/military aviation guard frequency.'),
    categories.AVIATION: _('Civil aviation band.'),
    categories.GMRS: _('General Mobile Radio Service.'),
    categories.FRS: _('Family Radio Service.'),
    categories.MURS: _('Multi-Use Radio Service.'),
    categories.MARINE: _('VHF marine band.'),
    categories.RAILROAD: _('Railroad operations band.'),
    categories.PUBLIC_SAFETY: _('Public safety allocation.'),
    categories.BUSINESS: _('Business/industrial land-mobile band.'),
    categories.WEATHER: _('NOAA Weather Radio channel.'),
    categories.UNKNOWN:
        _('Frequency not recognized by the current region profile.'),
}


def category_label(category_id):
    return CATEGORY_LABELS.get(category_id, category_id)


def category_description(category_id):
    return CATEGORY_DESCRIPTIONS.get(category_id, '')


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
            label = category_label(category_id)
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
