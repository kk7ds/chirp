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
from chirp import chirp_common
from chirp.drivers import icf


class TestBaseMapping(base.BaseTest):
    CLS = chirp_common.MemoryMapping

    def test_mapping(self):
        model = chirp_common.MappingModel(None, 'Foo')
        mapping = self.CLS(model, 1, 'Foo')
        self.assertEqual(str(mapping), 'Foo')
        self.assertEqual(mapping.get_name(), 'Foo')
        self.assertEqual(mapping.get_index(), 1)
        self.assertEqual(repr(mapping), '%s-1' % self.CLS.__name__)
        self.assertEqual(mapping._model, model)

    def test_mapping_eq(self):
        mapping1 = self.CLS(None, 1, 'Foo')
        mapping2 = self.CLS(None, 1, 'Bar')
        mapping3 = self.CLS(None, 2, 'Foo')

        self.assertEqual(mapping1, mapping2)
        self.assertNotEqual(mapping1, mapping3)


class TestBaseBank(TestBaseMapping):
    CLS = chirp_common.Bank


class _TestBaseClass(base.BaseTest):
    ARGS = tuple()

    def setUp(self):
        super(_TestBaseClass, self).setUp()
        self.model = self.CLS(*self.ARGS)

    def _test_base(self, method, *args):
        self.assertRaises(NotImplementedError,
                          getattr(self.model, method), *args)


class TestBaseMappingModel(_TestBaseClass):
    CLS = chirp_common.MappingModel
    ARGS = tuple([None, 'Foo'])

    def test_base_class(self):
        methods = [('get_num_mappings', ()),
                   ('get_mappings', ()),
                   ('add_memory_to_mapping', (None, None)),
                   ('remove_memory_from_mapping', (None, None)),
                   ('get_mapping_memories', (None,)),
                   ('get_memory_mappings', (None,)),
                   ]
        for method, args in methods:
            self._test_base(method, *args)

    def test_get_name(self):
        self.assertEqual(self.model.get_name(), 'Foo')


class TestBaseBankModel(TestBaseMappingModel):
    ARGS = tuple([None])
    CLS = chirp_common.BankModel

    def test_get_name(self):
        self.assertEqual(self.model.get_name(), 'Banks')


class TestBaseMappingModelIndexInterface(_TestBaseClass):
    CLS = chirp_common.MappingModelIndexInterface

    def test_base_class(self):
        methods = [('get_index_bounds', ()),
                   ('get_memory_index', (None, None)),
                   ('set_memory_index', (None, None, None)),
                   ('get_next_mapping_index', (None,)),
                   ]
        for method, args in methods:
            self._test_base(method, *args)


class TestIcomBanks(TestBaseMapping):
    def test_icom_bank(self):
        bank = icf.IcomBank(None, 1, 'Foo')
        # IcomBank has an index attribute used by IcomBankModel
        self.assertTrue(hasattr(bank, 'index'))


