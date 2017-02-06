# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

from chirp import bandplan, bandplan_iaru_r2


SHORTNAME = "north_america"

DESC = {
  "name": "North American Band Plan",
  "url":  "http://www.arrl.org/band-plan"
}

BANDS_160M = (
  bandplan.Band((1800000, 2000000), "160 Meter Band", mode="CW"),
  bandplan.Band((1800000, 1810000), "Digital Modes"),
  bandplan.Band((1843000, 2000000), "SSB, SSTV and other wideband modes"),
  bandplan.Band((1995000, 2000000), "Experimental"),
  bandplan.Band((1999000, 2000000), "Beacons"),
)

BANDS_80M = (
  bandplan.Band((3500000, 4000000), "80 Meter Band"),
  bandplan.Band((3570000, 3600000), "RTTY/Data", mode="RTTY"),
  bandplan.Band((3790000, 3800000), "DX window"),
)

BANDS_40M = (
  bandplan.Band((7000000, 7300000), "40 Meter Band"),
  bandplan.Band((7080000, 7125000), "RTTY/Data", mode="RTTY"),
)

BANDS_30M = (
  bandplan.Band((10100000, 10150000), "30 Meter Band"),
  bandplan.Band((10130000, 10140000), "RTTY", mode="RTTY"),
  bandplan.Band((10140000, 10150000), "Packet"),
)

BANDS_20M = (
  bandplan.Band((14000000, 14350000), "20 Meter Band"),
  bandplan.Band((14070000, 14095000), "RTTY", mode="RTTY"),
  bandplan.Band((14095000, 14099500), "Packet"),
  bandplan.Band((14100500, 14112000), "Packet"),
)

BANDS_17M = (
  bandplan.Band((18068000, 18168000), "17 Meter Band"),
  bandplan.Band((18100000, 18105000), "RTTY", mode="RTTY"),
  bandplan.Band((18105000, 18110000), "Packet"),
)

BANDS_15M = (
  bandplan.Band((21000000, 21450000), "15 Meter Band"),
  bandplan.Band((21070000, 21110000), "RTTY/Data", mode="RTTY"),
)

BANDS_12M = (
  bandplan.Band((24890000, 24990000), "12 Meter Band"),
  bandplan.Band((24920000, 24925000), "RTTY", mode="RTTY"),
  bandplan.Band((24925000, 24930000), "Packet"),
)

BANDS_10M = (
  bandplan.Band((28000000, 29700000), "10 Meter Band"),
  bandplan.Band((28000000, 28070000), "CW", mode="CW"),
  bandplan.Band((28070000, 28150000), "RTTY", mode="RTTY"),
  bandplan.Band((28150000, 28190000), "CW", mode="CW"),
  bandplan.Band((28201000, 28300000), "Beacons", mode="CW"),
  bandplan.Band((28300000, 29300000), "Phone"),
  bandplan.Band((29000000, 29200000), "AM", mode="AM"),
  bandplan.Band((29300000, 29510000), "Satellite Downlinks"),
  bandplan.Band((29520000, 29590000), "Repeater Inputs",
                step_khz=10, mode="FM"),
  bandplan.Band((29610000, 29700000), "Repeater Outputs",
                step_khz=10, mode="FM", input_offset=-890000),
)

BANDS_6M = (
  bandplan.Band((50000000, 54000000), "6 Meter Band"),
  bandplan.Band((50000000, 50100000), "CW, beacons", mode="CW"),
  bandplan.Band((50060000, 50080000), "beacon subband"),
  bandplan.Band((50100000, 50300000), "SSB, CW", mode="USB"),
  bandplan.Band((50100000, 50125000), "DX window", mode="USB"),
  bandplan.Band((50300000, 50600000), "All modes"),
  bandplan.Band((50600000, 50800000), "Nonvoice communications"),
  bandplan.Band((50800000, 51000000), "Radio remote control", step_khz=20),
  bandplan.Band((51000000, 51100000), "Pacific DX window"),
  bandplan.Band((51120000, 51180000), "Digital repeater inputs", step_khz=10),
  bandplan.Band((51500000, 51600000), "Simplex"),
  bandplan.Band((51620000, 51980000), "Repeater outputs A",
                input_offset=-500000),
  bandplan.Band((51620000, 51680000), "Digital repeater outputs",
                input_offset=-500000),
  bandplan.Band((52020000, 52040000), "FM simplex", mode="FM"),
  bandplan.Band((52500000, 52980000), "Repeater outputs B",
                input_offset=-500000, step_khz=20, mode="FM"),
  bandplan.Band((53000000, 53100000), "FM simplex", mode="FM"),
  bandplan.Band((53100000, 53400000), "Radio remote control", step_khz=100),
  bandplan.Band((53500000, 53980000), "Repeater outputs C",
                input_offset=-500000),
  bandplan.Band((53500000, 53800000), "Radio remote control", step_khz=100),
  bandplan.Band((53520000, 53900000), "Simplex"),
)

