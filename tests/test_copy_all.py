import os

from chirp import chirp_common
from chirp.drivers import generic_csv
from chirp import import_logic
from tests import base


class TestCaseCopyAll(base.DriverTest):
    "Copy Memories From CSV"

    def setUp(self):
        super().setUp()
        csvfile = os.path.join(os.path.dirname(self.TEST_IMAGE),
                               'Generic_CSV.csv')
        self.src_radio = generic_csv.CSVRadio(csvfile)

    def test_copy(self):
        src_rf = self.src_radio.get_features()
        bounds = src_rf.memory_bounds

        for dst_number in range(self.rf.memory_bounds[0],
                                min(self.rf.memory_bounds[0] + 10,
                                    self.rf.memory_bounds[1])):
            cur_mem = self.radio.get_memory(dst_number)
            if not cur_mem.empty and 'freq' in cur_mem.immutable:
                # Keep looking
                continue
            else:
                break
        else:
            self.skipTest('No channels with mutable freq found to use')

        for number in range(bounds[0], bounds[1]):
            src_mem = self.src_radio.get_memory(number)
            if src_mem.empty:
                continue

            try:
                dst_mem = import_logic.import_mem(self.radio,
                                                  src_rf, src_mem,
                                                  overrides={
                                                      "number": dst_number})
                import_logic.import_bank(self.radio,
                                         self.src_radio,
                                         dst_mem,
                                         src_mem)
            except import_logic.DestNotCompatible:
                continue

            warn, err = chirp_common.split_validation_msgs(
                self.radio.validate_memory(dst_mem))
            self.radio.set_memory(dst_mem)

            if warn:
                # If the radio warned about something, we can assume it's
                # about duplex (i.e. tx inhibit) or mode (i.e. AM only on
                # airband)
                ignore = ['duplex', 'mode']
            else:
                ignore = None
            ret_mem = self.radio.get_memory(dst_number)
            self.assertEqualMem(dst_mem, ret_mem, ignore=ignore)
