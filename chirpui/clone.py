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

import threading

import gtk
import gobject

from chirp import platform

import miscwidgets
import cloneprog

class CloneSettingsDialog(gtk.Dialog):
    def make_field(self, title, control):
        hbox = gtk.HBox(True, 2)
        l = gtk.Label(title)
        l.show()
        hbox.pack_start(l, 0,0,0)
        hbox.pack_start(control, 1,1,0)

        hbox.show()

        # pylint: disable-msg=E1101
        self.vbox.pack_start(hbox, 0,0,0)
    
    def __init__(self, cloneIn=True, filename=None, rtype=None):
        buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                   gtk.STOCK_OK, gtk.RESPONSE_OK)
        gtk.Dialog.__init__(self, buttons=buttons, title="Clone")

        ports = platform.get_platform().list_serial_ports()
        self.port = miscwidgets.make_choice(ports, True, ports[0])
        self.port.show()

        rtypes = ["ic2820", "ic2200", "id800"]
        if rtype:
            if not rtype in rtypes:
                rtypes.insert(0, rtype)
            self.rtype = miscwidgets.make_choice(rtypes, False, rtype)
            self.rtype.set_sensitive(False)
        else:
            self.rtype = miscwidgets.make_choice(rtypes, False, rtypes[0])
        self.rtype.show()

        self.filename = miscwidgets.FilenameBox()
        if not cloneIn:
            self.filename.set_sensitive(False)
        if filename:
            self.filename.set_filename(filename)
        self.filename.show()

        self.make_field("Serial port", self.port)
        self.make_field("Radio type", self.rtype)
        self.make_field("Filename", self.filename)

    def get_values(self):
        return self.port.get_active_text(), \
            self.rtype.get_active_text(),   \
            self.filename.get_filename()

class CloneThread(threading.Thread):
    def __status(self, s):
        gobject.idle_add(self.__progw.status, s)

    def __init__(self, radio, fname=None, cb=None, parent=None):
        threading.Thread.__init__(self)

        self.__radio = radio
        self.__fname = fname
        self.__cback = cb

        self.__progw = cloneprog.CloneProg(parent=parent)

    def run(self):
        print "Clone thread started"

        gobject.idle_add(self.__progw.show)

        self.__radio.status_fn = self.__status
        
        try:
            if self.__fname:
                self.__radio.sync_in()
                self.__radio.save_mmap(self.__fname)
            else:
                self.__radio.sync_out()

            success = True
        except Exception, e:
            print "Clone failed: %s" % e
            success = False

        gobject.idle_add(self.__progw.hide)

        # NB: Compulsory close of the radio's serial connection
        self.__radio.pipe.close()

        print "Clone thread ended"

        if self.__cback and success:
            gobject.idle_add(self.__cback, self.__radio, self.__fname)