BANDS_2M = (
  bandplan.Band((144000000, 148000000), "2 Meter Band"),
  bandplan.Band((144000000, 144050000), "EME (CW)", mode="CW"),
  bandplan.Band((144050000, 144100000), "General CW and weak signals",
                mode="CW"),
  bandplan.Band((144100000, 144200000), "EME and weak-signal SSB",
                mode="USB"),
  bandplan.Band((144200000, 144275000), "General SSB operation",
                mode="USB"),
  bandplan.Band((144275000, 144300000), "Propagation beacons", mode="CW"),
  bandplan.Band((144300000, 144500000), "OSCAR subband"),
  bandplan.Band((144600000, 144900000), "FM repeater inputs", mode="FM"),
  bandplan.Band((144900000, 145100000), "Weak signal and FM simplex",
                mode="FM", step_khz=10),
  bandplan.Band((145100000, 145200000), "Linear translator outputs",
                input_offset=-600000),
  bandplan.Band((145200000, 145500000), "FM repeater outputs",
                input_offset=-600000, mode="FM",),
  bandplan.Band((145500000, 145800000), "Misc and experimental modes"),
  bandplan.Band((145800000, 146000000), "OSCAR subband"),
  bandplan.Band((146400000, 146580000), "Simplex"),
  bandplan.Band((146610000, 146970000), "Repeater outputs",
                input_offset=-600000),
  bandplan.Band((147000000, 147390000), "Repeater outputs",
                input_offset=600000),
  bandplan.Band((147420000, 147570000), "Simplex"),
)

BANDS_1_25M = (
  bandplan.Band((222000000, 225000000), "1.25 Meters"),
  bandplan.Band((222000000, 222150000), "Weak-signal modes"),
  bandplan.Band((222000000, 222025000), "EME"),
  bandplan.Band((222050000, 222060000), "Propagation beacons"),
  bandplan.Band((222100000, 222150000), "Weak-signal CW & SSB"),
  bandplan.Band((222150000, 222250000), "Local coordinator's option"),
  bandplan.Band((223400000, 223520000), "FM simplex", mode="FM"),
  bandplan.Band((223520000, 223640000), "Digital, packet"),
  bandplan.Band((223640000, 223700000), "Links, control"),
  bandplan.Band((223710000, 223850000), "Local coordinator's option"),
  bandplan.Band((223850000, 224980000), "Repeater outputs only",
                mode="FM", input_offset=-1600000),
)

BANDS_70CM = (
  bandplan.Band((420000000, 450000000), "70cm Band"),
  bandplan.Band((420000000, 426000000), "ATV repeater or simplex"),
  bandplan.Band((426000000, 432000000), "ATV simplex"),
  bandplan.Band((432000000, 432070000), "EME (Earth-Moon-Earth)"),
  bandplan.Band((432070000, 432100000), "Weak-signal CW", mode="CW"),
  bandplan.Band((432100000, 432300000), "Mixed-mode and weak-signal work"),
  bandplan.Band((432300000, 432400000), "Propagation beacons"),
  bandplan.Band((432400000, 433000000), "Mixed-mode and weak-signal work"),
  bandplan.Band((433000000, 435000000), "Auxiliary/repeater links"),
  bandplan.Band((435000000, 438000000), "Satellite only (internationally)"),
  bandplan.Band((438000000, 444000000), "ATV repeater input/repeater links",
                input_offset=5000000),
  bandplan.Band((442000000, 445000000), "Repeater input/output (local option)",
                input_offset=5000000),
  bandplan.Band((445000000, 447000000), "Shared by aux and control links, "
                "repeaters, simplex (local option)"),
  bandplan.Band((447000000, 450000000), "Repeater inputs and outputs "
                "(local option)", input_offset=-5000000),
)

BANDS_33CM = (
  bandplan.Band((902000000, 928000000), "33 Centimeter Band"),
  bandplan.Band((902075000, 902100000), "CW/SSB, Weak signal"),
  bandplan.Band((902100000, 902125000), "CW/SSB, Weak signal"),
  bandplan.Band((903000000, 903100000), "CW/SSB, Beacons and weak signal"),
  bandplan.Band((903100000, 903400000), "CW/SSB, Weak signal"),
  bandplan.Band((903400000, 909000000), "Mixed modes, Mixed operations "
                "including control links"),
  bandplan.Band((909000000, 915000000), "Analog/digital Broadband multimedia "
                "including ATV, DATV and SS"),
  bandplan.Band((915000000, 921000000), "Analog/digital Broadband multimedia "
                "including ATV, DATV and SS"),
  bandplan.Band((921000000, 927000000), "Analog/digital Broadband multimedia "
                "including ATV, DATV and SS"),
  bandplan.Band((927000000, 927075000), "FM / other including DV or CW/SSB",
                input_offset=-25000000, step_khz=12.5),
  bandplan.Band((927075000, 927125000), "FM / other including DV. Simplex"),
  bandplan.Band((927125000, 928000000), "FM / other including DV",
                input_offset=-25000000, step_khz=12.5),
)

