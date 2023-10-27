# Wouxun KG-Q10H Driver
# melvin.terechenok@gmail.com
#
# Based on the work of 2019 Pavel Milanes CO7WT <pavelmc@gmail.com>
# and Krystian Struzik <toner_82@tlen.pl>
# who figured out the crypt used and made possible the
# Wuoxun KG-UV8D Plus driver, in which this work is based.
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

"""Wouxun KG-Q10H radio management module"""

import struct
import time
import logging

from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettingValueMap, RadioSettings, \
    InvalidValueError, RadioSettingValueRGB


LOG = logging.getLogger(__name__)

CMD_ID = 128    # \x80
CMD_END = 129   # \x81
CMD_RD = 130    # \82
CMD_WR = 131    # \83

MEM_VALID = 158

# This map is used to download the radio memory in address order
Q10H_download_map_full = (
    (0x00, 64, 512),  # - Use for full Download testing
)

# This map is used to take the memory stored on the radio which has
# data spread all over the memory range in non-contiguous sections and
# remap it to put the data into contiguous sections where structures
# and indices can be used.
Q10H_mem_arrange_map = (
    (0x0300, 0x0400),
    (0x0200, 0x0300),
    (0x0100, 0x0200),
    (0x0000, 0x0100),
    (0x0700, 0x0800),
    (0x0600, 0x0700),  # channel 1 data start
    (0x0500, 0x0600),
    (0x0400, 0x0500),
    (0x0b00, 0x0c00),
    (0x0a00, 0x0b00),
    (0x0900, 0x0a00),
    (0x0800, 0x0900),
    (0x0f00, 0x1000),
    (0x0e00, 0x0f00),
    (0x0d00, 0x0e00),
    (0x0c00, 0x0d00),
    (0x1300, 0x1400),
    (0x1200, 0x1300),
    (0x1100, 0x1200),
    (0x1000, 0x1100),
    (0x1700, 0x1800),
    (0x1600, 0x1700),
    (0x1500, 0x1600),
    (0x1400, 0x1500),
    (0x1B00, 0x1c00),
    (0x1a00, 0x1b00),
    (0x1900, 0x1a00),
    (0x1800, 0x1900),
    (0x1f00, 0x2000),
    (0x1e00, 0x1f00),
    (0x1d00, 0x1e00),
    (0x1c00, 0x1d00),
    (0x2300, 0x2400),
    (0x2200, 0x2300),
    (0x2100, 0x2200),
    (0x2000, 0x2100),
    (0x2700, 0x2800),
    (0x2600, 0x2700),
    (0x2500, 0x2600),
    (0x2400, 0x2500),
    (0x2B00, 0x2C00),
    (0x2a00, 0x2b00),
    (0x2900, 0x2a00),
    (0x2800, 0x2900),
    (0x2f00, 0x3000),
    (0x2e00, 0x2f00),
    (0x2d00, 0x2e00),
    (0x2c00, 0x2d00),
    (0x3300, 0x3400),
    (0x3200, 0x3300),
    (0x3100, 0x3200),
    (0x3000, 0x3100),
    (0x3700, 0x3800),
    (0x3600, 0x3700),
    (0x3500, 0x3600),
    (0x3400, 0x3500),
    (0x3B00, 0x3C00),
    (0x3a00, 0x3b00),
    (0x3900, 0x3a00),
    (0x3800, 0x3900),
    (0x3f00, 0x4000),
    (0x3e00, 0x3f00),
    (0x3d00, 0x3e00),
    (0x3c00, 0x3d00),
    (0x4300, 0x4400),
    (0x4200, 0x4300),
    (0x4100, 0x4200),
    (0x4000, 0x4100),
    (0x4700, 0x4760),
    (0x4760, 0x4800),  # start of Ch names
    (0x4600, 0x4700),
    (0x4500, 0x4600),
    (0x4400, 0x4500),
    (0x4b00, 0x4c00),
    (0x4a00, 0x4B00),
    (0x4900, 0x4a00),
    (0x4800, 0x4900),
    (0x4f00, 0x5000),
    (0x4E00, 0x4F00),
    (0x4D00, 0x4E00),
    (0x4C00, 0x4d00),
    (0x5300, 0x5400),
    (0x5200, 0x5300),
    (0x5100, 0x5200),
    (0x5000, 0x5100),
    (0x5700, 0x5800),
    (0x5600, 0x5700),
    (0x5500, 0x5600),
    (0x5400, 0x5500),
    (0x5B00, 0x5C00),
    (0x5A00, 0x5B00),
    (0x5900, 0x5A00),
    (0x5800, 0x5900),
    (0x5F00, 0x6000),
    (0x5E00, 0x5F00),
    (0x5D00, 0x5E00),
    (0x5C00, 0x5D00),
    (0x6300, 0x6400),
    (0x6200, 0x6300),
    (0x6100, 0x6200),
    (0x6000, 0x6100),
    (0x6700, 0x6800),
    (0x6600, 0x6700),
    (0x6500, 0x6600),
    (0x6400, 0x6500),
    (0x6b00, 0x6c00),
    (0x6a00, 0x6b00),
    (0x6900, 0x6a00),
    (0x6800, 0x6900),
    (0x6F00, 0x7000),
    (0x6e00, 0x6F00),
    (0X6D00, 0X6E00),
    (0X6C00, 0X6D00),
    (0x7300, 0x7400),
    (0x7200, 0x7300),
    (0x7100, 0x7200),
    (0x7000, 0x7040),  # End of Ch Names
    (0x7040, 0x7100),  # start of ch valid
    (0x7700, 0x7800),
    (0x7600, 0x7700),
    (0x7500, 0x7600),
    (0x7400, 0x7440),  # end of ch valid
    (0x7440, 0x7500),
    (0x7b00, 0x7c00),
    (0x7a00, 0x7b00),
    (0x7900, 0x7a00),
    (0x7800, 0x7900),
    (0x7f00, 0x8000),
    (0x7e00, 0x7f00),
    (0x7d00, 0x7e00),
    (0x7c00, 0x7d00),
)

Q10H_upload_map = (
    #  This map serves 2 purposes-
    #   To limit the Upload to Radio Writes to known settings only
    #   And also to send the rearranged Chirp Memory data back to the radio
    #   using the proper radio addresses.
    #    Radio   Radio   Chirp   Chirp  Blk  cnt
    #    start   end     start   end     sz
    # (0x0000, 0x0400, 0x0000, 0x0400, 64, 16),
    # (0x0600, 0x06E0, 0x0400, 0x04E0, 32, 7),
    # (0x0002, 0x0022, 0x0302, 0x0322, 32, 1), # Tx Limits
    # (0x00a6, 0x00fe, 0x00a6, 0x00fe,  8, 11), # Rx Limits
    # (0x030a, 0x030a, 0x030a, 0x030a,  1, 1),  # Factory Locked Mode
    # (0x0640, 0x06c0, 0x0440, 0x04c0, 32, 7),  # VFO settings
    # (0x0700, 0x0800, 0x04E0, 0x05E0, 64, 4),  # settings
    # (0x06E0, 0x0700, 0x05E0, 0x0600, 32, 1),  # channel 1 data start
    (0x0300, 0x0400, 0x0000, 0x0100, 64, 4),
    (0x0200, 0x0300, 0x0100, 0x0200, 64, 4),
    (0x0100, 0x0200, 0x0200, 0x0300, 64, 4),
    (0x0000, 0x0100, 0x0300, 0x0400, 64, 4),
    (0x0700, 0x0800, 0x0400, 0x0500, 64, 4),
    (0x0600, 0x0700, 0x0500, 0x0600, 64, 4),
    (0x0500, 0x0600, 0x0600, 0x0700, 64, 4),
    (0x0400, 0x0500, 0x0700, 0x0800, 64, 4),
    (0x0b00, 0x0c00, 0x0800, 0x0900, 64, 4),
    (0x0a00, 0x0b00, 0x0900, 0x0A00, 64, 4),
    (0x0900, 0x0a00, 0x0A00, 0x0B00, 64, 4),
    (0x0800, 0x0900, 0x0B00, 0x0C00, 64, 4),
    (0x0f00, 0x1000, 0x0C00, 0x0D00, 64, 4),
    (0x0e00, 0x0f00, 0x0D00, 0x0E00, 64, 4),
    (0x0d00, 0x0e00, 0x0E00, 0x0F00, 64, 4),
    (0x0c00, 0x0d00, 0x0F00, 0x1000, 64, 4),
    (0x1300, 0x1400, 0x1000, 0x1100, 64, 4),
    (0x1200, 0x1300, 0x1100, 0x1200, 64, 4),
    (0x1100, 0x1200, 0x1200, 0x1300, 64, 4),
    (0x1000, 0x1100, 0x1300, 0x1400, 64, 4),
    (0x1700, 0x1800, 0x1400, 0x1500, 64, 4),
    (0x1600, 0x1700, 0x1500, 0x1600, 64, 4),
    (0x1500, 0x1600, 0x1600, 0x1700, 64, 4),
    (0x1400, 0x1500, 0x1700, 0x1800, 64, 4),
    (0x1B00, 0x1c00, 0x1800, 0x1900, 64, 4),
    (0x1a00, 0x1b00, 0x1900, 0x1A00, 64, 4),
    (0x1900, 0x1a00, 0x1A00, 0x1B00, 64, 4),
    (0x1800, 0x1900, 0x1B00, 0x1C00, 64, 4),
    (0x1f00, 0x2000, 0x1C00, 0x1D00, 64, 4),
    (0x1e00, 0x1f00, 0x1D00, 0x1E00, 64, 4),
    (0x1d00, 0x1e00, 0x1E00, 0x1F00, 64, 4),
    (0x1c00, 0x1d00, 0x1F00, 0x2000, 64, 4),
    (0x2300, 0x2400, 0x2000, 0x2100, 64, 4),
    (0x2200, 0x2300, 0x2100, 0x2200, 64, 4),
    (0x2100, 0x2200, 0x2200, 0x2300, 64, 4),
    (0x2000, 0x2100, 0x2300, 0x2400, 64, 4),
    (0x2700, 0x2800, 0x2400, 0x2500, 64, 4),
    (0x2600, 0x2700, 0x2500, 0x2600, 64, 4),
    (0x2500, 0x2600, 0x2600, 0x2700, 64, 4),
    (0x2400, 0x2500, 0x2700, 0x2800, 64, 4),
    (0x2B00, 0x2C00, 0x2800, 0x2900, 64, 4),
    (0x2a00, 0x2b00, 0x2900, 0x2A00, 64, 4),
    (0x2900, 0x2a00, 0x2A00, 0x2B00, 64, 4),
    (0x2800, 0x2900, 0x2B00, 0x2C00, 64, 4),
    (0x2f00, 0x3000, 0x2C00, 0x2D00, 64, 4),
    (0x2e00, 0x2f00, 0x2D00, 0x2E00, 64, 4),
    (0x2d00, 0x2e00, 0x2E00, 0x2F00, 64, 4),
    (0x2c00, 0x2d00, 0x2F00, 0x3000, 64, 4),
    (0x3300, 0x3400, 0x3000, 0x3100, 64, 4),
    (0x3200, 0x3300, 0x3100, 0x3200, 64, 4),
    (0x3100, 0x3200, 0x3200, 0x3300, 64, 4),
    (0x3000, 0x3100, 0x3300, 0x3400, 64, 4),
    (0x3700, 0x3800, 0x3400, 0x3500, 64, 4),
    (0x3600, 0x3700, 0x3500, 0x3600, 64, 4),
    (0x3500, 0x3600, 0x3600, 0x3700, 64, 4),
    (0x3400, 0x3500, 0x3700, 0x3800, 64, 4),
    (0x3B00, 0x3C00, 0x3800, 0x3900, 64, 4),
    (0x3a00, 0x3b00, 0x3900, 0x3A00, 64, 4),
    (0x3900, 0x3a00, 0x3A00, 0x3B00, 64, 4),
    (0x3800, 0x3900, 0x3B00, 0x3C00, 64, 4),
    (0x3f00, 0x4000, 0x3C00, 0x3D00, 64, 4),
    (0x3e00, 0x3f00, 0x3D00, 0x3E00, 64, 4),
    (0x3d00, 0x3e00, 0x3E00, 0x3F00, 64, 4),
    (0x3c00, 0x3d00, 0x3F00, 0x4000, 64, 4),
    (0x4300, 0x4400, 0x4000, 0x4100, 64, 4),
    (0x4200, 0x4300, 0x4100, 0x4200, 64, 4),
    (0x4100, 0x4200, 0x4200, 0x4300, 64, 4),
    (0x4000, 0x4100, 0x4300, 0x4400, 64, 4),
    (0x4700, 0x4760, 0x4400, 0x4460, 32, 3),  # End of Ch Data
    (0x4760, 0x4800, 0x4460, 0x4500, 32, 5),  # start of Ch names
    (0x4600, 0x4700, 0x4500, 0x4600, 64, 4),
    (0x4500, 0x4600, 0x4600, 0x4700, 64, 4),
    (0x4400, 0x4500, 0x4700, 0x4800, 64, 4),
    (0x4b00, 0x4c00, 0x4800, 0x4900, 64, 4),
    (0x4a00, 0x4B00, 0x4900, 0x4A00, 64, 4),
    (0x4900, 0x4a00, 0x4A00, 0x4B00, 64, 4),
    (0x4800, 0x4900, 0x4B00, 0x4C00, 64, 4),
    (0x4f00, 0x5000, 0x4C00, 0x4D00, 64, 4),
    (0x4E00, 0x4F00, 0x4D00, 0x4E00, 64, 4),
    (0x4D00, 0x4E00, 0x4E00, 0x4F00, 64, 4),
    (0x4C00, 0x4d00, 0x4F00, 0x5000, 64, 4),
    (0x5300, 0x5400, 0x5000, 0x5100, 64, 4),
    (0x5200, 0x5300, 0x5100, 0x5200, 64, 4),
    (0x5100, 0x5200, 0x5200, 0x5300, 64, 4),
    (0x5000, 0x5100, 0x5300, 0x5400, 64, 4),
    (0x5700, 0x5800, 0x5400, 0x5500, 64, 4),
    (0x5600, 0x5700, 0x5500, 0x5600, 64, 4),
    (0x5500, 0x5600, 0x5600, 0x5700, 64, 4),
    (0x5400, 0x5500, 0x5700, 0x5800, 64, 4),
    (0x5B00, 0x5C00, 0x5800, 0x5900, 64, 4),
    (0x5A00, 0x5B00, 0x5900, 0x5A00, 64, 4),
    (0x5900, 0x5A00, 0x5A00, 0x5B00, 64, 4),
    (0x5800, 0x5900, 0x5B00, 0x5C00, 64, 4),
    (0x5F00, 0x6000, 0x5C00, 0x5D00, 64, 4),
    (0x5E00, 0x5F00, 0x5D00, 0x5E00, 64, 4),
    (0x5D00, 0x5E00, 0x5E00, 0x5F00, 64, 4),
    (0x5C00, 0x5D00, 0x5F00, 0x6000, 64, 4),
    (0x6300, 0x6400, 0x6000, 0x6100, 64, 4),
    (0x6200, 0x6300, 0x6100, 0x6200, 64, 4),
    (0x6100, 0x6200, 0x6200, 0x6300, 64, 4),
    (0x6000, 0x6100, 0x6300, 0x6400, 64, 4),
    (0x6700, 0x6800, 0x6400, 0x6500, 64, 4),
    (0x6600, 0x6700, 0x6500, 0x6600, 64, 4),
    (0x6500, 0x6600, 0x6600, 0x6700, 64, 4),
    (0x6400, 0x6500, 0x6700, 0x6800, 64, 4),
    (0x6b00, 0x6c00, 0x6800, 0x6900, 64, 4),
    (0x6a00, 0x6b00, 0x6900, 0x6A00, 64, 4),
    (0x6900, 0x6a00, 0x6A00, 0x6B00, 64, 4),
    (0x6800, 0x6900, 0x6B00, 0x6C00, 64, 4),
    (0x6F00, 0x7000, 0x6C00, 0x6D00, 64, 4),
    (0x6e00, 0x6F00, 0x6D00, 0x6E00, 64, 4),
    (0x6D00, 0x6E00, 0x6E00, 0x6F00, 64, 4),
    (0x6C00, 0x6D00, 0x6F00, 0x7000, 64, 4),
    (0x7300, 0x7400, 0x7000, 0x7100, 64, 4),
    (0x7200, 0x7300, 0x7100, 0x7200, 64, 4),
    (0x7100, 0x7200, 0x7200, 0x7300, 64, 4),
    (0x7000, 0x7040, 0x7300, 0x7340, 64, 1),  # End of Ch Names
    (0x7040, 0x7100, 0x7340, 0x7400, 64, 3),  # start of ch valid
    (0x7700, 0x7800, 0x7400, 0x7500, 64, 4),
    (0x7600, 0x7700, 0x7500, 0x7600, 64, 4),
    (0x7500, 0x7600, 0x7600, 0x7700, 64, 4),
    (0x7400, 0x7440, 0x7700, 0x7740, 64, 1),  # end of ch valid
    (0x7440, 0x74e0, 0x7740, 0x77e0, 32, 5),  # scan groups
    (0x74e0, 0x74e8, 0x77e0, 0x77e8, 8, 1),  # VFO Scan range
    (0x7bB0, 0x7c00, 0x78B0, 0x7900, 16, 5),  # FM presets / Call ID Start
    (0x7a00, 0x7b00, 0x7900, 0x7A00, 64, 4),
    (0x7900, 0x7a00, 0x7A00, 0x7B00, 64, 4),
    (0x7800, 0x7900, 0x7B00, 0x7C00, 64, 4),  # Call ID end / Call Name Start
    (0x7f00, 0x8000, 0x7C00, 0x7D00, 64, 4),
    (0x7e00, 0x7f00, 0x7D00, 0x7E00, 64, 4),
    (0x7d00, 0x7e00, 0x7E00, 0x7F00, 64, 4),
    (0x7c00, 0x7d00, 0x7F00, 0x8000, 64, 4),  # Call Name End
)

