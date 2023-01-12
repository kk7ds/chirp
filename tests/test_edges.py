from chirp import chirp_common
from tests import base


class TestCaseEdges(base.DriverTest):
    def test_longname(self):
        m = self.get_mem()
        m.name = ("X" * 256)  # Should be longer than any radio can handle
        m.name = self.radio.filter_name(m.name)

        self.radio.set_memory(m)
        n = self.radio.get_memory(m.number)

        self.assertEqualMem(m, n)

    def test_badname(self):
        m = self.get_mem()

        ascii = "".join([chr(x) for x in range(ord(" "), ord("~")+1)])
        for i in range(0, len(ascii), 4):
            m.name = self.radio.filter_name(ascii[i:i+4])
            self.radio.set_memory(m)
            n = self.radio.get_memory(m.number)
            self.assertEqualMem(m, n)

    def test_bandedges(self):
        m = self.get_mem()
        min_step = min(self.rf.has_tuning_step and
                       self.rf.valid_tuning_steps or [10])

        for low, high in self.rf.valid_bands:
            for freq in (low, high - int(min_step * 1000)):
                m.freq = freq
                if self.radio.validate_memory(m):
                    # Radio doesn't like it, so skip
                    continue

                self.radio.set_memory(m)
                n = self.radio.get_memory(m.number)
                self.assertEqualMem(m, n)

    def test_oddsteps(self):
        odd_steps = {
            145000000: [145856250, 145862500],
            445000000: [445856250, 445862500],
            862000000: [862731250, 862737500],
            }

        m = self.get_mem()

        for low, high in self.rf.valid_bands:
            for band, totest in list(odd_steps.items()):
                if band < low or band > high:
                    continue
                for testfreq in totest:
                    step = chirp_common.required_step(testfreq)
                    if step not in self.rf.valid_tuning_steps:
                        continue

                    m.freq = testfreq
                    m.tuning_step = step
                    self.radio.set_memory(m)
                    n = self.radio.get_memory(m.number)
                    self.assertEqualMem(m, n, ignore=['tuning_step'])

    def test_empty_to_not(self):
        firstband = self.rf.valid_bands[0]
        testfreq = firstband[0]
        for loc in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(loc)
            if m.empty:
                m.empty = False
                m.freq = testfreq
                self.radio.set_memory(m)
                m = self.radio.get_memory(loc)
                self.assertEqual(testfreq, m.freq,
                                 'Radio returned an unexpected frequency when'
                                 'setting previously-empty location %i' % loc)
                break

    def test_delete_memory(self):
        if self.radio.MODEL == 'JT220M':
            self.skipTest('Jetstream JT220 has no delete function')

        firstband = self.rf.valid_bands[0]
        testfreq = firstband[0]
        for loc in range(*self.rf.memory_bounds):
            if loc == self.rf.memory_bounds[0]:
                # Some radios will not allow you to delete the first memory
                # /me glares at yaesu
                continue
            m = self.radio.get_memory(loc)
            if not m.empty:
                m.empty = True
                self.radio.set_memory(m)
                m = self.radio.get_memory(loc)
                print(repr(m.empty))
                print(m)
                self.assertTrue(m.empty,
                                'Radio returned non-empty memory when asked '
                                'to delete location %i' % loc)
                break