BANDS_23CM = (
  bandplan.Band((1240000000, 1300000000), "23 Centimeter Band"),
  bandplan.Band((1240000000, 1246000000), "ATV Channel #1"),
  bandplan.Band((1246000000, 1248000000), "Point-to-point links paired "
                "with 1258.000-1260.000", mode="FM"),
  bandplan.Band((1248000000, 1252000000), "Digital"),
  bandplan.Band((1252000000, 1258000000), "ATV Channel #2"),
  bandplan.Band((1258000000, 1260000000),
                "Point-to-point links paired with 1246.000-1248.000",
                mode="FM"),
  bandplan.Band((1240000000, 1260000000), "Regional option, FM ATV"),
  bandplan.Band((1260000000, 1270000000), "Satellite uplinks, Experimental, "
                "Simplex ATV"),
  bandplan.Band((1270000000, 1276000000), "FM, digital Repeater inputs "
                "(Regional option)", step_khz=25),
  bandplan.Band((1276000000, 1282000000), "ATV Channel #3"),
  bandplan.Band((1282000000, 1288000000), "FM, digital repeater outputs",
                step_khz=25, input_offset=-12000000),
  bandplan.Band((1288000000, 1294000000), "Various Broadband Experimental, "
                "Simplex ATV"),
  bandplan.Band((1290000000, 1294000000), "FM, digital Repeater outputs "
                "(Regional option)", step_khz=25, input_offset=-20000000),
  bandplan.Band((1294000000, 1295000000), "FM simplex", mode="FM"),
  bandplan.Band((1295000000, 1297000000), "Narrow Band Segment"),
  bandplan.Band((1295000000, 1295800000), "Narrow Band Image, Experimental"),
  bandplan.Band((1295800000, 1296080000), "CW, SSB, digital EME"),
  bandplan.Band((1296080000, 1296200000), "CW, SSB Weak Signal"),
  bandplan.Band((1296200000, 1296400000), "CW, digital Beacons"),
  bandplan.Band((1296400000, 1297000000), "General Narrow Band"),
  bandplan.Band((1297000000, 1300000000), "Digital"),
)

BANDS_13CM = (
  bandplan.Band((2300000000, 2450000000), "13 Centimeter Band"),
  bandplan.Band((2300000000, 2303000000), "Analog & Digital 0.05-1.0 MHz, "
                "including full duplex; paired with 2390-2393"),
  bandplan.Band((2303000000, 2303750000), "Analog & Digital <50kHz; "
                "paired with 2393 - 2393.750"),
  bandplan.Band((2303750000, 2304000000), "SSB, CW, digital weak-signal"),
  bandplan.Band((2304000000, 2304100000), "Weak Signal EME Band, <3kHz"),
  bandplan.Band((2304100000, 2304300000),
                "SSB, CW, digital weak-signal, <3kHz"),
  bandplan.Band((2304300000, 2304400000), "Beacons, <3kHz"),
  bandplan.Band((2304400000, 2304750000), "SSB, CW, digital weak-signal and "
                "NBFM, <6kHz"),
  bandplan.Band((2304750000, 2305000000), "Analog & Digital; paired with "
                "2394.750-2395, <50kHz"),
  bandplan.Band((2305000000, 2310000000), "Analog & Digital, paired with "
                "2395-2400, 0.05 - 1.0 MHz"),
  bandplan.Band((2310000000, 2390000000), "NON-AMATEUR"),
  bandplan.Band((2390000000, 2393000000), "Analog & Digital, including full "
                "duplex; paired with 2300-2303, 0.05 - 1.0 MHz"),
  bandplan.Band((2393000000, 2393750000), "Analog & Digital; paired with "
                "2303-2303.750, < 50 kHz"),
  bandplan.Band((2393750000, 2394750000), "Experimental"),
  bandplan.Band((2394750000, 2395000000), "Analog & Digital; paired with "
                "2304.750-2305, < 50 kHz"),
  bandplan.Band((2395000000, 2400000000), "Analog & Digital, including full "
                "duplex; paired with 2305-2310, 0.05-1.0 MHz"),
  bandplan.Band((2400000000, 2410000000), "Amateur Satellite Communications, "
                "<6kHz"),
  bandplan.Band((2410000000, 2450000000), "Broadband Modes, 22MHz max."),
)

BANDS = bandplan_iaru_r2.BANDS
BANDS += BANDS_160M + BANDS_80M + BANDS_40M + BANDS_30M + BANDS_20M
BANDS += BANDS_17M + BANDS_15M + BANDS_12M + BANDS_10M + BANDS_6M
BANDS += BANDS_2M + BANDS_1_25M + BANDS_70CM + BANDS_33CM + BANDS_23CM
BANDS += BANDS_13CM
