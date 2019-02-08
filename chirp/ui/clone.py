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

import collections
import threading
import logging
import os

import gtk
import gobject

from chirp import platform, directory, detect, chirp_common
from chirp.ui import miscwidgets, cloneprog, inputdialog, common, config

LOG = logging.getLogger(__name__)

AUTO_DETECT_STRING = "Auto Detect (Icom Only)"


class CloneSettings:
    def __init__(self):
        self.port = None
        self.radio_class = None

    def __str__(self):
        s = ""
        if self.radio_class:
            return _("{vendor} {model} on {port}").format(
                vendor=self.radio_class.VENDOR,
                model=self.radio_class.MODEL,
                port=self.port)


class CloneSettingsDialog(gtk.Dialog):
    def __make_field(self, label, widget):
        l = gtk.Label(label)
        self.__table.attach(l, 0, 1, self.__row, self.__row+1)
        self.__table.attach(widget, 1, 2, self.__row, self.__row+1)
        self.__row += 1

        l.show()
        widget.show()

    def __make_port(self, port):
        conf = config.get("state")

        ports = platform.get_platform().list_serial_ports()
        if not port:
            if conf.get("last_port"):
                port = conf.get("last_port")
            elif ports:
                port = ports[0]
            else:
                port = ""
            if port not in ports:
                ports.insert(0, port)

        return miscwidgets.make_choice(ports, True, port)

    def __make_model(self):
        return miscwidgets.make_choice([], False)

    def __make_vendor(self, modelbox):
        vendors = collections.defaultdict(list)
        for name, rclass in sorted(directory.DRV_TO_RADIO.items()):
            if not issubclass(rclass, chirp_common.CloneModeRadio) and \
                    not issubclass(rclass, chirp_common.LiveRadio):
                continue

            vendors[rclass.VENDOR].append(rclass)
            for alias in rclass.ALIASES:
                vendors[alias.VENDOR].append(alias)

        self.__vendors = vendors

        conf = config.get("state")
        if not conf.get("last_vendor"):
            conf.set("last_vendor", sorted(vendors.keys())[0])

        last_vendor = conf.get("last_vendor")
        if last_vendor not in list(vendors.keys()):
            last_vendor = list(vendors.keys())[0]

        v = miscwidgets.make_choice(sorted(vendors.keys()), False, last_vendor)

        def _changed(box, vendors, boxes):
            (vendorbox, modelbox) = boxes
            models = vendors[vendorbox.value]

            added_models = []

            model_store = modelbox.get_model()
            model_store.clear()
            for rclass in sorted(models, key=lambda c: c.__name__):
                if rclass.MODEL not in added_models:
                    model_store.append([rclass.MODEL])
                    added_models.append(rclass.MODEL)

            if vendorbox.value in detect.DETECT_FUNCTIONS:
                model_store.append([_("Detect")])
                added_models.insert(0, _("Detect"))

            model_names = [x.MODEL for x in models]
            if conf.get("last_model") in model_names:
                modelbox.value = conf.get("last_model")
            elif added_models:
                modelbox.value = added_models[0]

        v.widget.connect("changed", _changed, vendors, (v, modelbox))
        _changed(v, vendors, (v, modelbox))

        return v

    def __make_ui(self, settings):
        self.__table = gtk.Table(3, 2)
        self.__table.set_row_spacings(3)
        self.__table.set_col_spacings(10)
        self.__row = 0

        self.__port = self.__make_port(settings and settings.port or None)
        self.__modl = self.__make_model()
        self.__vend = self.__make_vendor(self.__modl)

        self.__make_field(_("Port"), self.__port.widget)
        self.__make_field(_("Vendor"), self.__vend.widget)
        self.__make_field(_("Model"), self.__modl.widget)

        if settings and settings.radio_class:
            self.__vend.value = settings.radio_class.VENDOR
            self.__modl.value = settings.radio_class.MODEL
            self.__vend.widget.set_sensitive(False)
            self.__modl.widget.set_sensitive(False)

        self.__table.show()
        self.vbox.pack_start(self.__table, 1, 1, 1)

    def __init__(self, settings=None, parent=None, title=_("Radio")):
        buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                   gtk.STOCK_OK, gtk.RESPONSE_OK)
        gtk.Dialog.__init__(self, title,
                            parent=parent,
                            flags=gtk.DIALOG_MODAL)
        self.__make_ui(settings)
        self.__cancel_button = self.add_button(gtk.STOCK_CANCEL,
                                               gtk.RESPONSE_CANCEL)
        self.__okay_button = self.add_button(gtk.STOCK_OK,
                                             gtk.RESPONSE_OK)
        self.__okay_button.grab_default()
        self.__okay_button.grab_focus()

    def run(self):
        r = gtk.Dialog.run(self)
        if r != gtk.RESPONSE_OK:
            return None

        vendor = self.__vend.value
        model = self.__modl.value

        cs = CloneSettings()
        cs.port = self.__port.value
        if model == _("Detect"):
            try:
                cs.radio_class = detect.DETECT_FUNCTIONS[vendor](cs.port)
                if not cs.radio_class:
                    raise Exception(
                        _("Unable to detect radio on {port}").format(
                            port=cs.port))
            except Exception as e:
                d = inputdialog.ExceptionDialog(e)
                d.run()
                d.destroy()
                return None
        else:
            for rclass in list(directory.DRV_TO_RADIO.values()):
                if rclass.MODEL == model:
                    cs.radio_class = rclass
                    break
                alias_match = None
                for alias in rclass.ALIASES:
                    if alias.MODEL == model:
                        alias_match = rclass
                        alias_class = alias
                        break
                if alias_match:

                    class DynamicRadioAlias(rclass):
                        VENDOR = alias.VENDOR
                        MODEL = alias.MODEL
                        VARIANT = alias.VARIANT

                    cs.radio_class = DynamicRadioAlias
                    LOG.debug(
                        'Chose %s alias for %s because model %s selected' % (
                            alias_match, cs.radio_class, model))
                    break
            if not cs.radio_class:
                common.show_error(
                    _("Internal error: Unable to upload to {model}").format(
                        model=model))
                LOG.info(self.__vendors)
                return None

        conf = config.get("state")
        conf.set("last_port", cs.port)
        conf.set("last_vendor", cs.radio_class.VENDOR)
        conf.set("last_model", model)

        return cs


