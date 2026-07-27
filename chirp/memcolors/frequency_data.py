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

"""Curated, region-scoped frequency data used by the color-code classifier.

IMPORTANT: this data is a convenience aid for grouping memories visually.
It is NOT a legal or regulatory determination of band allocation, licensing
class, or operating privileges. Allocations vary by country, ITU region,
licensing class, and local band plan, and change over time. Users remain
responsible for verifying their own frequencies and operating privileges.

Only a "US" region is populated today. The Region dataclass is the seam
for adding other countries/ITU regions later without touching the
classifier or any GUI code.
"""

import dataclasses

from chirp import bandplan
from chirp import bandplan_na

# Amateur band boundaries, reused (not re-curated) from the existing
# chirp.bandplan_na North American band plan data -- the top-level
# "N Meter Band" / "N Centimeter Band" entries define the outer edges of
# each amateur allocation, matching the same filter memedit/bandplan.py
# itself uses in BandPlans.get_repeater_bands().
HAM_BAND_RANGES = tuple(
    b.limits for b in bandplan_na.BANDS
    if b.name.lower().endswith('meter band')
)

# Well-known North American amateur calling frequencies (exact match).
# This is an operational aid, not an exclusive or regulatory reservation
# -- plenty of legitimate traffic occurs on these frequencies that isn't
# "calling". Sourced from widely-published band plans (ARRL band plan,
# http://www.arrl.org/band-plan).
HAM_CALLING_FREQS_HZ = frozenset((
    29600000,    # 10m FM calling
    28400000,    # 10m SSB/CW calling (Novice/Tech, common DX calling)
    50125000,    # 6m SSB calling
    52525000,    # 6m FM calling
    144200000,   # 2m SSB calling
    146520000,   # 2m FM national simplex calling
    223500000,   # 1.25m FM calling
    446000000,   # 70cm FM national simplex calling
    432100000,   # 70cm SSB calling
))

# Amateur satellite sub-bands (uplink/downlink), curated from the OSCAR
# sub-band notes already present in chirp.bandplan_na.BANDS_2M/BANDS_70CM.
HAM_SATELLITE_RANGES = (
    (144300000, 144500000),   # 2m OSCAR sub-band
    (145800000, 146000000),   # 2m OSCAR sub-band
    (435000000, 438000000),   # 70cm satellite-only (internationally)
)

# Amateur propagation-beacon sub-bands, curated from chirp.bandplan_na.
HAM_BEACON_RANGES = (
    (28201000, 28300000),     # 10m beacons
    (50060000, 50080000),     # 6m beacon sub-band
    (144275000, 144300000),   # 2m propagation beacons
    (432300000, 432400000),   # 70cm propagation beacons
)

# APRS/data (exact match; 144.390 is the North America APRS frequency).
HAM_APRS_FREQS_HZ = frozenset((144390000,))

# Modes that indicate amateur digital voice regardless of frequency.
HAM_DIGITAL_VOICE_MODES = frozenset(('DMR', 'DN', 'DV', 'P25'))

# Civil aviation VHF COM band, reused directly from chirp.bandplan.BANDS_AIR
# rather than re-curating the range.
AVIATION_RANGE = bandplan.BANDS_AIR[0].limits

# Civil (121.5 MHz) and military (243.0 MHz) aviation emergency/guard
# frequencies (exact match).
AVIATION_EMERGENCY_FREQS_HZ = frozenset((121500000, 243000000))

# GMRS/FRS share the same 22-channel plan under current (2017+) FCC rules,
# and frequency alone cannot distinguish the two services -- a memory on
# 462.5625 MHz might legitimately be either. This profile follows the
# common convention used by most GMRS/FRS programming references: channels
# 1-7 and 8-14 (the original FRS-only bubble-pack channels plus the
# low-power shared channels) are treated as FRS, while channels 15-22
# (GMRS repeater outputs/high-power channels, plus their +5 MHz repeater
# inputs) are treated as GMRS. This is a convenience default, not a
# regulatory determination -- both categories remain independently
# recolorable, and a memory can always be recategorized with a custom
# rule.
FRS_FREQS_HZ = frozenset(bandplan_na.GMRS_LOW + bandplan_na.GMRS_HHONLY)
GMRS_REPEATER_OUTPUT_FREQS_HZ = frozenset(bandplan_na.GMRS_HIRPT)
GMRS_REPEATER_INPUT_FREQS_HZ = frozenset(
    f + 5000000 for f in bandplan_na.GMRS_HIRPT)