Q10H_upload_map_nolims = (
    #  This map serves 2 purposes-
    #   To limit the Upload to Radio Writes to known settings only
    #   And also to send the rearranged Chirp Memory data back to the radio
    #   using the proper radio addresses.
    #    Radio   Radio   Chirp   Chirp  Blk  cnt
    #    start   end     start   end     sz
    # (0x0300, 0x0400, 0x0000, 0x0100, 64, 4),
    # (0x0200, 0x0300, 0x0100, 0x0200, 64, 4),
    # (0x0100, 0x0200, 0x0200, 0x0300, 64, 4),
    (0x030A, 0x030A, 0x000a, 0x000a, 1, 1),  # Unlock
    (0x0040, 0x0100, 0x0340, 0x0400, 64, 3),  # settings
    (0x0700, 0x0800, 0x0400, 0x0500, 64, 4),  # channel data
    (0x0600, 0x0700, 0x0500, 0x0600, 64, 4),
    (0x0500, 0x0600, 0x0600, 0x0700, 64, 4),
    (0x0400, 0x0500, 0x0700, 0x0800, 64, 4),
    (0x0b00, 0x0c00, 0x0800, 0x0900, 64, 4),
    (0x0a00, 0x0b00, 0x0900, 0x0A00, 64, 4),
    (0x0900, 0x0a00, 0x0A00, 0x0B00, 64, 4),
    (0x0800, 0x0900, 0x0B00, 0x0C00, 64, 4),
    (0x0f00, 0x1000, 0x0C00, 0x0D00, 64, 4),
    (0x0e00, 0x0f00, 0x0D00, 0x0E00, 64, 4),
    (0x0d00, 0x0e00, 0x0E00, 0x0F00, 64, 4),
    (0x0c00, 0x0d00, 0x0F00, 0x1000, 64, 4),
    (0x1300, 0x1400, 0x1000, 0x1100, 64, 4),
    (0x1200, 0x1300, 0x1100, 0x1200, 64, 4),
    (0x1100, 0x1200, 0x1200, 0x1300, 64, 4),
    (0x1000, 0x1100, 0x1300, 0x1400, 64, 4),
    (0x1700, 0x1800, 0x1400, 0x1500, 64, 4),
    (0x1600, 0x1700, 0x1500, 0x1600, 64, 4),
    (0x1500, 0x1600, 0x1600, 0x1700, 64, 4),
    (0x1400, 0x1500, 0x1700, 0x1800, 64, 4),
    (0x1B00, 0x1c00, 0x1800, 0x1900, 64, 4),
    (0x1a00, 0x1b00, 0x1900, 0x1A00, 64, 4),
    (0x1900, 0x1a00, 0x1A00, 0x1B00, 64, 4),
    (0x1800, 0x1900, 0x1B00, 0x1C00, 64, 4),
    (0x1f00, 0x2000, 0x1C00, 0x1D00, 64, 4),
    (0x1e00, 0x1f00, 0x1D00, 0x1E00, 64, 4),
    (0x1d00, 0x1e00, 0x1E00, 0x1F00, 64, 4),
    (0x1c00, 0x1d00, 0x1F00, 0x2000, 64, 4),
    (0x2300, 0x2400, 0x2000, 0x2100, 64, 4),
    (0x2200, 0x2300, 0x2100, 0x2200, 64, 4),
    (0x2100, 0x2200, 0x2200, 0x2300, 64, 4),
    (0x2000, 0x2100, 0x2300, 0x2400, 64, 4),
    (0x2700, 0x2800, 0x2400, 0x2500, 64, 4),
    (0x2600, 0x2700, 0x2500, 0x2600, 64, 4),
    (0x2500, 0x2600, 0x2600, 0x2700, 64, 4),
    (0x2400, 0x2500, 0x2700, 0x2800, 64, 4),
    (0x2B00, 0x2C00, 0x2800, 0x2900, 64, 4),
    (0x2a00, 0x2b00, 0x2900, 0x2A00, 64, 4),
    (0x2900, 0x2a00, 0x2A00, 0x2B00, 64, 4),
    (0x2800, 0x2900, 0x2B00, 0x2C00, 64, 4),
    (0x2f00, 0x3000, 0x2C00, 0x2D00, 64, 4),
    (0x2e00, 0x2f00, 0x2D00, 0x2E00, 64, 4),
    (0x2d00, 0x2e00, 0x2E00, 0x2F00, 64, 4),
    (0x2c00, 0x2d00, 0x2F00, 0x3000, 64, 4),
    (0x3300, 0x3400, 0x3000, 0x3100, 64, 4),
    (0x3200, 0x3300, 0x3100, 0x3200, 64, 4),
    (0x3100, 0x3200, 0x3200, 0x3300, 64, 4),
    (0x3000, 0x3100, 0x3300, 0x3400, 64, 4),
    (0x3700, 0x3800, 0x3400, 0x3500, 64, 4),
    (0x3600, 0x3700, 0x3500, 0x3600, 64, 4),
    (0x3500, 0x3600, 0x3600, 0x3700, 64, 4),
    (0x3400, 0x3500, 0x3700, 0x3800, 64, 4),
    (0x3B00, 0x3C00, 0x3800, 0x3900, 64, 4),
    (0x3a00, 0x3b00, 0x3900, 0x3A00, 64, 4),
    (0x3900, 0x3a00, 0x3A00, 0x3B00, 64, 4),
    (0x3800, 0x3900, 0x3B00, 0x3C00, 64, 4),
    (0x3f00, 0x4000, 0x3C00, 0x3D00, 64, 4),
    (0x3e00, 0x3f00, 0x3D00, 0x3E00, 64, 4),
    (0x3d00, 0x3e00, 0x3E00, 0x3F00, 64, 4),
    (0x3c00, 0x3d00, 0x3F00, 0x4000, 64, 4),
    (0x4300, 0x4400, 0x4000, 0x4100, 64, 4),
    (0x4200, 0x4300, 0x4100, 0x4200, 64, 4),
    (0x4100, 0x4200, 0x4200, 0x4300, 64, 4),
    (0x4000, 0x4100, 0x4300, 0x4400, 64, 4),
    (0x4700, 0x4760, 0x4400, 0x4460, 32, 3),  # End of Ch Data
    (0x4760, 0x4800, 0x4460, 0x4500, 32, 5),  # start of Ch names
    (0x4600, 0x4700, 0x4500, 0x4600, 64, 4),
    (0x4500, 0x4600, 0x4600, 0x4700, 64, 4),
    (0x4400, 0x4500, 0x4700, 0x4800, 64, 4),
    (0x4b00, 0x4c00, 0x4800, 0x4900, 64, 4),
    (0x4a00, 0x4B00, 0x4900, 0x4A00, 64, 4),
    (0x4900, 0x4a00, 0x4A00, 0x4B00, 64, 4),
    (0x4800, 0x4900, 0x4B00, 0x4C00, 64, 4),
    (0x4f00, 0x5000, 0x4C00, 0x4D00, 64, 4),
    (0x4E00, 0x4F00, 0x4D00, 0x4E00, 64, 4),
    (0x4D00, 0x4E00, 0x4E00, 0x4F00, 64, 4),
    (0x4C00, 0x4d00, 0x4F00, 0x5000, 64, 4),
    (0x5300, 0x5400, 0x5000, 0x5100, 64, 4),
    (0x5200, 0x5300, 0x5100, 0x5200, 64, 4),
    (0x5100, 0x5200, 0x5200, 0x5300, 64, 4),
    (0x5000, 0x5100, 0x5300, 0x5400, 64, 4),
    (0x5700, 0x5800, 0x5400, 0x5500, 64, 4),
    (0x5600, 0x5700, 0x5500, 0x5600, 64, 4),
    (0x5500, 0x5600, 0x5600, 0x5700, 64, 4),
    (0x5400, 0x5500, 0x5700, 0x5800, 64, 4),
    (0x5B00, 0x5C00, 0x5800, 0x5900, 64, 4),
    (0x5A00, 0x5B00, 0x5900, 0x5A00, 64, 4),
    (0x5900, 0x5A00, 0x5A00, 0x5B00, 64, 4),
    (0x5800, 0x5900, 0x5B00, 0x5C00, 64, 4),
    (0x5F00, 0x6000, 0x5C00, 0x5D00, 64, 4),
    (0x5E00, 0x5F00, 0x5D00, 0x5E00, 64, 4),
    (0x5D00, 0x5E00, 0x5E00, 0x5F00, 64, 4),
    (0x5C00, 0x5D00, 0x5F00, 0x6000, 64, 4),
    (0x6300, 0x6400, 0x6000, 0x6100, 64, 4),
    (0x6200, 0x6300, 0x6100, 0x6200, 64, 4),
    (0x6100, 0x6200, 0x6200, 0x6300, 64, 4),
    (0x6000, 0x6100, 0x6300, 0x6400, 64, 4),
    (0x6700, 0x6800, 0x6400, 0x6500, 64, 4),
    (0x6600, 0x6700, 0x6500, 0x6600, 64, 4),
    (0x6500, 0x6600, 0x6600, 0x6700, 64, 4),
    (0x6400, 0x6500, 0x6700, 0x6800, 64, 4),
    (0x6b00, 0x6c00, 0x6800, 0x6900, 64, 4),
    (0x6a00, 0x6b00, 0x6900, 0x6A00, 64, 4),
    (0x6900, 0x6a00, 0x6A00, 0x6B00, 64, 4),
    (0x6800, 0x6900, 0x6B00, 0x6C00, 64, 4),
    (0x6F00, 0x7000, 0x6C00, 0x6D00, 64, 4),
    (0x6e00, 0x6F00, 0x6D00, 0x6E00, 64, 4),
    (0x6D00, 0x6E00, 0x6E00, 0x6F00, 64, 4),
    (0x6C00, 0x6D00, 0x6F00, 0x7000, 64, 4),
    (0x7300, 0x7400, 0x7000, 0x7100, 64, 4),
    (0x7200, 0x7300, 0x7100, 0x7200, 64, 4),
    (0x7100, 0x7200, 0x7200, 0x7300, 64, 4),
    (0x7000, 0x7040, 0x7300, 0x7340, 64, 1),  # End of Ch Names
    (0x7040, 0x7100, 0x7340, 0x7400, 64, 3),  # start of ch valid
    (0x7700, 0x7800, 0x7400, 0x7500, 64, 4),
    (0x7600, 0x7700, 0x7500, 0x7600, 64, 4),
    (0x7500, 0x7600, 0x7600, 0x7700, 64, 4),
    (0x7400, 0x7440, 0x7700, 0x7740, 64, 1),  # end of ch valid
    (0x7440, 0x74e0, 0x7740, 0x77e0, 32, 5),  # scan groups
    (0x74e0, 0x74e8, 0x77e0, 0x77e8, 8, 1),  # VFO Scan range
    (0x7bB0, 0x7c00, 0x78B0, 0x7900, 16, 5),  # FM presets / Call ID Start
    (0x7a00, 0x7b00, 0x7900, 0x7A00, 64, 4),
    (0x7900, 0x7a00, 0x7A00, 0x7B00, 64, 4),
    (0x7800, 0x7900, 0x7B00, 0x7C00, 64, 4),  # Call ID end / Call Name Start
    (0x7f00, 0x8000, 0x7C00, 0x7D00, 64, 4),
    (0x7e00, 0x7f00, 0x7D00, 0x7E00, 64, 4),
    (0x7d00, 0x7e00, 0x7E00, 0x7F00, 64, 4),
    (0x7c00, 0x7d00, 0x7F00, 0x8000, 64, 4),  # Call Name End
)

