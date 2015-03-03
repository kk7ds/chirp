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

import gtk
import logging
from chirp import bandplan, bandplan_na, bandplan_au
from chirp import bandplan_iaru_r1, bandplan_iaru_r2, bandplan_iaru_r3
from chirp.ui import inputdialog

LOG = logging.getLogger(__name__)


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

        for plan in (bandplan_na, bandplan_au, bandplan_iaru_r1,
                     bandplan_iaru_r2, bandplan_iaru_r3):
            name = plan.DESC.get("name", plan.SHORTNAME)
            self.plans[plan.SHORTNAME] = (name, plan)

            rpt_inputs = []
            for band in plan.BANDS:
                # Check for duplicates.
                duplicates = [x for x in plan.BANDS if x == band]
                if len(duplicates) > 1:
                    LOG.warn("Bandplan %s has duplicates %s" %
                             (name, duplicates))
                # Add repeater inputs.
                rpt_input = band.inverse()
                if rpt_input not in plan.BANDS:
                    rpt_inputs.append(band.inverse())
            plan.bands = list(plan.BANDS)
            plan.bands.extend(rpt_inputs)

    def get_defaults_for_frequency(self, freq):
        freq = int(freq)
        result = bandplan.Band((freq, freq), repr(freq))

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
                    result.duplex = match.duplex or result.duplex
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

    def select_bandplan(self, parent_window):
        plans = ["None"]
        for shortname, details in self.plans.iteritems():
            if self._config.get_bool(shortname, "bandplan"):
                plans.insert(0, details[0])
            else:
                plans.append(details[0])

        d = inputdialog.ChoiceDialog(plans, parent=parent_window,
                                     title="Choose Defaults")
        d.label.set_text(_("Band plans define default channel settings for "
                           "frequencies in a region.  Choose a band plan "
                           "or None for completely manual channel "
                           "settings."))
        d.label.set_line_wrap(True)
        r = d.run()

        if r == gtk.RESPONSE_OK:
            selection = d.choice.get_active_text()
            for shortname, details in self.plans.iteritems():
                self._config.set_bool(shortname, selection == details[0],
                                      "bandplan")
                if selection == details[0]:
                    LOG.info("Selected band plan %s: %s" %
                             (shortname, selection))

        d.destroy()
