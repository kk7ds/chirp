# -*- coding: utf-8 -*-

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

"""Classes representing I{built-in} XSD schema objects."""

from suds import *
from suds.xsd import *
from suds.sax.date import *
from suds.xsd.sxbase import XBuiltin

import datetime
import decimal
import sys


class XAny(XBuiltin):
    """Represents an XSD <xsd:any/> node."""

    def __init__(self, schema, name):
        XBuiltin.__init__(self, schema, name)
        self.nillable = False

    def get_child(self, name):
        child = XAny(self.schema, name)
        return child, []

    def any(self):
        return True


class XBoolean(XBuiltin):
    """Represents an XSD boolean built-in type."""

    _xml_to_python = {"1": True, "true": True, "0": False, "false": False}
    _python_to_xml = {True: "true", 1: "true", False: "false", 0: "false"}

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str):
                return XBoolean._xml_to_python.get(value)
        else:
            if isinstance(value, (bool, int)):
                return XBoolean._python_to_xml.get(value)
            return value


class XDate(XBuiltin):
    """Represents an XSD <xsd:date/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return Date(value).value
        else:
            if isinstance(value, datetime.date):
                return Date(value)
            return value


class XDateTime(XBuiltin):
    """Represents an XSD <xsd:datetime/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return DateTime(value).value
        else:
            if isinstance(value, datetime.datetime):
                return DateTime(value)
            return value


