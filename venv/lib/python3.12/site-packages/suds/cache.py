# This program is free software; you can redistribute it and/or modify it under
# the terms of the (LGPL) GNU Lesser General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Library Lesser General Public License
# for more details at ( http://www.gnu.org/licenses/lgpl.html ).
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# written by: Jeff Ortel ( jortel@redhat.com )

"""
Basic caching classes.

"""

import suds
import suds.sax.element
import suds.sax.parser

import datetime
import os
try:
    import pickle as pickle
except Exception:
    import pickle
import shutil
import tempfile

from logging import getLogger
log = getLogger(__name__)


class Cache(object):
    """An object cache."""

    def get(self, id):
        """
        Get an object from the cache by id.

        @param id: The object id.
        @type id: str
        @return: The object, else None.
        @rtype: any

        """
        raise Exception("not-implemented")

    def put(self, id, object):
        """
        Put an object into the cache.

        @param id: The object id.
        @type id: str
        @param object: The object to add.
        @type object: any

        """
        raise Exception("not-implemented")

    def purge(self, id):
        """
        Purge an object from the cache by id.

        @param id: A object id.
        @type id: str

        """
        raise Exception("not-implemented")

    def clear(self):
        """Clear all objects from the cache."""
        raise Exception("not-implemented")


class NoCache(Cache):
    """The pass-through object cache."""

    def get(self, id):
        return

    def put(self, id, object):
        pass


class FileCache(Cache):
    """
    A file-based URL cache.

    @cvar fnprefix: The file name prefix.
    @type fnprefix: str
    @cvar remove_default_location_on_exit: Whether to remove the default cache
        location on process exit (default=True).
    @type remove_default_location_on_exit: bool
    @ivar duration: The duration after which cached entries expire (0=never).
    @type duration: datetime.timedelta
    @ivar location: The cached file folder.
    @type location: str

    """
    fnprefix = "suds"
    __default_location = None
    remove_default_location_on_exit = True

    def __init__(self, location=None, **duration):
        """
        Initialized a new FileCache instance.

        If no cache location is specified, a temporary default location will be
        used. Such default cache location will be shared by all FileCache
        instances with no explicitly specified location within the same
        process. The default cache location will be removed automatically on
        process exit unless user sets the remove_default_location_on_exit
        FileCache class attribute to False.

        @param location: The cached file folder.
        @type location: str
        @param duration: The duration after which cached entries expire
            (default: 0=never).
        @type duration: keyword arguments for datetime.timedelta constructor

        """
        if location is None:
            location = self.__get_default_location()
        self.location = location
        self.duration = datetime.timedelta(**duration)
        self.__check_version()

    def clear(self):
        for filename in os.listdir(self.location):
            path = os.path.join(self.location, filename)
            if os.path.isdir(path):
                continue
            if filename.startswith(self.fnprefix):
                os.remove(path)
                log.debug("deleted: %s", path)

    def fnsuffix(self):
        """
        Get the file name suffix.

        @return: The suffix.
        @rtype: str

        """
        return "gcf"

    def get(self, id):
        try:
            f = self._getf(id)
            try:
                return f.read()
            finally:
                f.close()
        except Exception:
            pass

    def purge(self, id):
        filename = self.__filename(id)
        try:
            os.remove(filename)
        except Exception:
            pass

    def put(self, id, data):
        try:
            filename = self.__filename(id)
            f = self.__open(filename, "wb")
            try:
                f.write(data)
            finally:
                f.close()
            return data
        except Exception:
            log.debug(id, exc_info=1)
            return data

    def _getf(self, id):
        """Open a cached file with the given id for reading."""
        try:
            filename = self.__filename(id)
            self.__remove_if_expired(filename)
            return self.__open(filename, "rb")
        except Exception:
            pass

    def __check_version(self):
        path = os.path.join(self.location, "version")
        try:
            f = self.__open(path)
            try:
                version = f.read()
            finally:
                f.close()
            if version != suds.__version__:
                raise Exception()
        except Exception:
            self.clear()
            f = self.__open(path, "w")
            try:
                f.write(suds.__version__)
            finally:
                f.close()

    def __filename(self, id):
        """Return the cache file name for an entry with a given id."""
        suffix = self.fnsuffix()
        filename = "%s-%s.%s" % (self.fnprefix, id, suffix)
        return os.path.join(self.location, filename)

    @staticmethod
    def __get_default_location():
        """
        Returns the current process's default cache location folder.

        The folder is determined lazily on first call.

        """
        if not FileCache.__default_location:
            tmp = tempfile.mkdtemp("suds-default-cache")
            FileCache.__default_location = tmp
            import atexit
            atexit.register(FileCache.__remove_default_location)
        return FileCache.__default_location

    def __mktmp(self):
        """Create the I{location} folder if it does not already exist."""
        try:
            if not os.path.isdir(self.location):
                os.makedirs(self.location)
        except Exception:
            log.debug(self.location, exc_info=1)
        return self

    def __open(self, filename, *args):
        """Open cache file making sure the I{location} folder is created."""
        self.__mktmp()
        return open(filename, *args)

    @staticmethod
    def __remove_default_location():
        """
        Removes the default cache location folder.

        This removal may be disabled by setting the
        remove_default_location_on_exit FileCache class attribute to False.

        """
        if FileCache.remove_default_location_on_exit:
            # We must not load shutil here on-demand as under some
            # circumstances this may cause the shutil.rmtree() operation to
            # fail due to not having some internal module loaded. E.g. this
            # happens if you run the project's test suite using the setup.py
            # test command on Python 2.4.x.
            shutil.rmtree(FileCache.__default_location, ignore_errors=True)

    def __remove_if_expired(self, filename):
        """
        Remove a cached file entry if it expired.

        @param filename: The file name.
        @type filename: str

        """
        if not self.duration:
            return
        created = datetime.datetime.fromtimestamp(os.path.getctime(filename))
        expired = created + self.duration
        if expired < datetime.datetime.now():
            os.remove(filename)
            log.debug("%s expired, deleted", filename)


class DocumentCache(FileCache):
    """XML document file cache."""

    def fnsuffix(self):
        return "xml"

    def get(self, id):
        fp = None
        try:
            fp = self._getf(id)
            if fp is not None:
                p = suds.sax.parser.Parser()
                cached = p.parse(fp)
                fp.close()
                return cached
        except Exception:
            if fp is not None:
                fp.close()
            self.purge(id)

    def put(self, id, object):
        if isinstance(object,
                (suds.sax.document.Document, suds.sax.element.Element)):
            super(DocumentCache, self).put(id, suds.byte_str(str(object)))
        return object


class ObjectCache(FileCache):
    """
    Pickled object file cache.

    @cvar protocol: The pickling protocol.
    @type protocol: int

    """
    protocol = 2

    def fnsuffix(self):
        return "px"

    def get(self, id):
        fp = None
        try:
            fp = self._getf(id)
            if fp is not None:
                cached = pickle.load(fp)
                fp.close()
                return cached
        except Exception:
            if fp is not None:
                fp.close()
            self.purge(id)

    def put(self, id, object):
        data = pickle.dumps(object, self.protocol)
        super(ObjectCache, self).put(id, data)
        return object
