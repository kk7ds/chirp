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


def select_bandplan(bandplans, parent_window):
    plans = ["None"]
    for shortname, details in bandplans.plans.iteritems():
        if bandplans._config.get_bool(shortname, "bandplan"):
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
        for shortname, details in bandplans.plans.iteritems():
            bandplans._config.set_bool(shortname, selection == details[0],
                                       "bandplan")
            if selection == details[0]:
                LOG.info("Selected band plan %s: %s" %
                         (shortname, selection))

    d.destroy()
