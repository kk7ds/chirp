import gtk
import gobject
import pango
import re
import os
import logging

from chirp import bitwise
from chirp.ui import common, config

LOG = logging.getLogger(__name__)

CONF = config.get()


def do_insert_line_with_tags(b, line):
    def i(text, *tags):
        b.insert_with_tags_by_name(b.get_end_iter(), text, *tags)

    def ident(name):
        if "unknown" in name:
            i(name, 'grey', 'bold')
        else:
            i(name, 'bold')

    def nonzero(value):
        i(value, 'red', 'bold')

    def foo(value):
        i(value, 'blue', 'bold')

    m = re.match("^( *)([A-z0-9_]+: )(0x[A-F0-9]+) \((.*)\)$", line)
    if m:
        i(m.group(1))
        ident(m.group(2))
        if m.group(3) == '0x00':
            i(m.group(3))
        else:
            nonzero(m.group(3))
        i(' (')
        for char in m.group(4):
            if char == '1':
                nonzero(char)
            else:
                i(char)
        i(')')
        return

    m = re.match("^( *)([A-z0-9_]+: )(.*)$", line)
    if m:
        i(m.group(1))
        ident(m.group(2))
        i(m.group(3))
        return

    m = re.match("^(.*} )([A-z0-9_]+)( \()([0-9]+)( bytes at )(0x[A-F0-9]+)",
                 line)
    if m:
        i(m.group(1))
        ident(m.group(2))
        i(m.group(3))
        foo(m.group(4))
        i(m.group(5))
        foo(m.group(6))
        i(")")
        return

    i(line)


def do_insert_with_tags(buf, text):
    buf.set_text('')
    lines = text.split(os.linesep)
    for line in lines:
        do_insert_line_with_tags(buf, line)
        buf.insert_with_tags_by_name(buf.get_end_iter(), os.linesep)


def classname(obj):
    return str(obj.__class__).split('.')[-1]


def bitwise_type(classname):
    return classname.split("DataElement")[0]


class FixedEntry(gtk.Entry):
    def __init__(self, *args, **kwargs):
        super(FixedEntry, self).__init__(*args, **kwargs)

        try:
            fontsize = CONF.get_int("browser_fontsize", "developer")
        except Exception:
            fontsize = 10
        if fontsize < 4 or fontsize > 144:
            LOG.warn("Unsupported browser_fontsize %i. Using 10." % fontsize)
            fontsize = 11

        fontdesc = pango.FontDescription("Courier bold %i" % fontsize)
        self.modify_font(fontdesc)


class IntegerEntry(FixedEntry):
    def _colorize(self, _self):
        value = self.get_text()
        if value.startswith("0x"):
            value = value[2:]
        value = value.replace("0", "")
        if not value:
            self.modify_text(gtk.STATE_NORMAL, None)
        else:
            self.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse('red'))

    def __init__(self, *args, **kwargs):
        super(IntegerEntry, self).__init__(*args, **kwargs)
        self.connect("changed", self._colorize)


class BitwiseEditor(gtk.HBox):
    def __init__(self, element):
        super(BitwiseEditor, self).__init__(False, 3)
        self._element = element
        self._build_ui()


class IntegerEditor(BitwiseEditor):
    def _changed(self, entry, base):
        if not self._update:
            return
        value = entry.get_text()
        if value.startswith("0x"):
            value = value[2:]
        self._element.set_value(int(value, base))
        self._update_entries(skip=entry)

    def _update_entries(self, skip=None):
        self._update = False
        for ent, format_spec in self._entries:
            if ent != skip:
                ent.set_text(format_spec.format(int(self._element)))
        self._update = True

    def _build_ui(self):
        self._entries = []
        self._update = True

        hexdigits = ((self._element.size() / 4) +
                     (self._element.size() % 4 and 1 or 0))
        formats = [('Hex', 16, '0x{:0%iX}' % hexdigits),
                   ('Dec', 10, '{:d}'),
                   ('Bin', 2, '{:0%ib}' % self._element.size())]
        for name, base, format_spec in formats:
            lab = gtk.Label(name)
            self.pack_start(lab, 0, 0, 0)
            lab.show()
            int(self._element)
            ent = IntegerEntry()
            self._entries.append((ent, format_spec))
            ent.connect('changed', self._changed, base)
            self.pack_start(ent, 0, 0, 0)
            ent.show()
        self._update_entries()


class BCDArrayEditor(BitwiseEditor):
    def _changed(self, entry, hexent):
        self._element.set_value(int(entry.get_text()))
        self._format_hexent(hexent)

    def _format_hexent(self, hexent):
        value = ""
        for i in self._element:
            a, b = i.get_value()
            value += "%i%i" % (a, b)
        hexent.set_text(value)

    def _build_ui(self):
        lab = gtk.Label("Dec")
        lab.show()
        self.pack_start(lab, 0, 0, 0)
        ent = FixedEntry()
        ent.set_text(str(int(self._element)))
        ent.show()
        self.pack_start(ent, 1, 1, 1)

        lab = gtk.Label("Hex")
        lab.show()
        self.pack_start(lab, 0, 0, 0)

        hexent = FixedEntry()
        hexent.show()
        self.pack_start(hexent, 1, 1, 1)
        hexent.set_editable(False)

        ent.connect('changed', self._changed, hexent)
        self._format_hexent(hexent)


