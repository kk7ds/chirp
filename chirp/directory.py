# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

import os
import tempfile

from chirp import icf
from chirp import chirp_common, util, rfinder, errors

def radio_class_id(cls):
    ident = "%s_%s" % (cls.VENDOR, cls.MODEL)
    if cls.VARIANT:
        ident += "_%s" % cls.VARIANT
    ident = ident.replace("/", "_")
    ident = ident.replace(" ", "_")
    ident = ident.replace("(", "")
    ident = ident.replace(")", "")
    return ident

def register(cls):
    global DRV_TO_RADIO
    ident = radio_class_id(cls)
    if ident in DRV_TO_RADIO.keys():
        raise Exception("Duplicate radio driver id `%s'" % ident)
    DRV_TO_RADIO[ident] = cls
    RADIO_TO_DRV[cls] = ident
    print "Registered %s = %s" % (ident, cls.__name__)

    return cls

DRV_TO_RADIO = {}
RADIO_TO_DRV = {}

def get_radio(driver):
    if DRV_TO_RADIO.has_key(driver):
        return DRV_TO_RADIO[driver]
    else:
        raise Exception("Unknown radio type `%s'" % driver)

def get_driver(radio):
    if RADIO_TO_DRV.has_key(radio):
        return RADIO_TO_DRV[radio]
    elif RADIO_TO_DRV.has_key(radio.__bases__[0]):
        return RADIO_TO_DRV[radio.__bases__[0]]
    else:
        raise Exception("Unknown radio type `%s'" % radio)

def icf_to_image(icf_file, img_file):
    mdata, mmap = icf.read_file(icf_file)
    img_data = None

    for model in DRV_TO_RADIO.values():
        try:
            if model._model == mdata:
                img_data = mmap.get_packed()[:model._memsize]
                break
        except Exception:
            pass # Skip non-Icoms

    if img_data:
        f = file(img_file, "wb")
        f.write(img_data)
        f.close()
    else:
        print "Unsupported model data:"
        print util.hexprint(mdata)
        raise Exception("Unsupported model")

def get_radio_by_image(image_file):
    if image_file.startswith("rfinder://"):
        method, _, email, passwd, lat, lon = image_file.split("/")
        rf = rfinder.RFinderRadio(None)
        rf.set_params(float(lat), float(lon), email, passwd)
        return rf
    
    if os.path.exists(image_file) and icf.is_icf_file(image_file):
        tempf = tempfile.mktemp()
        icf_to_image(image_file, tempf)
        print "Auto-converted %s -> %s" % (image_file, tempf)
        image_file = tempf

    if os.path.exists(image_file):
        f = file(image_file, "rb")
        filedata = f.read()
        f.close()
    else:
        filedata = ""

    for radio in DRV_TO_RADIO.values():
        if not issubclass(radio, chirp_common.FileBackedRadio):
            continue
        if radio.match_model(filedata, image_file):
            return radio(image_file)
    raise errors.ImageDetectFailed("Unknown file format")

def get_radio_name(driver):
    cls = DRV_TO_RADIO[driver]
    return cls._get_name(cls)

if __name__ == "__main__":
    vendors = {
        "Icom" : {},
        "Yaesu" : {},
        "Kenwood" : {},
        }

    for radio in DRV_TO_RADIO.values():
        vendors[radio.VENDOR][radio.MODEL]
        print "%s %s:" % (radio.VENDOR, radio.MODEL)
        if radio.VARIANT:
            print "  Variant: %s" % radio.VARIANT
        print "  Baudrate: %i" % radio.BAUD_RATE
