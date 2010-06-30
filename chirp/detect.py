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
from chirp import thd7

def detect_icom_radio(port):
    s = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    md = icf.get_model_data(s)
    s.close()

    for rtype, rclass in directory.DRV_TO_RADIO.items():
        if not issubclass(rclass, chirp_common.IcomFileBackedRadio):
            continue
        if rclass._model[:4] == md[:4]:
            print "Auto-detected radio `%s' on port `%s'" % (rtype, port)
            return rtype


    raise errors.RadioError("Unknown radio type %02x%02x%02x%02x" % (md[0],
                                                                     md[1],
                                                                     md[2],
                                                                     md[3]))

def detect_kenwoodlive_radio(port):
    s = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    r_id = thd7.get_id(s)
    s.close()

    models = {
        "TH-D7"   : thd7.THD7Radio,
        "TM-D700" : thd7.TMD700Radio,
        "TM-V7"   : thd7.TMV7Radio,
        }

    if r_id in models.keys():
        return models[r_id]
    else:
        raise errors.RadioError("Unsupported model `%s'" % r_id)

if __name__ == "__main__":
    import sys

    print "Found %s" % detect_radio(sys.argv[1])
