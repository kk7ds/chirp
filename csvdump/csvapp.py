#!/usr/bin/env python
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

import gobject
import gtk
import threading
import serial
import os

import csvdump
from chirp.ui import inputdialog, cloneprog

import chirp
from chirp import ic9x, id800, ic2820, ic2200, errors
from chirp import platform

gobject.threads_init()

RADIOS = {"ic9x:A": ic9x.IC9xRadioA,
          "ic9x:B": ic9x.IC9xRadioB,
          "id800":  id800.ID800v2Radio,
          "ic2820": ic2820.IC2820Radio,
          "ic2200": ic2200.IC2200Radio,
          }


class CsvDumpApp:
    def update_status(self, s):
        gobject.idle_add(self.progwin.status, s)

    def _download_img(self):
        gobject.idle_add(self.progwin.show)
        fn = "%s.img" % self.rtype

        try:
            s = serial.Serial(port=self.rport,
                              baudrate=RADIOS[self.rtype].BAUD_RATE,
                              timeout=0.5)

            radio = RADIOS[self.rtype](s)
            radio.status_fn = self.update_status
            radio.sync_in()

            print "Sync done, saving to: %s" % fn
            radio.save_mmap(fn)

            self.refresh_radio()
        except serial.SerialException, e:
            gobject.idle_add(self.mainwin.set_status,
                             "Error: Unable to open serial port")
        except Exception, e:
            gobject.idle_add(self.mainwin.set_status,
                             "Error: %s" % e)

        try:
            s.close()
        except Exception:
            pass

        gobject.idle_add(self.progwin.hide)

    def download_img(self):
        t = threading.Thread(target=self._download_img)
        t.start()

    def _upload_img(self):
        gobject.idle_add(self.progwin.show)
        fn = "%s.img" % self.rtype

        try:
            s = serial.Serial(port=self.rport,
                              baudrate=RADIOS[self.rtype].BAUD_RATE,
                              timeout=0.5)

            radio = RADIOS[self.rtype](s)
            radio.status_fn = self.update_status

            print "Loading image from %s" % fn
            radio.load_mmap(fn)

            radio.sync_out()
        except Exception, e:
            gobject.idle_add(self.mainwin.set_status,
                             "Error: %s" % e)

        try:
            s.close()
        except Exception:
            pass

        gobject.idle_add(self.progwin.hide)

    def upload_img(self):
        t = threading.Thread(target=self._upload_img)
        t.start()

    def _export_file_mmap(self, fname):
        count = 0

        try:
            f = file(fname, "w")
        except Exception, e:
            self.mainwin.set_status("%s: %s" % (fname, e))
            return

        print >>f, chirp.chirp_common.Memory.CSV_FORMAT
        for m in self.radio.get_memories():
            print >>f, m.to_csv()
            count += 1
        f.close()

        self.mainwin.set_status("Exported %i memories" % count)

    def _export_file_live(self, fname, l, h):
        gobject.idle_add(self.progwin.show)

        try:
            f = file(fname, "w")
        except Exception, e:
            gobject.idle_add(self.progwin.hide)
            gobject.idle_add(self.mainwin.set_status, "%s: %s" % (fname, e))
            return

        print >>f, chirp.chirp_common.Memory.CSV_FORMAT
        for i in range(l, h+1):
            s = chirp.chirp_common.Status()
            s.msg = "Reading memory %i" % i
            s.cur = i
            s.max = h+1
            gobject.idle_add(self.progwin.status, s)

            try:
                m = self.radio.get_memory(i)
                print >>f, m.to_csv()
            except chirp.errors.InvalidMemoryLocation:
                pass

        f.close()

        gobject.idle_add(self.progwin.hide)

    def get_mem_range(self):
        d = inputdialog.FieldDialog(title="Select Memory Range")

        limit = RADIOS[self.rtype].mem_upper_limit

        la = gtk.Adjustment(0, 0, limit, 1, 10, 10)
        d.add_field("Start", gtk.SpinButton(la, 0))

        ua = gtk.Adjustment(100, 0, limit, 1, 10, 10)
        d.add_field("End", gtk.SpinButton(ua, 0))

        r = d.run()
        low = int(la.get_value())
        high = int(ua.get_value())
        d.destroy()

        if r == gtk.RESPONSE_OK:
            return low, high
        else:
            return None, None

    def export_file(self, fname):
        if not fname.lower().endswith(".csv"):
            fname += ".csv"

        if self.rtype.startswith("ic9x"):
            l, h = self.get_mem_range()
            if l is None or h is None:
                return

            t = threading.Thread(target=self._export_file_live,
                                 args=(fname, l, h))
            t.start()
        else:
            self._export_file_mmap(fname)

    def _parse_mem_line(self, line):
        try:
            num, name, freq, _ = line.split(",")
            m = chirp.chirp_common.Memory()
            m.name = name
            m.number = int(num)
            m.freq = float(freq)
        except Exception, e:
            print "Failed to parse `%s': %s" % (line, e)
            return None

        return m

    def _import_file_live(self, fname):
        gobject.idle_add(self.progwin.show)

        try:
            f = file(fname, "rU")
        except Exception, e:
            gobject.idle_add(self.progwin.hide)
            gobject.idle_add(self.mainwin.set_status,
                             "%s: %s" % (fname, e))
            return

        lines = f.readlines()
        f.close()

        memories = []
        lineno = 0
        for line in lines:
            try:
                m = chirp.chirp_common.Memory.from_csv(line)
            except errors.InvalidMemoryLocation:
                continue
            except Exception, e:
                print "Parse error on line %i: %s" % (lineno, e)
                break  # FIXME: Report error here

            lineno += 1
            memories.append(m)

        count = 0
        for m in memories:
            s = chirp.chirp_common.Status()
            s.msg = "Sending memory %i" % m.number
            s.cur = count
            s.max = len(memories)
            gobject.idle_add(self.progwin.status, s)