class XDecimal(XBuiltin):
    """
    Represents an XSD <xsd:decimal/> built-in type.

    Excerpt from the XSD datatype specification
    (http://www.w3.org/TR/2004/REC-xmlschema-2-20041028):

    > 3.2.3 decimal
    >
    > [Definition:] decimal represents a subset of the real numbers, which can
    > be represented by decimal numerals. The ·value space· of decimal is the
    > set of numbers that can be obtained by multiplying an integer by a
    > non-positive power of ten, i.e., expressible as i × 10^-n where i and n
    > are integers and n >= 0. Precision is not reflected in this value space;
    > the number 2.0 is not distinct from the number 2.00. The ·order-relation·
    > on decimal is the order relation on real numbers, restricted to this
    > subset.
    >
    > 3.2.3.1 Lexical representation
    >
    > decimal has a lexical representation consisting of a finite-length
    > sequence of decimal digits (#x30-#x39) separated by a period as a decimal
    > indicator. An optional leading sign is allowed. If the sign is omitted,
    > "+" is assumed. Leading and trailing zeroes are optional. If the
    > fractional part is zero, the period and following zero(es) can be
    > omitted. For example: -1.23, 12678967.543233, +100000.00, 210.

    """

    # Python versions before 2.7 do not support the decimal.Decimal.canonical()
    # method but they maintain their decimal.Decimal encoded in canonical
    # format internally so we can easily emulate that function by simply
    # returning the same decimal instance.
    if sys.version_info < (2, 7):
        _decimal_canonical = staticmethod(lambda decimal: decimal)
    else:
        _decimal_canonical = decimal.Decimal.canonical

    @staticmethod
    def _decimal_to_xsd_format(value):
        """
        Converts a decimal.Decimal value to its XSD decimal type value.

        Result is a string containing the XSD decimal type's lexical value
        representation. The conversion is done without any precision loss.

        Note that Python's native decimal.Decimal string representation will
        not do here as the lexical representation desired here does not allow
        representing decimal values using float-like `<mantissa>E<exponent>'
        format, e.g. 12E+30 or 0.10006E-12.

        """
        value = XDecimal._decimal_canonical(value)
        negative, digits, exponent = value.as_tuple()

        # The following implementation assumes the following tuple decimal
        # encoding (part of the canonical decimal value encoding):
        #  - digits must contain at least one element
        #  - no leading integral 0 digits except a single one in 0 (if a non-0
        #    decimal value has leading integral 0 digits they must be encoded
        #    in its 'exponent' value and not included explicitly in its
        #    'digits' tuple)
        assert digits
        assert digits[0] != 0 or len(digits) == 1

        result = []
        if negative:
            result.append("-")

        # No fractional digits.
        if exponent >= 0:
            result.extend(str(x) for x in digits)
            result.extend("0" * exponent)
            return "".join(result)

        digit_count = len(digits)

        # Decimal point offset from the given digit start.
        point_offset = digit_count + exponent

        # Trim trailing fractional 0 digits.
        fractional_digit_count = min(digit_count, -exponent)
        while fractional_digit_count and digits[digit_count - 1] == 0:
            digit_count -= 1
            fractional_digit_count -= 1

        # No trailing fractional 0 digits and a decimal point coming not after
        # the given digits, meaning there is no need to add additional trailing
        # integral 0 digits.
        if point_offset <= 0:
            # No integral digits.
            result.append("0")
            if digit_count > 0:
                result.append(".")
                result.append("0" * -point_offset)
                result.extend(str(x) for x in digits[:digit_count])
        else:
            # Have integral and possibly some fractional digits.
            result.extend(str(x) for x in digits[:point_offset])
            if point_offset < digit_count:
                result.append(".")
                result.extend(str(x) for x in digits[point_offset:digit_count])
        return "".join(result)

    @classmethod
    def translate(cls, value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return decimal.Decimal(value)
        else:
            if isinstance(value, decimal.Decimal):
                return cls._decimal_to_xsd_format(value)
            return value


class XFloat(XBuiltin):
    """Represents an XSD <xsd:float/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return float(value)
        else:
            return value


class XInteger(XBuiltin):
    """Represents an XSD <xsd:int/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return int(value)
        else:
            return value


class XLong(XBuiltin):
    """Represents an XSD <xsd:long/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return int(value)
        else:
            return value


class XString(XBuiltin):
    """Represents an XSD <xsd:string/> node."""
    pass


class XTime(XBuiltin):
    """Represents an XSD <xsd:time/> built-in type."""

    @staticmethod
    def translate(value, topython=True):
        if topython:
            if isinstance(value, str) and value:
                return Time(value).value
        else:
            if isinstance(value, datetime.time):
                return Time(value)
            return value


class Factory:

    tags = {
        # any
        "anyType": XAny,
        # strings
        "string": XString,
        "normalizedString": XString,
        "ID": XString,
        "Name": XString,
        "QName": XString,
        "NCName": XString,
        "anySimpleType": XString,
        "anyURI": XString,
        "NOTATION": XString,
        "token": XString,
        "language": XString,
        "IDREFS": XString,
        "ENTITIES": XString,
        "IDREF": XString,
        "ENTITY": XString,
        "NMTOKEN": XString,
        "NMTOKENS": XString,
        # binary
        "hexBinary": XString,
        "base64Binary": XString,
        # integers
        "int": XInteger,
        "integer": XInteger,
        "unsignedInt": XInteger,
        "positiveInteger": XInteger,
        "negativeInteger": XInteger,
        "nonPositiveInteger": XInteger,
        "nonNegativeInteger": XInteger,
        # longs
        "long": XLong,
        "unsignedLong": XLong,
        # shorts
        "short": XInteger,
        "unsignedShort": XInteger,
        "byte": XInteger,
        "unsignedByte": XInteger,
        # floats
        "float": XFloat,
        "double": XFloat,
        "decimal": XDecimal,
        # dates & times
        "date": XDate,
        "time": XTime,
        "dateTime": XDateTime,
        "duration": XString,
        "gYearMonth": XString,
        "gYear": XString,
        "gMonthDay": XString,
        "gDay": XString,
        "gMonth": XString,
        # boolean
        "boolean": XBoolean,
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
    def create(cls, schema, name):
        """
        Create an object based on the root tag name.

        @param schema: A schema object.
        @type schema: L{schema.Schema}
        @param name: The name.
        @type name: str
        @return: The created object.
        @rtype: L{XBuiltin}

        """
        fn = cls.tags.get(name, XBuiltin)
        return fn(schema, name)
