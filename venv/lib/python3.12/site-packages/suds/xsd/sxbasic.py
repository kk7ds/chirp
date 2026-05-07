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

"""Classes representing I{basic} XSD schema objects."""

from suds import *
from suds.reader import DocumentReader
from suds.sax import Namespace
from suds.transport import TransportError
from suds.xsd import *
from suds.xsd.query import *
from suds.xsd.sxbase import *

from urllib.parse import urljoin

from logging import getLogger
log = getLogger(__name__)


class RestrictionMatcher:
    """For use with L{NodeFinder} to match restriction."""
    def match(self, n):
        return isinstance(n, Restriction)


class TypedContent(Content):
    """Represents any I{typed} content."""

    def __init__(self, *args, **kwargs):
        Content.__init__(self, *args, **kwargs)
        self.resolved_cache = {}

    def resolve(self, nobuiltin=False):
        """
        Resolve the node's type reference and return the referenced type node.

        Returns self if the type is defined locally, e.g. as a <complexType>
        subnode. Otherwise returns the referenced external node.

        @param nobuiltin: Flag indicating whether resolving to XSD built-in
            types should not be allowed.
        @return: The resolved (true) type.
        @rtype: L{SchemaObject}

        """
        cached = self.resolved_cache.get(nobuiltin)
        if cached is not None:
            return cached
        resolved = self.__resolve_type(nobuiltin)
        self.resolved_cache[nobuiltin] = resolved
        return resolved

    def __resolve_type(self, nobuiltin=False):
        """
        Private resolve() worker without any result caching.

        @param nobuiltin: Flag indicating whether resolving to XSD built-in
            types should not be allowed.
        @return: The resolved (true) type.
        @rtype: L{SchemaObject}

        """
        # There is no need for a recursive implementation here since a node can
        # reference an external type node but XSD specification explicitly
        # states that that external node must not be a reference to yet another
        # node.
        qref = self.qref()
        if qref is None:
            return self
        query = TypeQuery(qref)
        query.history = [self]
        log.debug("%s, resolving: %s\n using:%s", self.id, qref, query)
        resolved = query.execute(self.schema)
        if resolved is None:
            log.debug(self.schema)
            raise TypeNotFound(qref)
        if resolved.builtin() and nobuiltin:
            return self
        return resolved

    def qref(self):
        """
        Get the I{type} qualified reference to the referenced XSD type.

        This method takes into account simple types defined through restriction
        which are detected by determining that self is simple (len == 0) and by
        finding a restriction child.

        @return: The I{type} qualified reference.
        @rtype: qref

        """
        qref = self.type
        if qref is None and len(self) == 0:
            ls = []
            m = RestrictionMatcher()
            finder = NodeFinder(m, 1)
            finder.find(self, ls)
            if ls:
                return ls[0].ref
        return qref


class Complex(SchemaObject):
    """
    Represents an XSD schema <xsd:complexType/> node.

    @cvar childtags: A list of valid child node names.
    @type childtags: (I{str},...)

    """

    def childtags(self):
        return ("all", "any", "attribute", "attributeGroup", "choice",
            "complexContent", "group", "sequence", "simpleContent")

    def description(self):
        return ("name",)

    def extension(self):
        for c in self.rawchildren:
            if c.extension():
                return True
        return False

    def mixed(self):
        for c in self.rawchildren:
            if isinstance(c, SimpleContent) and c.mixed():
                return True
        return False


class Group(SchemaObject):
    """
    Represents an XSD schema <xsd:group/> node.

    @cvar childtags: A list of valid child node names.
    @type childtags: (I{str},...)

    """

    def childtags(self):
        return "all", "choice", "sequence"

    def dependencies(self):
        deps = []
        midx = None
        if self.ref is not None:
            query = GroupQuery(self.ref)
            g = query.execute(self.schema)
            if g is None:
                log.debug(self.schema)
                raise TypeNotFound(self.ref)
            deps.append(g)
            midx = 0
        return midx, deps

    def merge(self, other):
        SchemaObject.merge(self, other)
        self.rawchildren = other.rawchildren

    def description(self):
        return "name", "ref"


