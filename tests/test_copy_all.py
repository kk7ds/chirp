import os

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

        dst_number = self.rf.memory_bounds[0]

        failures = []

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

            self.radio.set_memory(dst_mem)
            ret_mem = self.radio.get_memory(dst_number)
            self.assertEqualMem(dst_mem, ret_mem)
