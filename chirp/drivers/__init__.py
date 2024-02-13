import os
import sys
from glob import glob
import warnings

# This won't be here in the frozen build because we convert this file to
# a static list of driver modules to import.
warnings.filterwarnings('once', category=DeprecationWarning,
                        module=__name__)

module_dir = os.path.dirname(sys.modules["chirp.drivers"].__file__ or '.')
__all__ = []
for i in sorted(glob(os.path.join(module_dir, "*.py"))):
    name = os.path.basename(i)[:-3]
    if not name.startswith("__"):
        __all__.append(name)
