# Copyright 2010 Dan Smith <dsmith@danplanet.com>
# Copyright 2012 Tom Hayward <tom@tomh.us>
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

import glob
import os
import logging
import sys

from chirp import chirp_common, errors

LOG = logging.getLogger(__name__)


def radio_class_id(cls):
    """Return a unique identification string for @cls"""
    ident = "%s_%s" % (cls.VENDOR, cls.MODEL)
    if cls.VARIANT:
        ident += "_%s" % cls.VARIANT
    ident = ident.replace("/", "_")
    ident = ident.replace(" ", "_")
    ident = ident.replace("(", "")
    ident = ident.replace(")", "")
    return ident


ALLOW_DUPS = False


def enable_reregistrations():
    """Set the global flag ALLOW_DUPS=True, which will enable a driver
    to re-register for a slot in the directory without triggering an
    exception"""
    global ALLOW_DUPS
    if not ALLOW_DUPS:
        LOG.info("driver re-registration enabled")
    ALLOW_DUPS = True


def register(cls):
    """Register radio @cls with the directory"""
    global DRV_TO_RADIO
    ident = radio_class_id(cls)
    if ident in list(DRV_TO_RADIO.keys()):
        if ALLOW_DUPS:
            LOG.warn("Replacing existing driver id `%s'" % ident)
        else:
            raise Exception("Duplicate radio driver id `%s'" % ident)
    elif ALLOW_DUPS:
        LOG.info("Registered %s = %s" % (ident, cls.__name__))
    DRV_TO_RADIO[ident] = cls
    RADIO_TO_DRV[cls] = ident

    if not hasattr(cls, '_DETECTED_BY'):
        cls._DETECTED_BY = None

    return cls


def detected_by(manager_class):
    """Mark a class as detected by another class

    This means it may not be offered directly as a choice and instead is added
    to @manager_class's DETECTED_MODELS list and should be returned from
    detect_from_serial() when appropriate.
    """
    assert issubclass(manager_class, chirp_common.CloneModeRadio)

    def wrapper(cls):
        assert issubclass(cls, chirp_common.CloneModeRadio)

        cls._DETECTED_BY = manager_class
        manager_class.detect_model(cls)
        return cls

    return wrapper


DRV_TO_RADIO = {}
RADIO_TO_DRV = {}
AUX_FORMATS = set()


def register_format(name, pattern, readonly=False):
    """Register a named format and file pattern.

    The name and pattern must not exist in the directory already
    (except together). The name should be something like "CSV" or
    "Icom ICF" and the pattern should be a glob like "*.icf".

    Returns a unique name to go in Radio.FORMATS so the UI knows what
    additional formats a driver can read (and write unless readonly is
    set).
    """
    if (name, pattern) not in [(n, p) for n, p, r in AUX_FORMATS]:
        if name in [x[0] for x in AUX_FORMATS]:
            raise Exception('Duplicate format name %r' % name)
    AUX_FORMATS.add((name, pattern, readonly))
    return name


def get_radio(driver):
    """Get radio driver class by identification string"""
    if driver in DRV_TO_RADIO:
        return DRV_TO_RADIO[driver]
    else:
        raise Exception("Unknown radio type `%s'" % driver)


def get_driver(rclass):
    """Get the identification string for a given class"""
    if rclass in RADIO_TO_DRV:
        return RADIO_TO_DRV[rclass]
    elif rclass.__bases__[0] in RADIO_TO_DRV:
        return RADIO_TO_DRV[rclass.__bases__[0]]
    else:
        raise Exception("Unknown radio type `%s'" % rclass)


# This is a mapping table of radio models that have changed in the past.
# ideally we would never do this, but in the case where a radio was added
# as the wrong model name, or a model has to be split, we need to be able
# to open older files and do something intelligent with them.
MODEL_COMPAT = {
    ('Retevis', 'RT-5R'): ('Retevis', 'RT5R'),
    ('Retevis', 'RT-5RV'): ('Retevis', 'RT5RV'),
    ('Signus', 'XTR-5'): ('Cignus', 'XTR-5'),
}


def get_radio_by_image(image_file):
    """Attempt to get the radio class that owns @image_file"""
    if os.path.exists(image_file):
        with open(image_file, "rb") as f:
            filedata = f.read()
    else:
        filedata = b""

    data, metadata = chirp_common.CloneModeRadio._strip_metadata(filedata)

    for rclass in list(DRV_TO_RADIO.values()):
        if not issubclass(rclass, chirp_common.FileBackedRadio):
            continue

        if not metadata:
            # If no metadata, we do the old thing
            try:
                if rclass.match_model(filedata, image_file):
                    return rclass(image_file)
            except Exception as e:
                LOG.error('Radio class %s failed during detection: %s' % (
                    rclass.__name__, e))
                pass

        meta_vendor = metadata.get('vendor')
        meta_model = metadata.get('model')
        meta_variant = metadata.get('variant')

        meta_vendor, meta_model = MODEL_COMPAT.get((meta_vendor, meta_model),
                                                   (meta_vendor, meta_model))

        # If metadata, then it has to match one of the aliases or the parent
        for alias in rclass.ALIASES + [rclass]:
            if (alias.VENDOR == meta_vendor and alias.MODEL == meta_model and
                    (meta_variant is None or alias.VARIANT == meta_variant)):

                class DynamicRadioAlias(rclass):
                    _orig_rclass = rclass
                    VENDOR = meta_vendor
                    MODEL = meta_model
                    VARIANT = metadata.get('variant')

                    def __repr__(self):
                        return repr(self._orig_rclass)

                return DynamicRadioAlias(image_file)

    if metadata:
        ex = errors.ImageMetadataInvalidModel("Unsupported model %s %s" % (
            metadata.get("vendor"), metadata.get("model")))
        ex.metadata = metadata
        raise ex
    else:
        # If we don't find anything else and the file appears to be a CSV
        # file, then explicitly open it with the generic driver so we can
        # get relevant errors instead of just "Unknown file format".
        if image_file.lower().endswith('.csv'):
            rclass = get_radio('Generic_CSV')
            return rclass(image_file)
        raise errors.ImageDetectFailed("Unknown file format")


def import_drivers(limit=None):
    frozen = getattr(sys, 'frozen', False)
    if sys.platform == 'win32' and frozen:
        # We are in a frozen win32 build, so we can not glob
        # the driver files, but we do not need to anyway
        import chirp.drivers
        for module in chirp.drivers.__all__:
            try:
                __import__('chirp.drivers.%s' % module)
            except Exception as e:
                print('Failed to import %s: %s' % (module, e))
        return

    # Safe import of everything in chirp/drivers. We need to import them
    # to get them to register, but should not abort if one import fails
    chirp_module_base = os.path.dirname(os.path.abspath(__file__))
    driver_files = glob.glob(os.path.join(chirp_module_base,
                                          'drivers',
                                          '*.py'))
    for driver_file in driver_files:
        module, ext = os.path.splitext(driver_file)
        driver_module = os.path.basename(module)
        if limit and driver_module not in limit:
            continue
        __import__('chirp.drivers.%s' % driver_module)
