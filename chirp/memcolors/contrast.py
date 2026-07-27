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

"""WCAG-style contrast-ratio helpers for validating color pairs."""

import re

_HEX_RE = re.compile(r'^#([0-9A-Fa-f]{6})$')


def parse_hex_color(value):
    """Parse a '#RRGGBB' string into an (r, g, b) tuple of ints 0-255.

    Raises ValueError for anything else, including alpha channels --
    this feature does not support or persist partial transparency.
    """
    if not isinstance(value, str):
        raise ValueError('Color must be a string, got %r' % (value,))
    m = _HEX_RE.match(value)
    if not m:
        raise ValueError('%r is not a #RRGGBB color' % (value,))
    hexval = m.group(1)
    return tuple(int(hexval[i:i + 2], 16) for i in (0, 2, 4))


def is_valid_hex_color(value):
    try:
        parse_hex_color(value)
        return True
    except ValueError:
        return False


def _srgb_to_linear(channel):
    c = channel / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    """Return the WCAG relative luminance of an (r, g, b) tuple."""
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color_a, color_b):
    """Return the WCAG contrast ratio between two '#RRGGBB' colors.

    Result is in the range [1.0, 21.0]; higher is more contrast.
    """
    la = relative_luminance(parse_hex_color(color_a))
    lb = relative_luminance(parse_hex_color(color_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def meets_wcag_aa(fg, bg, large_text=False):
    """Return True if fg/bg meet WCAG AA contrast for the given text size."""
    threshold = 3.0 if large_text else 4.5
    return contrast_ratio(fg, bg) >= threshold
