# Copyright 2010 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Language:
#
# Example definitions:
#
#  bit  foo[8];  /* Eight single bit values                 */
#  u8   foo;     /* Unsigned 8-bit value                    */
#  u16  foo;     /* Unsigned 16-bit value                   */
#  ul16 foo;     /* Unsigned 16-bit value (LE)              */
#  u24  foo;     /* Unsigned 24-bit value                   */
#  ul24 foo;     /* Unsigned 24-bit value (LE)              */
#  u32  foo;     /* Unsigned 32-bit value                   */
#  ul32 foo;     /* Unsigned 32-bit value (LE)              */
#  i8   foo;     /* Signed 8-bit value                      */
#  i16  foo;     /* Signed 16-bit value                     */
#  il16 foo;     /* Signed 16-bit value (LE)                */
#  i24  foo;     /* Signed 24-bit value                     */
#  il24 foo;     /* Signed 24-bit value (LE)                */
#  i32  foo;     /* Signed 32-bit value                     */
#  il32 foo;     /* Signed 32-bit value (LE)                */
#  char foo;     /* Character (single-byte                  */
#  lbcd foo;     /* BCD-encoded byte (LE)                   */
#  bbcd foo;     /* BCD-encoded byte (BE)                   */
#  char foo[8];  /* 8-char array                            */
#  struct {
#   u8 foo;
#   u16 bar;
#  } baz;        /* Structure with u8 and u16               */
#
# Example directives:
#
# #seekto 0x1AB; /* Set the data offset to 0x1AB            */
# #seek 4;       /* Set the data offset += 4                */
# #printoffset "foobar" /* Echo the live data offset,
#                          prefixed by string while parsing */
#
# Usage:
#
# Create a data definition in a string, and pass it and the data
# to parse to the parse() function.  The result is a structure with
# dict-like objects for structures, indexed by name, and lists of
# objects for arrays.  The actual data elements can be interpreted
# as integers directly (for int types).  Strings and BCD arrays
# behave as expected.

import struct
import os
import logging

from chirp import bitwise_grammar
from chirp.memmap import MemoryMap

LOG = logging.getLogger(__name__)


class ParseError(Exception):
    """Indicates an error parsing a definition"""
    pass


def format_binary(nbits, value, pad=8):
    s = ""
    for i in range(0, nbits):
        s = "%i%s" % (value & 0x01, s)
        value >>= 1
    return "%s%s" % ((pad - len(s)) * ".", s)


def bits_between(start, end):
    bits = (1 << (end - start)) - 1
    return bits << start


def pp(structure, level=0):
    for i in structure:
        if isinstance(i, list):
            pp(i, level+2)
        elif isinstance(i, tuple):
            if isinstance(i[1], str):
                print "%s%s: %s" % (" " * level, i[0], i[1])
            else:
                print "%s%s:" % (" " * level, i[0])
                pp(i, level+2)
        elif isinstance(i, str):
            print "%s%s" % (" " * level, i)


def array_copy(dst, src):
    """Copy an array src into DataElement array dst"""
    if len(dst) != len(src):
        raise Exception("Arrays differ in size")

    for i in range(0, len(dst)):
        dst[i].set_value(src[i])


def bcd_to_int(bcd_array):
    """Convert an array of bcdDataElement like \x12\x34
    into an int like 1234"""
    value = 0
    for bcd in bcd_array:
        a, b = bcd.get_value()
        value = (value * 100) + (a * 10) + b
    return value


def int_to_bcd(bcd_array, value):
    """Convert an int like 1234 into bcdDataElements like "\x12\x34" """
    for i in reversed(range(0, len(bcd_array))):
        bcd_array[i].set_value(value % 100)
        value /= 100


def get_string(char_array):
    """Convert an array of charDataElements into a string"""
    return "".join([x.get_value() for x in char_array])


def set_string(char_array, string):
    """Set an array of charDataElements from a string"""
    array_copy(char_array, list(string))


