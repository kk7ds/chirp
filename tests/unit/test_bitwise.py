# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

import struct
import unittest
from chirp import bitwise
from chirp import memmap


class BaseTest(unittest.TestCase):
    def _compare_structure(self, obj, primitive):
        for key, value in primitive.iteritems():
            if isinstance(value, dict):
                self._compare_structure(getattr(obj, key), value)
            else:
                self.assertEqual(type(value)(getattr(obj, key)), value)


class TestBitwiseBaseIntTypes(BaseTest):
    def _test_type(self, datatype, _data, value):
        data = memmap.MemoryMap(_data)
        obj = bitwise.parse("%s foo;" % datatype, data)
        self.assertEqual(int(obj.foo), value)
        self.assertEqual(obj.foo.size(), len(data) * 8)

        obj.foo = 0
        self.assertEqual(int(obj.foo), 0)
        self.assertEqual(data.get_packed(), ("\x00" * (obj.size() / 8)))

        obj.foo = value
        self.assertEqual(int(obj.foo), value)
        self.assertEqual(data.get_packed(), _data)

    def test_type_u8(self):
        self._test_type("u8", "\x80", 128)

    def test_type_u16(self):
        self._test_type("u16", "\x01\x00", 256)

    def test_type_u24(self):
        self._test_type("u24", "\x80\x00\x00", 2**23)

    def test_type_u32(self):
        self._test_type("u32", "\x80\x00\x00\x00", 2**31)

    def test_type_ul16(self):
        self._test_type("ul16", "\x00\x01", 256)

    def test_type_ul24(self):
        self._test_type("ul24", "\x00\x00\x80", 2**23)

    def test_type_ul32(self):
        self._test_type("ul32", "\x00\x00\x00\x80", 2**31)

    def test_int_array(self):
        data = memmap.MemoryMap('\x00\x01\x02\x03')
        obj = bitwise.parse('u8 foo[4];', data)
        for i in range(4):
            self.assertEqual(i, obj.foo[i])
            obj.foo[i] = i * 2
        self.assertEqual('\x00\x02\x04\x06', data.get_packed())

    def test_int_array(self):
        data = memmap.MemoryMap('\x00\x01\x02\x03')
        obj = bitwise.parse('u8 foo[4];', data)
        for i in range(4):
            self.assertEqual(i, obj.foo[i])
            obj.foo[i] = i * 2
        self.assertEqual('\x00\x02\x04\x06', data.get_packed())


class TestBitfieldTypes(BaseTest):
    def test_bitfield_u8(self):
        defn = "u8 foo:4, bar:4;"
        data = memmap.MemoryMap("\x12")
        obj = bitwise.parse(defn, data)
        self.assertEqual(obj.foo, 1)
        self.assertEqual(obj.bar, 2)
        self.assertEqual(obj.foo.size(), 4)
        self.assertEqual(obj.bar.size(), 4)
        obj.foo = 0x8
        obj.bar = 0x1
        self.assertEqual(data.get_packed(), "\x81")

    def _test_bitfield_16(self, variant, data):
        defn = "u%s16 foo:4, bar:8, baz:4;" % variant
        data = memmap.MemoryMap(data)
        obj = bitwise.parse(defn, data)
        self.assertEqual(int(obj.foo), 1)
        self.assertEqual(int(obj.bar), 0x23)
        self.assertEqual(int(obj.baz), 4)
        self.assertEqual(obj.foo.size(), 4)
        self.assertEqual(obj.bar.size(), 8)
        self.assertEqual(obj.baz.size(), 4)
        obj.foo = 0x2
        obj.bar = 0x11
        obj.baz = 0x3
        if variant == "l":
            self.assertEqual(data.get_packed(), "\x13\x21")
        else:
            self.assertEqual(data.get_packed(), "\x21\x13")

    def test_bitfield_u16(self):
        self._test_bitfield_16("", "\x12\x34")

    def test_bitfield_ul16(self):
        self._test_bitfield_16('l', "\x34\x12")

    def _test_bitfield_24(self, variant, data):
        defn = "u%s24 foo:12, bar:6, baz:6;" % variant
        data = memmap.MemoryMap(data)
        obj = bitwise.parse(defn, data)
        self.assertEqual(int(obj.foo), 4)
        self.assertEqual(int(obj.bar), 3)
        self.assertEqual(int(obj.baz), 2)
        self.assertEqual(obj.foo.size(), 12)
        self.assertEqual(obj.bar.size(), 6)
        self.assertEqual(obj.baz.size(), 6)
        obj.foo = 1
        obj.bar = 2
        obj.baz = 3
        if variant == 'l':
            self.assertEqual(data.get_packed(), "\x83\x10\x00")
        else:
            self.assertEqual(data.get_packed(), "\x00\x10\x83")

    def test_bitfield_u24(self):
        self._test_bitfield_24("", "\x00\x40\xC2")

    def test_bitfield_ul24(self):
        self._test_bitfield_24("l", "\xC2\x40\x00")


