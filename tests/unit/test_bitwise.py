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

import unittest
from chirp import bitwise

class BaseTest(unittest.TestCase):
    def _compare_structure(self, obj, primitive):
        for key, value in primitive.iteritems():
            if isinstance(value, dict):
                self._compare_structure(getattr(obj, key), value)
            else:
                self.assertEqual(type(value)(getattr(obj, key)), value)

class TestBitwiseBaseIntTypes(BaseTest):
    def _test_type(self, datatype, data, value):
        obj = bitwise.parse("%s foo;" % datatype, data)
        self.assertEqual(int(obj.foo), value)
        self.assertEqual(obj.foo.size(), len(data) * 8)

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

class TestBitfieldTypes(BaseTest):
    def test_bitfield_u8(self):
        defn = "u8 foo:4, bar:4;"
        obj = bitwise.parse(defn, "\x12")
        self.assertEqual(obj.foo, 1)
        self.assertEqual(obj.bar, 2)
        self.assertEqual(obj.foo.size(), 4)
        self.assertEqual(obj.bar.size(), 4)

    def _test_bitfield_16(self, variant, data):
        defn = "u%s16 foo:4, bar:8, baz:4;" % variant
        obj = bitwise.parse(defn, data)
        self.assertEqual(int(obj.foo), 1)
        self.assertEqual(int(obj.bar), 0x23)
        self.assertEqual(int(obj.baz), 4)
        self.assertEqual(obj.foo.size(), 4)
        self.assertEqual(obj.bar.size(), 8)
        self.assertEqual(obj.baz.size(), 4)

    def test_bitfield_u16(self):
        self._test_bitfield_16("", "\x12\x34")

    def test_bitfield_ul16(self):
        self._test_bitfield_16('l', "\x34\x12")

    def _test_bitfield_24(self, variant, data):
        defn = "u%s24 foo:12, bar:6, baz:6;" % variant
        obj = bitwise.parse(defn, data)
        self.assertEqual(int(obj.foo), 4)
        self.assertEqual(int(obj.bar), 3)
        self.assertEqual(int(obj.baz), 2)
        self.assertEqual(obj.foo.size(), 12)
        self.assertEqual(obj.bar.size(), 6)
        self.assertEqual(obj.baz.size(), 6)

    def test_bitfield_u24(self):
        self._test_bitfield_24("", "\x00\x40\xC2")

    def test_bitfield_ul24(self):
        self._test_bitfield_24("l", "\xC2\x40\x00")

class TestBitType(BaseTest):
    def test_bit_array(self):
        defn = "bit foo[24];"
        obj = bitwise.parse(defn, "\x00\x80\x01")
        for i, v in [(0, False), (8, True), (23, True)]:
            self.assertEqual(bool(obj.foo[i]), v)

    def test_bit_array_fail(self):
        self.assertRaises(ValueError, bitwise.parse, "bit foo[23];", "000")

class TestBitwiseBCDTypes(BaseTest):
    def _test_def(self, definition, name, data, value):
        obj = bitwise.parse(definition, data)
        self.assertEqual(int(getattr(obj, name)), value)
        self.assertEqual(getattr(obj, name).size(), len(data) * 8)

    def test_bbcd(self):
        self._test_def("bbcd foo;", "foo", "\x12", 12)

    def test_lbcd(self):
        self._test_def("lbcd foo;", "foo", "\x12", 21)

    def test_bbcd_array(self):
        self._test_def("bbcd foo[2];", "foo", "\x12\x34", 1234)

    def test_lbcd_array(self):
        self._test_def("lbcd foo[2];", "foo", "\x12\x34", 3412)

class TestBitwiseCharTypes(BaseTest):
    def test_char(self):
        obj = bitwise.parse("char foo;", "c")
        self.assertEqual(str(obj.foo), "c")
        self.assertEqual(obj.foo.size(), 8)

    def test_string(self):
        obj = bitwise.parse("char foo[6];", "foobar")
        self.assertEqual(str(obj.foo), "foobar")
        self.assertEqual(obj.foo.size(), 8 * 6)

class TestBitwiseStructTypes(BaseTest):
    def _test_def(self, definition, data, primitive):
        obj = bitwise.parse(definition, data)
        self._compare_structure(obj, primitive)
        self.assertEqual(obj.size(), len(data) * 8)

    def test_struct_one_element(self):
        defn = "struct { u8 bar; } foo;"
        value = {"foo" : {"bar": 128}}
        self._test_def(defn, "\x80", value)

    def test_struct_two_elements(self):
        defn = "struct { u8 bar; u16 baz; } foo;"
        value = {"foo" : {"bar": 128, "baz": 256}}
        self._test_def(defn, "\x80\x01\x00", value)

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
