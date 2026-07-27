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

"""Configurable memory color-coding: classification and color-profile model.

This package is intentionally free of any wx/GUI dependency so that
classification and profile logic can be unit-tested in isolation. The
wx-facing rendering adapter lives in chirp.wxui.memcolors.

Classifications produced here are a convenience aid for visually grouping
memories in the editor. They are not a regulatory or legal determination
of band allocation, licensing class, or operating privileges -- frequency
allocations vary by country, ITU region, and local band plan, and change
over time. Users remain responsible for verifying their own frequencies
and operating privileges.
"""
