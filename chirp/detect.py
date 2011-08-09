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

from chirp import chirp_common, errors, idrp, util, icf, directory, ic9x_ll
from chirp import kenwood_live, tmv71, tmv71_ll, icomciv, thd72

def _icom_model_data_to_rclass(md):
    for rtype, rclass in directory.DRV_TO_RADIO.items():
        if rclass.VENDOR != "Icom":
            continue
        if rclass._model[:4] == md[:4]:
            return rclass

    raise errors.RadioError("Unknown radio type %02x%02x%02x%02x" %\
                                (ord(md[0]),
                                 ord(md[1]),
                                 ord(md[2]),
                                 ord(md[3])))

def _detect_icom_radio(s):
    # ICOM VHF/UHF Clone-type radios @ 9600 baud

    try:
        s.setBaudrate(9600)
        md = icf.get_model_data(s)
        return _icom_model_data_to_rclass(md)
    except errors.RadioError, e:
        print e
        pass

    # ICOM IC-91/92 Live-mode radios @ 4800/38400 baud

    s.setBaudrate(4800)
    try:
        ic9x_ll.send_magic(s)
        return _icom_model_data_to_rclass("ic9x")
    except errors.RadioError:
        pass

    # ICOM CI/V Radios @ various bauds

    for rate in [9600, 4800, 19200]:
        try:
            s.setBaudrate(rate)
            return icomciv.probe_model(s)
        except errors.RadioError:
            pass

    s.close()

    raise errors.RadioError("Unable to get radio model")

def detect_icom_radio(port):
    s = serial.Serial(port=port, timeout=0.5)

    try:
        result = _detect_icom_radio(s)
    except Exception:
        s.close()
        raise

    s.close()

    print "Auto-detected %s %s on %s" % (result.VENDOR,
                                         result.MODEL,
                                         port)

    return result

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
        raise errors.RadioError("Unable to probe radio model")

    models = {
        "TH-D7"   : kenwood_live.THD7Radio,
        "TH-D72"  : thd72.THD72Radio,
        "TH-D7G"   : kenwood_live.THD7Radio,
        "TM-D700" : kenwood_live.TMD700Radio,
        "TM-D710" : kenwood_live.TMD710Radio,
        "TM-V71" : kenwood_live.TMV71Radio,
        "TM-V7"   : kenwood_live.TMV7Radio,
        "TH-F6"  : kenwood_live.THF6ARadio,
        "TH-K2"  : kenwood_live.THK2Radio,
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
