import os
import sys
from glob import glob

module_dir = os.path.dirname(sys.modules["chirp.drivers"].__file__)
__all__ = []
for i in sorted(glob(os.path.join(module_dir, "*.py"))):
    name = os.path.basename(i)[:-3]
    if not name.startswith("__"):
        __all__.append(name)