class TestIcomBankModel(base.BaseTest):
    CLS = icf.IcomBankModel

    def _get_rf(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 10)
        return rf

    def setUp(self):
        super(TestIcomBankModel, self).setUp()

        class FakeRadio(icf.IcomCloneModeRadio):
            _num_banks = 10
            _bank_index_bounds = (0, 10)

            def get_features(the_radio):
                return self._get_rf()

            def _set_bank(self, number, index):
                pass

            def _get_bank(self, number):
                pass

            def _get_bank_index(self, number):
                pass

            def _set_bank_index(self, number, index):
                pass

            def get_memory(self, number):
                pass

        self._radio = FakeRadio(None)
        self._model = self.CLS(self._radio)
        self.mox.StubOutWithMock(self._radio, '_set_bank')
        self.mox.StubOutWithMock(self._radio, '_get_bank')
        self.mox.StubOutWithMock(self._radio, '_set_bank_index')
        self.mox.StubOutWithMock(self._radio, '_get_bank_index')
        self.mox.StubOutWithMock(self._radio, 'get_memory')

    def test_get_num_mappings(self):
        self.assertEqual(self._model.get_num_mappings(), 10)

    def test_get_mappings(self):
        banks = self._model.get_mappings()
        self.assertEqual(len(banks), 10)
        i = 0
        for bank in banks:
            index = chr(ord("A") + i)
            self.assertEqual(bank.get_index(), index)
            self.assertEqual(bank.get_name(), 'BANK-%s' % index)
            self.assertEqual(bank.index, i)
            i += 1

    def test_add_memory_to_mapping(self):
        mem = chirp_common.Memory()
        mem.number = 5
        banks = self._model.get_mappings()
        bank = banks[2]
        self._radio._set_bank(5, 2)
        self.mox.ReplayAll()
        self._model.add_memory_to_mapping(mem, bank)

    def _setup_test_remove_memory_from_mapping(self, curbank):
        mem = chirp_common.Memory()
        mem.number = 5
        banks = self._model.get_mappings()
        bank = banks[2]
        self._radio._get_bank(5).AndReturn(curbank)
        if curbank == 2:
            self._radio._set_bank(5, None)
        self.mox.ReplayAll()
        return mem, bank

    def test_remove_memory_from_mapping(self):
        mem, bank = self._setup_test_remove_memory_from_mapping(2)
        self._model.remove_memory_from_mapping(mem, bank)

    def test_remove_memory_from_mapping_wrong_bank(self):
        mem, bank = self._setup_test_remove_memory_from_mapping(3)
        self.assertRaises(Exception,
                          self._model.remove_memory_from_mapping, mem, bank)

    def test_remove_memory_from_mapping_no_bank(self):
        mem, bank = self._setup_test_remove_memory_from_mapping(None)
        self.assertRaises(Exception,
                          self._model.remove_memory_from_mapping, mem, bank)

    def test_get_mapping_memories(self):
        banks = self._model.get_mappings()
        expected = []
        for i in range(1, 10):
            should_include = bool(i % 2)
            self._radio._get_bank(i).AndReturn(
                should_include and banks[1].index or None)
            if should_include:
                self._radio.get_memory(i).AndReturn(i)
                expected.append(i)
        self.mox.ReplayAll()
        members = self._model.get_mapping_memories(banks[1])
        self.assertEqual(members, expected)

    def test_get_memory_mappings(self):
        banks = self._model.get_mappings()
        mem1 = chirp_common.Memory()
        mem1.number = 5
        mem2 = chirp_common.Memory()
        mem2.number = 6
        self._radio._get_bank(mem1.number).AndReturn(2)
        self._radio._get_bank(mem2.number).AndReturn(None)
        self.mox.ReplayAll()
        self.assertEqual(self._model.get_memory_mappings(mem1)[0], banks[2])
        self.assertEqual(self._model.get_memory_mappings(mem2), [])


class TestIcomIndexedBankModel(TestIcomBankModel):
    CLS = icf.IcomIndexedBankModel

    def _get_rf(self):
        rf = super(TestIcomIndexedBankModel, self)._get_rf()
        rf.has_bank_index = True
        return rf

    def test_get_index_bounds(self):
        self.assertEqual(self._model.get_index_bounds(), (0, 10))

    def test_get_memory_index(self):
        mem = chirp_common.Memory()
        mem.number = 5
        self._radio._get_bank_index(mem.number).AndReturn(1)
        self.mox.ReplayAll()
        self.assertEqual(self._model.get_memory_index(mem, None), 1)

    def test_set_memory_index(self):
        mem = chirp_common.Memory()
        mem.number = 5
        banks = self._model.get_mappings()
        self.mox.StubOutWithMock(self._model, 'get_memory_mappings')
        self._model.get_memory_mappings(mem).AndReturn([banks[3]])
        self._radio._set_bank_index(mem.number, 1)
        self.mox.ReplayAll()
        self._model.set_memory_index(mem, banks[3], 1)

    def test_set_memory_index_bad_bank(self):
        mem = chirp_common.Memory()
        mem.number = 5
        banks = self._model.get_mappings()
        self.mox.StubOutWithMock(self._model, 'get_memory_mappings')
        self._model.get_memory_mappings(mem).AndReturn([banks[4]])
        self.mox.ReplayAll()
        self.assertRaises(Exception,
                          self._model.set_memory_index, mem, banks[3], 1)

    def test_set_memory_index_bad_index(self):
        mem = chirp_common.Memory()
        mem.number = 5
        banks = self._model.get_mappings()
        self.mox.StubOutWithMock(self._model, 'get_memory_mappings')
        self._model.get_memory_mappings(mem).AndReturn([banks[3]])
        self.mox.ReplayAll()
        self.assertRaises(Exception,
                          self._model.set_memory_index, mem, banks[3], 99)

    def test_get_next_mapping_index(self):
        banks = self._model.get_mappings()
        for i in range(*self._radio.get_features().memory_bounds):
            self._radio._get_bank(i).AndReturn((i % 2) and banks[1].index)
            if bool(i % 2):
                self._radio._get_bank_index(i).AndReturn(i)
        idx = 0
        for i in range(*self._radio.get_features().memory_bounds):
            self._radio._get_bank(i).AndReturn((i % 2) and banks[2].index)
            if i % 2:
                self._radio._get_bank_index(i).AndReturn(idx)
                idx += 1
        self.mox.ReplayAll()
        self.assertEqual(self._model.get_next_mapping_index(banks[1]), 0)
        self.assertEqual(self._model.get_next_mapping_index(banks[2]), 5)
