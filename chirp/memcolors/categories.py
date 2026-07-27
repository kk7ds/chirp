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

"""The default memory color-coding category table.

Category ids are stable, untranslated schema identifiers -- they are
persisted in config and must never change once released. `label` is the
untranslated English display string; this module intentionally has no
wx/gettext dependency of its own (so it stays trivially unit-testable).
Translated display strings live in chirp.wxui.memcolorlegend, keyed by
category id.

Colors are '#RRGGBB' strings only -- no alpha. Every default pair here is
checked for WCAG AA contrast (>=4.5:1) by tests/unit/test_memcolors_*.py.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Category:
    id: str
    label: str
    default_bg: str
    default_fg: str
    priority: int
    description: str = ''
    bold: bool = False


# Precedence tiers, lowest number = resolved/wins first. Mirrors the
# documented classification precedence order; used only to order the
# legend and to sanity-check tests, not consulted by classify() itself
# (classify() encodes the actual precedence procedurally).
TIER_INVALID = 0
TIER_DISABLED = 1
TIER_USER_RULE = 2
TIER_EMERGENCY_CALLING = 3
TIER_SPECIALIZED = 4
TIER_SERVICE = 5
TIER_RECEIVE_ONLY = 6
TIER_UNKNOWN = 7

# --- Operational overrides -------------------------------------------------

INVALID = 'invalid'
DISABLED = 'disabled'
EMERGENCY = 'emergency'
CALLING = 'calling'
RECEIVE_ONLY = 'receive_only'

# --- Amateur radio -----------------------------------------------------

HAM_REPEATER = 'ham_repeater'
HAM_SIMPLEX = 'ham_simplex'
HAM_CALLING = 'ham_calling'
HAM_SATELLITE = 'ham_satellite'
HAM_APRS_DATA = 'ham_aprs_data'
HAM_DIGITAL_VOICE = 'ham_digital_voice'
HAM_BEACON_SPECIALTY = 'ham_beacon_specialty'
HAM_RECEIVE_ONLY = 'ham_receive_only'
HAM_GENERAL = 'ham_general'

# --- Other services ------------------------------------------------------

AVIATION = 'aviation'
AVIATION_EMERGENCY = 'aviation_emergency'
GMRS = 'gmrs'
FRS = 'frs'
MURS = 'murs'
MARINE = 'marine'
RAILROAD = 'railroad'
PUBLIC_SAFETY = 'public_safety'
BUSINESS = 'business'
WEATHER = 'weather'
UNKNOWN = 'unknown'


DEFAULT_CATEGORIES = (
    Category(INVALID, 'Invalid', '#B71C1C', '#FFFFFF', TIER_INVALID,
             'Fails radio validation (opt-in visual override).', bold=True),
    Category(DISABLED, 'Disabled / Skipped', '#9E9E9E', '#212121',
             TIER_DISABLED, 'Empty or skipped memory slot.'),
    Category(EMERGENCY, 'Emergency', '#C62828', '#FFFFFF',
             TIER_EMERGENCY_CALLING, 'Known emergency/distress frequency.',
             bold=True),
    Category(CALLING, 'Calling', '#B25400', '#FFFFFF',
             TIER_EMERGENCY_CALLING,
             'Commonly-used calling channel (operational aid, not '
             'exclusive or regulatory).'),
    Category(RECEIVE_ONLY, 'Receive-only', '#B0BEC5', '#212121',
             TIER_RECEIVE_ONLY, 'No transmit frequency configured.'),

    Category(HAM_REPEATER, 'Ham: Repeater', '#1B5E20', '#FFFFFF',
             TIER_SPECIALIZED, 'Amateur repeater (duplex + offset).'),
    Category(HAM_SIMPLEX, 'Ham: Simplex', '#66BB6A', '#0B2E0D',
             TIER_SERVICE, 'Amateur simplex (no offset/split).'),
    Category(HAM_CALLING, 'Ham: Calling', '#00C853', '#0B2E0D',
             TIER_EMERGENCY_CALLING,
             'Well-known amateur calling frequency.'),
    Category(HAM_SATELLITE, 'Ham: Satellite', '#00786B', '#FFFFFF',
             TIER_SPECIALIZED, 'Amateur satellite uplink/downlink band.'),
    Category(HAM_APRS_DATA, 'Ham: APRS/Data', '#00838F', '#FFFFFF',
             TIER_SPECIALIZED, 'APRS or other amateur data frequency.'),
    Category(HAM_DIGITAL_VOICE, 'Ham: Digital Voice', '#2E7D32', '#FFFFFF',
             TIER_SPECIALIZED, 'DMR/D-STAR/System Fusion/P25 mode.'),
    Category(HAM_BEACON_SPECIALTY, 'Ham: Beacon/Specialty', '#827717',
             '#FFFFFF', TIER_SPECIALIZED,
             'Propagation beacon or weak-signal specialty sub-band.'),
    Category(HAM_RECEIVE_ONLY, 'Ham: Receive-only', '#C8E6C9', '#1B3A1D',
             TIER_RECEIVE_ONLY, 'Amateur memory with no transmit.'),
    Category(HAM_GENERAL, 'Ham: General', '#A5D6A7', '#1B3A1D',
             TIER_SERVICE, 'Amateur allocation, no specific subtype.'),

    Category(AVIATION_EMERGENCY, 'Aviation Emergency', '#AD1457', '#FFFFFF',
             TIER_EMERGENCY_CALLING, 'Civil/military aviation guard '
             'frequency.', bold=True),
    Category(AVIATION, 'Aviation', '#1565C0', '#FFFFFF', TIER_SERVICE,
             'Civil aviation band.'),
    Category(GMRS, 'GMRS', '#6A1B9A', '#FFFFFF', TIER_SERVICE,
             'General Mobile Radio Service.'),
    Category(FRS, 'FRS', '#8E24AA', '#FFFFFF', TIER_SERVICE,
             'Family Radio Service.'),
    Category(MURS, 'MURS', '#5E35B1', '#FFFFFF', TIER_SERVICE,
             'Multi-Use Radio Service.'),
    Category(MARINE, 'Marine', '#0277BD', '#FFFFFF', TIER_SERVICE,
             'VHF marine band.'),
    Category(RAILROAD, 'Railroad', '#4E342E', '#FFFFFF', TIER_SERVICE,
             'Railroad operations band.'),
    Category(PUBLIC_SAFETY, 'Public Safety', '#37474F', '#FFFFFF',
             TIER_SERVICE, 'Public safety allocation.'),
    Category(BUSINESS, 'Business/Industrial', '#616161', '#FFFFFF',
             TIER_SERVICE, 'Business/industrial land-mobile band.'),
    Category(WEATHER, 'NOAA/Weather', '#00695C', '#FFFFFF', TIER_SERVICE,
             'NOAA Weather Radio channel.'),
    Category(UNKNOWN, 'Unknown', '#ECEFF1', '#455A64', TIER_UNKNOWN,
             'Frequency not recognized by the current region profile.'),
)


BY_ID = {c.id: c for c in DEFAULT_CATEGORIES}

# Amateur-radio subcategory ids, in the order the spec lists them --
# used by the settings dialog to group the "Amateur radio" section.
HAM_CATEGORY_IDS = (
    HAM_REPEATER, HAM_SIMPLEX, HAM_CALLING, HAM_SATELLITE, HAM_APRS_DATA,
    HAM_DIGITAL_VOICE, HAM_BEACON_SPECIALTY, HAM_RECEIVE_ONLY, HAM_GENERAL,
)

OPERATIONAL_CATEGORY_IDS = (
    INVALID, DISABLED, EMERGENCY, CALLING, RECEIVE_ONLY,
)

OTHER_SERVICE_CATEGORY_IDS = (
    AVIATION, AVIATION_EMERGENCY, GMRS, FRS, MURS, MARINE, RAILROAD,
    PUBLIC_SAFETY, BUSINESS, WEATHER, UNKNOWN,
)


def default_category(category_id):
    """Return the built-in Category for @category_id, or None."""
    return BY_ID.get(category_id)
