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
Contains transport interface (classes).

"""

from suds import UnicodeMixin

import sys


class TransportError(Exception):
    def __init__(self, reason, httpcode, fp=None):
        Exception.__init__(self, reason)
        self.httpcode = httpcode
        self.fp = fp


class Request(UnicodeMixin):
    """
    A transport request.

    Request URL input data may be given as either a byte or a unicode string,
    but it may not under any circumstances contain non-ASCII characters. The
    URL value is stored as a str value internally. With Python versions prior
    to 3.0, str is the byte string type, while with later Python versions it is
    the unicode string type.

    @ivar url: The URL for the request.
    @type url: str
    @ivar message: The optional message to be sent in the request body.
    @type message: bytes|None
    @type timeout: int|None
    @ivar headers: The HTTP headers to be used for the request.
    @type headers: dict

    """

    def __init__(self, url, message=None, timeout=None):
        """
        Raised exception in case of detected non-ASCII URL characters may be
        either UnicodeEncodeError or UnicodeDecodeError, depending on the used
        Python version's str type and the exact value passed as URL input data.

        @param url: The URL for the request.
        @type url: bytes|str|unicode
        @param message: The optional message to be sent in the request body.
        @type message: bytes|None

        """
        self.__set_URL(url)
        self.headers = {}
        self.message = message
        self.timeout = timeout

    def __unicode__(self):
        result = ["URL: %s\nHEADERS: %s" % (self.url, self.headers)]
        if self.message is not None:
            result.append("MESSAGE:")
            result.append(self.message.decode("raw_unicode_escape"))
        return "\n".join(result)

    def __set_URL(self, url):
        """
        URL is stored as a str internally and must not contain ASCII chars.

        Raised exception in case of detected non-ASCII URL characters may be
        either UnicodeEncodeError or UnicodeDecodeError, depending on the used
        Python version's str type and the exact value passed as URL input data.

        """
        if isinstance(url, str):
            url.encode("ascii")  # Check for non-ASCII characters.
            self.url = url
        elif sys.version_info < (3, 0):
            self.url = url.encode("ascii")
        else:
            self.url = url.decode("ascii")


class Reply(UnicodeMixin):
    """
    A transport reply.

    @ivar code: The HTTP code returned.
    @type code: int
    @ivar headers: The HTTP headers included in the received reply.
    @type headers: dict
    @ivar message: The message received as a reply.
    @type message: bytes

    """

    def __init__(self, code, headers, message):
        """
        @param code: The HTTP code returned.
        @type code: int
        @param headers: The HTTP headers included in the received reply.
        @type headers: dict
        @param message: The (optional) message received as a reply.
        @type message: bytes

        """
        self.code = code
        self.headers = headers
        self.message = message

    def __unicode__(self):
        return """\
CODE: %s
HEADERS: %s
MESSAGE:
%s""" % (self.code, self.headers, self.message.decode("raw_unicode_escape"))


class Transport(object):
    """The transport I{interface}."""

    def __init__(self):
        from suds.transport.options import Options
        self.options = Options()

    def open(self, request):
        """
        Open the URL in the specified request.

        @param request: A transport request.
        @type request: L{Request}
        @return: An input stream.
        @rtype: stream
        @raise TransportError: On all transport errors.

        """
        raise Exception('not-implemented')

    def send(self, request):
        """
        Send SOAP message. Implementations are expected to handle:
            - proxies
            - I{HTTP} headers
            - cookies
            - sending message
            - brokering exceptions into L{TransportError}

        @param request: A transport request.
        @type request: L{Request}
        @return: The reply
        @rtype: L{Reply}
        @raise TransportError: On all transport errors.

        """
        raise Exception('not-implemented')
