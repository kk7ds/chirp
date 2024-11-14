# Copyright 2013 Sean Burford <sburford@google.com>
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

import logging

from chirp import chirp_common

LOG = logging.getLogger(__name__)


class Band(object):
    def __init__(self, limits, name, mode=None, step_khz=None,
                 input_offset=None, output_offset=None, tones=None,
                 duplex=None):
        # Apply semantic and chirp limitations to settings.
        # memedit applies radio limitations when settings are applied.
        try:
            assert limits[0] <= limits[1], "Lower freq > upper freq"
            if mode is not None:
                assert mode in chirp_common.MODES, "Mode %s not one of %s" % (
                    mode, chirp_common.MODES)
            if step_khz is not None:
                assert step_khz in chirp_common.TUNING_STEPS, (
                    "step_khz %s not one of %s" %
                    (step_khz, chirp_common.TUNING_STEPS))
            if tones:
                for tone in tones:
                    assert tone in chirp_common.TONES, (
                        "tone %s not one of %s" % (tone, chirp_common.TONES))
        except AssertionError as e:
            raise ValueError("%s %s: %s" % (name, limits, e))

        self.name = name
        self.mode = mode
        self.step_khz = step_khz
        self.tones = tones
        self.limits = limits
        self.offset = input_offset
        self.duplex = duplex
        if duplex is None and self.offset:
            self.duplex = '+' if self.offset > 0 else '-'

    def __eq__(self, other):
        return (other.limits[0] == self.limits[0] and
                other.limits[1] == self.limits[1])

    def contains(self, other):
        return (other.limits[0] >= self.limits[0] and
                other.limits[1] <= self.limits[1])

    def width(self):
        return self.limits[1] - self.limits[0]

    def inverse(self):
        """Create an RX/TX shadow of this band using the offset."""
        if not self.offset:
            return self
        limits = (self.limits[0] + self.offset, self.limits[1] + self.offset)
        offset = -1 * self.offset
        if self.duplex in '+-':
            duplex = '+' if self.duplex == '-' else '-'
            return Band(limits, self.name, self.mode, self.step_khz,
                        input_offset=offset, tones=self.tones, duplex=duplex)
        return Band(limits, self.name, self.mode, self.step_khz,
                    output_offset=offset, tones=self.tones)

    def __repr__(self):
        desc = '%s%s%s%s' % (
            self.mode and 'mode: %s ' % (self.mode,) or '',
            self.step_khz and 'step_khz: %s ' % (self.step_khz,) or '',
            self.offset and 'offset: %s ' % (self.offset,) or '',
            self.tones and 'tones: %s ' % (self.tones,) or '')

        return "%s-%s %s %s %s" % (
            self.limits[0], self.limits[1], self.name, self.duplex, desc)


class BandPlans(object):
    def __init__(self, config):
        self._config = config
        self.plans = {}

        # Migrate old "automatic repeater offset" setting to
        # "North American Amateur Band Plan"
        ro = self._config.get("autorpt", "memedit")
        if ro is not None:
            self._config.set_bool("north_america", ro, "bandplan")
            self._config.remove_option("autorpt", "memedit")
        # And default new users to North America.
        if not self._config.is_defined("north_america", "bandplan"):
            self._config.set_bool("north_america", True, "bandplan")

        from chirp import bandplan_na, bandplan_au
        from chirp import bandplan_iaru_r1, bandplan_iaru_r2, bandplan_iaru_r3

        for plan in (bandplan_na, bandplan_au, bandplan_iaru_r1,
                     bandplan_iaru_r2, bandplan_iaru_r3):
            name = plan.DESC.get("name", plan.SHORTNAME)
            self.plans[plan.SHORTNAME] = (name, plan)

            rpt_inputs = []
            for band in plan.BANDS:
                # Add repeater inputs.
                rpt_input = band.inverse()
                if rpt_input not in plan.BANDS:
                    rpt_inputs.append(band.inverse())
            plan.bands = list(plan.BANDS)
            plan.bands.extend(rpt_inputs)

    def get_defaults_for_frequency(self, freq):
        freq = int(freq)
        result = Band((freq, freq), repr(freq))

        for shortname, details in self.plans.items():
            if self._config.get_bool(shortname, "bandplan"):
                matches = [x for x in details[1].bands if x.contains(result)]
                # Add matches to defaults, favoring more specific matches.
                matches = sorted(matches, key=lambda x: x.width(),
                                 reverse=True)
                for match in matches:
                    result.mode = match.mode or result.mode
                    result.step_khz = match.step_khz or result.step_khz
                    result.offset = match.offset or result.offset
                    result.duplex = (match.duplex if match.duplex is not None
                                     else result.duplex)
                    result.tones = match.tones or result.tones
                    if match.name:
                        result.name = '/'.join((result.name or '', match.name))
                # Limit ourselves to one band plan match for simplicity.
                # Note that if the user selects multiple band plans by editing
                # the config file it will work as expected (except where plans
                # conflict).
                if matches:
                    break

        return result

    def get_enabled_plan(self):
        for shortname, details in self.plans.items():
            if self._config.get_bool(shortname, "bandplan"):
                return details[1]

    def get_repeater_bands(self):
        bands_with_repeaters = []
        current_plan = self.get_enabled_plan()

        # For now, assume anything above 28 MHz could have a repeater.
        # Alternately, we could scan for bands with repeater sub-bands and only
        # include those.
        min_freq = chirp_common.to_MHz(28)

        def add_nodupes(b):
            for existing in bands_with_repeaters:
                if b.name == existing.name:
                    if sum(b.limits) < sum(existing.limits):
                        # Don't add, this is smaller
                        return
                    else:
                        bands_with_repeaters.remove(existing)
                        break
            bands_with_repeaters.append(b)

        for band in current_plan.bands:
            if (band.limits[0] >= min_freq and
                    (band.name.lower().endswith('meter band') or
                     band.name.lower().endswith('cm band'))):
                add_nodupes(band)
        return sorted(bands_with_repeaters,
                      key=lambda b: b.limits[0])


BANDS_AIR = (
  Band((118000000, 136975000), "Aviation", mode="AM"),
)