class DataElement:
    _size = 1

    def __init__(self, data, offset, count=1):
        self._data = data
        self._offset = offset
        self._count = count

    def size(self):
        return self._size * 8

    def get_offset(self):
        return self._offset

    def _get_value(self, data):
        raise Exception("Not implemented")

    def get_value(self):
        value = self._data[self._offset:self._offset + self._size]
        return self._get_value(value)

    def set_value(self, value):
        raise Exception("Not implemented for %s" % self.__class__)

    def get_raw(self):
        return self._data[self._offset:self._offset+self._size]

    def set_raw(self, data):
        self._data[self._offset] = data[:self._size]

    def __getattr__(self, name):
        raise AttributeError("Unknown attribute %s in %s" % (name,
                                                             self.__class__))

    def __repr__(self):
        return "(%s:%i bytes @ %04x)" % (self.__class__.__name__,
                                         self._size,
                                         self._offset)


class arrayDataElement(DataElement):
    def __repr__(self):
        if isinstance(self.__items[0], bcdDataElement):
            return "%i:[(%i)]" % (len(self.__items), int(self))

        if isinstance(self.__items[0], charDataElement):
            return "%i:[(%s)]" % (len(self.__items), repr(str(self))[1:-1])

        s = "%i:[" % len(self.__items)
        s += ",".join([repr(item) for item in self.__items])
        s += "]"
        return s

    def __init__(self, offset):
        self.__items = []
        self._offset = offset

    def append(self, item):
        self.__items.append(item)

    def get_value(self):
        return list(self.__items)

    def get_raw(self):
        return "".join([item.get_raw() for item in self.__items])

    def __setitem__(self, index, val):
        self.__items[index].set_value(val)

    def __getitem__(self, index):
        return self.__items[index]

    def __len__(self):
        return len(self.__items)

    def __str__(self):
        if isinstance(self.__items[0], charDataElement):
            return "".join([x.get_value() for x in self.__items])
        else:
            return str(self.__items)

    def __int__(self):
        if isinstance(self.__items[0], bcdDataElement):
            val = 0
            if isinstance(self.__items[0], bbcdDataElement):
                items = self.__items
            else:
                items = reversed(self.__items)
            for i in items:
                tens, ones = i.get_value()
                val = (val * 100) + (tens * 10) + ones
            return val
        else:
            raise ValueError("Cannot coerce this to int")

    def __set_value_bbcd(self, value):
        for i in reversed(self.__items):
            twodigits = value % 100
            value /= 100
            i.set_value(twodigits)

    def __set_value_lbcd(self, value):
        for i in self.__items:
            twodigits = value % 100
            value /= 100
            i.set_value(twodigits)

    def __set_value_char(self, value):
        if len(value) != len(self.__items):
            raise ValueError("String expects exactly %i characters" %
                             len(self.__items))
        for i in range(0, len(self.__items)):
            self.__items[i].set_value(value[i])

    def set_value(self, value):
        if isinstance(self.__items[0], bbcdDataElement):
            self.__set_value_bbcd(int(value))
        elif isinstance(self.__items[0], lbcdDataElement):
            self.__set_value_lbcd(int(value))
        elif isinstance(self.__items[0], charDataElement):
            self.__set_value_char(str(value))
        elif len(value) != len(self.__items):
            raise ValueError("Array cardinality mismatch")
        else:
            for i in range(0, len(value)):
                self.__items[i].set_value(value[i])

    def index(self, value):
        index = 0
        for i in self.__items:
            if i.get_value() == value:
                return index
            index += 1
        raise IndexError()

    def __iter__(self):
        return iter(self.__items)

    def items(self):
        index = 0
        for item in self.__items:
            yield (str(index), item)
            index += 1

    def size(self):
        size = 0
        for i in self.__items:
            size += i.size()
        return size


