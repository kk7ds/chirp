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
Provides XML I{attribute} classes.

"""

from suds import UnicodeMixin
from suds.sax import splitPrefix, Namespace
from suds.sax.text import Text


class Attribute(UnicodeMixin):
    """
    An XML attribute object.

    @ivar parent: The node containing this attribute.
    @type parent: L{element.Element}
    @ivar prefix: The I{optional} namespace prefix.
    @type prefix: basestring
    @ivar name: The I{unqualified} attribute name.
    @type name: basestring
    @ivar value: The attribute's value.
    @type value: basestring

    """

    def __init__(self, name, value=None):
        """
        @param name: The attribute's name with I{optional} namespace prefix.
        @type name: basestring
        @param value: The attribute's value.
        @type value: basestring

        """
        self.parent = None
        self.prefix, self.name = splitPrefix(name)
        self.setValue(value)

    def clone(self, parent=None):
        """
        Clone this object.

        @param parent: The parent for the clone.
        @type parent: L{element.Element}
        @return: A copy of this object assigned to the new parent.
        @rtype: L{Attribute}

        """
        a = Attribute(self.qname(), self.value)
        a.parent = parent
        return a

    def qname(self):
        """
        Get this attribute's B{fully} qualified name.

        @return: The fully qualified name.
        @rtype: basestring

        """
        if self.prefix is None:
            return self.name
        return ":".join((self.prefix, self.name))

    def setValue(self, value):
        """
        Set the attribute's value.

        @param value: The new value (may be None).
        @type value: basestring
        @return: self
        @rtype: L{Attribute}

        """
        if isinstance(value, Text):
            self.value = value
        else:
            self.value = Text(value)
        return self

    def getValue(self, default=Text("")):
        """
        Get the attributes value with optional default.

        @param default: An optional value to return when the attribute's value
            has not been set.
        @type default: basestring
        @return: The attribute's value, or I{default}.
        @rtype: L{Text}

        """
        return self.value or default

    def hasText(self):
        """
        Get whether the attribute has a non-empty I{text} string value.

        @return: True when has I{text}.
        @rtype: boolean

        """
        return bool(self.value)

    def namespace(self):
        """
        Get the attribute's namespace. This may either be the namespace defined
        by an optional prefix, or the default namespace.

        @return: The attribute's namespace.
        @rtype: (I{prefix}, I{name})

        """
        if self.prefix is None:
            return Namespace.default
        return self.resolvePrefix(self.prefix)

    def resolvePrefix(self, prefix):
        """
        Resolve the specified prefix to a known namespace.

        @param prefix: A declared prefix.
        @type prefix: basestring
        @return: The namespace mapped to I{prefix}.
        @rtype: (I{prefix}, I{name})

        """
        if self.parent is None:
            return Namespace.default
        return self.parent.resolvePrefix(prefix)

    def match(self, name=None, ns=None):
        """
        Match by (optional) name and/or (optional) namespace.

        @param name: The optional attribute tag name.
        @type name: str
        @param ns: An optional namespace.
        @type ns: (I{prefix}, I{name})
        @return: True if matched.
        @rtype: boolean

        """
        byname = name is None or (self.name == name)
        byns = ns is None or (self.namespace()[1] == ns[1])
        return byname and byns

    def __eq__(self, rhs):
        """Equals operator."""
        return (isinstance(rhs, Attribute) and self.prefix == rhs.name and
            self.name == rhs.name)

    def __repr__(self):
        """Programmer friendly string representation."""
        return "attr (prefix=%s, name=%s, value=(%s))" % (self.prefix,
            self.name, self.value)

    def __unicode__(self):
        """XML string representation."""
        return '%s="%s"' % (self.qname(), self.value and self.value.escape())