class CharArrayEditor(BitwiseEditor):
    def _changed(self, entry):
        self._element.set_value(entry.get_text().ljust(len(self._element)))

    def _build_ui(self):
        ent = FixedEntry(len(self._element))
        ent.set_text(str(self._element).rstrip("\x00"))
        ent.connect('changed', self._changed)
        ent.show()
        self.pack_start(ent, 1, 1, 1)


class OtherEditor(BitwiseEditor):
    def _build_ui(self):
        name = classname(self._element)
        name = bitwise_type(name)
        if isinstance(self._element, bitwise.arrayDataElement):
            name += " %s[%i]" % (
                bitwise_type(classname(self._element[0])),
                len(self._element))

        l = gtk.Label(name)
        l.show()
        self.pack_start(l, 1, 1, 1)


class RadioBrowser(common.Editor):
    def _build_ui(self):
        self._display = gtk.Table(20, 2)

        self._store = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self._tree = gtk.TreeView(self._store)

        rend = gtk.CellRendererText()
        tvc = gtk.TreeViewColumn('Element', rend, text=0)
        self._tree.append_column(tvc)
        self._tree.connect('button_press_event', self._tree_click)

        self.root = gtk.HPaned()
        self.root.set_position(200)
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self._tree)
        sw.show()
        self.root.add1(sw)
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(self._display)
        sw.show()
        self.root.add2(sw)
        self._tree.show()
        self._display.show()
        self.root.show()

    def _fill(self, name, obj, parent=None):
        iter = self._store.append(parent, (name, obj))

        if isinstance(obj, bitwise.structDataElement):
            for name, item in obj.items():
                if isinstance(item, bitwise.structDataElement):
                    self._fill(name, item, iter)
                elif isinstance(item, bitwise.arrayDataElement):
                    self._fill("%s[%i]" % (name, len(item)), item, iter)
        elif isinstance(obj, bitwise.arrayDataElement):
            i = 0
            for item in obj:
                if isinstance(obj[0], bitwise.structDataElement):
                    self._fill("%s[%i]" % (name, i), item, iter)
                i += 1

    def _tree_click(self, view, event):
        if event.button != 1:
            return

        index = [0]

        def pack(widget, pos):
            self._display.attach(widget, pos, pos + 1, index[0], index[0] + 1,
                                 xoptions=gtk.FILL, yoptions=0)

        def next_row():
            index[0] += 1

        def abandon(child):
            self._display.remove(child)

        pathinfo = view.get_path_at_pos(int(event.x), int(event.y))
        path = pathinfo[0]
        iter = self._store.get_iter(path)
        name, obj = self._store.get(iter, 0, 1)

        self._display.foreach(abandon)

        for name, item in obj.items():
            if item.size() % 8 == 0:
                name = '<b>%s</b> <small>(%s %i bytes)</small>' % (
                    name, bitwise_type(classname(item)), item.size() / 8)
            else:
                name = '<b>%s</b> <small>(%s %i bits)</small>' % (
                    name, bitwise_type(classname(item)), item.size())
            l = gtk.Label(name + "   ")
            l.set_use_markup(True)
            l.show()
            pack(l, 0)

            if (isinstance(item, bitwise.intDataElement) or
                    isinstance(item, bitwise.bcdDataElement)):
                e = IntegerEditor(item)
            elif (isinstance(item, bitwise.arrayDataElement) and
                  isinstance(item[0], bitwise.bcdDataElement)):
                e = BCDArrayEditor(item)
            elif (isinstance(item, bitwise.arrayDataElement) and
                  isinstance(item[0], bitwise.charDataElement)):
                e = CharArrayEditor(item)
            else:
                e = OtherEditor(item)
            e.show()
            pack(e, 1)
            next_row()

    def __init__(self, rthread):
        super(RadioBrowser, self).__init__(rthread)
        self._radio = rthread.radio
        self._focused = False
        self._build_ui()
        self._fill('root', self._radio._memobj)

    def focus(self):
        self._focused = True

    def unfocus(self):
        if self._focused:
            self.emit("changed")
            self._focused = False


if __name__ == "__main__":
    from chirp.drivers import *
    from chirp import directory
    import sys

    r = directory.get_radio_by_image(sys.argv[1])

    class Foo:
        radio = r

    w = gtk.Window()
    b = RadioBrowser(Foo)
    w.set_default_size(1024, 768)
    w.add(b.root)
    w.show()
    gtk.main()
