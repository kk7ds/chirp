import gtk

class CloneProg(gtk.Window):
    def __init__(self, **args):
        gtk.Window.__init__(self, **args)

        vbox = gtk.VBox(False, 2)
        vbox.show()
        self.add(vbox)

        self.set_title("Clone Progress")
        self.set_resizable(False)

        self.infolabel = gtk.Label("Cloning")
        self.infolabel.show()
        vbox.pack_start(self.infolabel, 1,1,1)

        self.progbar = gtk.ProgressBar()
        self.progbar.set_fraction(0.0)
        self.progbar.show()
        vbox.pack_start(self.progbar, 0,0,0)

    def status(self, s):
        self.infolabel.set_text(s.msg)

        self.progbar.set_fraction(s.cur / float(s.max))

if __name__ == "__main__":
    w = CloneProg()
    w.show()

    gtk.main()
