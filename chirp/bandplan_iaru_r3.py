# Copyright 2013 Sean Burford <sburford@google.com>
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

from chirp import bandplan

SHORTNAME = "iaru_r3"

DESC = {
  "name": "IARU Region 3 (Asia Pacific)",
  "updated": "16 October 2009",
  "url": "http://www.iaru.org/uploads/1/3/0/7/13073366/r3_band_plan.pdf"
}

# Bands are broken up like this so that other plans can import bits.

BANDS_2100M = (
  bandplan.Band((135700, 137800), "137 kHz Band", mode="CW"),
)

BANDS_160M = (
  bandplan.Band((1800000, 2000000), "160 Meter Band"),
  bandplan.Band((1830000, 1840000), "Digimodes", mode="RTTY"),
  bandplan.Band((1840000, 2000000), "Phone"),
)

BANDS_80M = (
  bandplan.Band((3500000, 3900000), "80 Meter Band"),
  bandplan.Band((3500000, 3510000), "CW, priority for DX", mode="CW"),
  bandplan.Band((3535000, 3900000), "Phone"),
  bandplan.Band((3775000, 3800000), "All modes, SSB DX preferred", mode="LSB"),
)

BANDS_40M = (
  bandplan.Band((7000000, 7300000), "40 Meter Band"),
  bandplan.Band((7000000, 7025000), "CW, priority for DX", mode="CW"),
  bandplan.Band((7025000, 7035000), "All narrow band modes, cw", mode="CW"),
  bandplan.Band((7035000, 7040000), "All narrow band modes, phone"),
  bandplan.Band((7040000, 7300000), "All modes, digimodes"),
)

BANDS_30M = (
  bandplan.Band((10100000, 10150000), "30 Meter Band"),
  bandplan.Band((10100000, 10130000), "CW", mode="CW"),
  bandplan.Band((10130000, 10150000), "All narrow band digimodes"),
)

BANDS_20M = (
  bandplan.Band((14000000, 14350000), "20 Meter Band"),
  bandplan.Band((14000000, 14070000), "CW", mode="CW"),
  bandplan.Band((14070000, 14099000), "All narrow band modes, digimodes"),
  bandplan.Band((14099000, 14101000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((14101000, 14112000), "All narrow band modes, digimodes"),
  bandplan.Band((14101000, 14350000), "All modes, digimodes"),
)

BANDS_17M = (
  bandplan.Band((18068000, 18168000), "17 Meter Band"),
  bandplan.Band((18068000, 18100000), "CW", mode="CW"),
  bandplan.Band((18100000, 18109000), "All narrow band modes, digimodes"),
  bandplan.Band((18109000, 18111000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((18111000, 18168000), "All modes, digimodes"),
)

BANDS_15M = (
  bandplan.Band((21000000, 21450000), "15 Meter Band"),
  bandplan.Band((21000000, 21070000), "CW", mode="CW"),
  bandplan.Band((21070000, 21125000), "All narrow band modes, digimodes"),
  bandplan.Band((21125000, 21149000), "All narrow band modes, digimodes"),
  bandplan.Band((21149000, 21151000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((21151000, 21450000), "All modes", mode="USB"),
)

BANDS_12M = (
  bandplan.Band((24890000, 24990000), "12 Meter Band"),
  bandplan.Band((24890000, 24920000), "CW", mode="CW"),
  bandplan.Band((24920000, 24929000), "All narrow band modes, digimodes"),
  bandplan.Band((24929000, 24931000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((24931000, 24990000), "All modes, digimodes", mode="USB"),
)

BANDS_10M = (
  bandplan.Band((28000000, 29700000), "10 Meter Band"),
  bandplan.Band((28000000, 28050000), "CW", mode="CW"),
  bandplan.Band((28050000, 28150000), "All narrow band modes, digimodes"),
  bandplan.Band((28150000, 28190000), "All narrow band modes, digimodes"),
  bandplan.Band((28190000, 28199000), "Beacons", mode="CW"),
  bandplan.Band((28199000, 28201000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((28201000, 28300000), "Beacons", mode="CW"),
  bandplan.Band((28300000, 29300000), "Phone"),
  bandplan.Band((29300000, 29510000), "Satellite downlink"),
  bandplan.Band((29510000, 29520000), "Guard band, no transmission allowed"),
  bandplan.Band((29520000, 29700000), "Wide band", step_khz=10, mode="NFM"),
)

BANDS_6M = (
  bandplan.Band((50000000, 54000000), "6 Meter Band"),
  bandplan.Band((50000000, 50100000), "Beacons", mode="CW"),
  bandplan.Band((50100000, 50500000), "Phone and narrow band"),
  bandplan.Band((50500000, 54000000), "Wide band"),
)

BANDS_2M = (
  bandplan.Band((144000000, 148000000), "2 Meter Band"),
  bandplan.Band((144000000, 144035000), "Earth Moon Earth"),
  bandplan.Band((145800000, 146000000), "Satellite"),
)

BANDS_70CM = (
  bandplan.Band((430000000, 450000000), "70cm Band"),
  bandplan.Band((431900000, 432240000), "Earth Moon Earth"),
  bandplan.Band((435000000, 438000000), "Satellite"),
)

BANDS_23CM = (
  bandplan.Band((1240000000, 1300000000), "23cm Band"),
  bandplan.Band((1260000000, 1270000000), "Satellite"),
  bandplan.Band((1296000000, 1297000000), "Earth Moon Earth"),
)

BANDS = BANDS_2100M + BANDS_160M + BANDS_80M + BANDS_40M + BANDS_30M + \
        BANDS_20M + BANDS_17M + BANDS_15M + BANDS_12M + BANDS_10M + \
        BANDS_6M + BANDS_2M + BANDS_70CM + BANDS_23CM + bandplan.BANDS_AIR
