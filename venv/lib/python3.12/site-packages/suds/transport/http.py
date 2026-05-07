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
Basic HTTP transport implementation classes.

"""

from suds.properties import Unskin
from suds.transport import *

import base64
from http.cookiejar import CookieJar
import http.client
import socket
import sys
import urllib.request, urllib.error, urllib.parse
import gzip
import zlib

from logging import getLogger
log = getLogger(__name__)


class HttpTransport(Transport):
    """
    Basic HTTP transport implemented using using urllib2, that provides for
    cookies & proxies but no authentication.

    """

    def __init__(self, **kwargs):
        """
        @param kwargs: Keyword arguments.
            - B{proxy} - An HTTP proxy to be specified on requests.
                 The proxy is defined as {protocol:proxy,}
                    - type: I{dict}
                    - default: {}
            - B{timeout} - Set the URL open timeout (seconds).
                    - type: I{float}
                    - default: 90

        """
        Transport.__init__(self)
        Unskin(self.options).update(kwargs)
        self.cookiejar = CookieJar()
        self.proxy = {}
        self.urlopener = None

    def open(self, request):
        try:
            url = self.__get_request_url_for_urllib(request)
            headers = request.headers
            log.debug('opening (%s)', url)
            u2request = urllib.request.Request(url, headers=headers)
            self.proxy = self.options.proxy
            return self.u2open(u2request)
        except urllib.error.HTTPError as e:
            raise TransportError(str(e), e.code, e.fp)

    def send(self, request):
        url = self.__get_request_url_for_urllib(request)
        msg = request.message
        headers = request.headers
        if 'Content-Encoding' in headers:
            encoding = headers['Content-Encoding']
            if encoding == 'gzip':
                msg = gzip.compress(msg)
            elif encoding == 'deflate':
                msg = zlib.compress(msg)
        try:
            u2request = urllib.request.Request(url, msg, headers)
            self.addcookies(u2request)
            self.proxy = self.options.proxy
            request.headers.update(u2request.headers)
            log.debug('sending:\n%s', request)
            fp = self.u2open(u2request, timeout=request.timeout)
            self.getcookies(fp, u2request)
            headers = fp.headers
            if sys.version_info < (3, 0):
                headers = headers.dict
            message = fp.read()
            if 'Content-Encoding' in headers:
                encoding = headers['Content-Encoding']
                if encoding == 'gzip':
                    message = gzip.decompress(message)
                elif encoding == 'deflate':
                    message = zlib.decompress(message)
            reply = Reply(http.client.OK, headers, message)
            log.debug('received:\n%s', reply)
            return reply
        except urllib.error.HTTPError as e:
            if e.code not in (http.client.ACCEPTED, http.client.NO_CONTENT):
                raise TransportError(e.msg, e.code, e.fp)

    def addcookies(self, u2request):
        """
        Add cookies in the cookiejar to the request.

        @param u2request: A urllib2 request.
        @rtype: u2request: urllib2.Request.

        """
        self.cookiejar.add_cookie_header(u2request)

    def getcookies(self, fp, u2request):
        """
        Add cookies in the request to the cookiejar.

        @param u2request: A urllib2 request.
        @rtype: u2request: urllib2.Request.

        """
        self.cookiejar.extract_cookies(fp, u2request)

    def u2open(self, u2request, timeout=None):
        """
        Open a connection.

        @param u2request: A urllib2 request.
        @type u2request: urllib2.Request.
        @return: The opened file-like urllib2 object.
        @rtype: fp

        """
        tm = timeout or self.options.timeout
        url = self.u2opener()
        return url.open(u2request, timeout=tm)

    def u2opener(self):
        """
        Create a urllib opener.

        @return: An opener.
        @rtype: I{OpenerDirector}

        """
        if self.urlopener is None:
            return urllib.request.build_opener(*self.u2handlers())
        return self.urlopener

    def u2handlers(self):
        """
        Get a collection of urllib handlers.

        @return: A list of handlers to be installed in the opener.
        @rtype: [Handler,...]

        """
        return [urllib.request.ProxyHandler(self.proxy)]

    def u2ver(self):
        """
        Get the major/minor version of the urllib2 lib.

        @return: The urllib2 version.
        @rtype: float

        """
        try:
            return float('%d.%d' % sys.version_info[:2])
        except Exception as e:
            return 0

    def __deepcopy__(self, memo={}):
        clone = self.__class__()
        p = Unskin(self.options)
        cp = Unskin(clone.options)
        cp.update(p)
        return clone

    @staticmethod
    def __get_request_url_for_urllib(request):
        """
        Returns the given request's URL, properly encoded for use with urllib.

        We expect that the given request object already verified that the URL
        contains ASCII characters only and stored it as a native str value.

        urllib accepts URL information as a native str value and may break
        unexpectedly if given URL information in another format.

        Python 3.x httplib.client implementation must be given a unicode string
        and not a bytes object and the given string is internally converted to
        a bytes object using an explicitly specified ASCII encoding.

        Python 2.7 httplib implementation expects the URL passed to it to not
        be a unicode string. If it is, then passing it to the underlying
        httplib Request object will cause that object to forcefully convert all
        of its data to unicode, assuming that data contains ASCII data only and
        raising a UnicodeDecodeError exception if it does not (caused by simple
        unicode + string concatenation).

        Python 2.4 httplib implementation does not really care about this as it
        does not use the internal optimization present in the Python 2.7
        implementation causing all the requested data to be converted to
        unicode.

        """
        assert isinstance(request.url, str)
        return request.url


class HttpAuthenticated(HttpTransport):
    """
    Provides basic HTTP authentication for servers that do not follow the
    specified challenge/response model. Appends the I{Authorization} HTTP
    header with base64 encoded credentials on every HTTP request.

    """

    def open(self, request):
        self.addcredentials(request)
        return HttpTransport.open(self, request)

    def send(self, request):
        self.addcredentials(request)
        return HttpTransport.send(self, request)

    def addcredentials(self, request):
        credentials = self.credentials()
        if None not in credentials:
            credentials = ':'.join(credentials)
            if sys.version_info < (3, 0):
                encodedString = base64.b64encode(credentials)
            else:
                encodedBytes = base64.urlsafe_b64encode(credentials.encode())
                encodedString = encodedBytes.decode()
            request.headers['Authorization'] = 'Basic %s' % encodedString

    def credentials(self):
        return self.options.username, self.options.password