class AttributeGroup(SchemaObject):
    """
    Represents an XSD schema <xsd:attributeGroup/> node.

    @cvar childtags: A list of valid child node names.
    @type childtags: (I{str},...)

    """

    def childtags(self):
        return "attribute", "attributeGroup"

    def dependencies(self):
        deps = []
        midx = None
        if self.ref is not None:
            query = AttrGroupQuery(self.ref)
            ag = query.execute(self.schema)
            if ag is None:
                log.debug(self.schema)
                raise TypeNotFound(self.ref)
            deps.append(ag)
            midx = 0
        return midx, deps

    def merge(self, other):
        SchemaObject.merge(self, other)
        self.rawchildren = other.rawchildren

    def description(self):
        return "name", "ref"


class Simple(SchemaObject):
    """Represents an XSD schema <xsd:simpleType/> node."""

    def childtags(self):
        return "any", "list", "restriction"

    def enum(self):
        for child, ancestry in self.children():
            if isinstance(child, Enumeration):
                return True
        return False

    def mixed(self):
        return len(self)

    def description(self):
        return ("name",)

    def extension(self):
        for c in self.rawchildren:
            if c.extension():
                return True
        return False

    def restriction(self):
        for c in self.rawchildren:
            if c.restriction():
                return True
        return False


class List(SchemaObject):
    """Represents an XSD schema <xsd:list/> node."""

    def childtags(self):
        return ()

    def description(self):
        return ("name",)

    def xslist(self):
        return True


class Restriction(SchemaObject):
    """Represents an XSD schema <xsd:restriction/> node."""

    def __init__(self, schema, root):
        SchemaObject.__init__(self, schema, root)
        self.ref = root.get("base")

    def childtags(self):
        return "attribute", "attributeGroup", "enumeration"

    def dependencies(self):
        deps = []
        midx = None
        if self.ref is not None:
            query = TypeQuery(self.ref)
            super = query.execute(self.schema)
            if super is None:
                log.debug(self.schema)
                raise TypeNotFound(self.ref)
            if not super.builtin():
                deps.append(super)
                midx = 0
        return midx, deps

    def restriction(self):
        return True

    def merge(self, other):
        SchemaObject.merge(self, other)
        filter = Filter(False, self.rawchildren)
        self.prepend(self.rawchildren, other.rawchildren, filter)

    def description(self):
        return ("ref",)


class Collection(SchemaObject):
    """Represents an XSD schema collection (a.k.a. order indicator) node."""

    def childtags(self):
        return "all", "any", "choice", "element", "group", "sequence"


class All(Collection):
    """Represents an XSD schema <xsd:all/> node."""
    def all(self):
        return True


class Choice(Collection):
    """Represents an XSD schema <xsd:choice/> node."""
    def choice(self):
        return True


class Sequence(Collection):
    """Represents an XSD schema <xsd:sequence/> node."""
    def sequence(self):
        return True


class ComplexContent(SchemaObject):
    """Represents an XSD schema <xsd:complexContent/> node."""

    def childtags(self):
        return "attribute", "attributeGroup", "extension", "restriction"

    def extension(self):
        for c in self.rawchildren:
            if c.extension():
                return True
        return False

    def restriction(self):
        for c in self.rawchildren:
            if c.restriction():
                return True
        return False


class SimpleContent(SchemaObject):
    """Represents an XSD schema <xsd:simpleContent/> node."""

    def childtags(self):
        return "extension", "restriction"

    def extension(self):
        for c in self.rawchildren:
            if c.extension():
                return True
        return False

    def restriction(self):
        for c in self.rawchildren:
            if c.restriction():
                return True
        return False

    def mixed(self):
        return len(self)


class Enumeration(Content):
    """Represents an XSD schema <xsd:enumeration/> node."""

    def __init__(self, schema, root):
        Content.__init__(self, schema, root)
        self.name = root.get("value")

    def description(self):
        return ("name",)

    def enum(self):
        return True


