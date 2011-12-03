#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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
import gobject

from chirpui import common, miscwidgets

class BankEditor(common.Editor):
    def refresh(self):
        def set_banks(banks):
            i = ord("A")
            for bank in banks:
                self.listw.set_item(chr(i), chr(i), str(bank))
                i += 1

            self.listw.connect("item-set", self.bank_changed)

        job = common.RadioJob(set_banks, "get_banks")
        job.set_desc(_("Retrieving bank list"))
        self.rthread.submit(job)

    def get_bank_list(self):
        banks = []
        keys = self.listw.get_keys()
        for key in keys:
            banks.append(self.listw.get_item(key)[2])

        return banks
    
    def bank_changed(self, listw, key):
        def cb(*args):
            self.emit("changed")

        job = common.RadioJob(cb, "set_banks", self.get_bank_list())
        job.set_desc(_("Setting bank list"))
        self.rthread.submit(job)

        return True

    def __init__(self, rthread):
        common.Editor.__init__(self)
        self.rthread = rthread

        types = [(gobject.TYPE_STRING, "key"),
                 (gobject.TYPE_STRING, _("Bank")),
                 (gobject.TYPE_STRING, _("Name"))]

        self.listw = miscwidgets.KeyedListWidget(types)
        self.listw.set_editable(1, True)
        self.listw.set_sort_column(0, 1)
        self.listw.set_sort_column(1, -1)
        self.listw.show()

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(self.listw)

        self.root = sw

        self.refresh()
