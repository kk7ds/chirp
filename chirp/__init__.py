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

import os
import sys
from glob import glob

CHIRP_VERSION = "0.3.0dev"

module_dir = os.path.dirname(sys.modules["chirp"].__file__)
__all__ = []
for i in glob(os.path.join(module_dir, "*.py")):
    name = os.path.basename(i)[:-3]
    if not name.startswith("__"):
        __all__.append(name)