class intDataElement(DataElement):
    def __repr__(self):
        fmt = "0x%%0%iX" % (self._size * 2)
        return fmt % int(self)

    def __int__(self):
        return self.get_value()

    def __invert__(self):
        return ~self.get_value()

    def __trunc__(self):
        return self.get_value()

    def __abs__(self):
        return abs(self.get_value())

    def __mod__(self, val):
        return self.get_value() % val

    def __mul__(self, val):
        return self.get_value() * val

    def __div__(self, val):
        return self.get_value() / val

    def __add__(self, val):
        return self.get_value() + val

    def __sub__(self, val):
        return self.get_value() - val

    def __or__(self, val):
        return self.get_value() | val

    def __xor__(self, val):
        return self.get_value() ^ val

    def __and__(self, val):
        return self.get_value() & val

    def __radd__(self, val):
        return val + self.get_value()

    def __rsub__(self, val):
        return val - self.get_value()

    def __rmul__(self, val):
        return val * self.get_value()

    def __rdiv__(self, val):
        return val / self.get_value()

    def __rand__(self, val):
        return val & self.get_value()

    def __ror__(self, val):
        return val | self.get_value()

    def __rxor__(self, val):
        return val ^ self.get_value()

    def __rmod__(self, val):
        return val % self.get_value()

    def __lshift__(self, val):
        return self.get_value() << val

    def __rshift__(self, val):
        return self.get_value() >> val

    def __iadd__(self, val):
        self.set_value(self.get_value() + val)
        return self

    def __isub__(self, val):
        self.set_value(self.get_value() - val)
        return self

    def __imul__(self, val):
        self.set_value(self.get_value() * val)
        return self

    def __idiv__(self, val):
        self.set_value(self.get_value() / val)
        return self

    def __imod__(self, val):
        self.set_value(self.get_value() % val)
        return self

    def __iand__(self, val):
        self.set_value(self.get_value() & val)
        return self

    def __ior__(self, val):
        self.set_value(self.get_value() | val)
        return self

    def __ixor__(self, val):
        self.set_value(self.get_value() ^ val)
        return self

    def __index__(self):
        return abs(self)

    def __eq__(self, val):
        return self.get_value() == val

    def __ne__(self, val):
        return self.get_value() != val

    def __lt__(self, val):
        return self.get_value() < val

    def __le__(self, val):
        return self.get_value() <= val

    def __gt__(self, val):
        return self.get_value() > val

    def __ge__(self, val):
        return self.get_value() >= val

    def __nonzero__(self):
        return self.get_value() != 0


class u8DataElement(intDataElement):
    _size = 1

    def _get_value(self, data):
        return ord(data)

    def set_value(self, value):
        self._data[self._offset] = (int(value) & 0xFF)


class u16DataElement(intDataElement):
    _size = 2
    _endianess = ">"

    def _get_value(self, data):
        return struct.unpack(self._endianess + "H", data)[0]

    def set_value(self, value):
        self._data[self._offset] = struct.pack(self._endianess + "H",
                                               int(value) & 0xFFFF)


class ul16DataElement(u16DataElement):
    _endianess = "<"


class u24DataElement(intDataElement):
    _size = 3
    _endianess = ">"

    def _get_value(self, data):
        pre = self._endianess == ">" and "\x00" or ""
        post = self._endianess == "<" and "\x00" or ""
        return struct.unpack(self._endianess + "I", pre+data+post)[0]

    def set_value(self, value):
        if self._endianess == "<":
            start = 0
            end = 3
        else:
            start = 1
            end = 4
        packed = struct.pack(self._endianess + "I", int(value) & 0xFFFFFFFF)
        self._data[self._offset] = packed[start:end]


class ul24DataElement(u24DataElement):
    _endianess = "<"


class u32DataElement(intDataElement):
    _size = 4
    _endianess = ">"

    def _get_value(self, data):
        return struct.unpack(self._endianess + "I", data)[0]

    def set_value(self, value):
        self._data[self._offset] = struct.pack(self._endianess + "I",
                                               int(value) & 0xFFFFFFFF)


class ul32DataElement(u32DataElement):
    _endianess = "<"


class i8DataElement(u8DataElement):
    _size = 1

    def _get_value(self, data):
        return struct.unpack("b", data)[0]

    def set_value(self, value):
        self._data[self._offset] = struct.pack("b", int(value))


class i16DataElement(intDataElement):
    _size = 2
    _endianess = ">"

    def _get_value(self, data):
        return struct.unpack(self._endianess + "h", data)[0]

    def set_value(self, value):
        self._data[self._offset] = struct.pack(self._endianess + "h",
                                               int(value))


class il16DataElement(i16DataElement):
    _endianess = "<"


