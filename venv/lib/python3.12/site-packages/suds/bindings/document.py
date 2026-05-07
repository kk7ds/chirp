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
Classes for the (WS) SOAP I{document/literal} binding.

"""

from suds import *
from suds.argparser import parse_args
from suds.bindings.binding import Binding
from suds.sax.element import Element


class Document(Binding):
    """
    The document/literal style. Literal is the only (@use) supported since
    document/encoded is pretty much dead.

    Although the SOAP specification supports multiple documents within the SOAP
    <body/>, it is very uncommon. As such, suds library supports presenting an
    I{RPC} view of service methods defined with only a single document
    parameter. To support the complete specification, service methods defined
    with multiple documents (multiple message parts), are still presented using
    a full I{document} view.

    More detailed description:

    An interface is considered I{wrapped} if:
      - There is exactly one message part in that interface.
      - The message part resolves to an element of a non-builtin type.
    Otherwise it is considered I{bare}.

    I{Bare} interface is interpreted directly as specified in the WSDL schema,
    with each message part represented by a single parameter in the suds
    library web service operation proxy interface (input or output).

    I{Wrapped} interface is interpreted without the external wrapping document
    structure, with each of its contained elements passed through suds
    library's web service operation proxy interface (input or output)
    individually instead of as a single I{document} object.

    """
    def bodycontent(self, method, args, kwargs):
        wrapped = method.soap.input.body.wrapped
        if wrapped:
            pts = self.bodypart_types(method)
            root = self.document(pts[0])
        else:
            root = []

        def add_param(param_name, param_type, in_choice_context, value):
            """
            Construct request data for the given input parameter.

            Called by our argument parser for every input parameter, in order.

            A parameter's type is identified by its corresponding XSD schema
            element.

            """
            # Do not construct request data for undefined input parameters
            # defined inside a choice order indicator. An empty choice
            # parameter can still be included in the constructed request by
            # explicitly providing an empty string value for it.
            #TODO: This functionality might be better placed inside the
            # mkparam() function but to do that we would first need to better
            # understand how different Binding subclasses in suds work and how
            # they would be affected by this change.
            if in_choice_context and value is None:
                return

            # Construct request data for the current input parameter.
            pdef = (param_name, param_type)
            p = self.mkparam(method, pdef, value)
            if p is None:
                return
            if not wrapped:
                ns = param_type.namespace("ns0")
                p.setPrefix(ns[0], ns[1])
            root.append(p)

        parse_args(method.name, self.param_defs(method), args, kwargs,
            add_param, self.options().extraArgumentErrors)

        return root

    def replycontent(self, method, body):
        if method.soap.output.body.wrapped:
            return body[0].children
        return body.children

    def document(self, wrapper):
        """
        Get the document root. For I{document/literal}, this is the name of the
        wrapper element qualified by the schema's target namespace.

        @param wrapper: The method name.
        @type wrapper: L{xsd.sxbase.SchemaObject}
        @return: A root element.
        @rtype: L{Element}

        """
        tag = wrapper[1].name
        ns = wrapper[1].namespace("ns0")
        return Element(tag, ns=ns)

    def mkparam(self, method, pdef, object):
        """
        Expand list parameters into individual parameters each with the type
        information. This is because in document arrays are simply
        multi-occurrence elements.

        """
        if isinstance(object, (list, tuple)):
            return [self.mkparam(method, pdef, item) for item in object]
        return super(Document, self).mkparam(method, pdef, object)

    def param_defs(self, method):
        """Get parameter definitions for document literal."""
        pts = self.bodypart_types(method)
        if not method.soap.input.body.wrapped:
            return pts
        pt = pts[0][1].resolve()
        return [(c.name, c, a) for c, a in pt if not c.isattr()]

    def returned_types(self, method):
        rts = super(Document, self).returned_types(method)
        if not method.soap.output.body.wrapped:
            return rts
        return [child for child, ancestry in rts[0].resolve(nobuiltin=True)]