Q10H_upload_map_full_radio_address_order = (
    # - Use for full radio address order upload testing
    (0x0000, 0x8000, 0x0000, 0x8000, 64, 512),
    )

AB_LIST = ["A", "B"]
STEPS = [2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 25.0, 50.0, 100.0]
STEP_LIST = [str(x) + "k" for x in STEPS]
STEPS2 = [2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 20.0, 25.0, 50.0, 100.0]
STEP2_LIST = [str(x) + "k" for x in STEPS2]
ROGER_LIST = ["OFF", "Begin", "End", "Both"]
TIMEOUT_LIST = ["OFF"] + [str(x) + "s" for x in range(15, 901, 15)]
BANDWIDTH_LIST = ["Narrow", "Wide"]
SCANMODE_LIST = ["TO", "CO", "SE"]
WORKMODE_LIST = ["VFO", "Ch.Number.", "Ch.Freq.", "Ch.Name"]
BACKLIGHT_LIST = ["Always On"] + [str(x) + "s" for x in range(1, 21)] + \
    ["Always Off"]
OFFSET_LIST = ["OFF", "Plus Shift", "Minus Shift"]
PONMSG_LIST = ["Startup Display", "Battery Volts"]
SPMUTE_LIST = ["QT", "QT+DTMF", "QT*DTMF"]
DTMFST_LIST = ["OFF", "DTMF", "ANI", "DTMF+ANI"]
DTMF_TIMES = [('%dms' % dtmf, (dtmf // 10)) for dtmf in range(50, 501, 10)]
ALERTS = [1750, 2100, 1000, 1450]
ALERTS_LIST = [str(x) + " Hz" for x in ALERTS]
PTTID_LIST = ["OFF", "BOT", "EOT", "Both"]
LIST_10 = ["OFF"] + ["%s" % x for x in range(1, 11)]
LIST_10S = ["OFF"] + ["%s" % x + "s" for x in range(1, 11)]
LIST_TOA = ["OFF"] + ["%s" % x + "s" for x in range(1, 11)]
SCANGRP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
SMUTESET_LIST = ["OFF", "Rx", "Tx", "Rx+Tx"]
POWER_LIST = ["Lo", "Mid", "Hi", "UltraHigh"]
HOLD_TIMES = ["OFF"] + ["%s" % x + "s" for x in range(100, 5001, 100)]
RPTTYPE_MAP = [("X-DIRPT", 1), ("X-TWRPT", 2)]
THEME_LIST = ["White-1", "White-2", "Black-1", "Black-2",
              "Cool", "Rain", "NotARubi", "Sky", "BTWR", "Candy",
              "Custom 1", "Custom 2", "Custom 3", "Custom 4"]
DSPBRTSBY_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
DSPBRTACT_MAP = [("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5),
                 ("6", 6), ("7", 7), ("8", 8), ("9", 9), ("10", 10)]
TONESCANSAVELIST = ["Rx", "Tx", "Tx/Rx"]
PTTDELAY_TIMES = [('%dms' % pttdelay,
                  (pttdelay // 100)) for pttdelay in range(100, 3001, 100)]
SCRAMBLE_LIST = ["OFF"] + [str(x) for x in range(1, 9)]
ONOFF_LIST = ["OFF", "ON"]
TONE_MAP = [('OFF - No Tone', 0x0000)] + \
           [('%.1f' % tone,
            int(0x8000 + tone * 10)) for tone in chirp_common.TONES] + \
           [('D%03dn' % tone, int(0x4000 + int(str(tone), 8)))
               for tone in chirp_common.DTCS_CODES] + \
           [('D%03di' % tone, int(0x6000 + int(str(tone), 8)))
               for tone in chirp_common.DTCS_CODES]
BATT_DISP_LIST = ["Icon", "Voltage", "Percent"]
WX_TYPE = ["Weather", "Icon-Only", "Tone", "Flash", "Tone-Flash"]
AM_MODE = ["OFF", "AM Rx", "AM Rx+Tx"]
AM_MODE_CH = [("AM Rx", 1), ("AM Rx+Tx", 2)]
AM_MODE_2 = ["OFF", "AM Rx"]
TIME_ZONE = ["GMT-12", "GMT-11", "GMT-10", "GMT-9", "GMT-8",
             "GMT-7", "GMT-6", "GMT-5", "GMT-4", "GMT-3",
             "GMT-2", "GMT-1", "GMT", "GMT+1", "GMT+2",
             "GMT+3", "GMT+4", "GMT+5", "GMT+6", "GMT+7",
             "GMT+8", "GMT+9", "GMT+10", "GMT+11", "GMT+12"]
GPS_SEND_FREQ = ["OFF", "PTT SEND", "1 min", "2 min", "3 min",
                 "4 min", "5 min", "6 min", "7 min", "8 min",
                 "9 min", "10 min"]
VFOABAND_MAP = [("150M", 0),
                ("400M", 1),
                ("200M", 2),
                ("66M", 3),
                ("800M", 4),
                ("300M", 5)]
VFOABAND_MAP2 = [("150M", 0),
                 ("400M", 1),
                 ("200M", 2),
                 ("26M", 3),
                 ("800M", 4),
                 ("300M", 5)]

VFOBBAND_MAP = [("150M", 0),
                ("400M", 1)]
PTT_LIST = ["Area A", "Area B", "Main Tx", "Secondary Tx", "Low Power",
            "Ultra Hi Power", "Call"]
PROG_KEY_LIST = ["DISABLE/UNDEF", "ALARM", "BACKLIGHT", "BRIGHT+", "FAVORITE",
                 "FLASHLIGHT", "FM-RADIO", "DISPLAY-MAP", "MONITOR",
                 "REVERSE", "SCAN", "SCAN-CTC", "SCAN-DCS", "SOS",
                 "STROBE", "TALK-AROUND", "WEATHER"]
PROG_KEY_LIST2 = ["DISABLE/UNDEF", "ALARM", "BACKLIGHT", "BRIGHT+", "FAVORITE",
                  "FLASHLIGHT", "FM-RADIO", "DISPLAY-MAP", "MONITOR",
                  "REVERSE", "SCAN", "SCAN-CTC", "SCAN-DCS", "SOS",
                  "STROBE", "TALK-AROUND", "WEATHER", "FM/AM", "CH-WIZARD"]

VFO_SCANMODE_LIST = ["Current Band", "Range", "All"]
ACTIVE_AREA_LIST = ["Area A - Top", "Area B - Bottom"]
TDR_LIST = ["TDR ON", "TDR OFF"]
PRICHAN_LIST = ["OFF", "ON Standby - Rx OFF", "Always On"]
# First Q10H Firmware revison did not support 20k Step Size option
NO_20K_STEP_FIRMWARE = ["VC1.00"]

_MEM_FORMAT_Q10H_oem_read = """
    #seekto 0x02c2;
    struct {
        ul32    rx12lim_start;
        ul32    rx12lim_stop;
        ul32    rx13lim_start;
        ul32    rx13lim_stop;
        ul32    rx14lim_start;
        ul32    rx14lim_stop;
        ul32    rx15lim_start;
        ul32    rx15lim_stop;
        ul32    rx16lim_start;
        ul32    rx16lim_stop;
        ul32    rx17lim_start;
        ul32    rx17lim_stop;
        ul32    rx18lim_start;
        ul32    rx18lim_stop;
        ul32    rx19lim_start;
        ul32    rx19lim_stop;
        #seekto 0x0302;
        ul32    tworx_start;
        ul32    tworx_stop;
        ul32    cm70_tx_start;  //70cm Tx
        ul32    cm70_tx_stop;   //70cm Tx
        ul32    m125_tx_start;  //1.25m Tx
        ul32    m125_tx_stop;   //1.25m Tx
        ul32    m6_tx_start;    //6m Tx
        ul32    m6_tx_stop;     //6m Tx
        #seekto 0x03a6;
        ul32    rx1lim_start;
        ul32    rx1lim_stop;
        ul32    rx2lim_start;
        ul32    rx2lim_stop;
        ul32    rx3lim_start;
        ul32    rx3lim_stop;
        ul32    rx4lim_start;
        ul32    rx4lim_stop;
        ul32    rx5lim_start;
        ul32    rx5lim_stop;
        ul32    rx6lim_start;
        ul32    rx6lim_stop;
        ul32    rx7lim_start;
        ul32    rx7lim_stop;
        ul32    rx8lim_start;
        ul32    rx8lim_stop;
        ul32    m2tx_start;     // 2m Tx
        ul32    m2tx_stop;      // 2m tx
        ul32    rx10lim_start;
        ul32    rx10lim_stop;
        ul32    rx11lim_start;
        ul32    rx11lim_stop;
        #seekto 0x3a6;
        struct {
        ul32    lim_start;
        ul32    lim_stop;
        } more_limits[14];
    } limits;

    #seekto 0x0340;
    struct {
        char     oem1[8];
        #seekto 0x036c; //0x002c;
        char    name[8];
        #seekto 0x0392; //0x0052;
        char     firmware[6];
        #seekto 0x0378; //0x0038;
        char     date[10];
        #seekto 0x000a;
        u8      locked;
    } oem_info;

    #seekto 0x7740;
    struct {
        struct {
            ul16 scan_st;
            ul16 scan_end;
        } addrs[10];
        struct {
            char name[12];
        } names[10];
    } scn_grps;

    #seekto 0x78e0;
    struct {
        u8 cid[6];
    } call_ids[100];

    #seekto 0x7B40;
    struct {
        char    call_name[12];
    } call_names[100];


    #seekto 0x0440;
    struct {
        u8      channel_menu;
        u8      power_save;
        u8      roger_beep;
        u8      timeout;
        u8      toalarm;
        u8      wxalert;
        u8      wxalert_type;
        u8      vox;
        u8      unk_xp8;
        u8      voice;
        u8      beep;
        u8      scan_rev;
        u8      backlight;
        u8      DspBrtAct;
        u8      DspBrtSby;
        u8      ponmsg;
        u8      ptt_id; //0x530
        u8      ptt_delay;
        u8      dtmf_st;
        u8      dtmf_tx_time;
        u8      dtmf_interval;
        u8      ring_time;
        u8      alert;
        u8      autolock;
        ul16     pri_ch;
        u8      prich_sw;
        u8      rpttype;
        u8      rpt_spk;
        u8      rpt_ptt;
        u8      rpt_tone;
        u8      rpt_hold;
        u8      scan_det;
        u8      smuteset; //0x540
        u8      batt_ind;
        u8      ToneScnSave;
        #seekto 0x0464;
        u8      theme;
        u8      unkx545;
        u8      disp_time;
        u8      time_zone;
        u8      GPS_send_freq;
        u8      GPS;
        u8      GPS_rcv;
        ul16    custcol1_text;
        ul16    custcol1_bg;
        ul16    custcol1_icon;
        ul16    custcol1_line;
        ul16    custcol2_text;
        ul16    custcol2_bg;
        ul16    custcol2_icon;
        ul16    custcol2_line;
        ul16    custcol3_text;
        ul16    custcol3_bg;
        ul16    custcol3_icon;
        ul16    custcol3_line;
        ul16    custcol4_text;
        ul16    custcol4_bg;
        ul16    custcol4_icon;
        ul16    custcol4_line;
//        #seekto 0x048b;
        char      mode_sw_pwd[6];
        char      reset_pwd[6];
        u8      work_mode_a;
        u8      work_mode_b;
        ul16      work_ch_a;
        ul16      work_ch_b;
        u8      vfostepA;
        u8      vfostepB;
        u8      squelchA;
        u8      squelchB;
        u8      BCL_A;
        u8      BCL_B;
        u8      vfobandA;
        u8      vfobandB;
        #seekto 0x04a7;
        u8      top_short;
        u8      top_long;
        u8      ptt1;
        u8      ptt2;
        u8      pf1_short;
        u8      pf1_long;
        u8      pf2_short;
        u8      pf2_long;
        u8      ScnGrpA_Act;
        u8      ScnGrpB_Act;
        u8      vfo_scanmodea;
        u8      vfo_scanmodeb; //x592
        u8      ani_id[6];
        u8      scc[6];
        #seekto 0x04c1;
        u8      act_area;
        u8      tdr;
        u8      keylock;
        #seekto 0x04c7;
        u8      stopwatch; //0x04c7
        u8      x0x04c8;
        char    dispstr[12];
        #seekto 0x04dD;
        char    areamsg[12];
        u8      xUnk_1;
        u8      xunk_2;
        u8      xunk_ani_sw;
        u8      xani_code[6];
        u8      xpf1_shrt;
        u8      xpf1_long;
        u8      xpf2_shrt;
        u8      xpf2_long;
        u8      main_band;
        u8      xTDR_single_mode;
        u8      xunk1;
        u8      xunk2;
        u8      cur_call_grp;
        u8 VFO_repeater_a;
        u8 VFO_repeater_b;
        u8 sim_rec;
    } settings;

    #seekto 0x78B0;
    struct {
        ul16    FM_radio;
    } fm[20];

    #seekto 0x0540;
    struct {
        ul32     rxfreq;
        ul32     offset;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      ofst_dir:3,
                unknown:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
      } vfoa[6];

    #seekto 0x05a0;
    struct {
        ul32     rxfreq;
        ul32     offset;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      ofst_dir:3,
                unknown:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
    } vfob[2];

    #seekto 0x05E0;
    struct {
        ul32     rxfreq;
        ul32     txfreq;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      unknown3:1,
                send_loc:1,
                scan_add:1,
                favorite:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
    } memory[1000];

    #seekto 0x4460;
    struct {
        u8    name[12];
    } names[1000];

    #seekto 0x7340;
    u8          valid[1000];

    #seekto 0x77E0;
    struct {
        ul16    vfo_scan_start_A;
        ul16    vfo_scan_end_A;
        ul16    vfo_scan_start_B;
        ul16    vfo_scan_end_B;
    } vfo_scan;

    """

_MEM_FORMAT_Q10H_oem_read_nolims = """

    #seekto 0x0340;
    struct {
        char     oem1[8];
        #seekto 0x036c; //0x002c;
        char    name[8];
        #seekto 0x0392; //0x0052;
        char     firmware[6];
        #seekto 0x0378; //0x0038;
        char     date[10];
        #seekto 0x000a;
        u8      locked;
    } oem_info;

    #seekto 0x7740;
    struct {
        struct {
            ul16 scan_st;
            ul16 scan_end;
        } addrs[10];
        struct {
            char name[12];
        } names[10];
    } scn_grps;

    #seekto 0x78e0;
    struct {
        u8 cid[6];
    } call_ids[100];

    #seekto 0x7B40;
    struct {
        char    call_name[12];
    } call_names[100];


    #seekto 0x0440;
    struct {
        u8      channel_menu;
        u8      power_save;
        u8      roger_beep;
        u8      timeout;
        u8      toalarm;
        u8      wxalert;
        u8      wxalert_type;
        u8      vox;
        u8      unk_xp8;
        u8      voice;
        u8      beep;
        u8      scan_rev;
        u8      backlight;
        u8      DspBrtAct;
        u8      DspBrtSby;
        u8      ponmsg;
        u8      ptt_id; //0x530
        u8      ptt_delay;
        u8      dtmf_st;
        u8      dtmf_tx_time;
        u8      dtmf_interval;
        u8      ring_time;
        u8      alert;
        u8      autolock;
        ul16     pri_ch;
        u8      prich_sw;
        u8      rpttype;
        u8      rpt_spk;
        u8      rpt_ptt;
        u8      rpt_tone;
        u8      rpt_hold;
        u8      scan_det;
        u8      smuteset; //0x540
        u8      batt_ind;
        u8      ToneScnSave;
        #seekto 0x0464;
        u8      theme;
        u8      unkx545;
        u8      disp_time;
        u8      time_zone;
        u8      GPS_send_freq;
        u8      GPS;
        u8      GPS_rcv;
        ul16    custcol1_text;
        ul16    custcol1_bg;
        ul16    custcol1_icon;
        ul16    custcol1_line;
        ul16    custcol2_text;
        ul16    custcol2_bg;
        ul16    custcol2_icon;
        ul16    custcol2_line;
        ul16    custcol3_text;
        ul16    custcol3_bg;
        ul16    custcol3_icon;
        ul16    custcol3_line;
        ul16    custcol4_text;
        ul16    custcol4_bg;
        ul16    custcol4_icon;
        ul16    custcol4_line;
//        #seekto 0x048b;
        char      mode_sw_pwd[6];
        char      reset_pwd[6];
        u8      work_mode_a;
        u8      work_mode_b;
        ul16      work_ch_a;
        ul16      work_ch_b;
        u8      vfostepA;
        u8      vfostepB;
        u8      squelchA;
        u8      squelchB;
        u8      BCL_A;
        u8      BCL_B;
        u8      vfobandA;
        u8      vfobandB;
        #seekto 0x04a7;
        u8      top_short;
        u8      top_long;
        u8      ptt1;
        u8      ptt2;
        u8      pf1_short;
        u8      pf1_long;
        u8      pf2_short;
        u8      pf2_long;
        u8      ScnGrpA_Act;
        u8      ScnGrpB_Act;
        u8      vfo_scanmodea;
        u8      vfo_scanmodeb; //x592
        u8      ani_id[6];
        u8      scc[6];
        #seekto 0x04c1;
        u8      act_area;
        u8      tdr;
        u8      keylock;
        #seekto 0x04c7;
        u8      stopwatch; //0x04c7
        u8      x0x04c8;
        char    dispstr[12];
        #seekto 0x04dD;
        char    areamsg[12];
        u8      xunk_1;
        u8      xunk_2;
        u8      xunk_ani_sw;
        u8      xani_code[6];
        u8      xpf1_shrt;
        u8      xpf1_long;
        u8      xpf2_shrt;
        u8      xpf2_long;
        u8      main_band;
        u8      xTDR_single_mode;
        u8      xunk1;
        u8      xunk2;
        u8      cur_call_grp;
        u8 VFO_repeater_a;
        u8 VFO_repeater_b;
        u8 sim_rec;
    } settings;

    #seekto 0x78B0;
    struct {
        ul16    FM_radio;
    } fm[20];

    #seekto 0x0540;
    struct {
        ul32     rxfreq;
        ul32     offset;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      ofst_dir:3,
                unknown:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
      } vfoa[6];

    #seekto 0x05a0;
    struct {
        ul32     rxfreq;
        ul32     offset;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      ofst_dir:3,
                unknown:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
    } vfob[2];

    #seekto 0x05E0;
    struct {
        ul32     rxfreq;
        ul32     txfreq;
        ul16     rxtone;
        ul16     txtone;
        u8      scrambler:4,
                am_mode:2,
                power:2;
        u8      unknown3:1,
                send_loc:1,
                scan_add:1,
                favorite:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      call_group;
        u8      unknown6;
    } memory[1000];

    #seekto 0x4460;
    struct {
        u8    name[12];
    } names[1000];

    #seekto 0x7340;
    u8          valid[1000];

    #seekto 0x77E0;
    struct {
        ul16    vfo_scan_start_A;
        ul16    vfo_scan_end_A;
        ul16    vfo_scan_start_B;
        ul16    vfo_scan_end_B;
    } vfo_scan;

    """

# Support for the Wouxun KG-Q10H radio
# Serial coms are at 115200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7c)
#    1      Command (\x80 Identify \x81 End/Reboot \x82 Read \x83 Write)
#    2      direction (\xff PC-> Radio, \x00 Radio -> PC)
#    3      length of payload (excluding header/checksum) (n)
#    4      payload (n bytes)
#    4+n+1  checksum - byte sum (% 256) of bytes 1 -> 4+n
#
# Memory Read Records:
# the payload is 3 bytes, first 2 are offset (big endian),
# 3rd is number of bytes to read
# Memory Write Records:
# the maximum payload size (from the Wouxun software) seems to be 66 bytes
#  (2 bytes location + 64 bytes data).


def name2str(name):
    """ Convert a callid or scan group name to a string
    Deal with fixed field padding (\0 or \0xff)
    """

    namestr = ""
    for i in range(0, len(name)):
        b = ord(name[i].get_value())
        if b != 0 and b != 0xff:
            namestr += chr(b)
    return namestr


def str2name(val, size=6, fillchar='\0', emptyfill='\0'):
    """ Convert a string to a name. A name is a 6 element bytearray
    with ascii chars.
    """
    val = str(val).rstrip(' \t\r\n\0\xff')
    if len(val) == 0:
        name = "".ljust(size, emptyfill)
    else:
        name = val.ljust(size, fillchar)
    return name


def str2callid(val):
    """ Convert caller id strings from callid2str.
    """
    ascii2bin = "0123456789"
    s = str(val).strip()
    LOG.debug("val = %s" % val)
    LOG.debug("s = %s" % s)
    if len(s) < 3 or len(s) > 6:
        raise InvalidValueError(
            "Caller ID must be at least 3 and no more than 6 digits")
    if s[0] == '0':
        raise InvalidValueError(
            "First digit of a Caller ID cannot be a zero '0'")
    blk = bytearray()
    for c in s:
        if c not in ascii2bin:
            raise InvalidValueError(
                "Caller ID must be all digits 0x%x" % c)
        b = ascii2bin.index(c)
        blk.append(b)
    if len(blk) < 6:
        blk.append(0x0F)  # EOL a short ID
    if len(blk) < 6:
        for i in range(0, (6 - len(blk))):
            blk.append(0xf0)
    LOG.debug("blk = %s" % blk)
    return blk


def digits2str(digits, padding=' ', width=6):
    """Convert a password or SCC digit string to a string
    Passwords are expanded to and must be 6 chars. Fill them with '0'
    """

    bin2ascii = "0123456789"
    digitsstr = ""
    for i in range(0, 6):
        b = digits[i].get_value()
        if b == 0x0F:  # the digits EOL
            break
        if b >= 0xa:
            raise InvalidValueError(
                "Value has illegal byte 0x%x" % ord(b))
        digitsstr += bin2ascii[b]
    digitsstr = digitsstr.ljust(width, padding)
    return digitsstr


def str2digits(val):
    """ Callback for edited strings from digits2str.
    """
    ascii2bin = " 0123456789"
    s = str(val).strip()
    if len(s) < 3 or len(s) > 6:
        raise InvalidValueError(
            "Value must be at least 3 and no more than 6 digits")
    blk = bytearray()
    for c in s:
        if c not in ascii2bin:
            raise InvalidValueError("Value must be all digits 0x%x" % c)
        blk.append(int(c))
    for i in range(len(blk), 6):
        blk.append(0x0f)  # EOL a short ID
    return blk


def apply_scc(setting, obj):
    c = str2digits(setting.value)
    obj.scc = c


@directory.register
class KGQ10HRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-Q10H"""
    VENDOR = "Wouxun"
    MODEL = "KG-Q10H"
    NEEDS_COMPAT_SERIAL = False
    _model = b"KG-Q10H"
    BAUD_RATE = 115200
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=0.5),
                    chirp_common.PowerLevel("M", watts=4.5),
                    chirp_common.PowerLevel("H", watts=5.5),
                    chirp_common.PowerLevel("U", watts=6.0)]
    _record_start = 0x7C
    _RADIO_ID = ""
    cryptbyte = 0x54
    am_mode_list_ch = AM_MODE_CH
    am_mode_list = AM_MODE
    themelist = THEME_LIST
    vfoa_grp_label = "VFO A Settings"
    vfob_grp_label = "VFO B Settings"
    workmodelist = WORKMODE_LIST
    dispmesg = "Top Message"
    areamsglabel = "Area Message"
    vfo_area = "VFO "
    pttdly_msg = "PTT-DLY - menu 34"
    idtx_msg = "PTT-ID - menu 33"
    vfoa3_msg = "66M Settings"
    _prog_key = PROG_KEY_LIST
    _vfoaband = VFOABAND_MAP
    _offset_dir_rpt = OFFSET_LIST
    _offset_dir_rpt_label = "A Shift Dir"
    rpttonemenu = 43
    timemenu = 44
    tzmenu = 45
    locmenu = 47
    show_limits = False

    def check_for_beta1_file(self):
        check1 = self.get_mmap()[0x0000:0x0005]
        check2 = self.get_mmap()[0x0340:0x0346]
        if ((check1 == b'\xdd\xdd\xdd\xdd\xdd') &
           (check2 == b'\x57\x4F\x55\x58\x55\x4E')):
            beta1 = False
        else:
            beta1 = True
        return beta1

    def process_mmap(self):
        if self.show_limits:
            self._memobj = bitwise.parse(_MEM_FORMAT_Q10H_oem_read,
                                         self._mmap)
        else:
            self._memobj = bitwise.parse(_MEM_FORMAT_Q10H_oem_read_nolims,
                                         self._mmap)

    def _checksum(self, data):
        cs = 0
        for byte in data:
            cs += byte
        return cs % 256

    def strxor(self, xora, xorb):
        return bytes([xora ^ xorb])

    # Wouxun data jumps around the memory map and is not in continuous memory
    # order
    # Rearrange Mem Map to put all memory into order where data is continuous
    def _rearrange_image(self, image_in):
        image_out = b""
        cfgmap = Q10H_mem_arrange_map

        for start, end in cfgmap:
            LOG.debug("start = " + str(hex(start)))
            LOG.debug("end = " + str(hex(end)))

            for i in range(start, end, 1):
                image_out += image_in[i]

        return image_out

    def sync_in(self):
        try:
            self._mmap_addrorder = self._download()
            self._mmap = memmap.MemoryMapBytes(self._rearrange_image
                                               (self._mmap_addrorder))
            # self._mmap = self._download()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        self._upload()

    def _upload(self):
        # Beta 1.x files had a different memory map arrangement
        # Use of Beta 1.x files with Beta 2.x and beyond driver
        # will send settings
        # to incorrect locations on the radio casuing issues-
        # Detect and Prevent!!
        # Check for specific data (static) at specific locations
        # to confirm Beta2 vs Beta1 memory layout.
        beta1 = self.check_for_beta1_file()
        if beta1:
            LOG.debug("Beta1 file detected = %s" % beta1)
            raise errors.RadioError("Beta 1 img detected!!!\n"
                                    "Upload Canceled!\n"
                                    "Select a Beta 2.x img or\n"
                                    "Download from radio to get a Beta2 img\n"
                                    "Then Retry the Upload")
        try:
            self._identify()
            self._do_upload()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        return

    def _do_upload(self):
        if self._RADIO_ID == self._model:
            LOG.debug("Starting Upload")
            if self.show_limits:
                cfgmap = Q10H_upload_map
            else:
                cfgmap = Q10H_upload_map_nolims

            for (radioaddress, radioend, start, memend,
                 blocksize, count) in cfgmap:
                end = start + (blocksize * count)
                LOG.debug("start = " + str(start))
                LOG.debug("end = " + str(end))
                LOG.debug("blksize = " + str(blocksize))
                ptr2 = radioaddress

                for addr in range(start, end, blocksize):
                    ptr = addr
                    LOG.debug("ptr = " + str(hex(ptr)))
                    LOG.debug("ptr2 = " + str(hex(ptr2)))
                    req = struct.pack('>H', ptr2)
                    chunk = self.get_mmap()[ptr:ptr + blocksize]
                    self._write_record(CMD_WR, req + chunk)
                    LOG.debug(util.hexprint(req + chunk))
                    cserr, ack = self._read_record()
                    LOG.debug(util.hexprint(ack))
                    j = struct.unpack('>H', ack)[0]
                    if cserr or j != ptr2:
                        LOG.debug(util.hexprint(ack))
                        raise Exception("Checksum Error on Ack at %i" % ptr)
                    ptr += blocksize
                    ptr2 += blocksize
                    if self.status_fn:
                        status = chirp_common.Status()
                        status.cur = ptr
                        status.max = 0x8000
                        status.msg = "Cloning to radio"
                        self.status_fn(status)
            LOG.debug("Upload Completed")
        else:
            raise errors.RadioError("Radio is not a KG-Q10H. Upload Canceled")

        self._finish()

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 12
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_bands = [(50000000, 54997500),    # 6m
                          (108000000, 174997500),  # AM Airband and VHF
                          (222000000, 225997500),  # 1.25M
                          (320000000, 479997500),  # UHF
                          (714000000, 999997500)]  # Fixed Land Mobile

        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)  # 999 memories
        rf.valid_tuning_steps = STEPS2
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('THIS DRIVER IS BETA 2.x - ''\n'
             'DO NOT USE SAVED IMG FILES FROM''\n'
             'BETA 1.x DRIVER WITH BETA 2.x TO UPLOAD TO RADIO''\n'
             'DOWNLOAD FROM RADIO WITH BETA 2.x FIRST THEN MODIFY'
             ' AND UPLOAD''\n'
             'This driver is experimental.  USE AT YOUR OWN RISK\n'
             '\n'
             'Please save a copy of the image from your radio with Chirp '
             'before modifying any values.\n'
             '\n'
             'Please keep a copy of your memories with the original Wouxon'
             'CPS software if you treasure them, this driver is new and '
             'may contain bugs.\n'
             )
        # rp.pre_download = _(
        #     "Please ensure you have selected the correct radio driver\n")
        rp.pre_upload = (
            "WARNING: THIS DRIVER IS BETA 2.x\n"
            "\n"
            "UPLOADS REQUIRE the use of Beta 2.x Radio img files. \n"
            "DO NOT USE Radio Image files from Beta 1.x"
            " to upload to radio.  \n"
            "It will cause incorrect settings on the radio.\n"
            "\n"
            "Please DOWNLOAD FROM RADIO with this driver"
            " to get a Beta 2.x img file\n"
            "for use BEFORE UPLOADING anything with this driver.\n"
            "CANCEL the Upload if you are using a Beta 1.x img \n"
            "Continue if you are using a Beta 2.x img file. \n"
            "\n"
            "If you don't know the img version...\n"
            "The driver will try a check to confirm.\n"
            "If it fails the check - Do a DOWNLOAD FROM RADIO then try again.")
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _get_tone(self, _mem, mem):
        # MRT - Chirp Uses N for n DCS Tones and R for i DCS Tones
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x2000) and "R" or "N"
            return code, pol
        tpol = False
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x4000) == 0x4000:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7fff) / 10.0
            txmode = "Tone"
        else:
            txmode = ""
        rpol = False
        if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x4000) == 0x4000:
            rcode, rpol = _get_dcs(_mem.rxtone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rxtone != 0xFFFF and _mem.rxtone != 0x0:
            mem.ctone = (_mem.rxtone & 0x7fff) / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        # always set it even if no dtcs is used
        mem.dtcs_polarity = "%s%s" % (tpol or "N", rpol or "N")

        # LOG.debug("Got TX %s (%i) RX %s (%i)" %
        #           (txmode, _mem.txtone, rxmode, _mem.rxtone))

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number
        _valid = self._memobj.valid[mem.number]
        LOG.debug("Channel %d Valid = %s", number, _valid == MEM_VALID)
        if _valid != MEM_VALID:
            mem.empty = True
            return mem
        else:
            mem.empty = False

        mem.freq = int(_mem.rxfreq) * 10

        if (_mem.txfreq == 0xFFFFFFFF or _mem.txfreq == 0x00000000):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if char != 0:
                mem.name += chr(char)
        mem.name = mem.name.rstrip()

        mem.extra = RadioSettingGroup("Extra", "Extra")
        rs = RadioSetting("mute_mode", "Mute Mode",
                          RadioSettingValueList(
                              SPMUTE_LIST, SPMUTE_LIST[_mem.mute_mode]))
        mem.extra.append(rs)
        rs = RadioSetting("scrambler", "Scramble/Descramble",
                          RadioSettingValueList(
                              SCRAMBLE_LIST, SCRAMBLE_LIST[_mem.scrambler]))
        mem.extra.append(rs)
        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueList(
                             ONOFF_LIST, ONOFF_LIST[_mem.compander]))
        mem.extra.append(rs)
        if _mem.am_mode != 0:
            rs = RadioSetting("am_mode", "AM Mode",
                              RadioSettingValueMap(
                                  self.am_mode_list_ch, _mem.am_mode))
            mem.extra.append(rs)
        rs = RadioSetting("favorite", "Favorite",
                          RadioSettingValueList(
                             ONOFF_LIST, ONOFF_LIST[_mem.favorite]))
        mem.extra.append(rs)
        rs = RadioSetting("send_loc", "Send Location",
                          RadioSettingValueList(
                             ONOFF_LIST, ONOFF_LIST[_mem.send_loc]))
        mem.extra.append(rs)

        if _mem.call_group == 0:
            _mem.call_group = 1
        rs = RadioSetting("call_group", "Call Group",
                          RadioSettingValueInteger(
                             1, 99, _mem.call_group))
        mem.extra.append(rs)

        self._get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan_add) else "S"
        _mem.power = _mem.power & 0x3
        if _mem.power > 3:
            _mem.power = 3
        mem.power = self.POWER_LEVELS[_mem.power]
        if _mem.am_mode != 0:
            mem.mode = "AM"
        elif _mem.iswide:
            mem.mode = "FM"
        else:
            mem.mode = "NFM"
        return mem

    def _scan_grp(self):
        """Scan groups
        """
        _settings = self._memobj.settings

        def apply_name(setting, obj):
            name = str2name(setting.value, 12, '\0', '\0')
            obj.name = name

        def apply_start(setting, obj):
            """Do a callback to deal with RadioSettingInteger limitation
            on memory address resolution
            """
            obj.scan_st = int(setting.value)

        def apply_end(setting, obj):
            """Do a callback to deal with RadioSettingInteger limitation
            on memory address resolution
            """
            obj.scan_end = int(setting.value)

        sgrp = self._memobj.scn_grps
        scan = RadioSettingGroup("scn_grps", "Channel Scan Groups")
        rs = RadioSetting("ScnGrpA_Act", "Scan Group A Active",
                          RadioSettingValueList(SCANGRP_LIST,
                                                SCANGRP_LIST[_settings.
                                                             ScnGrpA_Act]))
        scan.append(rs)
        rs = RadioSetting("ScnGrpB_Act", "Scan Group B Active",
                          RadioSettingValueList(SCANGRP_LIST,
                                                SCANGRP_LIST[_settings.
                                                             ScnGrpB_Act]))
        scan.append(rs)
        for i in range(0, 10):
            s_grp = sgrp.addrs[i]
            s_name = sgrp.names[i]
            rs_name = RadioSettingValueString(0, 12,
                                              name2str(s_name.name))
            rs = RadioSetting("scn_grps.names[%i].name" % i,
                              "Group %i Name" % (i + 1), rs_name)
            rs.set_apply_callback(apply_name, s_name)
            scan.append(rs)
            rs_st = RadioSettingValueInteger(1, 999, s_grp.scan_st)
            rs = RadioSetting("scn_grps.addrs[%i].scan_st" % i,
                              "     Group %i Start Channel" % (i + 1), rs_st)
            rs.set_apply_callback(apply_start, s_grp)
            scan.append(rs)
            rs_end = RadioSettingValueInteger(1, 999, s_grp.scan_end)
            rs = RadioSetting("scn_grps.addrs[%i].scan_end" % i,
                              "     Group %i End Channel" % (i + 1), rs_end)
            rs.set_apply_callback(apply_end, s_grp)
            scan.append(rs)
        return scan

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) | 0x4000
            if pol == "R":
                val += 0x2000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0x0000

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            txtone = int(mem.rtone * 10) + 0x8000
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = int(mem.ctone * 10) + 0x8000
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10) + 0x8000
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10) + 0x8000

        _mem.rxtone = rxtone
        _mem.txtone = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.txtone, rx_mode, _mem.rxtone))

    def set_memory(self, mem):
        number = mem.number

        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        if mem.empty:
            _mem.set_raw("\x00" * (_mem.size() // 8))
            self._memobj.valid[number] = 0
            self._memobj.names[number].set_raw("\x00" * (_nam.size() // 8))
            return

        _mem.rxfreq = int(mem.freq / 10)
        if mem.duplex == "off":
            # _mem.txfreq = 0xFFFFFFFF
            _mem.txfreq = 0x00000000
        elif mem.duplex == "split":
            _mem.txfreq = int(mem.offset / 10)
        elif mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "+":
            _mem.txfreq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.txfreq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.txfreq = int(mem.freq / 10)
        _mem.scan_add = int(mem.skip != "S")

        if ((mem.mode == "FM") or (mem.mode == "NFM")):
            _mem.iswide = int((mem.mode == "FM"))
            _mem.am_mode = 0
        elif mem.mode == "AM":
            _mem.am_mode = 1
            #  Q10H radio only supports wide AM mode
            _mem.iswide = 1

        # set the tone
        self._set_tone(mem, _mem)

        # set the power
        _mem.power = _mem.power & 0x3
        if mem.power:
            if _mem.power > 3:
                _mem.power = 3
            _mem.power = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = True

        for setting in mem.extra:
            if setting.get_name() != "am_mode":
                setattr(_mem, setting.get_name(), setting.value)
            else:
                if mem.mode != "AM":
                    setattr(_mem, setting.get_name(), 0)
                elif int(setting.value) == 2:
                    setattr(_mem, setting.get_name(), 2)
                elif int(setting.value) == 1:
                    setattr(_mem, setting.get_name(), 1)

        for i in range(0, len(_nam.name)):
            if i < len(mem.name) and mem.name[i]:
                _nam.name[i] = ord(mem.name[i])
            else:
                _nam.name[i] = 0x0
        self._memobj.valid[mem.number] = MEM_VALID

    def _get_settings(self):
        _settings = self._memobj.settings
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _vfo_scan = self._memobj.vfo_scan
        _fm = self._memobj.fm
        scan_grp = self._scan_grp()
        _oem = self._memobj.oem_info
        firmware_rev = str(_oem.firmware)
        # release of Q10H Firmware VC1.02 includes 20K Step
        LOG.debug("Firmware revision %s detected" % firmware_rev)
        if firmware_rev not in (NO_20K_STEP_FIRMWARE):
            steps = STEP2_LIST
            LOG.debug("20K Step Included")
        else:
            steps = STEP_LIST
            LOG.debug("20K Step NOT Included")

        cfg_grp = RadioSettingGroup("cfg_grp", "Config Settings")
        cfg_grp[0] = RadioSettingGroup("color_grp", "Custom Theme Colors")
        vfoa_grp = RadioSettingGroup("vfoa_grp", self.vfoa_grp_label)
        vfoa_grp[0] = RadioSettingGroup("vfoa150_grp", "150M Settings")
        vfoa_grp[1] = RadioSettingGroup("vfoa400_grp", "400M Settings")
        vfoa_grp[2] = RadioSettingGroup("vfoa200_grp", "200M Settings")
        vfoa_grp[3] = RadioSettingGroup("vfoa3_grp", self.vfoa3_msg)
        vfoa_grp[4] = RadioSettingGroup("vfoa800_grp", "800M Settings")
        vfoa_grp[5] = RadioSettingGroup("vfoa300_grp", "300M Settings")
        vfob_grp = RadioSettingGroup("vfob_grp", self.vfob_grp_label)
        vfob_grp[0] = RadioSettingGroup("vfob150_grp", "150M Settings")
        vfob_grp[1] = RadioSettingGroup("vfob400_grp", "400M Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Settings")
        fmradio_grp = RadioSettingGroup("fmradio_grp", "FM Broadcast Memory")
        lmt_grp = RadioSettingGroup("lmt_grp", "Frequency Limits")
        lmt_grp[0] = RadioSettingGroup("lmt_grp", "TX Limits")
        lmt_grp[1] = RadioSettingGroup("lmt_grp", "RX Limits")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")
        scanv_grp = RadioSettingGroup("scnv_grp", "VFO Scan Mode")
        call_grp = RadioSettingGroup("call_grp", "Call Group Settings")

        if self.show_limits:
            group = RadioSettings(cfg_grp, vfoa_grp,  vfob_grp,
                                  fmradio_grp, key_grp, scan_grp, scanv_grp,
                                  call_grp, lmt_grp, oem_grp)
        else:
            group = RadioSettings(cfg_grp, vfoa_grp,  vfob_grp,
                                  fmradio_grp, key_grp, scan_grp, scanv_grp,
                                  call_grp, oem_grp)

#         # Call Settings

        def apply_callid(setting, obj):
            c = str2callid(setting.value)
            obj.cid = c

        for i in range(1, 100):
            call = self._memobj.call_names[i].call_name
            _msg = str(call).split("\0")[0]
            val = RadioSettingValueString(0, 12, _msg)
            val.set_mutable(True)
            rs = RadioSetting("call_names[%i].call_name" % i,
                              "Call Name %i" % i, val)
            call_grp.append(rs)

            callid = self._memobj.call_ids[i]
            c_id = RadioSettingValueString(0, 6,
                                           self.callid2str(callid.cid),
                                           False)
            rs = RadioSetting("call_ids[%i].cid" % i,
                              "     Call Code %s" % str(i), c_id)
            rs.set_apply_callback(apply_callid, callid)
            call_grp.append(rs)

        # Configuration Settings
        #
        rs = RadioSetting("channel_menu", "Menu available in channel mode",
                          RadioSettingValueBoolean(_settings.channel_menu))
        cfg_grp.append(rs)
        rs = RadioSetting("power_save", "Battery Saver - menu 4",
                          RadioSettingValueBoolean(_settings.power_save))
        cfg_grp.append(rs)
        rs = RadioSetting("wxalert", "Weather Alert - menu 5",
                          RadioSettingValueBoolean(_settings.wxalert))
        cfg_grp.append(rs)
        rs = RadioSetting("wxalert_type",
                          "Weather Alert Notification - menu 6",
                          RadioSettingValueList(WX_TYPE,
                                                WX_TYPE[_settings.
                                                        wxalert_type]))
        cfg_grp.append(rs)
        rs = RadioSetting("roger_beep", "Roger Beep - menu 13",
                          RadioSettingValueList(ROGER_LIST,
                                                ROGER_LIST[_settings.
                                                           roger_beep]))
        cfg_grp.append(rs)
        rs = RadioSetting("timeout", "Timeout Timer (TOT) - menu 14",
                          RadioSettingValueList(
                              TIMEOUT_LIST, TIMEOUT_LIST[_settings.timeout]))
        cfg_grp.append(rs)
        rs = RadioSetting("toalarm", "Timeout Pre-Alert (TOA) - menu 15",
                          RadioSettingValueList(LIST_10S,
                                                LIST_10S[_settings.toalarm]))
        cfg_grp.append(rs)
        rs = RadioSetting("vox", "VOX - menu 16",
                          RadioSettingValueList(LIST_10,
                                                LIST_10[_settings.vox]))
        cfg_grp.append(rs)
        rs = RadioSetting("voice", "Voice Guide - menu 17",
                          RadioSettingValueBoolean(_settings.voice))
        cfg_grp.append(rs)
        rs = RadioSetting("beep", "Keypad Beep - menu 18",
                          RadioSettingValueBoolean(_settings.beep))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_rev", "Scan Mode - menu 8",
                          RadioSettingValueList(SCANMODE_LIST,
                                                SCANMODE_LIST[_settings.
                                                              scan_rev]))
        cfg_grp.append(rs)
        rs = RadioSetting("backlight", "Backlight Active Time - menu 3",
                          RadioSettingValueList(BACKLIGHT_LIST,
                                                BACKLIGHT_LIST[_settings.
                                                               backlight]))
        cfg_grp.append(rs)

        rs = RadioSetting("DspBrtAct", "Display Brightness ACTIVE - menu 1",
                          RadioSettingValueMap(DSPBRTACT_MAP,
                                               _settings.DspBrtAct))
        cfg_grp.append(rs)
        rs = RadioSetting("DspBrtSby", "Display Brightness STANDBY - menu 2",
                          RadioSettingValueList(
                              DSPBRTSBY_LIST, DSPBRTSBY_LIST[
                                  _settings.DspBrtSby]))
        cfg_grp.append(rs)

        rs = RadioSetting("theme", "Theme - menu 7",
                          RadioSettingValueList(
                              self.themelist,
                              self.themelist[_settings.theme]))
        cfg_grp.append(rs)
        rs = RadioSetting("ponmsg", "Startup Display - menu 27",
                          RadioSettingValueList(
                               PONMSG_LIST, PONMSG_LIST[_settings.ponmsg]))
        cfg_grp.append(rs)
        rs = RadioSetting("batt_ind", "Battery Indicator - menu 39",
                          RadioSettingValueList(
                               BATT_DISP_LIST,
                               BATT_DISP_LIST[_settings.batt_ind]))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_id", self.idtx_msg,
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_settings.ptt_id]))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_delay", self.pttdly_msg,
                          RadioSettingValueMap(PTTDELAY_TIMES,
                                               _settings.ptt_delay))
        cfg_grp.append(rs)

        rs = RadioSetting("dtmf_st", "DTMF Sidetone - menu 31",
                          RadioSettingValueList(DTMFST_LIST,
                                                DTMFST_LIST[_settings.
                                                            dtmf_st]))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_tx_time", "DTMF Transmit Time",
                          RadioSettingValueMap(DTMF_TIMES,
                                               _settings.dtmf_tx_time))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_interval", "DTMF Interval Time",
                          RadioSettingValueMap(DTMF_TIMES,
                                               _settings.dtmf_interval))
        cfg_grp.append(rs)
        rs = RadioSetting("ring_time", "Ring Time - menu 35",
                          RadioSettingValueList(LIST_10S,
                                                LIST_10S[_settings.ring_time]))
        cfg_grp.append(rs)
        rs = RadioSetting("alert", "Alert Tone - menu 36",
                          RadioSettingValueList(ALERTS_LIST,
                                                ALERTS_LIST[_settings.alert]))
        cfg_grp.append(rs)

        rs = RadioSetting("autolock", "Autolock - menu 30",
                          RadioSettingValueBoolean(_settings.autolock))
        cfg_grp.append(rs)

        rs = RadioSetting("prich_sw", "Priority Channel Scan - menu 11",
                          RadioSettingValueList(PRICHAN_LIST,
                                                PRICHAN_LIST[
                                                    _settings.prich_sw]))
        cfg_grp.append(rs)
        rs = RadioSetting("pri_ch",
                          "Priority Channel - Can not be empty Channel",
                          RadioSettingValueInteger(1, 999, _settings.pri_ch))
        cfg_grp.append(rs)

        if self.MODEL == "KG-Q10H":
            rs = RadioSetting("rpttype", "Repeater Type - menu 40",
                              RadioSettingValueMap(RPTTYPE_MAP,
                                                   _settings.rpttype))
            cfg_grp.append(rs)

            rs = RadioSetting("rpt_spk", "Repeater SPK - menu 41",
                              RadioSettingValueBoolean(_settings.rpt_spk))
            cfg_grp.append(rs)

            rs = RadioSetting("rpt_ptt", "Repeater PTT - menu 42",
                              RadioSettingValueBoolean(_settings.rpt_ptt))
            cfg_grp.append(rs)

        rs = RadioSetting("rpt_tone",
                          "Repeater Tone - menu %i" % self.rpttonemenu,
                          RadioSettingValueBoolean(_settings.rpt_tone))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_hold", "RPT Hold Time",
                          RadioSettingValueList(
                               HOLD_TIMES, HOLD_TIMES[_settings.rpt_hold]))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_det", "Scan Mode Tone Detect - menu 9",
                          RadioSettingValueBoolean(_settings.scan_det))
        cfg_grp.append(rs)
        rs = RadioSetting("ToneScnSave", "Tone Scan Save - menu 12",
                          RadioSettingValueList(TONESCANSAVELIST,
                                                TONESCANSAVELIST[_settings.
                                                                 ToneScnSave]))
        cfg_grp.append(rs)
        rs = RadioSetting("smuteset", "Sub-Freq Mute (SMUTESET) - menu 38",
                          RadioSettingValueList(SMUTESET_LIST,
                                                SMUTESET_LIST[_settings.
                                                              smuteset]))
        cfg_grp.append(rs)
        # rs = RadioSetting("ani_sw", ani_msg,
        #                   RadioSettingValueBoolean(_settings.ani_sw))
        # cfg_grp.append(rs)

#             rs = RadioSetting("sim_rec", "Simultaneous Receive",
#                               RadioSettingValueBoolean(_settings.sim_rec))
#             cfg_grp.append(rs)

        rs = RadioSetting("disp_time",
                          "Display Time - menu %i" % self.timemenu,
                          RadioSettingValueBoolean(_settings.disp_time))
        cfg_grp.append(rs)
        rs = RadioSetting("time_zone", "Time Zone - menu %i" % self.tzmenu,
                          RadioSettingValueList(
                              TIME_ZONE,
                              TIME_ZONE[_settings.time_zone]))
        cfg_grp.append(rs)
        rs = RadioSetting("GPS", "GPS - menu %i.1" % self.locmenu,
                          RadioSettingValueBoolean(_settings.GPS))
        cfg_grp.append(rs)
        rs = RadioSetting("GPS_send_freq",
                          "GPS Send Frequency - menu %i.2" % self.locmenu,
                          RadioSettingValueList(
                              GPS_SEND_FREQ,
                              GPS_SEND_FREQ[_settings.GPS_send_freq]))
        cfg_grp.append(rs)
        rs = RadioSetting("GPS_rcv", "GPS Receive - menu %i.3" % self.locmenu,
                          RadioSettingValueBoolean(_settings.GPS_rcv))
        cfg_grp.append(rs)

        rs = RadioSetting("stopwatch", "Timer / Stopwatch Enabled - menu 37",
                          RadioSettingValueBoolean(_settings.stopwatch))
        cfg_grp.append(rs)
        rs = RadioSetting("keylock", "Keypad Locked",
                          RadioSettingValueBoolean(_settings.keylock))
        cfg_grp.append(rs)

        rs = RadioSetting("act_area", "Active Area",
                          RadioSettingValueList(
                              ACTIVE_AREA_LIST,
                              ACTIVE_AREA_LIST[_settings.act_area]))
        cfg_grp.append(rs)
        rs = RadioSetting("tdr", "TDR",
                          RadioSettingValueList(
                              TDR_LIST,
                              TDR_LIST[_settings.tdr]))
        cfg_grp.append(rs)

        pswdchars = "0123456789"
        _msg = str(_settings.mode_sw_pwd).split("\0")[0]
        val = RadioSettingValueString(0, 6, _msg, False)
        val.set_mutable(True)
        val.set_charset(pswdchars)
        rs = RadioSetting("mode_sw_pwd", "Mode SW Pwd", val)
        cfg_grp.append(rs)

        _msg = str(_settings.reset_pwd).split("\0")[0]
        val = RadioSettingValueString(0, 6, _msg, False)
        val.set_charset(pswdchars)
        val.set_mutable(True)
        rs = RadioSetting("reset_pwd", "Reset Pwd", val)
        cfg_grp.append(rs)
#         Custom Color Settings
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol1_text)
        rs = RadioSetting("settings.custcol1_text", "Custom 1 - Text",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol1_bg)
        rs = RadioSetting("settings.custcol1_bg", "Custom 1 - Background",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol1_icon)
        rs = RadioSetting("settings.custcol1_icon", "Custom 1 - Icon",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol1_line)
        rs = RadioSetting("settings.custcol1_line", "Custom 1 - Line",
                          val)
        cfg_grp[0].append(rs)

        val = RadioSettingValueRGB.from_rgb16(_settings.custcol2_text)
        rs = RadioSetting("settings.custcol2_text", "     Custom 2 - Text",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol2_bg)
        rs = RadioSetting("settings.custcol2_bg",
                          "     Custom 2 - Background",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol2_icon)
        rs = RadioSetting("settings.custcol2_icon", "     Custom 2 - Icon",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol2_line)
        rs = RadioSetting("settings.custcol2_line", "     Custom 2 - Line",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol3_text)
        rs = RadioSetting("settings.custcol3_text", "Custom 3 - Text",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol3_bg)
        rs = RadioSetting("settings.custcol3_bg", "Custom 3 - Background",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol3_icon)
        rs = RadioSetting("settings.custcol3_icon", "Custom 3 - Icon",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol3_line)
        rs = RadioSetting("settings.custcol3_line", "Custom 3 - Line",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol4_text)
        rs = RadioSetting("settings.custcol4_text",
                          "     Custom 4 - Text",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol4_bg)
        rs = RadioSetting("settings.custcol4_bg",
                          "     Custom 4 - Background",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol4_icon)
        rs = RadioSetting("settings.custcol4_icon",
                          "     Custom 4 - Icon",
                          val)
        cfg_grp[0].append(rs)
        val = RadioSettingValueRGB.from_rgb16(_settings.custcol4_line)
        rs = RadioSetting("settings.custcol4_line",
                          "     Custom 4 - Line",
                          val)
        cfg_grp[0].append(rs)


#         # Key Settings
#         #
        _msg = str(_settings.dispstr).split("\0")[0]
        val = RadioSettingValueString(0, 12, _msg)
        val.set_mutable(True)
        rs = RadioSetting("dispstr",
                          self.dispmesg, val)
        key_grp.append(rs)

        def _decode(lst):
            _str = ''.join([chr(int(c)) for c in lst
                            if chr(int(c)) in chirp_common.CHARSET_ASCII])
            return _str

        _str = _decode(self._memobj.settings.areamsg)
        val = RadioSettingValueString(0, 12, _str)
        val.set_mutable(True)
        rs = RadioSetting("settings.areamsg", self.areamsglabel, val)
        key_grp.append(rs)

        def apply_ani_id(setting, obj):
            c = str2callid(setting.value)
            obj.ani_id = c

        cid = self._memobj.settings
        my_callid = RadioSettingValueString(3, 6,
                                            self.callid2str(cid.ani_id),
                                            False)
        rs = RadioSetting("ani_id", "Radio ID", my_callid)
        rs.set_apply_callback(apply_ani_id, cid)
        key_grp.append(rs)

        stun = self._memobj.settings
        st = RadioSettingValueString(0, 6, digits2str(stun.scc), False)
        rs = RadioSetting("scc", "Control code", st)
        rs.set_apply_callback(apply_scc, stun)
        key_grp.append(rs)

        rs = RadioSetting("ptt1", "PTT1 Key function",
                          RadioSettingValueList(
                              PTT_LIST,
                              PTT_LIST[_settings.ptt1]))
        key_grp.append(rs)
        rs = RadioSetting("ptt2", "PTT2 Key function",
                          RadioSettingValueList(
                              PTT_LIST,
                              PTT_LIST[_settings.ptt2]))
        key_grp.append(rs)
        rs = RadioSetting("top_short", "TOP SHORT Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.top_short]))
        key_grp.append(rs)
        rs = RadioSetting("top_long", "TOP LONG Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.top_long]))
        key_grp.append(rs)

        rs = RadioSetting("pf1_short", "PF1 SHORT Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.pf1_short]))
        key_grp.append(rs)
        rs = RadioSetting("pf1_long", "PF1 LONG Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.pf1_long]))
        key_grp.append(rs)
        rs = RadioSetting("pf2_short", "PF2 SHORT Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.pf2_short]))
        key_grp.append(rs)
        rs = RadioSetting("pf2_long", "PF2 LONG Key function",
                          RadioSettingValueList(
                              self._prog_key,
                              self._prog_key[_settings.pf2_long]))
        key_grp.append(rs)

# #       SCAN GROUP settings
        rs = RadioSetting("settings.vfo_scanmodea", "VFO A Scan Mode",
                          RadioSettingValueList(
                              VFO_SCANMODE_LIST,
                              VFO_SCANMODE_LIST[_settings.vfo_scanmodea]))
        scanv_grp.append(rs)
        rs = RadioSetting("vfo_scan.vfo_scan_start_A",
                          "     VFO A Scan Start (MHz)",
                          RadioSettingValueInteger(
                              1, 999, _vfo_scan.vfo_scan_start_A))
        scanv_grp.append(rs)
        rs = RadioSetting("vfo_scan.vfo_scan_end_A",
                          "     VFO A Scan End (MHz)",
                          RadioSettingValueInteger(
                              1, 999, _vfo_scan.vfo_scan_end_A))
        scanv_grp.append(rs)
        rs = RadioSetting("settings.vfo_scanmodeb", "VFO B Scan Mode",
                          RadioSettingValueList(
                              VFO_SCANMODE_LIST,
                              VFO_SCANMODE_LIST[_settings.vfo_scanmodeb]))
        scanv_grp.append(rs)
        rs = RadioSetting("vfo_scan.vfo_scan_start_B",
                          "     VFO B Scan Start (MHz)",
                          RadioSettingValueInteger(
                              1, 999, _vfo_scan.vfo_scan_start_B))
        scanv_grp.append(rs)
        rs = RadioSetting("vfo_scan.vfo_scan_end_B",
                          "     VFO B Scan End (MHz)",
                          RadioSettingValueInteger(
                              1, 999, _vfo_scan.vfo_scan_end_B))
        scanv_grp.append(rs)

        # VFO A Settings
        #
        wml = self.workmodelist
        rs = RadioSetting("work_mode_a", self.vfo_area + "A Workmode",
                          RadioSettingValueList(wml,
                                                wml[_settings.work_mode_a]))
        vfoa_grp.append(rs)
        rs = RadioSetting("work_ch_a", self.vfo_area + "A Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.work_ch_a))
        vfoa_grp.append(rs)
        for i in range(0, 6):
            rs = RadioSetting("vfoa[%i].rxfreq" % i,
                              self.vfo_area + "A Rx Frequency (MHz)",
                              RadioSettingValueFloat(
                                  0.00000, 999.999999,
                                  (_vfoa[i].rxfreq / 100000.0),
                                  0.000001, 6))
            vfoa_grp[i].append(rs)
            if self.MODEL == "KG-Q10H":
                rs = RadioSetting("vfoa[%i].offset" % i,
                                  self.vfo_area + "A Offset (MHz)",
                                  RadioSettingValueFloat(
                                      0.00000, 599.999999,
                                      (_vfoa[i].offset / 100000.0),
                                      0.000001, 6))
                vfoa_grp[i].append(rs)

            rs = RadioSetting("vfoa[%i].rxtone" % i,
                              self.vfo_area + "A Rx tone",
                              RadioSettingValueMap(
                                TONE_MAP, _vfoa[i].rxtone))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].txtone" % i,
                              self.vfo_area + "A Tx tone",
                              RadioSettingValueMap(
                                  TONE_MAP, _vfoa[i].txtone))
            vfoa_grp[i].append(rs)

#         # MRT - AND power with 0x03 to display only the lower 2 bits for
#         # power level and to clear the upper bits
#         # MRT - any bits set in the upper 2 bits will cause radio to show
#         # invalid values for power level and a display glitch
#         # MRT - when PTT is pushed
            _vfoa[i].power = _vfoa[i].power & 0x3
            if _vfoa[i].power > 3:
                _vfoa[i].power = 3
            rs = RadioSetting("vfoa[%i].power" % i, self.vfo_area + "A Power",
                              RadioSettingValueList(
                                  POWER_LIST, POWER_LIST[_vfoa[i].power]))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].iswide" % i,
                              self.vfo_area + "A Wide/Narrow",
                              RadioSettingValueList(
                                  BANDWIDTH_LIST,
                                  BANDWIDTH_LIST[_vfoa[i].iswide]))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].mute_mode" % i,
                              self.vfo_area + "A Mute (SP Mute)",
                              RadioSettingValueList(
                                  SPMUTE_LIST,
                                  SPMUTE_LIST[_vfoa[i].mute_mode]))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].ofst_dir" % i,
                              self.vfo_area + self._offset_dir_rpt_label,
                              RadioSettingValueList(
                                  self._offset_dir_rpt,
                                  self._offset_dir_rpt[_vfoa[i].ofst_dir]))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].scrambler" % i,
                              self.vfo_area + "A Scramble/Descramble",
                              RadioSettingValueList(
                                  SCRAMBLE_LIST,
                                  SCRAMBLE_LIST[_vfoa[i].scrambler]))
            vfoa_grp[i].append(rs)

            rs = RadioSetting("vfoa[%i].compander" % i,
                              self.vfo_area + "A Compander",
                              RadioSettingValueList(
                                  ONOFF_LIST, ONOFF_LIST[_vfoa[i].compander]))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].call_group" % i,
                              self.vfo_area + "A Call Group",
                              RadioSettingValueInteger(
                                  1, 99, _vfoa[i].call_group))
            vfoa_grp[i].append(rs)
            rs = RadioSetting("vfoa[%i].am_mode" % i,
                              self.vfo_area + "A AM Mode",
                              RadioSettingValueList(
                                  self.am_mode_list,
                                  self.am_mode_list[_vfoa[i].am_mode]))
            vfoa_grp[i].append(rs)

        rs = RadioSetting("settings.vfostepA", self.vfo_area + "A Step (kHz)",
                          RadioSettingValueList(
                              steps, steps[_settings.vfostepA]))
        vfoa_grp.append(rs)
        rs = RadioSetting("settings.squelchA", self.vfo_area + "A Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_settings.squelchA]))
        vfoa_grp.append(rs)
        rs = RadioSetting("BCL_A", "Busy Channel Lock-out A",
                          RadioSettingValueBoolean(_settings.BCL_A))
        vfoa_grp.append(rs)
        rs = RadioSetting("settings.vfobandA", "VFO A Current Band",
                          RadioSettingValueMap(self._vfoaband,
                                               _settings.vfobandA))
        vfoa_grp.append(rs)

#         # VFO B Settings
        wml = self.workmodelist
        rs = RadioSetting("work_mode_b", self.vfo_area + "B Workmode",
                          RadioSettingValueList(wml,
                                                wml[_settings.work_mode_b]))
        vfob_grp.append(rs)
        rs = RadioSetting("work_ch_b", self.vfo_area + "B Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.work_ch_b))
        vfob_grp.append(rs)
        for i in range(0, 2):
            rs = RadioSetting("vfob[%i].rxfreq" % i,
                              self.vfo_area + "B Rx Frequency (MHz)",
                              RadioSettingValueFloat(
                                  0.00000, 999.999999,
                                  (_vfob[i].rxfreq / 100000.0),
                                  0.000001, 6))
            vfob_grp[i].append(rs)
            if self.MODEL == "KG-Q10H":
                rs = RadioSetting("vfob[%i].offset" % i,
                                  self.vfo_area + "B Offset (MHz)",
                                  RadioSettingValueFloat(
                                      0.00000, 599.999999,
                                      (_vfob[i].offset / 100000.0),
                                      0.000001, 6))
                vfob_grp[i].append(rs)

            rs = RadioSetting("vfob[%i].rxtone" % i,
                              self.vfo_area + "B Rx tone",
                              RadioSettingValueMap(
                                  TONE_MAP, _vfob[i].rxtone))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].txtone" % i,
                              self.vfo_area + "B Tx tone",
                              RadioSettingValueMap(
                                  TONE_MAP, _vfob[i].txtone))
            vfob_grp[i].append(rs)

#         # MRT - AND power with 0x03 to display only the lower 2 bits for
#         # power level and to clear the upper bits
#         # MRT - any bits set in the upper 2 bits will cause radio to show
#         # invalid values for power level and a display glitch
#         # MRT - when PTT is pushed
            _vfob[i].power = _vfob[i].power & 0x3
            if _vfob[i].power > 3:
                _vfob[i].power = 3
            rs = RadioSetting("vfob[%i].power" % i,
                              self.vfo_area + "B Power",
                              RadioSettingValueList(
                                  POWER_LIST, POWER_LIST[_vfob[i].power]))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].iswide" % i,
                              self.vfo_area + "B Wide/Narrow",
                              RadioSettingValueList(
                                  BANDWIDTH_LIST,
                                  BANDWIDTH_LIST[_vfob[i].iswide]))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].mute_mode" % i,
                              self.vfo_area + "B Mute (SP Mute)",
                              RadioSettingValueList(
                                  SPMUTE_LIST,
                                  SPMUTE_LIST[_vfob[i].mute_mode]))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].ofst_dir" % i,
                              self.vfo_area + self._offset_dir_rpt_label,
                              RadioSettingValueList(
                                  self._offset_dir_rpt,
                                  self._offset_dir_rpt[_vfob[i].ofst_dir]))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].scrambler" % i,
                              self.vfo_area + "B Scramble/Descramble",
                              RadioSettingValueList(
                                  SCRAMBLE_LIST,
                                  SCRAMBLE_LIST[_vfob[i].scrambler]))
            vfob_grp[i].append(rs)

            rs = RadioSetting("vfob[%i].compander" % i,
                              self.vfo_area + "B Compander",
                              RadioSettingValueList(
                                  ONOFF_LIST, ONOFF_LIST[_vfob[i].compander]))
            vfob_grp[i].append(rs)
            rs = RadioSetting("vfob[%i].call_group" % i,
                              self.vfo_area + "B Call Group",
                              RadioSettingValueInteger(
                                  1, 99, _vfob[i].call_group))
            vfob_grp[i].append(rs)

        rs = RadioSetting("settings.vfostepB", self.vfo_area + "B Step (kHz)",
                          RadioSettingValueList(
                              steps, steps[_settings.vfostepB]))
        vfob_grp.append(rs)
        rs = RadioSetting("settings.squelchB", self.vfo_area + "B Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_settings.squelchB]))
        vfob_grp.append(rs)
        rs = RadioSetting("BCL_B", "Busy Channel Lock-out B",
                          RadioSettingValueBoolean(_settings.BCL_B))
        vfob_grp.append(rs)
        rs = RadioSetting("settings.vfobandB", "VFO B Current Band",
                          RadioSettingValueMap(VFOBBAND_MAP,
                                               _settings.vfobandB))
        vfob_grp.append(rs)

        # FM RADIO PRESETS

        # memory stores raw integer value like 760
        # radio will divide 760 by 10 and interpret correctly at 76.0Mhz
        for i in range(1, 21):
            chan = str(i)
            s = i-1
            rs = RadioSetting("fm[%s].FM_radio" % s, "FM Preset " + chan,
                              RadioSettingValueFloat(76.0, 108.0,
                                                     _fm[i-1].FM_radio / 10.0,
                                                     0.1, 1))
            fmradio_grp.append(rs)

        if self.show_limits:
            lim = self._memobj.limits
            rs = RadioSetting("limits.m2tx_start",
                              "2M TX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  118.000000, 299.999999,
                                  (lim.m2tx_start / 100000.0),
                                  0.000001, 6))

            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.m2tx_stop",
                              "2M TX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  118.000000, 299.999999,
                                  (lim.m2tx_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.tworx_start",
                              "2M TX SUPER Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  108.000000, 299.999999,
                                  (lim.tworx_start / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.tworx_stop",
                              "2M TX SUPER Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  108.000000, 299.999999,
                                  (lim.tworx_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)

            rs = RadioSetting("limits.cm70_tx_start",
                              "70cm TX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  300.000000, 999.999999,
                                  (lim.cm70_tx_start / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.cm70_tx_stop",
                              "70cm TX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  300.000000, 999.999999,
                                  (lim.cm70_tx_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.m125_tx_start",
                              "1.25M TX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  200.000000, 299.999999,
                                  (lim.m125_tx_start / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.m125_tx_stop",
                              "1.25M TX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  200.000000, 299.999999,
                                  (lim.m125_tx_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.m6_tx_start",
                              "6M TX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  26.000000, 99.999999,
                                  (lim.m6_tx_start / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.m6_tx_stop",
                              "6M TX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  26.000000, 99.999999,
                                  (lim.m6_tx_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.rx1lim_start",
                              "2M Area A RX Lower Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  108.000000, 299.999999,
                                  (lim.rx1lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx1lim_stop",
                              "2M Area A RX Upper Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx1lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx7lim_start",
                              "2M Area B RX Lower Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  136.000000, 999.999999,
                                  (lim.rx7lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx7lim_stop",
                              "2M Area B RX Upper Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx7lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx12lim_start",
                              "2m Area A SUPER Rx Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx12lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx12lim_stop",
                              "2m Area A SUPER Rx Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx12lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx18lim_start",
                              "2m Area B SUPER Rx Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx18lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx18lim_stop",
                              "2m Area B SUPER Rx Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx18lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx13lim_start",
                              "70cm Area A SUPER Rx Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx13lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx13lim_stop",
                              "70cm Area A SUPER Rx Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx13lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx2lim_start",
                              "70cm Area A RX Lower Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx2lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx2lim_stop",
                              "70cm Area A RX Upper Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx2lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx8lim_start",
                              "70cm Area B RX Lower Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx8lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx8lim_stop",
                              "70cm Area B RX Upper Limit (MHz) - Verified",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx8lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx19lim_start",
                              "70cm Area B SUPER RX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx19lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx19lim_stop",
                              "70cm Area B SUPER RX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx19lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx3lim_start",
                              "1.25m RX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx3lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx3lim_stop",
                              "1.25m RX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx3lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx4lim_start",
                              "6M RX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx4lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx4lim_stop",
                              "6M RX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx4lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx5lim_start",
                              "800MHz Rz Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx5lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx5lim_stop",
                              "800MHz Rz Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx5lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx6lim_start",
                              "rx6_start Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx6lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx6lim_stop",
                              "rx6_stop Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx6lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx10lim_start",
                              "70cm Area B TX Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx10lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.rx10lim_stop",
                              "70cm Area B TX Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx10lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp[0].append(rs)
            rs = RadioSetting("limits.rx14lim_start",
                              "rx14lim_start Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx14lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx14lim_stop",
                              "rx14lim_stop Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx14lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx15lim_start",
                              "rx15lim_start Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx15lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx15lim_stop",
                              "rx15lim_stop Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx15lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx16lim_start",
                              "rx16lim_start Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx16lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx16lim_stop",
                              "rx16lim_stop Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx16lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx17lim_start",
                              "rx17lim_start Lower Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx17lim_start / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            rs = RadioSetting("limits.rx17lim_stop",
                              "rx17lim_stop Upper Limit (MHz)",
                              RadioSettingValueFloat(
                                  0.000000, 999.999999,
                                  (lim.rx17lim_stop / 100000.0),
                                  0.000001, 6))
            lmt_grp.append(rs)
            for i in range(0, 14):
                s = self._memobj.limits.more_limits[i]
                rs = RadioSetting("limits.more_limits[%i].lim_start" % i,
                                  "More %i Lower Limit (MHz)" % i,
                                  RadioSettingValueFloat(
                                      0.000000, 999.999999,
                                      (s.lim_start / 100000.0),
                                      0.000001, 6))
                lmt_grp.append(rs)
                rs = RadioSetting("limits.more_limits[%i].lim_stop" % i,
                                  "More %i Upper Limit (MHz)" % i,
                                  RadioSettingValueFloat(
                                      0.000000, 999.999999,
                                      (s.lim_stop / 100000.0),
                                      0.000001, 6))
                lmt_grp.append(rs)

        # # OEM info

        def _decode(lst):
            _str = ''.join([chr(int(c)) for c in lst
                            if chr(int(c)) in chirp_common.CHARSET_ASCII])
            return _str

        def do_nothing(setting, obj):
            return

        _str = _decode(self._memobj.oem_info.oem1)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.oem1", "OEM String 1", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)
        # if self.MODEL == "KG-Q10H" :
        _str = _decode(self._memobj.oem_info.name)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.name", "Radio Model", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)

        _str = _decode(self._memobj.oem_info.firmware)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.firmware", "Firmware Version", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)

        _str = _decode(self._memobj.oem_info.date)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.date", "OEM Date", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)
        if self.MODEL == "KG-Q10H":
            rs = RadioSetting("oem_info.locked", "OEM Lock Mode -"
                              " Tx/Rx Range Locked to factory settings",
                              RadioSettingValueBoolean(
                                  self._memobj.oem_info.locked))
            oem_grp.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except Exception:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "[" in bit and "]" in bit:
                                bit, index = bit.split("[", 1)
                                index, junk = index.split("]", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        element.run_apply_callback()
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        if self._is_freq(element):
                            # MRT rescale freq values to match radio
                            # expected values
                            setattr(obj, setting,
                                    int(element.values()[0]._current *
                                        100000.0))
                        elif self._is_fmradio(element):
                            # MRT rescale FM Radio values to match radio
                            # expected values
                            setattr(obj, setting,
                                    int(element.values()[0]._current * 10.0))
                        elif self._is_color(element):
                            setattr(obj, setting,
                                    RadioSettingValueRGB.get_rgb16(
                                        element.value))
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _is_freq(self, element):
        return ("rxfreq" in element.get_name() or
                "offset" in element.get_name() or
                "rx_start" in element.get_name() or
                "rx_stop" in element.get_name() or
                "lim_start" in element.get_name() or
                "lim_stop" in element.get_name() or
                "tx_start" in element.get_name() or
                "tx_stop" in element.get_name())

    def _is_color(self, element):
        return "custcol" in element.get_name()

    def _is_fmradio(self, element):
        return "FM_radio" in element.get_name()

    def callid2str(self, cid):
        """Caller ID per MDC-1200 spec? Must be 3-6 digits (100 - 999999).
        One digit (binary) per byte, terminated with '0xc'
        """

        bin2ascii = "0123456789"
        cidstr = ""
        for i in range(0, 6):
            b = cid[i].get_value()
            # Handle fluky firmware 0x0a is sometimes used instead of 0x00
            if b == 0x0a:
                b = 0x00
            if b == 0xc or b == 0xf:  # the cid EOL
                break
            if b > 0xa:
                raise InvalidValueError(
                    "Caller ID code has illegal byte 0x%x" % b)
            cidstr += bin2ascii[b]
        return cidstr

    def _checksum2(self, data):
        cs = 0
        cs_adj = 0
        for byte in data:
            cs += byte
        cs %= 256
        cs_adj = (data[3] & 0x0F) % 4
        if cs_adj == 0:
            cs += 3
        elif cs_adj == 1:
            cs += 1
        elif cs_adj == 2:
            cs -= 1
        elif cs_adj == 3:
            cs -= 3
        return (cs & 0xFF)

    def _checksum_adjust(self, data):
        cs_mod = 0
        cs_adj = 0
        cs_adj = (data & 0x0F) % 4
        if cs_adj == 0:
            cs_mod = 3
        elif cs_adj == 1:
            cs_mod = 1
        elif cs_adj == 2:
            cs_mod = -1
        elif cs_adj == 3:
            cs_mod = -3
        return (cs_mod)

    def _write_record(self, cmd, payload=b''):
        _packet = struct.pack('BBBB', self._record_start, cmd, 0xFF,
                              len(payload))
        LOG.debug("Sent: Unencrypt\n%s" % util.hexprint(_packet + payload))
        checksum = bytes([self._checksum2(_packet[1:] + payload)])
        _packet += self.encrypt(payload + checksum)
        LOG.debug("Sent:\n%s" % util.hexprint(_packet))
        self.pipe.write(_packet)
        time.sleep(0.000005)

    def _identify(self):
        """Wouxun CPS sends the same Read command 3 times to establish comms"""
        """Read Resp and check radio model in prep for actual download"""
        LOG.debug("Starting Radio Identifcation")

        for i in range(0, 3):
            ident = struct.pack(
                'BBBBBBBB', 0x7c, 0x82, 0xff, 0x03, 0x54, 0x14, 0x54, 0x53)
            self.pipe.write(ident)
        _chksum_err, _resp = self._read_record()
        _radio_id = _resp[46:53]
        self._RADIO_ID = _radio_id
        LOG.debug("Radio Identified as Model %s" % _radio_id)
        if _chksum_err:
            LOG.debug(util.hexprint(_resp))
            raise errors.RadioError("Checksum Error on Identify")
        elif _radio_id != self._model:
            self._finish()
            raise errors.RadioError("Radio identified as Model: %s \n"
                                    "You selected Model: %s.\n"
                                    # "Please select the correct radio model"
                                    # " to continue"
                                    "Your Model is not currently supported"
                                    % (_radio_id.decode('UTF-8'),
                                       self._model.decode('UTF-8')))
        LOG.debug("Ending Radio Identifcation")

    def _download(self):
        try:
            self._identify()
            return self._do_download()
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _do_download(self):
        LOG.debug("Starting Download")
        # allocate & fill memory
        image = b""
        # Download full memory in 0x0000 to 0x8000 address order
        # it will be rearranged later
        cfgmap = Q10H_download_map_full

        for start, blocksize, count in cfgmap:
            end = start + (blocksize * count)
            LOG.debug("start = " + str(start))
            LOG.debug("end = " + str(end))
            LOG.debug("blksize = " + str(blocksize))

            for i in range(start, end, blocksize):
                time.sleep(0.005)
                req = struct.pack('>HB', i, blocksize)
                self._write_record(CMD_RD, req)
                cs_error, resp = self._read_record()
                if cs_error:
                    LOG.debug(util.hexprint(resp))
                    raise Exception("Checksum error on read")
                LOG.debug("Got:\n%s" % util.hexprint(resp))
                image += resp[2:]
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = i
                    status.max = 0x8000
                    status.msg = "Cloning from radio"
                    self.status_fn(status)
        self._finish()
        LOG.debug("Download Completed")
        return memmap.MemoryMapBytes(image)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)

        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond \n'
                                    'Confirm proper radio selection \n'
                                    'Confirm radio is Powered On and '
                                    'programming cable is fully inserted')
        _length = struct.unpack('xxxB', _header)[0]
        _packet = self.pipe.read(_length)

        _rcs_xor = _packet[-1]
        _packet = self.decrypt(_packet)
        LOG.debug("Header =%a" % util.hexprint(_header + _packet[0:2]))
        _cs = self._checksum(_header[1:])
        _cs += self._checksum(_packet)
        _csa = self._checksum_adjust(_packet[0])
        LOG.debug("_cs (preadjusted)=%x", _cs & 0xff)
        _cs += _csa
        _cs = _cs & 0xFF
        _rcs = self.strxor(self.pipe.read(1)[0], _rcs_xor)[0]
        LOG.debug("_csa=%x", _csa)
        LOG.debug("_cs (adjusted)=%x", _cs)
        LOG.debug("_rcs=%x", _rcs)
        return (_rcs != _cs, _packet)

    def _finish(self):
        # this is the encrypted finish command sent by Q10H CPS
        finish = struct.pack('BBBBB', 0x7c, 0x81, 0xff, 0x00, 0xd7)
        self.pipe.write(finish)
        return

    def decrypt(self, data):
        result = b''
        for i in range(len(data)-1, 0, -1):
            result += self.strxor(data[i], data[i - 1])
        result += self.strxor(data[0], self.cryptbyte)
        return result[::-1]

    def encrypt(self, data):
        result = self.strxor(self.cryptbyte, data[0])
        for i in range(1, len(data), 1):
            result += self.strxor(result[i - 1], data[i])
        return result
