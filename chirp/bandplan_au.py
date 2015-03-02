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


from chirp import bandplan, bandplan_iaru_r3


SHORTNAME = "australia"

DESC = {
  "name":    "Australian Amateur Band Plan",
  "updated": "April 2010",
  "url":     "http://www.wia.org.au/members/bandplans/data"
             "/documents/Australian%20Band%20Plans%20100404.pdf",
}

BANDS_10M = (
  # bandplan.Band((28000000, 29700000), "10 Meter Band"),
  bandplan.Band((29520000, 29680000), "FM Simplex and Repeaters",
                mode="FM", step_khz=20),
  bandplan.Band((29620000, 29680000), "FM Repeaters", input_offset=-100000),
)

BANDS_6M = (
  # bandplan.Band((50000000, 54000000), "6 Meter Band"),
  bandplan.Band((52525000, 53975000), "FM Simplex and Repeaters",
                mode="FM", step_khz=25),
  bandplan.Band((53550000, 53975000), "FM Repeaters", input_offset=-1000000),
)

BANDS_2M = (
  bandplan.Band((144000000, 148000000), "2 Meter Band",
                tones=(91.5, 123.0, 141.3, 146.2, 85.4)),
  bandplan.Band((144400000, 144600000), "Beacons", step_khz=1),
  bandplan.Band((146025000, 147975000), "FM Simplex and Repeaters",
                mode="FM", step_khz=25),
  bandplan.Band((146625000, 147000000), "FM Repeaters Group A",
                input_offset=-600000),
  bandplan.Band((147025000, 147375000), "FM Repeaters Group B",
                input_offset=600000),
)

BANDS_70CM = (
  bandplan.Band((420000000, 450000000), "70cm Band",
                tones=(91.5, 123.0, 141.3, 146.2, 85.4)),
  bandplan.Band((432400000, 432600000), "Beacons", step_khz=1),
  bandplan.Band((438025000, 439975000), "FM Simplex and Repeaters",
                mode="FM", step_khz=25),
  bandplan.Band((438025000, 438725000), "FM Repeaters Group A",
                input_offset=-5000000),
  bandplan.Band((439275000, 439975000), "FM Repeaters Group B",
                input_offset=-5000000),
)

BANDS_23CM = (
  # bandplan.Band((1240000000, 1300000000), "23cm Band"),
  bandplan.Band((1273025000, 1273975000), "FM Repeaters",
                mode="FM", step_khz=25, input_offset=20000000),
  bandplan.Band((1296400000, 1296600000), "Beacons", step_khz=1),
  bandplan.Band((1297025000, 1300400000), "General FM Simplex Data",
                mode="FM", step_khz=25),
)

BANDS_13CM = (
  bandplan.Band((2300000000, 2450000000), "13cm Band"),
  bandplan.Band((2403400000, 2403600000), "Beacons", step_khz=1),
  bandplan.Band((2425000000, 2428000000), "FM Simplex",
                mode="FM", step_khz=25),
  bandplan.Band((2428025000, 2429000000), "FM Duplex (Voice)",
                mode="FM", step_khz=25, input_offset=20000000),
  bandplan.Band((2429000000, 2429975000), "FM Duplex (Data)",
                mode="FM", step_khz=100, input_offset=20000000),
)

BANDS_9CM = (
  bandplan.Band((3300000000, 3600000000), "9cm Band"),
  bandplan.Band((3320000000, 3340000000), "WB Channel 2: Voice/Data",
                step_khz=100),
  bandplan.Band((3400400000, 3400600000), "Beacons", step_khz=1),
  bandplan.Band((3402000000, 3403000000), "FM Simplex (Voice)",
                mode="FM", step_khz=100),
  bandplan.Band((3403000000, 3405000000), "FM Simplex (Data)",
                mode="FM", step_khz=100),
)

BANDS_6CM = (
  bandplan.Band((5650000000, 5850000000), "6cm Band"),
  bandplan.Band((5760400000, 5760600000), "Beacons", step_khz=1),
  bandplan.Band((5700000000, 5720000000), "WB Channel 2: Data",
                step_khz=100, input_offset=70000000),
  bandplan.Band((5720000000, 5740000000), "WB Channel 3: Voice",
                step_khz=100, input_offset=70000000),
  bandplan.Band((5762000000, 5763000000), "FM Simplex (Voice)",
                mode="FM", step_khz=100),
  bandplan.Band((5763000000, 5765000000), "FM Simplex (Data)",
                mode="FM", step_khz=100),
)

BANDS = bandplan_iaru_r3.BANDS_20M + bandplan_iaru_r3.BANDS_17M
BANDS += bandplan_iaru_r3.BANDS_15M + bandplan_iaru_r3.BANDS_12M
BANDS += bandplan_iaru_r3.BANDS_10M + bandplan_iaru_r3.BANDS_6M
BANDS += BANDS_10M + BANDS_6M + BANDS_2M + BANDS_70CM + BANDS_23CM
BANDS += BANDS_13CM + BANDS_9CM + BANDS_6CM