#            try:
#                self.radio.get_memory(m.number, 2)
#            except errors.InvalidMemoryLocation:
#                m

            try:
                self.radio.set_memory(m)
            except Exception, e:
                print "Error setting memory %i: %s" % (m.number, e)
                break

            count += 1

        gobject.idle_add(self.progwin.hide)

        gobject.idle_add(self.mainwin.set_status, "Wrote %i memories" % count)

    def _import_file_mmap(self, fname):
        try:
            f = file(fname, "rU")
        except Exception, e:
            self.progwin.hide()
            self.mainwin.set_status("%s: %s" % (fname, e))
            return

        lines = f.readlines()
        f.close()
        lineno = 0

        for line in lines:
            lineno += 1
            try:
                m = chirp.chirp_common.Memory.from_csv(line.strip())
                print "Imported: %s" % m
            except Exception, e:
                if lineno == 1:
                    continue
                import traceback
                traceback.print_exc()
                self.mainwin.set_status("Error on line %i: %s" % (lineno, e))
                return

            print "Setting memory: %s" % m
            self.radio.set_memory(m)

        print "Saving image to %s.img" % self.rtype
        self.radio.save_mmap("%s.img" % self.rtype)

        self.mainwin.set_status("Imported %s" % os.path.basename(fname))

    def import_file(self, fname):
        if self.rtype.startswith("ic9x"):
            t = threading.Thread(target=self._import_file_live,
                                 args=(fname,))
            t.start()
        else:
            self._import_file_mmap(fname)

    def refresh_radio(self):
        rtype = RADIOS[self.rtype]
        smsg = "Ready"

        if self.radio:
            try:
                self.radio.pipe.close()
            except Exception, e:
                pass

        if not self.rtype.startswith("ic9x"):
            mmap = "%s.img" % self.rtype
            if os.path.isfile(mmap):
                self.radio = rtype(mmap)
                self.mainwin.set_image_info(True, True, "Image loaded")
            else:
                self.radio = None
                self.mainwin.set_image_info(False, False, "No image")
                smsg = "Radio image must be downloaded"
        else:
            try:
                s = serial.Serial(port=self.rport,
                                  baudrate=rtype.BAUD_RATE,
                                  timeout=0.1)
                self.radio = rtype(s)
                self.mainwin.set_image_info(False, True, "Live")
            except Exception, e:
                smsg = "Error: Unable to open serial port"
                self.mainwin.set_image_info(False, False, "")

        self.mainwin.set_status(smsg)

    def select_radio(self, radio, port):
        self.rtype = radio
        self.rport = port
        self.refresh_radio()

    def __init__(self):
        self.mainwin = csvdump.CsvDumpWindow(self.select_radio,
                                             self.download_img,
                                             self.upload_img,
                                             self.import_file,
                                             self.export_file)

        self.progwin = cloneprog.CloneProg()
        self.progwin.set_transient_for(self.mainwin)
        self.progwin.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)

        self.radio = None

    def run(self):
        self.mainwin.show()
        self.mainwin.connect("destroy", lambda x: gtk.main_quit())

        gtk.main()


if __name__ == "__main__":
    a = CsvDumpApp()
    a.run()
