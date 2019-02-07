import contextlib
import logging

import gtk

LOG = logging.getLogger('uicompat')


@contextlib.contextmanager
def py3safe():
    try:
        yield
    except Exception as e:
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
