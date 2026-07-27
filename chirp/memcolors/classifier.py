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

"""Deterministic memory -> color-category classification.

Precedence (highest wins first):

    1. invalid       -- caller-supplied validation failure (opt-in; see
                         classify()'s @validation_errors parameter).
    2. disabled       -- empty or skipped memory slot.
    3. user rule      -- first enabled custom rule (by priority) that
                          matches, evaluated against the memory AND the
                          built-in candidate category computed below, so
                          rules can either target raw memory fields or
                          override "whatever the built-in classifier
                          would have said".
    4. emergency/calling  -- known emergency or calling frequency.
    5. specialized amateur operation -- repeater/satellite/APRS/digital
                          voice/beacon, which are recognized independent
                          of transmit capability.
    6. service-level  -- plain service membership (GMRS, FRS, aviation,
                          generic amateur, etc).
    7. receive-only modifier -- applied when nothing more specific above
                          matched and the memory has no transmit
                          frequency configured (duplex == "off").
    8. unknown        -- frequency not recognized by the region profile.

This module has no GUI/wx dependency and is independently unit-testable.
"""

import dataclasses

from chirp.memcolors import categories
from chirp.memcolors import frequency_data
from chirp.memcolors import rules as rules_mod


@dataclasses.dataclass(frozen=True)
class ClassificationResult:
    category_id: str
    rule: object = None  # a rules.Rule, if a user rule produced this result

    @property
    def is_rule_override(self):
        return self.rule is not None


def _in_any_range(freq, ranges):
    return any(lo <= freq <= hi for lo, hi in ranges)


def _is_ham_repeater(memory):
    """Repeater semantics live in duplex/offset, never in tone alone."""
    if memory.duplex in ('+', '-'):
        # A zero offset with a +/- duplex is a degenerate/malformed
        # state (no actual shift), not a real repeater.
        return bool(memory.offset)
    if memory.duplex == 'split':
        # For "split" memories, offset holds the absolute TX frequency
        # (not a delta) by CHIRP convention -- a real split repeater has
        # a TX frequency different from the RX frequency.
        return memory.offset != memory.freq
    return False


def _classify_ham(memory):
    freq = memory.freq
    if freq in frequency_data.HAM_CALLING_FREQS_HZ:
        return categories.HAM_CALLING
    # Checked before the (broader) satellite sub-band ranges: 144.390
    # MHz APRS sits inside the 2m OSCAR sub-band range, and an exact,
    # well-known frequency match is more specific/reliable than a wide
    # range match.
    if freq in frequency_data.HAM_APRS_FREQS_HZ:
        return categories.HAM_APRS_DATA
    if _in_any_range(freq, frequency_data.HAM_SATELLITE_RANGES):
        return categories.HAM_SATELLITE
    if memory.mode in frequency_data.HAM_DIGITAL_VOICE_MODES:
        return categories.HAM_DIGITAL_VOICE
    if _in_any_range(freq, frequency_data.HAM_BEACON_RANGES):
        return categories.HAM_BEACON_SPECIALTY
    if _is_ham_repeater(memory):
        return categories.HAM_REPEATER
    if memory.duplex == '':
        return categories.HAM_SIMPLEX
    if memory.duplex == 'off':
        return categories.HAM_RECEIVE_ONLY
    return categories.HAM_GENERAL


_SERVICE_CATEGORY = {
    'gmrs': categories.GMRS,
    'frs': categories.FRS,
    'murs': categories.MURS,
    'railroad': categories.RAILROAD,
    'public_safety': categories.PUBLIC_SAFETY,
    'business': categories.BUSINESS,
    'weather': categories.WEATHER,
}


def _classify_builtin(memory, region_data):
    """Return (category_id, service_id_or_None) ignoring rules/disabled."""
    freq = memory.freq
    is_rx_only = memory.duplex == 'off'

    if frequency_data.is_amateur(freq):
        return _classify_ham(memory), 'ham'

    service = region_data.identify_service(freq)

    if service == 'aviation':
        if region_data.is_aviation_emergency(freq):
            return categories.AVIATION_EMERGENCY, service
        return ((categories.RECEIVE_ONLY if is_rx_only
                 else categories.AVIATION), service)

    if service == 'marine':
        if region_data.is_marine_emergency(freq):
            return categories.EMERGENCY, service
        return ((categories.RECEIVE_ONLY if is_rx_only
                 else categories.MARINE), service)

    if service in _SERVICE_CATEGORY:
        if is_rx_only:
            return categories.RECEIVE_ONLY, service
        return _SERVICE_CATEGORY[service], service

    # Unrecognized frequency: receive-only still outranks "unknown" per
    # the documented precedence (tier 7 above tier 8).
    return ((categories.RECEIVE_ONLY if is_rx_only
             else categories.UNKNOWN), None)


def classify(memory, region=frequency_data.DEFAULT_REGION, rules=(),
             validation_errors=None):
    """Classify @memory into a color category.

    @region: region/profile code (e.g. 'US') selecting curated frequency
        data.
    @rules: an iterable of rules.Rule to check before falling back to the
        built-in classification.
    @validation_errors: if truthy, the memory is classified as
        categories.INVALID unconditionally. Callers decide when this is
        appropriate -- e.g. the wx integration only passes real
        validation failures for memories that are actually meant to
        transmit, so a receive-only memory that's outside a radio's TX
        range is never misreported as "invalid".
    """
    if validation_errors:
        return ClassificationResult(categories.INVALID)

    if memory.empty or memory.skip in ('S', 'P'):
        return ClassificationResult(categories.DISABLED)

    region_data = frequency_data.get_region(region)
    candidate, service = _classify_builtin(memory, region_data)

    context = rules_mod.build_match_context(
        memory, service=service, candidate_category=candidate)
    matched_rule = rules_mod.find_matching_rule(rules, context)
    if matched_rule:
        return ClassificationResult(candidate, rule=matched_rule)

    return ClassificationResult(candidate)