class i24DataElement(intDataElement):
    _size = 3
    _endianess = ">"

    def _get_value(self, data):
        pre = self._endianess == ">" and "\x00" or ""
        post = self._endianess == "<" and "\x00" or ""
        return struct.unpack(self._endianess + "i", pre+data+post)[0]

    def set_value(self, value):
        if self._endianess == "<":
            start = 0
            end = 3
        else:
            start = 1
            end = 4
        self._data[self._offset] = struct.pack(self._endianess + "i",
                                               int(value))[start:end]


class il24DataElement(i24DataElement):
    _endianess = "<"


class i32DataElement(intDataElement):
    _size = 4
    _endianess = ">"

    def _get_value(self, data):
        return struct.unpack(self._endianess + "i", data)[0]

    def set_value(self, value):
        self._data[self._offset] = struct.pack(self._endianess + "i",
                                               int(value))


class il32DataElement(i32DataElement):
    _endianess = "<"


class charDataElement(DataElement):
    _size = 1

    def __str__(self):
        return str(self.get_value())

    def __int__(self):
        return ord(self.get_value())

    def _get_value(self, data):
        return data

    def set_value(self, value):
        self._data[self._offset] = str(value)


class bcdDataElement(DataElement):
    def __int__(self):
        tens, ones = self.get_value()
        return (tens * 10) + ones

    def set_bits(self, mask):
        self._data[self._offset] = ord(self._data[self._offset]) | int(mask)

    def clr_bits(self, mask):
        self._data[self._offset] = ord(self._data[self._offset]) & ~int(mask)

    def get_bits(self, mask):
        return ord(self._data[self._offset]) & int(mask)

    def set_raw(self, data):
        if isinstance(data, int):
            self._data[self._offset] = data & 0xFF
        elif isinstance(data, str):
            self._data[self._offset] = data[0]
        else:
            raise TypeError("Unable to set bcdDataElement from type %s" %
                            type(data))

    def set_value(self, value):
        self._data[self._offset] = int("%02i" % value, 16)

    def _get_value(self, data):
        a = (ord(data) & 0xF0) >> 4
        b = ord(data) & 0x0F
        return (a, b)


class lbcdDataElement(bcdDataElement):
    _size = 1


class bbcdDataElement(bcdDataElement):
    _size = 1


class bitDataElement(intDataElement):
    _nbits = 0
    _shift = 0
    _subgen = u8DataElement  # Default to a byte

    def __repr__(self):
        fmt = "0x%%0%iX (%%sb)" % (self._size * 2)
        return fmt % (int(self), format_binary(self._nbits, self.get_value()))

    def get_value(self):
        data = self._subgen(self._data, self._offset).get_value()
        mask = bits_between(self._shift-self._nbits, self._shift)
        val = (data & mask) >> (self._shift - self._nbits)
        return val

    def set_value(self, value):
        mask = bits_between(self._shift-self._nbits, self._shift)

        data = self._subgen(self._data, self._offset).get_value()
        data &= ~mask

        value = ((int(value) << (self._shift-self._nbits)) & mask) | data

        self._subgen(self._data, self._offset).set_value(value)

    def size(self):
        return self._nbits


