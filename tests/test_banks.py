from chirp import chirp_common
from tests import base


class TestCaseBanks(base.DriverTest):
    @base.requires_feature('has_bank_names')
    def test_bank_names(self, testname='T'):
        bm = self.radio.get_bank_model()
        banks = bm.get_mappings()

        for bank in banks:
            self.assertIsInstance(bank.get_name(), str,
                                  'Bank model returned non-string name')
            bank.set_name(testname)

        for bank in bm.get_mappings():
            # We allow truncated storage of the name
            self.assertTrue(
                testname.lower().startswith(bank.get_name().lower()),
                'Bank name %r did not stick after set_name(%r)' % (
                    bank.get_name(), testname))
            # Bank names should not contain trailing whitespace
            self.assertEqual(bank.get_name(), bank.get_name().rstrip(),
                             'Bank stored with trailing whitespace')

    @base.requires_feature('has_bank_names')
    def test_bank_names_toolong(self):
        testname = "Not possibly this long"
        self.test_bank_names(testname)

    @base.requires_feature('has_bank_names')
    def test_bank_names_no_trailing_whitespace(self):
        self.test_bank_names('foo  ')

    @base.requires_feature('has_bank')
    def test_bank_store(self):
        loc = self.rf.memory_bounds[0]
        mem = chirp_common.Memory()
        mem.number = loc
        mem.freq = self.rf.valid_bands[0][0] + 100000

        # Make sure the memory is empty and we create it from scratch
        mem.empty = True
        self.radio.set_memory(mem)

        mem.empty = False
        self.radio.set_memory(mem)

        model = self.radio.get_bank_model()

        if isinstance(model, chirp_common.StaticBankModel):
            # Nothing to test with this type
            return

        # If in your bank model every channel has to be tied to a bank, just
        # add a variable named channelAlwaysHasBank to it and make it True
        try:
            channelAlwaysHasBank = model.channelAlwaysHasBank
        except Exception:
            channelAlwaysHasBank = False

        mem_banks = model.get_memory_mappings(mem)
        if channelAlwaysHasBank:
            self.assertNotEqual(0, len(mem_banks),
                                'Freshly-created memory has no banks '
                                'but it should')
        else:
            self.assertEqual(0, len(mem_banks),
                             'Freshly-created memory has banks '
                             'and should not')

        banks = model.get_mappings()

        model.add_memory_to_mapping(mem, banks[0])
        self.assertIn(banks[0], model.get_memory_mappings(mem),
                      'Memory does not claim bank after add')
        self.assertIn(loc, [x.number
                            for x in model.get_mapping_memories(banks[0])],
                      'Bank does not claim memory after add')

        model.remove_memory_from_mapping(mem, banks[0])
        if not channelAlwaysHasBank:
            self.assertNotIn(banks[0], model.get_memory_mappings(mem),
                             'Memory claims bank after remove')
            self.assertNotIn(loc, [x.number
                                   for x in model.get_mapping_memories(
                                       banks[0])],
                             'Bank claims memory after remove')

        if not channelAlwaysHasBank:
            # FIXME: We really need a standard exception for this, because
            # catching Exception here papers over the likely failures from
            # this going unchecked.
            self.assertRaises(Exception,
                              model.remove_memory_from_mapping, mem, banks[0])

    @base.requires_feature('has_bank_index')
    def test_bank_index(self):
        loc = self.rf.memory_bounds[0]
        mem = chirp_common.Memory()
        mem.number = loc
        mem.freq = self.rf.valid_bands[0][0] + 100000

        self.radio.set_memory(mem)

        model = self.radio.get_bank_model()
        banks = model.get_mappings()
        index_bounds = model.get_index_bounds()

        model.add_memory_to_mapping(mem, banks[0])
        for i in range(*index_bounds):
            model.set_memory_index(mem, banks[0], i)
            self.assertEqual(i, model.get_memory_index(mem, banks[0]),
                             'Bank index not persisted')

        suggested_index = model.get_next_mapping_index(banks[0])
        self.assertIn(suggested_index, list(range(*index_bounds)),
                      'Suggested bank index not in valid range')