class TestBitType(BaseTest):
    def test_bit_array(self):
        defn = "bit foo[24];"
        data = memmap.MemoryMap("\x00\x80\x01")
        obj = bitwise.parse(defn, data)
        for i, v in [(0, False), (8, True), (23, True)]:
            self.assertEqual(bool(obj.foo[i]), v)
        for i in range(0, 24):
            obj.foo[i] = i % 2
        self.assertEqual(data.get_packed(), "\x55\x55\x55")

    def test_bit_array_fail(self):
        self.assertRaises(ValueError, bitwise.parse, "bit foo[23];", "000")


class TestBitwiseBCDTypes(BaseTest):
    def _test_def(self, definition, name, _data, value):
        data = memmap.MemoryMap(_data)
        obj = bitwise.parse(definition, data)
        self.assertEqual(int(getattr(obj, name)), value)
        self.assertEqual(getattr(obj, name).size(), len(_data) * 8)
        setattr(obj, name, 0)
        self.assertEqual(data.get_packed(), ("\x00" * len(_data)))
        setattr(obj, name, 42)
        if definition.startswith("b"):
            expected = (len(_data) == 2 and "\x00" or "") + "\x42"
        else:
            expected = "\x42" + (len(_data) == 2 and "\x00" or "")
        raw = data.get_packed()
        self.assertEqual(raw, expected)

    def test_bbcd(self):
        self._test_def("bbcd foo;", "foo", "\x12", 12)

    def test_lbcd(self):
        self._test_def("lbcd foo;", "foo", "\x12", 12)

    def test_bbcd_array(self):
        self._test_def("bbcd foo[2];", "foo", "\x12\x34", 1234)

    def test_lbcd_array(self):
        self._test_def("lbcd foo[2];", "foo", "\x12\x34", 3412)


class TestBitwiseCharTypes(BaseTest):
    def test_char(self):
        data = memmap.MemoryMap("c")
        obj = bitwise.parse("char foo;", data)
        self.assertEqual(str(obj.foo), "c")
        self.assertEqual(obj.foo.size(), 8)
        obj.foo = "d"
        self.assertEqual(data.get_packed(), "d")

    def test_string(self):
        data = memmap.MemoryMap("foobar")
        obj = bitwise.parse("char foo[6];", data)
        self.assertEqual(str(obj.foo), "foobar")
        self.assertEqual(obj.foo.size(), 8 * 6)
        obj.foo = "bazfoo"
        self.assertEqual(data.get_packed(), "bazfoo")

    def test_string_invalid_chars(self):
        data = memmap.MemoryMap("\xFFoobar1")
        obj = bitwise.parse("struct {char foo[7];} bar;", data)
        self.assertIn('\\xffoobar1', repr(obj.bar))

    def test_string_wrong_length(self):
        data = memmap.MemoryMap("foobar")
        obj = bitwise.parse("char foo[6];", data)
        self.assertRaises(ValueError, setattr, obj, "foo", "bazfo")
        self.assertRaises(ValueError, setattr, obj, "foo", "bazfooo")


class TestBitwiseStructTypes(BaseTest):
    def _test_def(self, definition, data, primitive):
        obj = bitwise.parse(definition, data)
        self._compare_structure(obj, primitive)
        self.assertEqual(obj.size(), len(data) * 8)

    def test_struct_one_element(self):
        defn = "struct { u8 bar; } foo;"
        value = {"foo": {"bar": 128}}
        self._test_def(defn, "\x80", value)

    def test_struct_two_elements(self):
        defn = "struct { u8 bar; u16 baz; } foo;"
        value = {"foo": {"bar": 128, "baz": 256}}
        self._test_def(defn, "\x80\x01\x00", value)

    def test_struct_writes(self):
        data = memmap.MemoryMap("..")
        defn = "struct { u8 bar; u8 baz; } foo;"
        obj = bitwise.parse(defn, data)
        obj.foo.bar = 0x12
        obj.foo.baz = 0x34
        self.assertEqual(data.get_packed(), "\x12\x34")


class TestBitwiseSeek(BaseTest):
    def test_seekto(self):
        defn = "#seekto 4; char foo;"
        obj = bitwise.parse(defn, "abcdZ")
        self.assertEqual(str(obj.foo), "Z")

    def test_seek(self):
        defn = "char foo; #seek 3; char bar;"
        obj = bitwise.parse(defn, "AbcdZ")
        self.assertEqual(str(obj.foo), "A")
        self.assertEqual(str(obj.bar), "Z")


class TestBitwiseErrors(BaseTest):
    def test_missing_semicolon(self):
        self.assertRaises(SyntaxError, bitwise.parse, "u8 foo", "")


class TestBitwiseComments(BaseTest):
    def test_comment_inline_cppstyle(self):
        obj = bitwise.parse('u8 foo; // test', '\x10')
        self.assertEqual(16, obj.foo)

    def test_comment_cppstyle(self):
        obj = bitwise.parse('// Test this\nu8 foo;', '\x10')
        self.assertEqual(16, obj.foo)