class structDataElement(DataElement):
    def __repr__(self):
        s = "struct {" + os.linesep
        for prop in self._keys:
            s += "  %15s: %s%s" % (prop, repr(self._generators[prop]),
                                   os.linesep)
        s += "} %s (%i bytes at 0x%04X)%s" % (self._name,
                                              self.size() / 8,
                                              self._offset,
                                              os.linesep)
        return s

    def __init__(self, *args, **kwargs):
        self._generators = {}
        self._keys = []
        self._count = 1
        if "name" in kwargs.keys():
            self._name = kwargs["name"]
            del kwargs["name"]
        else:
            self._name = "(anonymous)"
        DataElement.__init__(self, *args, **kwargs)
        self.__init = True

    def _value(self, data, generators):
        result = {}
        for name, gen in generators.items():
            result[name] = gen.get_value(data)
        return result

    def get_value(self):
        result = []
        for i in range(0, self._count):
            result.append(self._value(self._data, self._generators[i]))

        if self._count == 1:
            return result[0]
        else:
            return result

    def __getitem__(self, key):
        return self._generators[key]

    def __setitem__(self, key, value):
        if key in self._generators:
            self._generators[key].set_value(value)
        else:
            self._generators[key] = value
            self._keys.append(key)

    def __getattr__(self, name):
        try:
            return self._generators[name]
        except KeyError:
            raise AttributeError("No attribute %s in struct" % name)

    def __setattr__(self, name, value):
        if "_structDataElement__init" not in self.__dict__:
            self.__dict__[name] = value
        else:
            self.__dict__["_generators"][name].set_value(value)

    def size(self):
        size = 0
        for name, gen in self._generators.items():
            if not isinstance(gen, list):
                gen = [gen]

            i = 0
            for el in gen:
                i += 1
                size += el.size()
        return size

    def get_raw(self):
        size = self.size() / 8
        return self._data[self._offset:self._offset+size]

    def set_raw(self, buffer):
        if len(buffer) != (self.size() / 8):
            raise ValueError("Struct size mismatch during set_raw()")
        self._data[self._offset] = buffer

    def __iter__(self):
        for item in self._generators.values():
            yield item

    def items(self):
        for key in self._keys:
            yield key, self._generators[key]


class Processor:

    _types = {
        "u8":    u8DataElement,
        "u16":   u16DataElement,
        "ul16":  ul16DataElement,
        "u24":   u24DataElement,
        "ul24":  ul24DataElement,
        "u32":   u32DataElement,
        "ul32":  ul32DataElement,
        "i8":    i8DataElement,
        "i16":   i16DataElement,
        "il16":  il16DataElement,
        "i24":   i24DataElement,
        "il24":  il24DataElement,
        "i32":   i32DataElement,
        "char":  charDataElement,
        "lbcd":  lbcdDataElement,
        "bbcd":  bbcdDataElement,
        }

    def __init__(self, data, offset):
        self._data = data
        self._offset = offset
        self._obj = None
        self._user_types = {}

    def do_symbol(self, symdef, gen):
        name = symdef[1]
        self._generators[name] = gen

    def do_bitfield(self, dtype, bitfield):
        bytes = self._types[dtype](self._data, 0).size() / 8
        bitsleft = bytes * 8

        for _bitdef, defn in bitfield:
            name = defn[0][1]
            bits = int(defn[1][1])
            if bitsleft < 0:
                raise ParseError("Invalid bitfield spec")

            class bitDE(bitDataElement):
                _nbits = bits
                _shift = bitsleft
                _subgen = self._types[dtype]

            self._generators[name] = bitDE(self._data, self._offset)
            bitsleft -= bits

        if bitsleft:
            LOG.warn("WARNING: %i trailing bits unaccounted for in %s" %
                     (bitsleft, bitfield))

        return bytes

    def do_bitarray(self, i, count):
        if count % 8 != 0:
            raise ValueError("bit array must be divisible by 8.")

        class bitDE(bitDataElement):
            _nbits = 1
            _shift = 8 - i % 8

        return bitDE(self._data, self._offset)

    def parse_defn(self, defn):
        dtype = defn[0]

        if defn[1][0] == "bitfield":
            size = self.do_bitfield(dtype, defn[1][1])
            count = 1
            self._offset += size
        else:
            if defn[1][0] == "array":
                sym = defn[1][1][0]
                count = int(defn[1][1][1][1])
            else:
                count = 1
                sym = defn[1]

            name = sym[1]
            res = arrayDataElement(self._offset)
            size = 0
            for i in range(0, count):
                if dtype == "bit":
                    gen = self.do_bitarray(i, count)
                    self._offset += int((i+1) % 8 == 0)
                else:
                    gen = self._types[dtype](self._data, self._offset)
                    self._offset += (gen.size() / 8)
                res.append(gen)

            if count == 1:
                self._generators[name] = res[0]
            else:
                self._generators[name] = res

    def parse_struct_decl(self, struct):
        block = struct[:-1]
        if block[0][0] == "symbol":
            # This is a pre-defined struct
            block = self._user_types[block[0][1]]
        deftype = struct[-1]
        if deftype[0] == "array":
            name = deftype[1][0][1]
            count = int(deftype[1][1][1])
        elif deftype[0] == "symbol":
            name = deftype[1]
            count = 1

        result = arrayDataElement(self._offset)
        for i in range(0, count):
            element = structDataElement(self._data, self._offset, count,
                                        name=name)
            result.append(element)
            tmp = self._generators
            self._generators = element
            self.parse_block(block)
            self._generators = tmp

        if count == 1:
            self._generators[name] = result[0]
        else:
            self._generators[name] = result

    def parse_struct_defn(self, struct):
        name = struct[0][1]
        block = struct[1:]
        self._user_types[name] = block

    def parse_struct(self, struct):
        if struct[0][0] == "struct_defn":
            return self.parse_struct_defn(struct[0][1])
        elif struct[0][0] == "struct_decl":
            return self.parse_struct_decl(struct[0][1])
        else:
            raise Exception("Internal error: What is `%s'?" % struct[0][0])

    def parse_directive(self, directive):
        name = directive[0][0]
        value = directive[0][1][0][1]
        if name == "seekto":
            self._offset = int(value, 0)
        elif name == "seek":
            self._offset += int(value, 0)
        elif name == "printoffset":
            LOG.debug("%s: %i (0x%08X)" %
                      (value[1:-1], self._offset, self._offset))

    def parse_block(self, lang):
        for t, d in lang:
            if t == "struct":
                self.parse_struct(d)
            elif t == "definition":
                self.parse_defn(d)
            elif t == "directive":
                self.parse_directive(d)

    def parse(self, lang):
        self._generators = structDataElement(self._data, self._offset)
        self.parse_block(lang)
        return self._generators


