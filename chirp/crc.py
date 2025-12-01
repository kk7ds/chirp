# Copyright 2008 Dan Smith <dsmith@danplanet.com>
# Copyright 2023 Jacek Lipkowski <sq5bpf@lipkowski.org>
# Copyright 2025 Thibaut Berg <thibaut.berg@hotmail.com>
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

# This is commonly called "xmodem CRC16"
CRC_POLY_CCITT = 0x1021
CRC_POLY_IBM_REV = 0xA001


def crc16(data, poly, reverse=False):
    crc = 0x0
    for byte in data:
        if reverse:
            crc ^= byte
        else:
            crc ^= (byte << 8)
        for _ in range(8):
            if reverse:
                if crc & 0x0001:
                    crc = (crc >> 1) ^ poly
                else:
                    crc >>= 1
            else:
                crc = crc << 1
                if crc & 0x10000:
                    crc = (crc ^ poly) & 0xFFFF
    return crc & 0xFFFF


def crc16_xmodem(data: bytes):
    return crc16(data, CRC_POLY_CCITT)


def crc16_ibm_rev(data):
    return crc16(data, CRC_POLY_IBM_REV, reverse=True)
