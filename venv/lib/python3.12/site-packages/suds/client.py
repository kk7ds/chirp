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
Service proxy implementation providing access to web services.

"""

import suds
from suds import *
import suds.bindings.binding
from suds.builder import Builder
import suds.cache
import suds.metrics as metrics
from suds.options import Options
from suds.plugin import PluginContainer
from suds.properties import Unskin
from suds.reader import DefinitionsReader
from suds.resolver import PathResolver
from suds.sax.document import Document
import suds.sax.parser
from suds.servicedefinition import ServiceDefinition
import suds.transport
import suds.transport.https
from suds.umx.basic import Basic as UmxBasic
from suds.wsdl import Definitions
from . import sudsobject

from http.cookiejar import CookieJar
from copy import deepcopy
import http.client

from logging import getLogger
log = getLogger(__name__)


class Client(UnicodeMixin):
    """
    A lightweight web service client.

    @ivar wsdl: The WSDL object.
    @type wsdl:L{Definitions}
    @ivar service: The service proxy used to invoke operations.
    @type service: L{Service}
    @ivar factory: The factory used to create objects.
    @type factory: L{Factory}
    @ivar sd: The service definition
    @type sd: L{ServiceDefinition}
    @ivar messages: The last sent/received messages.
    @type messages: str[2]

    """

    @classmethod
    def items(cls, sobject):
        """
        Extract I{items} from a suds object.

        Much like the items() method works on I{dict}.

        @param sobject: A suds object
        @type sobject: L{Object}
        @return: A list of items contained in I{sobject}.
        @rtype: [(key, value),...]

        """
        return sudsobject.items(sobject)

    @classmethod
    def dict(cls, sobject):
        """
        Convert a sudsobject into a dictionary.

        @param sobject: A suds object
        @type sobject: L{Object}
        @return: A dictionary of items contained in I{sobject}.
        @rtype: dict

        """
        return sudsobject.asdict(sobject)

    @classmethod
    def metadata(cls, sobject):
        """
        Extract the metadata from a suds object.

        @param sobject: A suds object
        @type sobject: L{Object}
        @return: The object's metadata
        @rtype: L{sudsobject.Metadata}

        """
        return sobject.__metadata__

    def __init__(self, url, **kwargs):
        """
        @param url: The URL for the WSDL.
        @type url: str
        @param kwargs: keyword arguments.
        @see: L{Options}

        """
        options = Options()
        options.transport = suds.transport.https.HttpAuthenticated()
        self.options = options
        if "cache" not in kwargs:
            kwargs["cache"] = suds.cache.ObjectCache(days=1)
        self.set_options(**kwargs)
        reader = DefinitionsReader(options, Definitions)
        self.wsdl = reader.open(url)
        plugins = PluginContainer(options.plugins)
        plugins.init.initialized(wsdl=self.wsdl)
        self.factory = Factory(self.wsdl)
        self.service = ServiceSelector(self, self.wsdl.services)
        self.sd = []
        for s in self.wsdl.services:
            sd = ServiceDefinition(self.wsdl, s)
            self.sd.append(sd)
        self.messages = dict(tx=None, rx=None)

    def set_options(self, **kwargs):
        """
        Set options.

        @param kwargs: keyword arguments.
        @see: L{Options}

        """
        p = Unskin(self.options)
        p.update(kwargs)

    def add_prefix(self, prefix, uri):
        """
        Add I{static} mapping of an XML namespace prefix to a namespace.

        Useful for cases when a WSDL and referenced XSD schemas make heavy use
        of namespaces and those namespaces are subject to change.

        @param prefix: An XML namespace prefix.
        @type prefix: str
        @param uri: An XML namespace URI.
        @type uri: str
        @raise Exception: prefix already mapped.

        """
        root = self.wsdl.root
        mapped = root.resolvePrefix(prefix, None)
        if mapped is None:
            root.addPrefix(prefix, uri)
            return
        if mapped[1] != uri:
            raise Exception('"%s" already mapped as "%s"' % (prefix, mapped))

    def last_sent(self):
        """
        Get last sent I{soap} message.
        @return: The last sent I{soap} message.
        @rtype: L{Document}
        """
        return self.messages.get('tx')

    def last_received(self):
        """
        Get last received I{soap} message.
        @return: The last received I{soap} message.
        @rtype: L{Document}
        """
        return self.messages.get('rx')

    def clone(self):
        """
        Get a shallow clone of this object.

        The clone only shares the WSDL. All other attributes are unique to the
        cloned object including options.

        @return: A shallow clone.
        @rtype: L{Client}

        """
        class Uninitialized(Client):
            def __init__(self):
                pass
        clone = Uninitialized()
        clone.options = Options()
        cp = Unskin(clone.options)
        mp = Unskin(self.options)
        cp.update(deepcopy(mp))
        clone.wsdl = self.wsdl
        clone.factory = self.factory
        clone.service = ServiceSelector(clone, self.wsdl.services)
        clone.sd = self.sd
        clone.messages = dict(tx=None, rx=None)
        return clone

    def __unicode__(self):
        s = ["\n"]
        s.append("Suds ( https://fedorahosted.org/suds/ )")
        s.append("  version: %s" % (suds.__version__,))
        if suds.__build__:
            s.append("  build: %s" % (suds.__build__,))
        for sd in self.sd:
            s.append("\n\n%s" % (str(sd),))
        return "".join(s)


class Factory:
    """
    A factory for instantiating types defined in the WSDL.

    @ivar resolver: A schema type resolver.
    @type resolver: L{PathResolver}
    @ivar builder: A schema object builder.
    @type builder: L{Builder}

    """

    def __init__(self, wsdl):
        """
        @param wsdl: A schema object.
        @type wsdl: L{wsdl.Definitions}

        """
        self.wsdl = wsdl
        self.resolver = PathResolver(wsdl)
        self.builder = Builder(self.resolver)

    def create(self, name):
        """
        Create a WSDL type by name.

        @param name: The name of a type defined in the WSDL.
        @type name: str
        @return: The requested object.
        @rtype: L{Object}

        """
        timer = metrics.Timer()
        timer.start()
        type = self.resolver.find(name)
        if type is None:
            raise TypeNotFound(name)
        if type.enum():
            result = sudsobject.Factory.object(name)
            for e, a in type.children():
                setattr(result, e.name, e.name)
        else:
            try:
                result = self.builder.build(type)
            except Exception as e:
                log.error("create '%s' failed", name, exc_info=True)
                raise BuildError(name, e)
        timer.stop()
        metrics.log.debug("%s created: %s", name, timer)
        return result

    def separator(self, ps):
        """
        Set the path separator.

        @param ps: The new path separator.
        @type ps: char

        """
        self.resolver = PathResolver(self.wsdl, ps)


class ServiceSelector:
    """
    The B{service} selector is used to select a web service.

    Most WSDLs only define a single service in which case access by subscript
    is passed through to a L{PortSelector}. This is also the behavior when a
    I{default} service has been specified. In cases where multiple services
    have been defined and no default has been specified, the service is found
    by name (or index) and a L{PortSelector} for the service is returned. In
    all cases, attribute access is forwarded to the L{PortSelector} for either
    the I{first} service or the I{default} service (when specified).

    @ivar __client: A suds client.
    @type __client: L{Client}
    @ivar __services: A list of I{WSDL} services.
    @type __services: list

    """
    def __init__(self, client, services):
        """
        @param client: A suds client.
        @type client: L{Client}
        @param services: A list of I{WSDL} services.
        @type services: list

        """
        self.__client = client
        self.__services = services

    def __getattr__(self, name):
        """
        Attribute access is forwarded to the L{PortSelector}.

        Uses the I{default} service if specified or the I{first} service
        otherwise.

        @param name: Method name.
        @type name: str
        @return: A L{PortSelector}.
        @rtype: L{PortSelector}.

        """
        default = self.__ds()
        if default is None:
            port = self.__find(0)
        else:
            port = default
        return getattr(port, name)

    def __getitem__(self, name):
        """
        Provides I{service} selection by name (string) or index (integer).

        In cases where only a single service is defined or a I{default} has
        been specified, the request is forwarded to the L{PortSelector}.

        @param name: The name (or index) of a service.
        @type name: int|str
        @return: A L{PortSelector} for the specified service.
        @rtype: L{PortSelector}.

        """
        if len(self.__services) == 1:
            port = self.__find(0)
            return port[name]
        default = self.__ds()
        if default is not None:
            port = default
            return port[name]
        return self.__find(name)

    def __find(self, name):
        """
        Find a I{service} by name (string) or index (integer).

        @param name: The name (or index) of a service.
        @type name: int|str
        @return: A L{PortSelector} for the found service.
        @rtype: L{PortSelector}.

        """
        service = None
        if not self.__services:
            raise Exception("No services defined")
        if isinstance(name, int):
            try:
                service = self.__services[name]
                name = service.name
            except IndexError:
                raise ServiceNotFound("at [%d]" % (name,))
        else:
            for s in self.__services:
                if name == s.name:
                    service = s
                    break
        if service is None:
            raise ServiceNotFound(name)
        return PortSelector(self.__client, service.ports, name)

    def __ds(self):
        """
        Get the I{default} service if defined in the I{options}.

        @return: A L{PortSelector} for the I{default} service.
        @rtype: L{PortSelector}.

        """
        ds = self.__client.options.service
        if ds is not None:
            return self.__find(ds)


class PortSelector:
    """
    The B{port} selector is used to select a I{web service} B{port}.

    In cases where multiple ports have been defined and no default has been
    specified, the port is found by name (or index) and a L{MethodSelector} for
    the port is returned. In all cases, attribute access is forwarded to the
    L{MethodSelector} for either the I{first} port or the I{default} port (when
    specified).

    @ivar __client: A suds client.
    @type __client: L{Client}
    @ivar __ports: A list of I{service} ports.
    @type __ports: list
    @ivar __qn: The I{qualified} name of the port (used for logging).
    @type __qn: str

    """
    def __init__(self, client, ports, qn):
        """
        @param client: A suds client.
        @type client: L{Client}
        @param ports: A list of I{service} ports.
        @type ports: list
        @param qn: The name of the service.
        @type qn: str

        """
        self.__client = client
        self.__ports = ports
        self.__qn = qn

    def __getattr__(self, name):
        """
        Attribute access is forwarded to the L{MethodSelector}.

        Uses the I{default} port when specified or the I{first} port otherwise.

        @param name: The name of a method.
        @type name: str
        @return: A L{MethodSelector}.
        @rtype: L{MethodSelector}.

        """
        default = self.__dp()
        if default is None:
            m = self.__find(0)
        else:
            m = default
        return getattr(m, name)

    def __getitem__(self, name):
        """
        Provides I{port} selection by name (string) or index (integer).

        In cases where only a single port is defined or a I{default} has been
        specified, the request is forwarded to the L{MethodSelector}.

        @param name: The name (or index) of a port.
        @type name: int|str
        @return: A L{MethodSelector} for the specified port.
        @rtype: L{MethodSelector}.

        """
        default = self.__dp()
        if default is None:
            return self.__find(name)
        return default

    def __find(self, name):
        """
        Find a I{port} by name (string) or index (integer).

        @param name: The name (or index) of a port.
        @type name: int|str
        @return: A L{MethodSelector} for the found port.
        @rtype: L{MethodSelector}.

        """
        port = None
        if not self.__ports:
            raise Exception("No ports defined: %s" % (self.__qn,))
        if isinstance(name, int):
            qn = "%s[%d]" % (self.__qn, name)
            try:
                port = self.__ports[name]
            except IndexError:
                raise PortNotFound(qn)
        else:
            qn = ".".join((self.__qn, name))
            for p in self.__ports:
                if name == p.name:
                    port = p
                    break
        if port is None:
            raise PortNotFound(qn)
        qn = ".".join((self.__qn, port.name))
        return MethodSelector(self.__client, port.methods, qn)

    def __dp(self):
        """
        Get the I{default} port if defined in the I{options}.

        @return: A L{MethodSelector} for the I{default} port.
        @rtype: L{MethodSelector}.

        """
        dp = self.__client.options.port
        if dp is not None:
            return self.__find(dp)


class MethodSelector:
    """
    The B{method} selector is used to select a B{method} by name.

    @ivar __client: A suds client.
    @type __client: L{Client}
    @ivar __methods: A dictionary of methods.
    @type __methods: dict
    @ivar __qn: The I{qualified} name of the method (used for logging).
    @type __qn: str

    """
    def __init__(self, client, methods, qn):
        """
        @param client: A suds client.
        @type client: L{Client}
        @param methods: A dictionary of methods.
        @type methods: dict
        @param qn: The I{qualified} name of the port.
        @type qn: str

        """
        self.__client = client
        self.__methods = methods
        self.__qn = qn

    def __getattr__(self, name):
        """
        Get a method by name and return it in an I{execution wrapper}.

        @param name: The name of a method.
        @type name: str
        @return: An I{execution wrapper} for the specified method name.
        @rtype: L{Method}

        """
        return self[name]

    def __getitem__(self, name):
        """
        Get a method by name and return it in an I{execution wrapper}.

        @param name: The name of a method.
        @type name: str
        @return: An I{execution wrapper} for the specified method name.
        @rtype: L{Method}

        """
        m = self.__methods.get(name)
        if m is None:
            qn = ".".join((self.__qn, name))
            raise MethodNotFound(qn)
        return Method(self.__client, m)


class Method:
    """
    The I{method} (namespace) object.

    @ivar client: A client object.
    @type client: L{Client}
    @ivar method: A I{WSDL} method.
    @type I{raw} Method.

    """

    def __init__(self, client, method):
        """
        @param client: A client object.
        @type client: L{Client}
        @param method: A I{raw} method.
        @type I{raw} Method.

        """
        self.client = client
        self.method = method

    def __call__(self, *args, **kwargs):
        """Invoke the method."""
        clientclass = self.clientclass(kwargs)
        client = clientclass(self.client, self.method)
        try:
            return client.invoke(args, kwargs)
        except WebFault as e:
            if self.faults():
                raise
            return http.client.INTERNAL_SERVER_ERROR, e

    def faults(self):
        """Get faults option."""
        return self.client.options.faults

    def clientclass(self, kwargs):
        """Get SOAP client class."""
        if _SimClient.simulation(kwargs):
            return _SimClient
        return _SoapClient


class RequestContext:
    """
    A request context.

    Returned by a suds Client when invoking a web service operation with the
    ``nosend`` enabled. Allows the caller to take care of sending the request
    himself and return back the reply data for further processing.

    @ivar envelope: The SOAP request envelope.
    @type envelope: I{bytes}

    """

    def __init__(self, process_reply, envelope):
        """
        @param process_reply: A callback for processing a user defined reply.
        @type process_reply: I{callable}
        @param envelope: The SOAP request envelope.
        @type envelope: I{bytes}

        """
        self.__process_reply = process_reply
        self.envelope = envelope

    def process_reply(self, reply, status=None, description=None):
        """
        Re-entry for processing a successful reply.

        Depending on how the ``retxml`` option is set, may return the SOAP
        reply XML or process it and return the Python object representing the
        returned value.

        @param reply: The SOAP reply envelope.
        @type reply: I{bytes}
        @param status: The HTTP status code.
        @type status: int
        @param description: Additional status description.
        @type description: I{bytes}
        @return: The invoked web service operation return value.
        @rtype: I{builtin}|I{subclass of} L{Object}|I{bytes}|I{None}

        """
        return self.__process_reply(reply, status, description)


class _SoapClient:
    """
    An internal lightweight SOAP based web service operation client.

    Each instance is constructed for specific web service operation and knows
    how to:
      - Construct a SOAP request for it.
      - Transport a SOAP request for it using a configured transport.
      - Receive a SOAP reply using a configured transport.
      - Process the received SOAP reply.

    Depending on the given suds options, may do all the tasks listed above or
    may stop the process at an earlier point and return some intermediate
    result, e.g. the constructed SOAP request or the raw received SOAP reply.
    See the invoke() method for more detailed information.

    @ivar service: The target method.
    @type service: L{Service}
    @ivar method: A target method.
    @type method: L{Method}
    @ivar options: A dictonary of options.
    @type options: dict
    @ivar cookiejar: A cookie jar.
    @type cookiejar: libcookie.CookieJar

    """

    TIMEOUT_ARGUMENT = "__timeout"

    def __init__(self, client, method):
        """
        @param client: A suds client.
        @type client: L{Client}
        @param method: A target method.
        @type method: L{Method}

        """
        self.client = client
        self.method = method
        self.options = client.options
        self.cookiejar = CookieJar()

    def invoke(self, args, kwargs):
        """
        Invoke a specified web service method.

        Depending on how the ``nosend`` & ``retxml`` options are set, may do
        one of the following:
          * Return a constructed web service operation SOAP request without
            sending it to the web service.
          * Invoke the web service operation and return its SOAP reply XML.
          * Invoke the web service operation, process its results and return
            the Python object representing the returned value.

        When returning a SOAP request, the request is wrapped inside a
        RequestContext object allowing the user to acquire a corresponding SOAP
        reply himself and then pass it back to suds for further processing.

        Constructed request data is automatically processed using registered
        plugins and serialized into a byte-string. Exact request XML formatting
        may be affected by the ``prettyxml`` suds option.

        @param args: A list of args for the method invoked.
        @type args: list|tuple
        @param kwargs: Named (keyword) args for the method invoked.
        @type kwargs: dict
        @return: SOAP request, SOAP reply or a web service return value.
        @rtype: L{RequestContext}|I{builtin}|I{subclass of} L{Object}|I{bytes}|
            I{None}

        """
        timer = metrics.Timer()
        timer.start()
        binding = self.method.binding.input
        timeout = kwargs.pop(_SoapClient.TIMEOUT_ARGUMENT, None)
        soapenv = binding.get_message(self.method, args, kwargs)
        timer.stop()
        method_name = self.method.name
        metrics.log.debug("message for '%s' created: %s", method_name, timer)
        timer.start()
        result = self.send(soapenv, timeout=timeout)
        timer.stop()
        metrics.log.debug("method '%s' invoked: %s", method_name, timer)
        return result

    def send(self, soapenv, timeout=None):
        """
        Send SOAP message.

        Depending on how the ``nosend`` & ``retxml`` options are set, may do
        one of the following:
          * Return a constructed web service operation request without sending
            it to the web service.
          * Invoke the web service operation and return its SOAP reply XML.
          * Invoke the web service operation, process its results and return
            the Python object representing the returned value.

        @param soapenv: A SOAP envelope to send.
        @type soapenv: L{Document}
        @return: SOAP request, SOAP reply or a web service return value.
        @rtype: L{RequestContext}|I{builtin}|I{subclass of} L{Object}|I{bytes}|
            I{None}

        """
        location = self.__location()
        log.debug("sending to (%s)\nmessage:\n%s", location, soapenv)
        self.last_sent(soapenv)
        plugins = PluginContainer(self.options.plugins)
        plugins.message.marshalled(envelope=soapenv.root())
        if self.options.prettyxml:
            soapenv = soapenv.str()
        else:
            soapenv = soapenv.plain()
        soapenv = soapenv.encode("utf-8")
        ctx = plugins.message.sending(envelope=soapenv)
        soapenv = ctx.envelope
        if self.options.nosend:
            return RequestContext(self.process_reply, soapenv)
        request = suds.transport.Request(location, soapenv, timeout)
        request.headers = self.__headers()
        try:
            timer = metrics.Timer()
            timer.start()
            reply = self.options.transport.send(request)
            timer.stop()
            metrics.log.debug("waited %s on server reply", timer)
        except suds.transport.TransportError as e:
            content = e.fp and e.fp.read() or ""
            return self.process_reply(content, e.httpcode, tostr(e))
        return self.process_reply(reply.message, None, None)

    def process_reply(self, reply, status, description):
        """
        Process a web service operation SOAP reply.

        Depending on how the ``retxml`` option is set, may return the SOAP
        reply XML or process it and return the Python object representing the
        returned value.

        @param reply: The SOAP reply envelope.
        @type reply: I{bytes}
        @param status: The HTTP status code (None indicates httplib.OK).
        @type status: int|I{None}
        @param description: Additional status description.
        @type description: str
        @return: The invoked web service operation return value.
        @rtype: I{builtin}|I{subclass of} L{Object}|I{bytes}|I{None}

        """
        if status is None:
            status = http.client.OK
        debug_message = "Reply HTTP status - %d" % (status,)
        if status in (http.client.ACCEPTED, http.client.NO_CONTENT):
            log.debug(debug_message)
            return
        #TODO: Consider whether and how to allow plugins to handle error,
        # httplib.ACCEPTED & httplib.NO_CONTENT replies as well as successful
        # ones.
        if status == http.client.OK:
            log.debug("%s\n%s", debug_message, reply)
        else:
            log.debug("%s - %s\n%s", debug_message, description, reply)

        plugins = PluginContainer(self.options.plugins)
        ctx = plugins.message.received(reply=reply)
        reply = ctx.reply

        # SOAP standard states that SOAP errors must be accompanied by HTTP
        # status code 500 - internal server error:
        #
        # From SOAP 1.1 specification:
        #   In case of a SOAP error while processing the request, the SOAP HTTP
        # server MUST issue an HTTP 500 "Internal Server Error" response and
        # include a SOAP message in the response containing a SOAP Fault
        # element (see section 4.4) indicating the SOAP processing error.
        #
        # From WS-I Basic profile:
        #   An INSTANCE MUST use a "500 Internal Server Error" HTTP status code
        # if the response message is a SOAP Fault.
        replyroot = None
        if status in (http.client.OK, http.client.INTERNAL_SERVER_ERROR):
            replyroot = _parse(reply)
            if len(reply) > 0:
                self.last_received(replyroot)
            plugins.message.parsed(reply=replyroot)
            fault = self.__get_fault(replyroot)
            if fault:
                if status != http.client.INTERNAL_SERVER_ERROR:
                    log.warning("Web service reported a SOAP processing fault "
                        "using an unexpected HTTP status code %d. Reporting "
                        "as an internal server error.", status)
                if self.options.faults:
                    raise WebFault(fault, replyroot)
                return http.client.INTERNAL_SERVER_ERROR, fault
        if status != http.client.OK:
            if self.options.faults:
                #TODO: Use a more specific exception class here.
                raise Exception((status, description))
            return status, description

        if self.options.retxml:
            return reply

        result = replyroot and self.method.binding.output.get_reply(
            self.method, replyroot)
        ctx = plugins.message.unmarshalled(reply=result)
        result = ctx.reply
        if self.options.faults:
            return result
        return http.client.OK, result

    def __get_fault(self, replyroot):
        """
        Extract fault information from a SOAP reply.

        Returns an I{unmarshalled} fault L{Object} or None in case the given
        XML document does not contain a SOAP <Fault> element.

        @param replyroot: A SOAP reply message root XML element or None.
        @type replyroot: L{Element}|I{None}
        @return: A fault object.
        @rtype: L{Object}

        """
        def get_fault(envns):
            soapenv = replyroot and replyroot.getChild("Envelope", envns)
            soapbody = soapenv and soapenv.getChild("Body", envns)
            return soapbody and soapbody.getChild("Fault", envns)

        fault = get_fault(suds.bindings.binding.envns) or get_fault(suds.bindings.binding.envns12)
        return fault is not None and UmxBasic().process(fault)

    def __headers(self):
        """
        Get HTTP headers for a HTTP/HTTPS SOAP request.

        @return: A dictionary of header/values.
        @rtype: dict

        """
        action = self.method.soap.action
        if isinstance(action, str):
            action = action.encode("utf-8")
        result = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action}
        result.update(**self.options.headers)
        log.debug("headers = %s", result)
        return result

    def __location(self):
        """Returns the SOAP request's target location URL."""
        return Unskin(self.options).get("location", self.method.location)

    def last_sent(self, d=None):
        """
        Get or set last SOAP sent messages document

        To get the last sent document call the function without parameter.
        To set the last sent message, pass the document as parameter.

        @param d: A SOAP reply dict message key
        @type string: I{bytes}
        @return: The last sent I{soap} message.
        @rtype: L{Document}

        """
        key = 'tx'
        messages = self.client.messages
        if d is None:
            return messages.get(key)
        else:
            messages[key] = d

    def last_received(self, d=None):
        """
        Get or set last SOAP received messages document

        To get the last received document call the function without parameter.
        To set the last sent message, pass the document as parameter.

        @param d: A SOAP reply dict message key
        @type string: I{bytes}
        @return: The last received I{soap} message.
        @rtype: L{Document}

        """
        key = 'rx'
        messages = self.client.messages
        if d is None:
            return messages.get(key)
        else:
            messages[key] = d


