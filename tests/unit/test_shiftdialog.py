import unittest
try:
    import mox
except ImportError:
    from mox3 import mox

from tests.unit import base
from chirp import chirp_common
from chirp import errors

shiftdialog = None


class FakeRadio(object):
    def __init__(self, *memories):
        self._mems = {}
        for location in memories:
            mem = chirp_common.Memory()
            mem.number = location
            self._mems[location] = mem
        self._features = chirp_common.RadioFeatures()

    def get_features(self):
        return self._features

    def get_memory(self, location):
        try:
            return self._mems[location]
        except KeyError:
            mem = chirp_common.Memory()
            mem.number = location
            mem.empty = True
            return mem

    def set_memory(self, memory):
        self._mems[memory.number] = memory

    def erase_memory(self, location):
        del self._mems[location]


class FakeRadioThread(object):
    def __init__(self, radio):
        self.radio = radio

    def lock(self):
        pass

    def unlock(self):
        pass


class ShiftDialogTest(base.BaseTest):
    def setUp(self):
        global shiftdialog
        super(ShiftDialogTest, self).setUp()
        base.mock_gtk()
        from chirp.ui import shiftdialog as shiftdialog_module
        shiftdialog = shiftdialog_module

    def tearDown(self):
        super(ShiftDialogTest, self).tearDown()
        base.unmock_gtk()

    def _test_hole(self, fn, starting, arg, expected):
        radio = FakeRadio(*tuple(starting))
        radio.get_features().memory_bounds = (0, 5)
        sd = shiftdialog.ShiftDialog(FakeRadioThread(radio))

        if isinstance(arg, tuple):
            getattr(sd, fn)(*arg)
        else:
            getattr(sd, fn)(arg)

        self.assertEqual(expected, sorted(radio._mems.keys()))
        self.assertEqual(expected,
                         sorted([mem.number for mem in radio._mems.values()]))

    def _test_delete_hole(self, starting, arg, expected):
        self._test_hole('_delete_hole', starting, arg, expected)

    def _test_insert_hole(self, starting, pos, expected):
        self._test_hole('_insert_hole', starting, pos, expected)

    def test_delete_hole_with_hole(self):
        self._test_delete_hole([1, 2, 3, 5],
                               2,
                               [1, 2, 5])

    def test_delete_hole_without_hole(self):
        self._test_delete_hole([1, 2, 3, 4, 5],
                               2,
                               [1, 2, 3, 4])

    def test_delete_hole_with_all(self):
        self._test_delete_hole([1, 2, 3, 5],
                               (2, True),
                               [1, 2, 4])

    def test_delete_hole_with_all_full(self):
        self._test_delete_hole([1, 2, 3, 4, 5],
                               (2, True),
                               [1, 2, 3, 4])

    def test_insert_hole_with_space(self):
        self._test_insert_hole([1, 2, 3, 5],
                               2,
                               [1, 3, 4, 5])

    def test_insert_hole_without_space(self):
        self.assertRaises(errors.InvalidMemoryLocation,
                          self._test_insert_hole, [1, 2, 3, 4, 5], 2, [])