GMRS_FREQS_HZ = GMRS_REPEATER_OUTPUT_FREQS_HZ | GMRS_REPEATER_INPUT_FREQS_HZ

MURS_FREQS_HZ = frozenset(bandplan_na.ALL_MURS_FREQS)

# US VHF marine band, and channel 16 (156.800 MHz) distress/calling/safety.
MARINE_RANGE = (156000000, 162025000)
MARINE_EMERGENCY_FREQS_HZ = frozenset((156800000,))

# NOAA Weather Radio channels (exact match; there is no meaningful "range"
# since these are discrete, narrowly-spaced channels).
WEATHER_FREQS_HZ = frozenset((
    162400000, 162425000, 162450000, 162475000,
    162500000, 162525000, 162550000,
))

# US railroad (AAR) VHF band.
RAILROAD_RANGE = (160215000, 161565000)

# Deliberately small, curated tables rather than wide band ranges: the US
# business/industrial and public-safety allocations overlap heavily with
# other services (trunked 700/800 MHz systems mix public safety and
# business use in ways that can't be told apart by frequency alone), so
# guessing broad ranges here would risk exactly the kind of
# over-classification the color-coding feature is meant to avoid. Instead
# these list only long-published, unambiguous national calling/mutual-aid
# channels; anything else in those bands falls through to "unknown"
# rather than being mislabeled.
PUBLIC_SAFETY_FREQS_HZ = frozenset((
    154265000,   # Fire Mutual Aid
    154280000,   # Fire Mutual Aid
    154295000,   # Fire Mutual Aid
    155475000,   # Law Enforcement Mutual Aid ("Intercity")
    155370000,   # National Search and Rescue
))
BUSINESS_FREQS_HZ = frozenset((
    151505000, 151625000, 151955000, 158400000,   # VHF business itinerant
    464500000, 464550000, 469500000, 469550000,   # UHF business itinerant
))


def _in_any_range(freq, ranges):
    return any(lo <= freq <= hi for lo, hi in ranges)


def is_amateur(freq):
    return _in_any_range(freq, HAM_BAND_RANGES)


@dataclasses.dataclass(frozen=True)
class Region:
    """A named, testable bundle of curated frequency data for one region.

    identify_service() returns a category id string from
    chirp.memcolors.categories for the *service*-level classification
    only (aviation/gmrs/frs/murs/marine/railroad/public_safety/business/
    weather), or None if the frequency isn't recognized. Amateur-band
    detection and sub-classification is handled separately by the
    classifier (via is_amateur() plus the tables above), since amateur
    memories get much richer sub-typing than other services.
    """
    code: str
    name: str

    def identify_service(self, freq):
        if _in_any_range(freq, (AVIATION_RANGE,)):
            return 'aviation'
        if freq in GMRS_FREQS_HZ:
            return 'gmrs'
        if freq in FRS_FREQS_HZ:
            return 'frs'
        if freq in MURS_FREQS_HZ:
            return 'murs'
        if freq in WEATHER_FREQS_HZ:
            return 'weather'
        # Checked before the (broader) marine range: the narrow AAR
        # railroad band (160.215-161.565 MHz) sits entirely inside the
        # nominal 156-162.025 MHz marine range, and a narrower, more
        # specific range match wins over a broader one.
        if _in_any_range(freq, (RAILROAD_RANGE,)):
            return 'railroad'
        if _in_any_range(freq, (MARINE_RANGE,)):
            return 'marine'
        if freq in PUBLIC_SAFETY_FREQS_HZ:
            return 'public_safety'
        if freq in BUSINESS_FREQS_HZ:
            return 'business'
        return None

    def is_aviation_emergency(self, freq):
        return freq in AVIATION_EMERGENCY_FREQS_HZ

    def is_marine_emergency(self, freq):
        return freq in MARINE_EMERGENCY_FREQS_HZ


REGIONS = {
    'US': Region('US', 'United States'),
}

DEFAULT_REGION = 'US'


def get_region(code):
    """Return the Region for @code, falling back to the default region."""
    return REGIONS.get(code, REGIONS[DEFAULT_REGION])