class _SimClient(_SoapClient):
    """
    Loopback _SoapClient used for SOAP request/reply simulation.

    Used when a web service operation is invoked with injected SOAP request or
    reply data.

    """

    __injkey = "__inject"

    @classmethod
    def simulation(cls, kwargs):
        """Get whether injected data has been specified in I{kwargs}."""
        return _SimClient.__injkey in kwargs

    def invoke(self, args, kwargs):
        """
        Invoke a specified web service method.

        Uses an injected SOAP request/response instead of a regularly
        constructed/received one.

        Depending on how the ``nosend`` & ``retxml`` options are set, may do
        one of the following:
          * Return a constructed web service operation request without sending
            it to the web service.
          * Invoke the web service operation and return its SOAP reply XML.
          * Invoke the web service operation, process its results and return
            the Python object representing the returned value.

        @param args: Positional arguments for the method invoked.
        @type args: list|tuple
        @param kwargs: Keyword arguments for the method invoked.
        @type kwargs: dict
        @return: SOAP request, SOAP reply or a web service return value.
        @rtype: L{RequestContext}|I{builtin}|I{subclass of} L{Object}|I{bytes}|
            I{None}

        """
        simulation = kwargs.pop(self.__injkey)
        msg = simulation.get("msg")
        if msg is not None:
            assert msg.__class__ is suds.byte_str_class
            return self.send(_parse(msg))
        msg = self.method.binding.input.get_message(self.method, args, kwargs)
        log.debug("inject (simulated) send message:\n%s", msg)
        reply = simulation.get("reply")
        if reply is not None:
            assert reply.__class__ is suds.byte_str_class
            status = simulation.get("status")
            description = simulation.get("description")
            if description is None:
                description = "injected reply"
            return self.process_reply(reply, status, description)
        raise Exception("reply or msg injection parameter expected")


def _parse(string):
    """
    Parses given XML document content.

    Returns the resulting root XML element node or None if the given XML
    content is empty.

    @param string: XML document content to parse.
    @type string: I{bytes}
    @return: Resulting root XML element node or None.
    @rtype: L{Element}|I{None}

    """
    if string:
        return suds.sax.parser.Parser().parse(string=string)
