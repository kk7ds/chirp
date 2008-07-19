
import gobject
import gtk
import threading
import serial
import os

import csvdump
import cloneprog

gobject.threads_init()

import chirp
from chirp import ic9x, id800, ic2820

import platform

RADIOS = { "ic9x"  : ic9x.IC9xRadio,
           "id800" : id800.ID800v2Radio,
           "ic2820": ic2820.IC2820Radio,
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
        except Exception, e:
            gobject.idle_add(self.mainwin.set_status,
                             "Error: %s" % e)

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

        gobject.idle_add(self.progwin.hide)

    def upload_img(self):
        t = threading.Thread(target=self._upload_img)
        t.start()
    
    def _export_file_mmap(self, fname):
        count = 0

        f = file(fname, "w")
        print >>f, "Location,Name,Frequency,"
        for m in self.radio.get_memories():
            print >>f, "%i,%s,%.3f," % (m.number, m.name, m.freq)
            count += 1
        f.close()

        self.mainwin.set_status("Exported %i memories" % count)

    def _export_file_live(self, fname):
        gobject.idle_add(self.progwin.show)

        f = file(fname, "w")

        for i in range(20):
            s = chirp.chirp_common.Status()
            s.msg = "Reading memory %i" % i
            s.cur = i
            s.max = 20
            gobject.idle_add(self.progwin.status, s)

            try:
                m = self.radio.get_memory(i, vfo=2)
                print >>f, "%i,%s,%.3f," % (m.number, m.name, m.freq)
            except chirp.errors.InvalidMemoryLocation:
                pass

        f.close()

        gobject.idle_add(self.progwin.hide)

    def export_file(self, fname):
        if self.rtype == "ic9x":
            t = threading.Thread(target=self._export_file_live,
                                 args=(fname,))
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

        f = file(fname, "r")
        lines = f.readlines()
        f.close()

        memories = []
        for line in lines:
            m = self._parse_mem_line(line)
            if m:
                memories.append(m)

        count = 0
        for m in memories:
            s = chirp.chirp_common.Status()
            s.msg = "Sending memory %i" % m.number
            s.cur = count
            s.max = len(memories)
            gobject.idle_add(self.progwin.status, s)

            try:
                self.radio.get_memory(m.number, 2)
                m.vfo = 2
                self.radio.set_memory(m)
            except Exception, e:
                print "Error setting memory %i: %s" % (m.number, e)
                break

            count += 1

        gobject.idle_add(self.progwin.hide)

        gobject.idle_add(self.mainwin.set_status, "Wrote %i memories" % count)

    def _import_file_mmap(self, fname):
        f = file(fname, "r")
        lines = f.readlines()
        f.close()

        for line in lines:
            m = self._parse_mem_line(line)
            if m:
                print "Setting memory: %s" % m
                self.radio.set_memory(m)

        print "Saving image to %s.img" % self.rtype
        self.radio.save_mmap("%s.img" % self.rtype)

        self.mainwin.set_status("Imported %s" % os.path.basename(fname))

    def import_file(self, fname):
        if self.rtype == "ic9x":
            t = threading.Thread(target=self._import_file_live,
                                 args=(fname,))
            t.start()
        else:
            self._import_file_mmap(fname)

    def refresh_radio(self):
        rtype = RADIOS[self.rtype]
        smsg = ""

        if self.rtype != "ic9x":
            mmap = "%s.img" % self.rtype
            if os.path.isfile(mmap):
                self.radio = rtype(mmap)
                self.mainwin.set_image_info(True, True, "Image loaded")
            else:
                self.radio = None
                self.mainwin.set_image_info(False, False, "No image")
        else:
            try:
                s = serial.Serial(port=self.rport,
                                  baudrate=rtype.BAUD_RATE,
                                  timeout=0.5)
                self.radio = rtype(s)
            except Exception, e:
                smsg = "Error: %s" % e

            self.mainwin.set_image_info(False, True, "Live")

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
        
    def run(self):
        self.mainwin.show()
        self.mainwin.connect("destroy", lambda x: gtk.main_quit())

        gtk.main()

if __name__ == "__main__":
    a = CsvDumpApp()
    a.run()
