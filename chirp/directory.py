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

from chirp import id800, id880, ic2820, ic2200, ic9x, icx8x, ic2100, ic2720
from chirp import icq7, icomciv, idrp, icf, ic9x_icf, icw32, ict70
from chirp import vx3, vx5, vx6, vx7, vx8, ft2800, ft7800, ft50, ft60
from chirp import kenwood_live, tmv71, thd72
from chirp import alinco
from chirp import wouxun
from chirp import xml, chirp_common, generic_csv, util, rfinder, errors

DRV_TO_RADIO = {
    # Virtual/Generic
    "csv"            : generic_csv.CSVRadio,
    "xml"            : xml.XMLRadio,

    # Icom
    "ic2720"         : ic2720.IC2720Radio,
    "ic2820"         : ic2820.IC2820Radio,
    "ic2200"         : ic2200.IC2200Radio,
    "ic2100"         : ic2100.IC2100Radio,
    "ic9x"           : ic9x.IC9xRadio,
    "id800"          : id800.ID800v2Radio,
    "id880"          : id880.ID880Radio,
    "icx8x"          : icx8x.ICx8xRadio,
    "idrpx000v"      : idrp.IDRPx000V,
    "icq7"           : icq7.ICQ7Radio,
    "icw32"          : icw32.ICW32ARadio,
    "ict70"          : ict70.ICT70Radio,
    "icom7200"       : icomciv.Icom7200Radio,
    "ic9xicf"        : ic9x_icf.IC9xICFRadio,

    # Yaesu
    "vx3"            : vx3.VX3Radio,
    "vx5"            : vx5.VX5Radio,
    "vx6"            : vx6.VX6Radio,
    "vx7"            : vx7.VX7Radio,
    "vx8"            : vx8.VX8Radio,
    "vx8d"           : vx8.VX8DRadio,
    "ft2800"         : ft2800.FT2800Radio,
    "ft7800"         : ft7800.FT7800Radio,
    "ft8800"         : ft7800.FT8800Radio,
    "ft8900"         : ft7800.FT8900Radio,
    #"ft50"           : ft50.FT50Radio,
    "ft60"           : ft60.FT60Radio,

    # Kenwood
    "thd7"           : kenwood_live.THD7Radio,
    "thd7g"          : kenwood_live.THD7GRadio,
    "thd72"          : thd72.THD72Radio,
    "tm271"          : kenwood_live.TM271Radio,
    "tmd700"         : kenwood_live.TMD700Radio,
    "tmd710"         : kenwood_live.TMD710Radio,
    "tmv7"           : kenwood_live.TMV7Radio,
    "thk2"           : kenwood_live.THK2Radio,
    "thf6"           : kenwood_live.THF6ARadio,
    "thf7"           : kenwood_live.THF7ERadio,
    "v71a"           : kenwood_live.TMV71Radio,

    # Jetstream
    "jt220m"         : alinco.JT220MRadio,

    # Alinco
    "dr03"           : alinco.DR03Radio,
    "dr06"           : alinco.DR06Radio,
    "dr135"          : alinco.DR135Radio,
    "dr235"          : alinco.DR235Radio,
    "dr435"          : alinco.DR435Radio,
    "dj596"          : alinco.DJ596Radio,

    # Wouxun
    "kguvd1p"        : wouxun.KGUVD1PRadio,

    # Puxing
    "px777"          : wouxun.Puxing777Radio,
    "px2r"           : wouxun.Puxing2RRadio,
   
    # Baofeng
    "uv3r"	     : wouxun.UV3RRadio,
}

RADIO_TO_DRV = {}
for __key, __val in DRV_TO_RADIO.items():
    RADIO_TO_DRV[__val] = __key

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
    
    if image_file.lower().endswith(".chirp"):
        return xml.XMLRadio(image_file)

    if image_file.lower().endswith(".csv"):
        return generic_csv.CSVRadio(image_file)

    if icf.is_9x_icf(image_file):
        return ic9x_icf.IC9xICFRadio(image_file)

    if icf.is_icf_file(image_file):
        tempf = tempfile.mktemp()
        icf_to_image(image_file, tempf)
        print "Auto-converted %s -> %s" % (image_file, tempf)
        image_file = tempf

    f = file(image_file, "rb")
    filedata = f.read()
    f.close()

    for radio in DRV_TO_RADIO.values():
        if not issubclass(radio, chirp_common.CloneModeRadio):
            continue
        if radio.match_model(filedata):
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
