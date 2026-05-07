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
The I{schema} module provides an intelligent representation of an XSD schema.
The I{raw} model is the XML tree and the I{model} is a denormalized,
objectified and intelligent view of the schema. Most of the I{value-add}
provided by the model is centered around transparent referenced type resolution
and targeted denormalization.

"""

from suds import *
from suds.xsd import *
from suds.xsd.depsort import dependency_sort
from suds.xsd.sxbuiltin import *
from suds.xsd.sxbase import SchemaObject
from suds.xsd.sxbasic import Factory as BasicFactory
from suds.xsd.sxbuiltin import Factory as BuiltinFactory
from suds.sax import splitPrefix, Namespace
from suds.sax.element import Element

from logging import getLogger
log = getLogger(__name__)


class SchemaCollection(UnicodeMixin):
    """
    A collection of schema objects.

    This class is needed because a WSDL may contain more then one <schema/>
    node.

    @ivar wsdl: A WSDL object.
    @type wsdl: L{suds.wsdl.Definitions}
    @ivar children: A list contained schemas.
    @type children: [L{Schema},...]
    @ivar namespaces: A dictionary of contained schemas by namespace.
    @type namespaces: {str: L{Schema}}

    """

    def __init__(self, wsdl):
        """
        @param wsdl: A WSDL object.
        @type wsdl: L{suds.wsdl.Definitions}

        """
        self.wsdl = wsdl
        self.children = []
        self.namespaces = {}

    def add(self, schema):
        """
        Add a schema node to the collection. Schema(s) within the same target
        namespace are consolidated.

        @param schema: A schema object.
        @type schema: (L{Schema})

        """
        key = schema.tns[1]
        existing = self.namespaces.get(key)
        if existing is None:
            self.children.append(schema)
            self.namespaces[key] = schema
        else:
            existing.root.children += schema.root.children
            existing.root.nsprefixes.update(schema.root.nsprefixes)

    def load(self, options, loaded_schemata):
        """
        Load schema objects for the root nodes.
            - de-reference schemas
            - merge schemas

        @param options: An options dictionary.
        @type options: L{options.Options}
        @param loaded_schemata: Already loaded schemata cache (URL --> Schema).
        @type loaded_schemata: dict
        @return: The merged schema.
        @rtype: L{Schema}

        """
        if options.autoblend:
            self.autoblend()
        for child in self.children:
            child.build()
        for child in self.children:
            child.open_imports(options, loaded_schemata)
        for child in self.children:
            child.dereference()
        log.debug("loaded:\n%s", self)
        merged = self.merge()
        log.debug("MERGED:\n%s", merged)
        return merged

    def autoblend(self):
        """
        Ensure that all schemas within the collection import each other which
        has a blending effect.

        @return: self
        @rtype: L{SchemaCollection}

        """
        namespaces = list(self.namespaces.keys())
        for s in self.children:
            for ns in namespaces:
                tns = s.root.get("targetNamespace")
                if tns == ns:
                    continue
                for imp in s.root.getChildren("import"):
                    if imp.get("namespace") == ns:
                        continue
                imp = Element("import", ns=Namespace.xsdns)
                imp.set("namespace", ns)
                s.root.append(imp)
        return self

    def locate(self, ns):
        """
        Find a schema by namespace. Only the URI portion of the namespace is
        compared to each schema's I{targetNamespace}.

        @param ns: A namespace.
        @type ns: (prefix, URI)
        @return: The schema matching the namespace, else None.
        @rtype: L{Schema}

        """
        return self.namespaces.get(ns[1])

    def merge(self):
        """
        Merge contained schemas into one.

        @return: The merged schema.
        @rtype: L{Schema}

        """
        if self.children:
            schema = self.children[0]
            for s in self.children[1:]:
                schema.merge(s)
            return schema

    def __len__(self):
        return len(self.children)

    def __unicode__(self):
        result = ["\nschema collection"]
        for s in self.children:
            result.append(s.str(1))
        return "\n".join(result)


class Schema(UnicodeMixin):
    """
    The schema is an objectification of a <schema/> (XSD) definition. It
    provides inspection, lookup and type resolution.

    @ivar root: The root node.
    @type root: L{sax.element.Element}
    @ivar baseurl: The I{base} URL for this schema.
    @type baseurl: str
    @ivar container: A schema collection containing this schema.
    @type container: L{SchemaCollection}
    @ivar children: A list of direct top level children.
    @type children: [L{SchemaObject},...]
    @ivar all: A list of all (includes imported) top level children.
    @type all: [L{SchemaObject},...]
    @ivar types: A schema types cache.
    @type types: {name:L{SchemaObject}}
    @ivar imports: A list of import objects.
    @type imports: [L{SchemaObject},...]
    @ivar elements: A list of <element/> objects.
    @type elements: [L{SchemaObject},...]
    @ivar attributes: A list of <attribute/> objects.
    @type attributes: [L{SchemaObject},...]
    @ivar groups: A list of group objects.
    @type groups: [L{SchemaObject},...]
    @ivar agrps: A list of attribute group objects.
    @type agrps: [L{SchemaObject},...]
    @ivar form_qualified: The flag indicating: (@elementFormDefault).
    @type form_qualified: bool

    """

    Tag = "schema"

    def __init__(self, root, baseurl, options, loaded_schemata=None,
            container=None):
        """
        @param root: The XML root.
        @type root: L{sax.element.Element}
        @param baseurl: The base URL used for importing.
        @type baseurl: basestring
        @param options: An options dictionary.
        @type options: L{options.Options}
        @param loaded_schemata: An optional already loaded schemata cache (URL
            --> Schema).
        @type loaded_schemata: dict
        @param container: An optional container.
        @type container: L{SchemaCollection}

        """
        self.root = root
        self.id = objid(self)
        self.tns = self.mktns()
        self.baseurl = baseurl
        self.container = container
        self.children = []
        self.all = []
        self.types = {}
        self.imports = []
        self.elements = {}
        self.attributes = {}
        self.groups = {}
        self.agrps = {}
        if options.doctor is not None:
            options.doctor.examine(root)
        form = self.root.get("elementFormDefault")
        self.form_qualified = form == "qualified"

        # If we have a container, that container is going to take care of
        # finishing our build for us in parallel with building all the other
        # schemata in that container. That allows the different schema within
        # the same container to freely reference each other.
        #TODO: check whether this container content build parallelization is
        # really necessary or if we can simply build our top-level WSDL
        # contained schemata one by one as they are loaded
        if container is None:
            if loaded_schemata is None:
                loaded_schemata = {}
            loaded_schemata[baseurl] = self
            #TODO: It seems like this build() step can be done for each schema
            # on its own instead of letting the container do it. Building our
            # XSD schema objects should not require any external schema
            # information and even references between XSD schema objects within
            # the same schema can not be established until all the XSD schema
            # objects have been built. The only reason I can see right now why
            # this step has been placed under container control is so our
            # container (a SchemaCollection instance) can add some additional
            # XML elements to our schema before our XSD schema object entities
            # get built, but there is bound to be a cleaner way to do this,
            # similar to how we support such XML modifications in suds plugins.
            self.build()
            self.open_imports(options, loaded_schemata)
            log.debug("built:\n%s", self)
            self.dereference()
            log.debug("dereferenced:\n%s", self)

    def mktns(self):
        """
        Make the schema's target namespace.

        @return: namespace representation of the schema's targetNamespace
            value.
        @rtype: (prefix, URI)

        """
        tns = self.root.get("targetNamespace")
        tns_prefix = None
        if tns is not None:
            tns_prefix = self.root.findPrefix(tns)
        return tns_prefix, tns

    def build(self):
        """
        Build the schema (object graph) using the root node using the factory.
            - Build the graph.
            - Collate the children.

        """
        self.children = BasicFactory.build(self.root, self)
        collated = BasicFactory.collate(self.children)
        self.children = collated[0]
        self.attributes = collated[2]
        self.imports = collated[1]
        self.elements = collated[3]
        self.types = collated[4]
        self.groups = collated[5]
        self.agrps = collated[6]

    def merge(self, schema):
        """
        Merge the schema contents.

        Only objects not already contained in this schema's collections are
        merged. This provides support for bidirectional imports producing
        cyclic includes.

        @returns: self
        @rtype: L{Schema}

        """
        for item in list(schema.attributes.items()):
            if item[0] in self.attributes:
                continue
            self.all.append(item[1])
            self.attributes[item[0]] = item[1]
        for item in list(schema.elements.items()):
            if item[0] in self.elements:
                continue
            self.all.append(item[1])
            self.elements[item[0]] = item[1]
        for item in list(schema.types.items()):
            if item[0] in self.types:
                continue
            self.all.append(item[1])
            self.types[item[0]] = item[1]
        for item in list(schema.groups.items()):
            if item[0] in self.groups:
                continue
            self.all.append(item[1])
            self.groups[item[0]] = item[1]
        for item in list(schema.agrps.items()):
            if item[0] in self.agrps:
                continue
            self.all.append(item[1])
            self.agrps[item[0]] = item[1]
        schema.merged = True
        return self

    def open_imports(self, options, loaded_schemata):
        """
        Instruct all contained L{sxbasic.Import} children to import all of
        their referenced schemas. The imported schema contents are I{merged}
        in.

        @param options: An options dictionary.
        @type options: L{options.Options}
        @param loaded_schemata: Already loaded schemata cache (URL --> Schema).
        @type loaded_schemata: dict

        """
        for imp in self.imports:
            imported = imp.open(options, loaded_schemata)
            if imported is None:
                continue
            imported.open_imports(options, loaded_schemata)
            log.debug("imported:\n%s", imported)
            self.merge(imported)

    def dereference(self):
        """Instruct all children to perform dereferencing."""
        all = []
        indexes = {}
        for child in self.children:
            child.content(all)
        dependencies = {}
        for x in all:
            x.qualify()
            midx, deps = x.dependencies()
            dependencies[x] = deps
            indexes[x] = midx
        for x, deps in dependency_sort(dependencies):
            midx = indexes.get(x)
            if midx is None:
                continue
            d = deps[midx]
            log.debug("(%s) merging %s <== %s", self.tns[1], Repr(x), Repr(d))
            x.merge(d)

    def locate(self, ns):
        """
        Find a schema by namespace. Only the URI portion of the namespace is
        compared to each schema's I{targetNamespace}. The request is passed on
        to the container.

        @param ns: A namespace.
        @type ns: (prefix, URI)
        @return: The schema matching the namespace, else None.
        @rtype: L{Schema}

        """
        if self.container is not None:
            return self.container.locate(ns)

    def custom(self, ref, context=None):
        """
        Get whether the specified reference is B{not} an (xs) builtin.

        @param ref: A str or qref.
        @type ref: (str|qref)
        @return: True if B{not} a builtin, else False.
        @rtype: bool

        """
        return ref is None or not self.builtin(ref, context)

    def builtin(self, ref, context=None):
        """
        Get whether the specified reference is an (xs) builtin.

        @param ref: A str or qref.
        @type ref: (str|qref)
        @return: True if builtin, else False.
        @rtype: bool

        """
        w3 = "http://www.w3.org"
        try:
            if isqref(ref):
                ns = ref[1]
                return ref[0] in Factory.tags and ns.startswith(w3)
            if context is None:
                context = self.root
            prefix = splitPrefix(ref)[0]
            prefixes = context.findPrefixes(w3, "startswith")
            return prefix in prefixes and ref[0] in Factory.tags
        except Exception:
            return False

    def instance(self, root, baseurl, loaded_schemata, options):
        """
        Create and return an new schema object using the specified I{root} and
        I{URL}.

        @param root: A schema root node.
        @type root: L{sax.element.Element}
        @param baseurl: A base URL.
        @type baseurl: str
        @param loaded_schemata: Already loaded schemata cache (URL --> Schema).
        @type loaded_schemata: dict
        @param options: An options dictionary.
        @type options: L{options.Options}
        @return: The newly created schema object.
        @rtype: L{Schema}
        @note: This is only used by Import children.

        """
        return Schema(root, baseurl, options, loaded_schemata)

    def str(self, indent=0):
        tab = "%*s" % (indent * 3, "")
        result = []
        result.append("%s%s" % (tab, self.id))
        result.append("%s(raw)" % (tab,))
        result.append(self.root.str(indent + 1))
        result.append("%s(model)" % (tab,))
        for c in self.children:
            result.append(c.str(indent + 1))
        result.append("")
        return "\n".join(result)

    def __repr__(self):
        return '<%s tns="%s"/>' % (self.id, self.tns[1])

    def __unicode__(self):
        return self.str()