class Element(TypedContent):
    """Represents an XSD schema <xsd:element/> node."""

    def __init__(self, schema, root):
        TypedContent.__init__(self, schema, root)
        is_reference = self.ref is not None
        is_top_level = root.parent is schema.root
        if is_reference or is_top_level:
            self.form_qualified = True
        else:
            form = root.get("form")
            if form is not None:
                self.form_qualified = (form == "qualified")
        nillable = self.root.get("nillable")
        if nillable is not None:
            self.nillable = (nillable in ("1", "true"))
        self.implany()

    def implany(self):
        """
        Set the type to <xsd:any/> when implicit.

        An element has an implicit <xsd:any/> type when it has no body and no
        explicitly defined type.

        @return: self
        @rtype: L{Element}

        """
        if self.type is None and self.ref is None and self.root.isempty():
            self.type = self.anytype()

    def childtags(self):
        return "any", "attribute", "complexType", "simpleType"

    def extension(self):
        for c in self.rawchildren:
            if c.extension():
                return True
        return False

    def restriction(self):
        for c in self.rawchildren:
            if c.restriction():
                return True
        return False

    def dependencies(self):
        deps = []
        midx = None
        e = self.__deref()
        if e is not None:
            deps.append(e)
            midx = 0
        return midx, deps

    def merge(self, other):
        SchemaObject.merge(self, other)
        self.rawchildren = other.rawchildren

    def description(self):
        return "name", "ref", "type"

    def anytype(self):
        """Create an xsd:anyType reference."""
        p, u = Namespace.xsdns
        mp = self.root.findPrefix(u)
        if mp is None:
            mp = p
            self.root.addPrefix(p, u)
        return ":".join((mp, "anyType"))

    def namespace(self, prefix=None):
        """
        Get this schema element's target namespace.

        In case of reference elements, the target namespace is defined by the
        referenced and not the referencing element node.

        @param prefix: The default prefix.
        @type prefix: str
        @return: The schema element's target namespace
        @rtype: (I{prefix},I{URI})

        """
        e = self.__deref()
        if e is not None:
            return e.namespace(prefix)
        return super(Element, self).namespace()

    def __deref(self):
        if self.ref is None:
            return
        query = ElementQuery(self.ref)
        e = query.execute(self.schema)
        if e is None:
            log.debug(self.schema)
            raise TypeNotFound(self.ref)
        return e


class Extension(SchemaObject):
    """Represents an XSD schema <xsd:extension/> node."""

    def __init__(self, schema, root):
        SchemaObject.__init__(self, schema, root)
        self.ref = root.get("base")

    def childtags(self):
        return ("all", "attribute", "attributeGroup", "choice", "group",
            "sequence")

    def dependencies(self):
        deps = []
        midx = None
        if self.ref is not None:
            query = TypeQuery(self.ref)
            super = query.execute(self.schema)
            if super is None:
                log.debug(self.schema)
                raise TypeNotFound(self.ref)
            if not super.builtin():
                deps.append(super)
                midx = 0
        return midx, deps

    def merge(self, other):
        SchemaObject.merge(self, other)
        filter = Filter(False, self.rawchildren)
        self.prepend(self.rawchildren, other.rawchildren, filter)

    def extension(self):
        return self.ref is not None

    def description(self):
        return ("ref",)


