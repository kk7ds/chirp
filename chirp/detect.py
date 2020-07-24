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
import logging

from chirp import chirp_common, errors, directory
from chirp.drivers import ic9x_ll, icf, kenwood_live, icomciv

LOG = logging.getLogger(__name__)


class DetectorRadio(chirp_common.Radio):
    """Minimal radio for model detection"""
    MUNCH_CLONE_RESP = False

    def get_payload(self, data, raw, checksum):
        return data


def _icom_model_data_to_rclass(md):
    for _rtype, rclass in directory.DRV_TO_RADIO.items():
        if rclass.VENDOR != "Icom":
            continue
        if not hasattr(rclass, 'get_model') or not rclass.get_model():
            continue
        if rclass.get_model()[:4] == md[:4]:
            return rclass

    raise errors.RadioError("Unknown radio type %02x%02x%02x%02x" %
                            (ord(md[0]), ord(md[1]), ord(md[2]), ord(md[3])))


def _detect_icom_radio(ser):
    # ICOM VHF/UHF Clone-type radios @ 9600 baud

    try:
        ser.baudrate = 9600
        md = icf.get_model_data(DetectorRadio(ser))
        return _icom_model_data_to_rclass(md)
    except errors.RadioError, e:
        LOG.error("_detect_icom_radio: %s", e)

    # ICOM IC-91/92 Live-mode radios @ 4800/38400 baud

    ser.baudrate = 4800
    try:
        ic9x_ll.send_magic(ser)
        return _icom_model_data_to_rclass("ic9x")
    except errors.RadioError:
        pass

    # ICOM CI/V Radios @ various bauds

    for rate in [9600, 4800, 19200]:
        try:
            ser.baudrate = rate
            return icomciv.probe_model(ser)
        except errors.RadioError:
            pass

    ser.close()

    raise errors.RadioError("Unable to get radio model")


def detect_icom_radio(port):
    """Detect which Icom model is connected to @port"""
    ser = serial.Serial(port=port, timeout=0.5)

    try:
        result = _detect_icom_radio(ser)
    except Exception:
        ser.close()
        raise

    ser.close()

    LOG.info("Auto-detected %s %s on %s" %
             (result.VENDOR, result.MODEL, port))

    return result


def detect_kenwoodlive_radio(port):
    """Detect which Kenwood model is connected to @port"""
    ser = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    r_id = kenwood_live.get_id(ser)
    ser.close()

    models = {}
    for rclass in directory.DRV_TO_RADIO.values():
        if rclass.VENDOR == "Kenwood":
            models[rclass.MODEL] = rclass

    if r_id in models.keys():
        return models[r_id]
    else:
        raise errors.RadioError("Unsupported model `%s'" % r_id)

DETECT_FUNCTIONS = {
    "Icom":    detect_icom_radio,
    "Kenwood": detect_kenwoodlive_radio,
}