class CloneCancelledException(Exception):
    pass


class CloneThread(threading.Thread):
    def __status(self, status):
        gobject.idle_add(self.__progw.status, status)

    def __init__(self, radio, direction, cb=None, parent=None):
        threading.Thread.__init__(self)

        self.__radio = radio
        self.__out = direction == "out"
        self.__cback = cb
        self.__cancelled = False

        self.__progw = cloneprog.CloneProg(parent=parent, cancel=self.cancel)

    def cancel(self):
        self.__radio.pipe.close()
        self.__cancelled = True

    def run(self):
        LOG.debug("Clone thread started")

        gobject.idle_add(self.__progw.show)

        self.__radio.status_fn = self.__status

        try:
            if self.__out:
                self.__radio.sync_out()
            else:
                self.__radio.sync_in()

            emsg = None
        except Exception as e:
            common.log_exception()
            LOG.error(_("Clone failed: {error}").format(error=e))
            emsg = e

        gobject.idle_add(self.__progw.hide)

        # NB: Compulsory close of the radio's serial connection
        self.__radio.pipe.close()

        LOG.debug("Clone thread ended")

        if self.__cback and not self.__cancelled:
            gobject.idle_add(self.__cback, self.__radio, emsg)


if __name__ == "__main__":
    d = CloneSettingsDialog("/dev/ttyUSB0")
    r = d.run()
    print(r)
