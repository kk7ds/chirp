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

from builtins import bytes

import unittest
from unittest import mock


from chirp import bitwise
from chirp import memmap


class BaseTest(unittest.TestCase):
    def _compare_structure(self, obj, primitive):
        for key, value in primitive.items():
            if isinstance(value, dict):
                self._compare_structure(getattr(obj, key), value)
            else:
                self.assertEqual(type(value)(getattr(obj, key)), value)


class TestMemoryMapCoherence(BaseTest):
    def test_byte_char_coherence(self):
        charmmap = memmap.MemoryMap('00')
        # This will to a get_byte_compatible() from chars
        obj = bitwise.parse('char foo[2];', charmmap)
        self.assertEqual('00', str(obj.foo))
        obj.foo = '11'
        # The above assignment happens on the byte-compatible mmap,
        # make sure it is still visible in the charmmap we know about.
        # This confirms that get_byte_compatible() links the backing
        # store of the original mmap to the new one.
        self.assertEqual('11', charmmap.get_packed())


class TestBitwiseBaseIntTypes(BaseTest):
    def _test_type(self, datatype, _data, value):
        data = memmap.MemoryMapBytes(bytes(_data))
        obj = bitwise.parse("%s foo;" % datatype, data)
        self.assertEqual(int(obj.foo), value)
        self.assertEqual(obj.foo.size(), len(data) * 8)

        obj.foo = 0
        self.assertEqual(int(obj.foo), 0)
        self.assertEqual(data.get_packed(), (b"\x00" * (obj.size() // 8)))

        obj.foo = value
        self.assertEqual(int(obj.foo), value)
        self.assertEqual(data.get_packed(), _data)

        obj.foo = 7
        # Compare against the equivalent real division so we get consistent
        # results on py2 and py3
        self.assertEqual(7 // 2, obj.foo // 2)
        self.assertEqual(7 / 2, obj.foo / 2)
        self.assertEqual(7 / 2.0, obj.foo / 2.0)

    def test_type_u8(self):
        self._test_type("u8", b"\x80", 128)

    def test_type_u16(self):
        self._test_type("u16", b"\x01\x00", 256)

    def test_type_u24(self):
        self._test_type("u24", b"\x80\x00\x00", 2**23)

    def test_type_u32(self):
        self._test_type("u32", b"\x80\x00\x00\x00", 2**31)

    def test_type_ul16(self):
        self._test_type("ul16", b"\x00\x01", 256)

    def test_type_ul24(self):
        self._test_type("ul24", b"\x00\x00\x80", 2**23)

    def test_type_ul32(self):
        self._test_type("ul32", b"\x00\x00\x00\x80", 2**31)

    def test_int_array(self):
        data = memmap.MemoryMapBytes(bytes(b'\x00\x01\x02\x03'))
        obj = bitwise.parse('u8 foo[4];', data)
        for i in range(4):
            self.assertEqual(i, obj.foo[i])
            obj.foo[i] = i * 2
        self.assertEqual(b'\x00\x02\x04\x06', data.get_packed())

    def test_int_array_set_raw(self):
        data = memmap.MemoryMapBytes(bytes(b'\x00\x01\x02\x03'))
        obj = bitwise.parse('u8 foo[4];', data)
        obj.foo.set_raw(b'\x09\x08\x07\x06')
        self.assertEqual(9, obj.foo[0])
        self.assertEqual(8, obj.foo[1])
        self.assertEqual(7, obj.foo[2])
        self.assertEqual(6, obj.foo[3])

        obj = bitwise.parse('u16 foo[2];', data)
        obj.foo.set_raw(b'\x00\x01\x00\x02')
        self.assertEqual(1, obj.foo[0])
        self.assertEqual(2, obj.foo[1])

        with self.assertRaises(AssertionError):
            obj.foo.set_raw(b'123')

        with self.assertRaises(AssertionError):
            obj.foo.set_raw(b'12345')


class TestBitfieldTypes(BaseTest):
    def test_bitfield_u8(self):
        defn = "u8 foo:4, bar:4;"
        data = memmap.MemoryMapBytes(bytes(b"\x12"))
        obj = bitwise.parse(defn, data)
        self.assertEqual(obj.foo, 1)
        self.assertEqual(obj.bar, 2)
        self.assertEqual(obj.foo.size(), 4)
        self.assertEqual(obj.bar.size(), 4)
        obj.foo = 0x8
        obj.bar = 0x1
        self.assertEqual(data.get_packed(), b"\x81")

    def _test_bitfield_16(self, variant, data):
        defn = "u%s16 foo:4, bar:8, baz:4;" % variant
        data = memmap.MemoryMapBytes(bytes(data))
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
            self.assertEqual(data.get_packed(), b"\x13\x21")
        else:
            self.assertEqual(data.get_packed(), b"\x21\x13")

    def test_bitfield_u16(self):
        self._test_bitfield_16("", b"\x12\x34")

    def test_bitfield_ul16(self):
        self._test_bitfield_16('l', b"\x34\x12")

    def _test_bitfield_24(self, variant, data):
        defn = "u%s24 foo:12, bar:6, baz:6;" % variant
        data = memmap.MemoryMapBytes(bytes(data))
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
            self.assertEqual(data.get_packed(), b"\x83\x10\x00")
        else:
            self.assertEqual(data.get_packed(), b"\x00\x10\x83")

    def test_bitfield_u24(self):
        self._test_bitfield_24("", b"\x00\x40\xC2")

    def test_bitfield_ul24(self):
        self._test_bitfield_24("l", b"\xC2\x40\x00")


class TestBitType(BaseTest):
    def test_bit_array(self):
        defn = "bit foo[24];"
        data = memmap.MemoryMapBytes(bytes(b"\x00\x80\x01"))
        obj = bitwise.parse(defn, data)
        for i, v in [(0, False), (8, True), (23, True)]:
            self.assertEqual(bool(obj.foo[i]), v)
        for i in range(0, 24):
            obj.foo[i] = i % 2
        self.assertEqual(data.get_packed(), b"\x55\x55\x55")

    def test_lbit_array(self):
        defn = "lbit foo[24];"
        data = memmap.MemoryMapBytes(bytes(b"\x00\x20\x80"))
        obj = bitwise.parse(defn, data)
        for i, v in [(0, False), (13, True), (23, True)]:
            self.assertEqual(bool(obj.foo[i]), v)
        for i in range(0, 24):
            obj.foo[i] = i % 2
        self.assertEqual(data.get_packed(), b"\xAA\xAA\xAA")

    def test_bit_array_fail(self):
        self.assertRaises(ValueError, bitwise.parse, "bit foo[23];", b"000")


class TestBitwiseBCDTypes(BaseTest):
    def _test_def(self, definition, name, _data, value):
        data = memmap.MemoryMapBytes(bytes(_data))
        obj = bitwise.parse(definition, data)
        self.assertEqual(int(getattr(obj, name)), value)
        self.assertEqual(getattr(obj, name).size(), len(_data) * 8)
        setattr(obj, name, 0)
        self.assertEqual(data.get_packed(), (b"\x00" * len(_data)))
        setattr(obj, name, 42)
        if definition.startswith("b"):
            expected = (len(_data) == 2 and b"\x00" or b"") + b"\x42"
        else:
            expected = b"\x42" + (len(_data) == 2 and b"\x00" or b"")
        raw = data.get_packed()
        self.assertEqual(raw, expected)

    def test_bbcd(self):
        self._test_def("bbcd foo;", "foo", b"\x12", 12)

    def test_lbcd(self):
        self._test_def("lbcd foo;", "foo", b"\x12", 12)

    def test_bbcd_array(self):
        self._test_def("bbcd foo[2];", "foo", b"\x12\x34", 1234)

    def test_lbcd_array(self):
        self._test_def("lbcd foo[2];", "foo", b"\x12\x34", 3412)


class TestBitwiseCharTypes(BaseTest):
    def test_char(self):
        data = memmap.MemoryMapBytes(bytes(b"c"))
        obj = bitwise.parse("char foo;", data)
        self.assertEqual(str(obj.foo), "c")
        self.assertEqual(obj.foo.size(), 8)
        obj.foo = "d"
        self.assertEqual(data.get_packed(), b"d")

    def test_string(self):
        data = memmap.MemoryMapBytes(bytes(b"foobar"))
        obj = bitwise.parse("char foo[6];", data)
        self.assertEqual(str(obj.foo), "foobar")
        self.assertEqual(obj.foo.size(), 8 * 6)
        obj.foo = "bazfoo"
        self.assertEqual(data.get_packed(), b"bazfoo")

    def test_string_invalid_chars(self):
        data = memmap.MemoryMapBytes(bytes(b"\xFFoobar1"))
        obj = bitwise.parse("struct {char foo[7];} bar;", data)

        expected = '\xffoobar1'

        self.assertIn(expected, repr(obj.bar))

    def test_string_wrong_length(self):
        data = memmap.MemoryMapBytes(bytes(b"foobar"))
        obj = bitwise.parse("char foo[6];", data)
        self.assertRaises(ValueError, setattr, obj, "foo", "bazfo")
        self.assertRaises(ValueError, setattr, obj, "foo", "bazfooo")

    def test_string_with_various_input_types(self):
        data = memmap.MemoryMapBytes(bytes(b"foobar"))
        obj = bitwise.parse("char foo[6];", data)
        self.assertEqual('foobar', str(obj.foo))
        self.assertEqual(6, len(b'barfoo'))
        obj.foo = b'barfoo'
        self.assertEqual('barfoo', str(obj.foo))
        obj.foo = [ord(c) for c in 'fffbbb']
        self.assertEqual('fffbbb', str(obj.foo))

    def test_string_get_raw(self):
        data = memmap.MemoryMapBytes(bytes(b"foobar"))
        obj = bitwise.parse("char foo[6];", data)
        self.assertEqual(b'foobar', obj.foo.get_raw())
        self.assertEqual('foobar', obj.foo.get_raw(asbytes=False))


class TestBitwiseStructTypes(BaseTest):
    def _test_def(self, definition, data, primitive):
        obj = bitwise.parse(definition, data)
        self._compare_structure(obj, primitive)
        self.assertEqual(obj.size(), len(data) * 8)

    def test_struct_one_element(self):
        defn = "struct { u8 bar; } foo;"
        value = {"foo": {"bar": 128}}
        self._test_def(defn, b"\x80", value)

    def test_struct_two_elements(self):
        defn = "struct { u8 bar; u16 baz; } foo;"
        value = {"foo": {"bar": 128, "baz": 256}}
        self._test_def(defn, b"\x80\x01\x00", value)

    def test_struct_writes(self):
        data = memmap.MemoryMapBytes(bytes(b".."))
        defn = "struct { u8 bar; u8 baz; } foo;"
        obj = bitwise.parse(defn, data)
        obj.foo.bar = 0x12
        obj.foo.baz = 0x34
        self.assertEqual(data.get_packed(), b"\x12\x34")

    def test_struct_get_raw(self):
        data = memmap.MemoryMapBytes(bytes(b".."))
        defn = "struct { u8 bar; u8 baz; } foo;"
        obj = bitwise.parse(defn, data)
        self.assertEqual(b'..', obj.get_raw())
        self.assertEqual('..', obj.get_raw(asbytes=False))

    def test_struct_get_raw_small(self):
        data = memmap.MemoryMapBytes(bytes(b"."))
        defn = "struct { u8 bar; } foo;"
        obj = bitwise.parse(defn, data)
        self.assertEqual(b'.', obj.get_raw())
        self.assertEqual('.', obj.get_raw(asbytes=False))

    def test_struct_set_raw(self):
        data = memmap.MemoryMapBytes(bytes(b"."))
        defn = "struct { u8 bar; } foo;"
        obj = bitwise.parse(defn, data)
        obj.set_raw(b'1')
        self.assertEqual(b'1', data.get_packed())
        obj.set_raw('2')
        self.assertEqual(b'2', data.get_packed())

    @mock.patch.object(bitwise.LOG, 'error')
    def test_struct_duplicate(self, mock_log):
        bitwise.parse('struct\n{ u8 foo; u8 foo1:2, foo:4, foo3:2;} bar;',
                      memmap.MemoryMapBytes(b'\x00' * 128))
        bitwise.parse('struct\n{ u8 foo; u8 foo;} bar;',
                      memmap.MemoryMapBytes(b'\x00' * 128))
        bitwise.parse('struct\n{ u8 foo; u8 foo[2];} bar;',
                      memmap.MemoryMapBytes(b'\x00' * 128))
        self.assertEqual(3, mock_log.call_count)

    def test_struct_fill_raw(self):
        data = memmap.MemoryMapBytes(bytes(b"..."))
        defn = "struct { u8 bar; u16 baz; } foo;"
        obj = bitwise.parse(defn, data)
        obj.fill_raw(b'\xAA')
        self.assertEqual(0xAA, obj.foo.bar)
        self.assertEqual(0xAAAA, obj.foo.baz)
        obj.foo.fill_raw(b'\xBB')
        self.assertEqual(0xBB, obj.foo.bar)
        self.assertEqual(0xBBBB, obj.foo.baz)
        obj.foo.bar.fill_raw(b'\xCC')
        self.assertEqual(0xCC, obj.foo.bar)
        self.assertEqual(0xBBBB, obj.foo.baz)

        self.assertRaises(AssertionError, obj.fill_raw, '1')
        self.assertRaises(AssertionError, obj.fill_raw, b'AB')
        self.assertRaises(AssertionError, obj.fill_raw, False)


class TestBitwisePrintoffset(BaseTest):
    @mock.patch.object(bitwise.LOG, 'debug')
    def test_printoffset(self, mock_log):
        defn = 'u8 foo; u16 bar; #printoffset "bar";'
        bitwise.parse(defn, b"abcdZ")
        mock_log.assert_called_once_with('bar: 3 (0x00000003)')


class TestBitwiseSeek(BaseTest):
    def test_seekto(self):
        defn = "#seekto 4; char foo;"
        obj = bitwise.parse(defn, b"abcdZ")
        self.assertEqual(str(obj.foo), "Z")

    def test_seek(self):
        defn = "char foo; #seek 3; char bar;"
        obj = bitwise.parse(defn, b"AbcdZ")
        self.assertEqual(str(obj.foo), "A")
        self.assertEqual(str(obj.bar), "Z")


class TestBitwiseErrors(BaseTest):
    def test_missing_semicolon(self):
        self.assertRaises(SyntaxError, bitwise.parse, "u8 foo", "")


class TestBitwiseComments(BaseTest):
    def test_comment_inline_cppstyle(self):
        obj = bitwise.parse('u8 foo; // test', b'\x10')
        self.assertEqual(16, obj.foo)

    def test_comment_cppstyle(self):
        obj = bitwise.parse('// Test this\nu8 foo;', b'\x10')
        self.assertEqual(16, obj.foo)


class TestBitwiseStringEncoders(BaseTest):
    def test_encode_bytes(self):
        self.assertEqual(b'foobar\x00',
                         bitwise.string_straight_encode('foobar\x00'))

    def test_decode_bytes(self):
        self.assertEqual('foobar\x00',
                         bitwise.string_straight_decode(b'foobar\x00'))


class TestPath(BaseTest):
    def test_get_path(self):
        fmt = ("u8 foo;"
               "u8 bar[2];"
               "struct {"
               "  u8 foo;"
               "  u8 bar[2];"
               "  u8 baz1:4,"
               "     baz2:4;"
               "  struct {"
               "    u16 childitem;"
               "  } child;"
               "} structure[2];")
        obj = bitwise.parse(fmt, memmap.MemoryMapBytes(b'\x00' * 128))
        obj.structure[0].bar[1] = 123
        obj.structure[1].child.childitem = 456
        self.assertEqual(123, obj.get_path('.structure[0].bar[1]'))
        self.assertEqual(456, obj.get_path('structure[1].child.childitem'))
