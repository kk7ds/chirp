# Copyright 2022 Matthew Handley <kf7tal@gmail.com>
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

"""Wouxun KG-UV920P-A radio management module based"""

from chirp.drivers import kguv920base
from chirp import directory


@directory.register
class KGUV920PARadio(kguv920base.KGUV920Radio):

    """Wouxun KG-UV920P-A"""
    MODEL = "KG-UV920P-A"
    _model = "KG-UV920Rr"   # what the radio responds to CMD_ID with
    _file_ident = b"KGUV920PA"

    _min_freq = 136000000
    _max_freq = 520000000

    def getUhfMinLimit(self):
        return 420

    def getUhfMaxLimit(self):
        return 520

    def getVhfMinLimit(self):
        return 136

    def getVhfMaxLimit(self):
        return 175

    def getMaxTxOffset(self):
        return 470000000

    def getMinFreq(self):
        return 136000000

    def getMaxFreq(self):
        return 520999999

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(136000000, 175000000),  # supports 2m
                          (420000000, 520000000)]  # supports 70cm
        return rf
