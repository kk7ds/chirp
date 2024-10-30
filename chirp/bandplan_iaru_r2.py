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

SHORTNAME = "iaru_r2"

DESC = {
  "name": "IARU Region 2 (The Americas)",
  "updated": "October 8, 2010",
  "url": "http://www.iaru.org/uploads/1/3/0/7/13073366/r2_band_plan.pdf"
}

# Bands are broken up like this so that other plans can import bits.

BANDS_160M = (
  bandplan.Band((1800000, 2000000), "160 Meter Band"),
  bandplan.Band((1800000, 1810000), "Digimodes"),
  bandplan.Band((1810000, 1830000), "CW", mode="CW"),
  bandplan.Band((1830000, 1840000), "CW, priority for DX", mode="CW"),
  bandplan.Band((1840000, 1850000), "SSB, priority for DX", mode="LSB"),
  bandplan.Band((1850000, 1999000), "All modes", mode="LSB"),
  bandplan.Band((1999000, 2000000), "Beacons", mode="CW"),
)

BANDS_80M = (
  bandplan.Band((3500000, 4000000), "80 Meter Band"),
  bandplan.Band((3500000, 3510000), "CW, priority for DX", mode="CW"),
  bandplan.Band((3510000, 3560000), "CW, contest preferred", mode="CW"),
  bandplan.Band((3560000, 3580000), "CW", mode="CW"),
  bandplan.Band((3580000, 3590000), "All narrow band modes, digimodes"),
  bandplan.Band((3590000, 3600000), "All modes"),
  bandplan.Band((3600000, 3650000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((3650000, 3700000), "All modes", mode="LSB"),
  bandplan.Band((3700000, 3775000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((3775000, 3800000), "All modes, SSB DX preferred", mode="LSB"),
  bandplan.Band((3800000, 4000000), "All modes"),
)

BANDS_40M = (
  bandplan.Band((7000000, 7300000), "40 Meter Band"),
  bandplan.Band((7000000, 7025000), "CW, priority for DX", mode="CW"),
  bandplan.Band((7025000, 7035000), "CW", mode="CW"),
  bandplan.Band((7035000, 7038000), "All narrow band modes, digimodes"),
  bandplan.Band((7038000, 7040000), "All narrow band modes, digimodes"),
  bandplan.Band((7040000, 7043000), "All modes, digimodes"),
  bandplan.Band((7043000, 7300000), "All modes"),
)

BANDS_30M = (
  bandplan.Band((10100000, 10150000), "30 Meter Band"),
  bandplan.Band((10100000, 10130000), "CW", mode="CW"),
  bandplan.Band((10130000, 10140000), "All narrow band digimodes"),
  bandplan.Band((10140000, 10150000), "All modes, digimodes, no phone"),
)

BANDS_20M = (
  bandplan.Band((14000000, 14350000), "20 Meter Band"),
  bandplan.Band((14000000, 14025000), "CW, priority for DX", mode="CW"),
  bandplan.Band((14025000, 14060000), "CW, contest preferred", mode="CW"),
  bandplan.Band((14060000, 14070000), "CW", mode="CW"),
  bandplan.Band((14070000, 14089000), "All narrow band modes, digimodes"),
  bandplan.Band((14089000, 14099000), "All modes, digimodes"),
  bandplan.Band((14099000, 14101000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((14101000, 14112000), "All modes, digimodes"),
  bandplan.Band((14112000, 14285000), "All modes, SSB contest preferred",
                mode="USB"),
  bandplan.Band((14285000, 14300000), "All modes", mode="AM"),
  bandplan.Band((14300000, 14350000), "All modes"),
)

BANDS_17M = (
  bandplan.Band((18068000, 18168000), "17 Meter Band"),
  bandplan.Band((18068000, 18095000), "CW", mode="CW"),
  bandplan.Band((18095000, 18105000), "All narrow band modes, digimodes"),
  bandplan.Band((18105000, 18109000), "All narrow band modes, digimodes"),
  bandplan.Band((18109000, 18111000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((18111000, 18120000), "All modes, digimodes"),
  bandplan.Band((18120000, 18168000), "All modes"),
)

BANDS_15M = (
  bandplan.Band((21000000, 21450000), "15 Meter Band"),
  bandplan.Band((21000000, 21070000), "CW", mode="CW"),
  bandplan.Band((21070000, 21090000), "All narrow band modes, digimodes"),
  bandplan.Band((21090000, 21110000), "All narrow band modes, digimodes"),
  bandplan.Band((21110000, 21120000), "All modes (exc SSB), digimodes"),
  bandplan.Band((21120000, 21149000), "All narrow band modes"),
  bandplan.Band((21149000, 21151000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((21151000, 21450000), "All modes", mode="USB"),
)

BANDS_12M = (
  bandplan.Band((24890000, 24990000), "12 Meter Band"),
  bandplan.Band((24890000, 24915000), "CW", mode="CW"),
  bandplan.Band((24915000, 24925000), "All narrow band modes, digimodes"),
  bandplan.Band((24925000, 24929000), "All narrow band modes, digimodes"),
  bandplan.Band((24929000, 24931000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((24931000, 24940000), "All modes, digimodes"),
  bandplan.Band((24940000, 24990000), "All modes", mode="USB"),
)

BANDS_10M = (
  bandplan.Band((28000000, 29520000), "10 Meter Band"),
  bandplan.Band((28000000, 28070000), "CW", mode="CW"),
  bandplan.Band((28070000, 28120000), "All narrow band modes, digimodes"),
  bandplan.Band((28120000, 28150000), "All narrow band modes, digimodes"),
  bandplan.Band((28150000, 28190000), "All narrow band modes, digimodes"),
  bandplan.Band((28190000, 28199000), "Regional time shared beacons",
                mode="CW"),
  bandplan.Band((28199000, 28201000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((28201000, 28225000), "Continuous duty beacons",
                mode="CW"),
  bandplan.Band((28225000, 28300000), "All modes, beacons"),
  bandplan.Band((28300000, 28320000), "All modes, digimodes"),
  bandplan.Band((28320000, 29000000), "All modes"),
  bandplan.Band((29000000, 29200000), "All modes, AM preferred", mode="AM"),
  bandplan.Band((29200000, 29300000), "All modes including FM, digimodes"),
  bandplan.Band((29300000, 29510000), "Satellite downlink"),
  bandplan.Band((29510000, 29520000), "Guard band, no transmission allowed"),
  bandplan.Band((29520000, 29700000), "FM", step_khz=10, mode="NFM"),
  bandplan.Band((29620000, 29690000), "FM Repeaters", input_offset=-100000),
)

BANDS = BANDS_160M + BANDS_80M + BANDS_40M + BANDS_30M + BANDS_20M + \
        BANDS_17M + BANDS_15M + BANDS_12M + BANDS_10M + bandplan.BANDS_AIR
