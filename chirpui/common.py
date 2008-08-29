import gobject

class Editor(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    root = None

    def __init__(self):
        gobject.GObject.__init__(self)

gobject.type_register(Editor)
