# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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


class InvalidDataError(Exception):
    """The radio driver encountered some invalid data"""
    pass


class InvalidValueError(Exception):
    """An invalid value for a given parameter was used"""
    pass


class InvalidMemoryLocation(Exception):
    """The requested memory location does not exist"""
    pass


class RadioError(Exception):
    """An error occurred while talking to the radio"""
    pass


class UnsupportedToneError(Exception):
    """The radio does not support the specified tone value"""
    pass


class ImageDetectFailed(Exception):
    """The driver for the supplied image could not be determined"""
    pass


class ImageMetadataInvalidModel(Exception):
    """The image contains metadata but no suitable driver is found"""
    pass
