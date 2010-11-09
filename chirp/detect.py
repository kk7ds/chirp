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

import serial

from chirp import chirp_common, errors, idrp, util, icf, directory
from chirp import kenwood_live, tmv71, tmv71_ll

def detect_icom_radio(port):
    s = serial.Serial(port=port, timeout=0.5)
    md = ""

    for rate in [9600, 4800, 38400]:
        try:
            s.setBaudrate(rate)
            md = icf.get_model_data(s)
            break
        except errors.RadioError:
            pass
    s.close()

    if not md:
        raise errors.RadioError("Unable to probe radio model")

    for rtype, rclass in directory.DRV_TO_RADIO.items():
        if rclass.VENDOR != "Icom":
            continue
        if rclass._model[:4] == md[:4]:
            print "Auto-detected radio `%s' on port `%s'" % (rtype, port)
            return rclass

    raise errors.RadioError("Unknown radio type %02x%02x%02x%02x" %\
                                (ord(md[0]),
                                 ord(md[1]),
                                 ord(md[2]),
                                 ord(md[3])))

def detect_kenwoodlive_radio(port):
    s = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    r_id = None

    for rate in [9600, 19200, 38400, 57600]:
        s.setBaudrate(rate)
        s.write("\r")
        s.read(25)
        try:
            #r_id = kenwood_live.get_id(s)
            r_id = tmv71_ll.get_id(s)
            break
        except errors.RadioError:
            pass
    s.close()

    if not r_id:
        raise errors.RadioError("Unale to probe radio model")

    models = {
        "TH-D7"   : kenwood_live.THD7Radio,
        "TH-D7G"   : kenwood_live.THD7Radio,
        "TM-D700" : kenwood_live.TMD700Radio,
        "TM-V7"   : kenwood_live.TMV7Radio,
        "TM-V71"  : tmv71.TMV71ARadio,
        }

    if r_id in models.keys():
        return models[r_id]
    else:
        raise errors.RadioError("Unsupported model `%s'" % r_id)

DETECT_FUNCTIONS = {
    "Icom" : detect_icom_radio,
    "Kenwood" : detect_kenwoodlive_radio,
}

if __name__ == "__main__":
    import sys

    print "Found %s" % detect_radio(sys.argv[1])
