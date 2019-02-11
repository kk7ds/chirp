import contextlib
import logging
import serial as base_serial
import six

try:
    import gtk
except ImportError:
    # FIXME
    # For chirpc
    gtk = None

from chirp import bitwise

LOG = logging.getLogger('uicompat')


@contextlib.contextmanager
def py3safe(quiet=False):
    try:
        yield
    except Exception as e:
        if not quiet:
            LOG.exception('FIXMEPY3: %s' % e)


def SpinButton(adj):
    try:
        return gtk.SpinButton(adj)
    except TypeError:
        sb = gtk.SpinButton()
        sb.configure(adj, 1.0, 0)
        return sb

def Frame(label):
    try:
        return gtk.Frame(label)
    except TypeError:
        f = gtk.Frame()
        f.set_label(label)
        return f


class CompatSerial(base_serial.Serial):
    """A PY2-compatible Serial class

    This wraps serial.Serial to provide translation between
    hex-char-having unicode strings in radios and the bytes-wanting
    serial channel. See bitwise.string_straigth_encode() and
    bitwise.string_straight_decode() for more details.

    This should only be used as a bridge for older drivers until
    they can be rewritten.
    """
    def write(self, data):
        data = bitwise.string_straight_encode(data)
        return super(CompatSerial, self).write(data)

    def read(self, count):
        data = super(CompatSerial, self).read(count)
        return bitwise.string_straight_decode(data)

    @classmethod
    def get(cls, needs_compat, *args, **kwargs):
        if six.PY3 and needs_compat:
            return cls(*args, **kwargs)
        else:
            return base_serial.Serial(*args, **kwargs)


class CompatTooltips(object):
    def __init__(self):
        try:
            self.tips = gtk.Tooltips()
        except AttributeError:
            self.tips = None

    def set_tip(self, widget, tip):
        if self.tips:
            self.tips.set_tip(widget, tip)
        else:
            widget.set_tooltip_text(tip)
