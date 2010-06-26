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
from chirp import id800, id880, ic2820, ic2200, ic9x, icx8x, idrp
from chirp import vx6, vx7, vx8, ft7800
from chirp import thd7, tmv71
from chirp import xml, chirp_common

DRV_TO_RADIO = {

    # Icom
    "ic2820"         : ic2820.IC2820Radio,
    "ic2200"         : ic2200.IC2200Radio,
    "ic9x"           : ic9x.IC9xRadio,
    "ic9x:A"         : ic9x.IC9xRadioA,
    "ic9x:B"         : ic9x.IC9xRadioB,
    "id800"          : id800.ID800v2Radio,
    "id880"          : id880.ID880Radio,
    "icx8x"          : icx8x.ICx8xRadio,
    "idrpx000v"      : idrp.IDRPx000V,

    # Yaesu
    "vx6"            : vx6.VX6Radio,
    "vx7"            : vx7.VX7Radio,
    "vx8"            : vx8.VX8Radio,
    "ft7800"         : ft7800.FT7800Radio,

    # Kenwood
    "thd7"           : thd7.THD7Radio,
    "v71a"           : tmv71.TMV71ARadio,
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
    else:
        raise Exception("Unknown radio type `%s'" % radio)

def get_radio_by_image(image_file):
    # Right now just detect by size

    size = os.stat(image_file).st_size

    for radio in DRV_TO_RADIO.values():
        if not issubclass(radio, chirp_common.IcomFileBackedRadio):
            continue
        if radio._memsize == size:
            return radio
    raise Exception("Unknown file format")

def get_radio_name(driver):
    cls = DRV_TO_RADIO[driver]
    return cls._get_name(cls)
