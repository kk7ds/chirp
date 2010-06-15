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
import os

import gtk
import gobject

from chirp import platform, directory, chirp_common
from chirpui import miscwidgets, cloneprog, inputdialog, common

AUTO_DETECT_STRING = "Auto Detect (Icom Only)"

class CloneSettingsDialog(gtk.Dialog):
    def make_field(self, title, control):
        hbox = gtk.HBox(True, 2)
        lab = gtk.Label(title)
        lab.show()
        hbox.pack_start(lab, 0, 0, 0)
        hbox.pack_start(control, 1, 1, 0)

        hbox.show()

        # pylint: disable-msg=E1101
        self.vbox.pack_start(hbox, 0, 0, 0)
    
    def fn_changed(self, fn):
        self.set_response_sensitive(gtk.RESPONSE_OK,
                                    len(fn.get_filename()) > 0)

    def run(self):
        while True:
            result = gtk.Dialog.run(self)
            if result == gtk.RESPONSE_CANCEL:
                break

            fn = self.filename.get_filename()
            if self.clone_in and os.path.exists(fn):
                dlg = inputdialog.OverwriteDialog(fn)
                owrite = dlg.run()
                dlg.destroy()
                if owrite == gtk.RESPONSE_OK:
                    break
            else:
                break

        return result

    def __init__(self, clone_in=True, filename=None, rtype=None, port=None):
        buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                   gtk.STOCK_OK, gtk.RESPONSE_OK)
        gtk.Dialog.__init__(self, buttons=buttons, title="Clone")

        self.clone_in = clone_in

        ports = platform.get_platform().list_serial_ports()
        if port:
            defport = port
        elif ports:
            defport = ports[0]
        else:
            defport = ""
        self.port = miscwidgets.make_choice(ports, True, defport)
        self.port.show()

        self.__rtypes = {}
        for drv in directory.DRV_TO_RADIO.keys():
            cls = directory.get_radio(drv)
            if issubclass(cls, chirp_common.IcomFileBackedRadio):
                self.__rtypes[directory.get_radio_name(drv)] = drv

        type_choices = sorted(self.__rtypes.keys())
        type_choices.insert(0, AUTO_DETECT_STRING)
        self.__rtypes[AUTO_DETECT_STRING] = AUTO_DETECT_STRING

        if rtype:
            self.rtype = miscwidgets.make_choice(type_choices, False,
                                                 directory.get_radio_name(rtype))
            self.rtype.set_sensitive(False)
        else:
            self.rtype = miscwidgets.make_choice(type_choices, False,
                                                 type_choices[0])
        self.rtype.show()

        types = [("CHIRP Radio Images (*.img)", "*.img")]
        self.filename = miscwidgets.FilenameBox(types=types)
        if not clone_in:
            self.filename.set_sensitive(False)
        if filename:
            self.filename.set_filename(filename)
        else:
            self.filename.set_filename("MyRadio.img")
        self.filename.show()
        self.filename.connect("filename-changed", self.fn_changed)

        self.make_field("Serial port", self.port)
        self.make_field("Radio type", self.rtype)
        self.make_field("Filename", self.filename)

    def get_values(self):
        rtype = self.rtype.get_active_text()
        
        return self.port.get_active_text(), \
            self.__rtypes.get(rtype, None), \
            self.filename.get_filename()

class CloneThread(threading.Thread):
    def __status(self, status):
        gobject.idle_add(self.__progw.status, status)

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

            emsg = None
        except Exception, e:
            common.log_exception()
            print "Clone failed: %s" % e
            emsg = e

        gobject.idle_add(self.__progw.hide)

        # NB: Compulsory close of the radio's serial connection
        self.__radio.pipe.close()

        print "Clone thread ended"

        if self.__cback:
            gobject.idle_add(self.__cback, self.__radio, self.__fname, emsg)