class Import(SchemaObject):
    """
    Represents an XSD schema <xsd:import/> node.

    @cvar locations: A dictionary of namespace locations.
    @type locations: dict
    @ivar ns: The imported namespace.
    @type ns: str
    @ivar location: The (optional) location.
    @type location: namespace-uri
    @ivar opened: Opened and I{imported} flag.
    @type opened: boolean

    """

    locations = {}

    @classmethod
    def bind(cls, ns, location=None):
        """
        Bind a namespace to a schema location (URI).

        This is used for imports that do not specify a schemaLocation.

        @param ns: A namespace-uri.
        @type ns: str
        @param location: The (optional) schema location for the namespace.
            (default=ns)
        @type location: str

        """
        if location is None:
            location = ns
        cls.locations[ns] = location

    def __init__(self, schema, root):
        SchemaObject.__init__(self, schema, root)
        self.ns = (None, root.get("namespace"))
        self.location = root.get("schemaLocation")
        if self.location is None:
            self.location = self.locations.get(self.ns[1])
        self.opened = False

    def open(self, options, loaded_schemata):
        """
        Open and import the referenced schema.

        @param options: An options dictionary.
        @type options: L{options.Options}
        @param loaded_schemata: Already loaded schemata cache (URL --> Schema).
        @type loaded_schemata: dict
        @return: The referenced schema.
        @rtype: L{Schema}

        """
        if self.opened:
            return
        self.opened = True
        log.debug("%s, importing ns='%s', location='%s'", self.id, self.ns[1],
            self.location)
        result = self.__locate()
        if result is None:
            if self.location is None:
                log.debug("imported schema (%s) not-found", self.ns[1])
            else:
                url = self.location
                if "://" not in url:
                    url = urljoin(self.schema.baseurl, url)
                result = (loaded_schemata.get(url) or
                    self.__download(url, loaded_schemata, options))
        log.debug("imported:\n%s", result)
        return result

    def __locate(self):
        """Find the schema locally."""
        if self.ns[1] != self.schema.tns[1]:
            return self.schema.locate(self.ns)

    def __download(self, url, loaded_schemata, options):
        """Download the schema."""
        try:
            reader = DocumentReader(options)
            d = reader.open(url)
            root = d.root()
            root.set("url", url)
            return self.schema.instance(root, url, loaded_schemata, options)
        except TransportError:
            msg = "import schema (%s) at (%s), failed" % (self.ns[1], url)
            log.error("%s, %s", self.id, msg, exc_info=True)
            raise Exception(msg)

    def description(self):
        return "ns", "location"


class Include(SchemaObject):
    """
    Represents an XSD schema <xsd:include/> node.

    @ivar location: The (optional) location.
    @type location: namespace-uri
    @ivar opened: Opened and I{imported} flag.
    @type opened: boolean

    """

    locations = {}

    def __init__(self, schema, root):
        SchemaObject.__init__(self, schema, root)
        self.location = root.get("schemaLocation")
        if self.location is None:
            self.location = self.locations.get(self.ns[1])
        self.opened = False

    def open(self, options, loaded_schemata):
        """
        Open and include the referenced schema.

        @param options: An options dictionary.
        @type options: L{options.Options}
        @param loaded_schemata: Already loaded schemata cache (URL --> Schema).
        @type loaded_schemata: dict
        @return: The referenced schema.
        @rtype: L{Schema}

        """
        if self.opened:
            return
        self.opened = True
        log.debug("%s, including location='%s'", self.id, self.location)
        url = self.location
        if "://" not in url:
            url = urljoin(self.schema.baseurl, url)
        result = (loaded_schemata.get(url) or
            self.__download(url, loaded_schemata, options))
        log.debug("included:\n%s", result)
        return result

    def __download(self, url, loaded_schemata, options):
        """Download the schema."""
        try:
            reader = DocumentReader(options)
            d = reader.open(url)
            root = d.root()
            root.set("url", url)
            self.__applytns(root)
            return self.schema.instance(root, url, loaded_schemata, options)
        except TransportError:
            msg = "include schema at (%s), failed" % url
            log.error("%s, %s", self.id, msg, exc_info=True)
            raise Exception(msg)

    def __applytns(self, root):
        """Make sure included schema has the same target namespace."""
        TNS = "targetNamespace"
        tns = root.get(TNS)
        if tns is None:
            tns = self.schema.tns[1]
            root.set(TNS, tns)
        else:
            if self.schema.tns[1] != tns:
                raise Exception("%s mismatch" % TNS)

    def description(self):
        return "location"


