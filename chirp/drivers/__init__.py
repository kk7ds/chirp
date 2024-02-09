import sys
import pkgutil

module_dir = sys.modules["chirp.drivers"].__path__
__all__ = []
for i in pkgutil.iter_modules(module_dir):
    __all__.append(i.name)
__all__.sort()
