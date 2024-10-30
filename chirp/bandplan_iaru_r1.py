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

SHORTNAME = "iaru_r1"

DESC = {
  "name":    "IARU Region 1 (Europe, Africa, Middle East and Northern Asia)",
  "url":     "http://iaru-r1.org/index.php?option=com_content"
             "&view=article&id=175&Itemid=127",
  "updated": "General Conference Sun City 2011",
}

# Bands are broken up like this so that other plans can import bits.

BANDS_2100M = (
  bandplan.Band((135700, 137800), "137 kHz Band", mode="CW"),
)

BANDS_160M = (
  bandplan.Band((1810000, 2000000), "160 Meter Band"),
  bandplan.Band((1810000, 1838000), "CW", mode="CW"),
  bandplan.Band((1838000, 1840000), "All narrow band modes"),
  bandplan.Band((1840000, 1843000), "All modes, digimodes", mode="RTTY"),
)

BANDS_80M = (
  bandplan.Band((3500000, 3800000), "80 Meter Band"),
  bandplan.Band((3500000, 3510000), "CW, priority for DX", mode="CW"),
  bandplan.Band((3510000, 3560000), "CW, contest preferred", mode="CW"),
  bandplan.Band((3560000, 3580000), "CW", mode="CW"),
  bandplan.Band((3580000, 3600000), "All narrow band modes, digimodes"),
  bandplan.Band((3590000, 3600000), "All narrow band, digimodes, unattended"),
  bandplan.Band((3600000, 3650000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((3600000, 3700000), "All modes, SSB QRP", mode="LSB"),
  bandplan.Band((3700000, 3800000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((3775000, 3800000), "All modes, SSB DX preferred", mode="LSB"),
)

BANDS_40M = (
  bandplan.Band((7000000, 7200000), "40 Meter Band"),
  bandplan.Band((7000000, 7040000), "CW", mode="CW"),
  bandplan.Band((7040000, 7047000), "All narrow band modes, digimodes"),
  bandplan.Band((7047000, 7050000), "All narrow band, digimodes, unattended"),
  bandplan.Band((7050000, 7053000), "All modes, digimodes, unattended"),
  bandplan.Band((7053000, 7060000), "All modes, digimodes"),
  bandplan.Band((7060000, 7100000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((7100000, 7130000),
                "All modes, R1 Emergency Center Of Activity", mode="LSB"),
  bandplan.Band((7130000, 7200000), "All modes, SSB contest preferred",
                mode="LSB"),
  bandplan.Band((7175000, 7200000), "All modes, SSB DX preferred", mode="LSB"),
)

BANDS_30M = (
  bandplan.Band((10100000, 10150000), "30 Meter Band"),
  bandplan.Band((10100000, 10140000), "CW", mode="CW"),
  bandplan.Band((10140000, 10150000), "All narrow band digimodes"),
)

BANDS_20M = (
  bandplan.Band((14000000, 14350000), "20 Meter Band"),
  bandplan.Band((14000000, 14070000), "CW", mode="CW"),
  bandplan.Band((14070000, 14099000), "All narrow band modes, digimodes"),
  bandplan.Band((14099000, 14101000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((14101000, 14112000), "All narrow band modes, digimodes"),
  bandplan.Band((14125000, 14350000), "All modes, SSB contest preferred",
                mode="USB"),
  bandplan.Band((14300000, 14350000),
                "All modes, Global Emergency center of activity", mode="USB"),
)

BANDS_17M = (
  bandplan.Band((18068000, 18168000), "17 Meter Band"),
  bandplan.Band((18068000, 18095000), "CW", mode="CW"),
  bandplan.Band((18095000, 18109000), "All narrow band modes, digimodes"),
  bandplan.Band((18109000, 18111000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((18111000, 18168000), "All modes, digimodes"),
)

BANDS_15M = (
  bandplan.Band((21000000, 21450000), "15 Meter Band"),
  bandplan.Band((21000000, 21070000), "CW", mode="CW"),
  bandplan.Band((21070000, 21090000), "All narrow band modes, digimodes"),
  bandplan.Band((21090000, 21110000),
                "All narrow band, digimodes, unattended"),
  bandplan.Band((21110000, 21120000), "All modes, digimodes, unattended"),
  bandplan.Band((21120000, 21149000), "All narrow band modes"),
  bandplan.Band((21149000, 21151000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((21151000, 21450000), "All modes", mode="USB"),
)

BANDS_12M = (
  bandplan.Band((24890000, 24990000), "12 Meter Band"),
  bandplan.Band((24890000, 24915000), "CW", mode="CW"),
  bandplan.Band((24915000, 24929000), "All narrow band modes, digimodes"),
  bandplan.Band((24929000, 24931000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((24931000, 24990000), "All modes, digimodes", mode="USB"),
)

BANDS_10M = (
  bandplan.Band((28000000, 29700000), "10 Meter Band"),
  bandplan.Band((28000000, 28070000), "CW", mode="CW"),
  bandplan.Band((28070000, 28120000), "All narrow band modes, digimodes"),
  bandplan.Band((28120000, 28150000),
                "All narrow band, digimodes, unattended"),
  bandplan.Band((28150000, 28190000), "All narrow band modes"),
  bandplan.Band((28190000, 28199000), "Beacons", mode="CW"),
  bandplan.Band((28199000, 28201000), "IBP, exclusively for beacons",
                mode="CW"),
  bandplan.Band((28201000, 28300000), "Beacons", mode="CW"),
  bandplan.Band((28300000, 28320000), "All modes, digimodes, unattended"),
  bandplan.Band((28320000, 29100000), "All modes"),
  bandplan.Band((29100000, 29200000), "FM simplex", mode="NFM", step_khz=10),
  bandplan.Band((29200000, 29300000), "All modes, digimodes, unattended"),
  bandplan.Band((29300000, 29510000), "Satellite downlink"),
  bandplan.Band((29510000, 29520000), "Guard band, no transmission allowed"),
  bandplan.Band((29520000, 29590000), "All modes, FM repeater inputs",
                step_khz=10, mode="NFM"),
  bandplan.Band((29600000, 29610000), "FM simplex", step_khz=10, mode="NFM"),
  bandplan.Band((29620000, 29700000), "All modes, FM repeater outputs",
                step_khz=10, mode="NFM", input_offset=-100000),
  bandplan.Band((29520000, 29700000), "Wide band", step_khz=10, mode="NFM"),
)

BANDS = BANDS_2100M + BANDS_160M + BANDS_80M + BANDS_40M + BANDS_30M + \
        BANDS_20M + BANDS_17M + BANDS_15M + BANDS_12M + BANDS_10M + \
        bandplan.BANDS_AIR


# EU Analogue/DMR PMR446 Frequencies
PMR446_FREQS = [446006250, 446018750, 446031250, 446043750,
                446056250, 446068750, 446081250, 446093750,
                446106250, 446118750, 446131250, 446143750,
                446156250, 446168750, 446181250, 446193750]