def parse(spec, data, offset=0):
    ast = bitwise_grammar.parse(spec)
    p = Processor(data, offset)
    return p.parse(ast)

if __name__ == "__main__":
    defn = """
struct mytype { u8 foo; };
struct mytype bar;
struct {
  u8 foo;
  u8 highbit:1,
     sixzeros:6,
     lowbit:1;
  char string[3];
  bbcd fourdigits[2];
} mystruct;
"""
    data = "\xab\x7F\x81abc\x12\x34"
    tree = parse(defn, data)

    print repr(tree)

    print "Foo %i" % tree.mystruct.foo
    print "Highbit: %i SixZeros: %i: Lowbit: %i" % (tree.mystruct.highbit,
                                                    tree.mystruct.sixzeros,
                                                    tree.mystruct.lowbit)
    print "String: %s" % tree.mystruct.string
    print "Fourdigits: %i" % tree.mystruct.fourdigits

    import sys
    sys.exit(0)

    test = """
    struct {
      u16 bar;
      u16 baz;
      u8 one;
      u8 upper:2,
         twobit:1,
         onebit:1,
         lower:4;
      u8 array[3];
      char str[3];
      bbcd bcdL[2];
    } foo[2];
    u8 tail;
    """
    data = "\xfe\x10\x00\x08\xFF\x23\x01\x02\x03abc\x34\x89"
    data = (data * 2) + "\x12"
    data = MemoryMap(data)

    ast = bitwise_grammar.parse(test)

    # Just for testing, pretty-print the tree
    pp(ast)

    # Mess with it a little
    p = Processor(data, 0)
    obj = p.parse(ast)
    print "Object: %s" % obj
    print obj["foo"][0]["bcdL"]
    print obj["tail"]
    print obj["foo"][0]["bar"]
    obj["foo"][0]["bar"].set_value(255 << 8)
    obj["foo"][0]["twobit"].set_value(0)
    obj["foo"][0]["onebit"].set_value(1)
    print "%i" % int(obj["foo"][0]["bar"])

    for i in obj["foo"][0]["array"]:
        print int(i)
    obj["foo"][0]["array"][1].set_value(255)

    for i in obj["foo"][0]["bcdL"]:
        print i.get_value()

    int_to_bcd(obj["foo"][0]["bcdL"], 1234)
    print bcd_to_int(obj["foo"][0]["bcdL"])

    set_string(obj["foo"][0]["str"], "xyz")
    print get_string(obj["foo"][0]["str"])

    print repr(data.get_packed())
