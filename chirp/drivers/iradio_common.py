# Copyright 2023 Jim Unroe <rock.unroe@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""common function for iRadio (or similar) radios"""

import logging
from chirp import errors

LOG = logging.getLogger(__name__)

CMD_ACK = b"\x06"


def enter_programming_mode(serial, magic, timeout=0.25):
    previous_timeout = serial.timeout
    serial.timeout = timeout

    try:
        for attempt in range(0, 5):
            serial.write(magic)
            ack = serial.read(1)

            if ack == CMD_ACK:
                return

            LOG.debug(f"Attempt #{attempt + 1} failed, trying again")

        # retries all failed, raise error
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    finally:
        serial.timeout = previous_timeout


def exit_programming_mode(serial, magic):
    try:
        serial.write(magic)
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")
