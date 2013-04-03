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
}

BANDS = bandplan_iaru_r2.BANDS + (
  bandplan.Band((50000000, 54000000), "6 Meter Band"),
  bandplan.Band((51620000, 51980000), "Repeaters A", input_offset=-500000),
  bandplan.Band((52500000, 52980000), "Repeaters B", input_offset=-500000),
  bandplan.Band((53500000, 53980000), "Repeaters C", input_offset=-500000),
  bandplan.Band((144000000, 148000000), "2 Meter Band"),
  bandplan.Band((145100000, 145500000), "Repeaters A", input_offset=-600000),
  bandplan.Band((146600000, 147000000), "Repeaters B", input_offset=-600000),
  bandplan.Band((147000000, 147400000), "Repeaters C", input_offset=600000),
  bandplan.Band((219000000, 225000000), "220MHz Band"),
  bandplan.Band((223850000, 224980000), "Repeaters", input_offset=-1600000),
  bandplan.Band((420000000, 450000000), "70cm Band"),
  bandplan.Band((440000000, 445000000), "Repeaters A", input_offset=5000000),
  bandplan.Band((447000000, 450000000), "Repeaters B", input_offset=-5000000),
  bandplan.Band((1240000000, 1300000000), "23cm Band"),
  bandplan.Band((1282000000, 1288000000), "Repeaters", input_offset=-12000000),
)
