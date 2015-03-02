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

from tests.unit import base
from chirp import settings


class TestSettingValues(base.BaseTest):
    def _set_and_test(self, rsv, *values):
        for value in values:
            rsv.set_value(value)
            self.assertEqual(rsv.get_value(), value)

    def _set_and_catch(self, rsv, *values):
        for value in values:
            self.assertRaises(settings.InvalidValueError,
                              rsv.set_value, value)

    def test_radio_setting_value_integer(self):
        value = settings.RadioSettingValueInteger(0, 10, 5)
        self.assertEqual(value.get_value(), 5)
        self._set_and_test(value, 1, 0, 10)
        self._set_and_catch(value, -1, 11)

    def test_radio_setting_value_float(self):
        value = settings.RadioSettingValueFloat(1.0, 10.5, 5.0)
        self.assertEqual(value.get_value(), 5.0)
        self._set_and_test(value, 2.5, 1.0, 10.5)
        self._set_and_catch(value, 0.9, 10.6, -1.5)

    def test_radio_setting_value_boolean(self):
        value = settings.RadioSettingValueBoolean(True)
        self.assertTrue(value.get_value())
        self._set_and_test(value, True, False)

    def test_radio_setting_value_list(self):
        opts = ["Abc", "Def", "Ghi"]
        value = settings.RadioSettingValueList(opts, "Abc")
        self.assertEqual(value.get_value(), "Abc")
        self.assertEqual(int(value), 0)
        self._set_and_test(value, "Def", "Ghi", "Abc")
        self._set_and_catch(value, "Jkl", "Xyz")
        self.assertEqual(value.get_options(), opts)

    def test_radio_setting_value_string(self):
        value = settings.RadioSettingValueString(1, 5, "foo", autopad=False)
        self.assertEqual(value.get_value(), "foo")
        self.assertEqual(str(value), "foo")
        self._set_and_test(value, "a", "abc", "abdef")
        self._set_and_catch(value, "", "abcdefg")

    def test_validate_callback(self):
        class TestException(Exception):
            pass

        value = settings.RadioSettingValueString(0, 5, "foo", autopad=False)

        def test_validate(val):
            if val == "bar":
                raise TestException()
        value.set_validate_callback(test_validate)
        value.set_value("baz")
        self.assertRaises(TestException, value.set_value, "bar")

    def test_changed(self):
        value = settings.RadioSettingValueBoolean(False)
        self.assertFalse(value.changed())
        value.set_value(False)
        self.assertFalse(value.changed())
        value.set_value(True)
        self.assertTrue(value.changed())


class TestSettingContainers(base.BaseTest):
    def test_radio_setting_group(self):
        s1 = settings.RadioSetting("s1", "Setting 1")
        s2 = settings.RadioSetting("s2", "Setting 2")
        s3 = settings.RadioSetting("s3", "Setting 3")
        group = settings.RadioSettingGroup("foo", "Foo Group", s1)
        self.assertEqual(group.get_name(), "foo")
        self.assertEqual(group.get_shortname(), "Foo Group")
        self.assertEqual(group.values(), [s1])
        self.assertEqual(group.keys(), ["s1"])
        group.append(s2)
        self.assertEqual(group.items(), [("s1", s1), ("s2", s2)])
        self.assertEqual(group["s1"], s1)
        group["s3"] = s3
        self.assertEqual(group.values(), [s1, s2, s3])
        self.assertEqual(group.keys(), ["s1", "s2", "s3"])
        self.assertEqual([x for x in group], [s1, s2, s3])

        def set_dupe():
            group["s3"] = s3
        self.assertRaises(KeyError, set_dupe)

    def test_radio_setting(self):
        val = settings.RadioSettingValueBoolean(True)
        rs = settings.RadioSetting("foo", "Foo", val)
        self.assertEqual(rs.value, val)
        rs.value = False
        self.assertEqual(val.get_value(), False)

    def test_radio_setting_multi(self):
        val1 = settings.RadioSettingValueBoolean(True)
        val2 = settings.RadioSettingValueBoolean(False)
        rs = settings.RadioSetting("foo", "Foo", val1, val2)
        self.assertEqual(rs[0], val1)
        self.assertEqual(rs[1], val2)
        rs[0] = False
        rs[1] = True
        self.assertEqual(val1.get_value(), False)
        self.assertEqual(val2.get_value(), True)

    def test_apply_callback(self):
        class TestException(Exception):
            pass

        rs = settings.RadioSetting("foo", "Foo")
        self.assertFalse(rs.has_apply_callback())

        def test_cb(setting, data1, data2):
            self.assertEqual(setting, rs)
            self.assertEqual(data1, "foo")
            self.assertEqual(data2, "bar")
            raise TestException()
        rs.set_apply_callback(test_cb, "foo", "bar")
        self.assertTrue(rs.has_apply_callback())
        self.assertRaises(TestException, rs.run_apply_callback)