class Attribute(TypedContent):
    """Represents an XSD schema <attribute/> node."""

    def __init__(self, schema, root):
        TypedContent.__init__(self, schema, root)
        self.use = root.get("use", default="")

    def childtags(self):
        return ("restriction",)

    def isattr(self):
        return True

    def get_default(self):
        """
        Gets the <xsd:attribute default=""/> attribute value.

        @return: The default value for the attribute
        @rtype: str

        """
        return self.root.get("default", default="")

    def optional(self):
        return self.use != "required"

    def dependencies(self):
        deps = []
        midx = None
        if self.ref is not None:
            query = AttrQuery(self.ref)
            a = query.execute(self.schema)
            if a is None:
                log.debug(self.schema)
                raise TypeNotFound(self.ref)
            deps.append(a)
            midx = 0
        return midx, deps

    def description(self):
        return "name", "ref", "type"


class Any(Content):
    """Represents an XSD schema <any/> node."""

    def get_child(self, name):
        root = self.root.clone()
        root.set("note", "synthesized (any) child")
        child = Any(self.schema, root)
        return child, []

    def get_attribute(self, name):
        root = self.root.clone()
        root.set("note", "synthesized (any) attribute")
        attribute = Any(self.schema, root)
        return attribute, []

    def any(self):
        return True


class Factory:
    """
    @cvar tags: A factory to create object objects based on tag.
    @type tags: {tag:fn,}

    """

    tags = {
        "all": All,
        "any": Any,
        "attribute": Attribute,
        "attributeGroup": AttributeGroup,
        "choice": Choice,
        "complexContent": ComplexContent,
        "complexType": Complex,
        "element": Element,
        "enumeration": Enumeration,
        "extension": Extension,
        "group": Group,
        "import": Import,
        "include": Include,
        "list": List,
        "restriction": Restriction,
        "simpleContent": SimpleContent,
        "simpleType": Simple,
        "sequence": Sequence,
    }

    @classmethod
    def maptag(cls, tag, fn):
        """
        Map (override) tag => I{class} mapping.

        @param tag: An XSD tag name.
        @type tag: str
        @param fn: A function or class.
        @type fn: fn|class.

        """
        cls.tags[tag] = fn

    @classmethod
    def create(cls, root, schema):
        """
        Create an object based on the root tag name.

        @param root: An XML root element.
        @type root: L{Element}
        @param schema: A schema object.
        @type schema: L{schema.Schema}
        @return: The created object.
        @rtype: L{SchemaObject}

        """
        fn = cls.tags.get(root.name)
        if fn is not None:
            return fn(schema, root)

    @classmethod
    def build(cls, root, schema, filter=("*",)):
        """
        Build an xsobject representation.

        @param root: An schema XML root.
        @type root: L{sax.element.Element}
        @param filter: A tag filter.
        @type filter: [str,...]
        @return: A schema object graph.
        @rtype: L{sxbase.SchemaObject}

        """
        children = []
        for node in root.getChildren(ns=Namespace.xsdns):
            if "*" in filter or node.name in filter:
                child = cls.create(node, schema)
                if child is None:
                    continue
                children.append(child)
                c = cls.build(node, schema, child.childtags())
                child.rawchildren = c
        return children

    @classmethod
    def collate(cls, children):
        imports = []
        elements = {}
        attributes = {}
        types = {}
        groups = {}
        agrps = {}
        for c in children:
            if isinstance(c, (Import, Include)):
                imports.append(c)
                continue
            if isinstance(c, Attribute):
                attributes[c.qname] = c
                continue
            if isinstance(c, Element):
                elements[c.qname] = c
                continue
            if isinstance(c, Group):
                groups[c.qname] = c
                continue
            if isinstance(c, AttributeGroup):
                agrps[c.qname] = c
                continue
            types[c.qname] = c
        for i in imports:
            children.remove(i)
        return children, imports, attributes, elements, types, groups, agrps


#######################################################
# Static Import Bindings :-(
#######################################################
Import.bind(
    "http://schemas.xmlsoap.org/soap/encoding/",
    "suds://schemas.xmlsoap.org/soap/encoding/")
Import.bind(
    "http://www.w3.org/XML/1998/namespace",
    "http://www.w3.org/2001/xml.xsd")
Import.bind(
    "http://www.w3.org/2001/XMLSchema",
    "http://www.w3.org/2001/XMLSchema.xsd")
