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

from chirp import chirp_common


class Band(object):
    def __init__(self, limits, name, mode=None, step_khz=None,
                 input_offset=None, output_offset=None, tones=None):
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
        except AssertionError, e:
            raise ValueError("%s %s: %s" % (name, limits, e))

        self.name = name
        self.mode = mode
        self.step_khz = step_khz
        self.tones = tones
        self.limits = limits
        self.offset = None
        self.duplex = "simplex"
        if input_offset is not None:
            self.offset = input_offset
            self.duplex = "rpt TX"
        elif output_offset is not None:
            self.offset = output_offset
            self.duplex = "rpt RX"

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
        if self.duplex == "rpt RX":
            return Band(limits, self.name, self.mode, self.step_khz,
                        input_offset=offset, tones=self.tones)
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
