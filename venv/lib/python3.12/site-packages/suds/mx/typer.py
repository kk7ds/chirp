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
Provides XSD typing classes.

"""

from suds.sax import Namespace
from suds.sax.text import Text
from suds.sudsobject import Object


class Typer:
    """
    Provides XML node typing as either automatic or manual.

    @cvar types: Class to XSD type mapping.
    @type types: dict

    """

    types = {
        bool: ("boolean", Namespace.xsdns),
        float: ("float", Namespace.xsdns),
        int: ("int", Namespace.xsdns),
        int: ("long", Namespace.xsdns),
        str: ("string", Namespace.xsdns),
        Text: ("string", Namespace.xsdns),
        str: ("string", Namespace.xsdns)}

    @classmethod
    def auto(cls, node, value=None):
        """
        Automatically set the node's xsi:type attribute based on either
        I{value}'s or the node text's class. When I{value} is an unmapped
        class, the default type (xs:any) is set.

        @param node: XML node.
        @type node: L{sax.element.Element}
        @param value: Object that is or would be the node's text.
        @type value: I{any}
        @return: Specified node.
        @rtype: L{sax.element.Element}

        """
        if value is None:
            value = node.getText()
        if isinstance(value, Object):
            known = cls.known(value)
            if known.name is None:
                return node
            tm = known.name, known.namespace()
        else:
            tm = cls.types.get(value.__class__, cls.types.get(str))
        cls.manual(node, *tm)
        return node

    @classmethod
    def manual(cls, node, tval, ns=None):
        """
        Set the node's xsi:type attribute based on either I{value}'s or the
        node text's class. Then adds the referenced prefix(s) to the node's
        prefix mapping.

        @param node: XML node.
        @type node: L{sax.element.Element}
        @param tval: XSD schema type name.
        @type tval: str
        @param ns: I{tval} XML namespace.
        @type ns: (prefix, URI)
        @return: Specified node.
        @rtype: L{sax.element.Element}

        """
        xta = ":".join((Namespace.xsins[0], "type"))
        node.addPrefix(Namespace.xsins[0], Namespace.xsins[1])
        if ns is None:
            node.set(xta, tval)
        else:
            ns = cls.genprefix(node, ns)
            qname = ":".join((ns[0], tval))
            node.set(xta, qname)
            node.addPrefix(ns[0], ns[1])
        return node

    @classmethod
    def genprefix(cls, node, ns):
        """
        Generate a prefix.

        @param node: XML node on which the prefix will be used.
        @type node: L{sax.element.Element}
        @param ns: Namespace needing a unique prefix.
        @type ns: (prefix, URI)
        @return: I{ns} with a new prefix.
        @rtype: (prefix, URI)

        """
        for i in range(1, 1024):
            prefix = "ns%d" % (i,)
            uri = node.resolvePrefix(prefix, default=None)
            if uri in (None, ns[1]):
                return prefix, ns[1]
        raise Exception("auto prefix, exhausted")

    @classmethod
    def known(cls, object):
        try:
            md = object.__metadata__
            known = md.sxtype
            return known
        except Exception:
            pass
