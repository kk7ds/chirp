#!/usr/bin/env python
#
# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

from __future__ import print_function
from builtins import bytes
import copy
import traceback
import sys
import os
import shutil
import glob
import tempfile
import time
from optparse import OptionParser
from serial import Serial

# change to the tests directory
scriptdir = os.path.dirname(sys.argv[0])
if scriptdir:
    os.chdir(scriptdir)

sys.path.insert(0, "../")

os.environ['CHIRP_TESTENV'] = 'sigh'
import logging
from chirp import logger

class LoggerOpts(object):
    quiet = 2
    verbose = 0
    log_file = os.path.join('logs', 'debug.log')
    log_level = logging.DEBUG

if not os.path.exists("logs"):
    os.mkdir("logs")
logger.handle_options(LoggerOpts())

from chirp import CHIRP_VERSION
# FIXME: Not all drivers are py3 compatible in syntax, so punt on this
# until that time, and defer to the safe import loop below.
# from chirp.drivers import *
from chirp import chirp_common, directory
from chirp import import_logic, memmap, settings, errors
from chirp import settings

directory.safe_import_drivers()

from chirp.drivers import generic_csv

TESTS = {}

time.sleep = lambda s: None


class TestError(Exception):
    def get_detail(self):
        return str(self)


class TestInternalError(TestError):
    pass


class TestCrashError(TestError):
    def __init__(self, tb, exc, args):
        Exception.__init__(self, str(exc))
        self.__tb = tb
        self.__exc = exc
        self.__args = args
        self.__mytb = "".join(traceback.format_stack())

    def __str__(self):
        return str(self.__exc)

    def get_detail(self):
        return str(self.__exc) + os.linesep + \
            ("Args were: %s" % self.__args) + os.linesep + \
            self.__tb + os.linesep + \
            "Called from:" + os.linesep + self.__mytb

    def get_original_exception(self):
        return self.__exc


class TestFailedError(TestError):
    def __init__(self, msg, detail=""):
        TestError.__init__(self, msg)
        self._detail = detail

    def get_detail(self):
        return self._detail


class TestSkippedError(TestError):
    pass


def get_tb():
    return traceback.format_exc()


class TestWrapper:
    def __init__(self, dstclass, filename, dst=None):
        self._ignored_exceptions = []
        self._dstclass = dstclass
        self._filename = filename
        self._make_reload = False
        self._dst = dst
        self.open()

    def pass_exception_type(self, et):
        self._ignored_exceptions.append(et)

    def nopass_exception_type(self, et):
        self._ignored_exceptions.remove(et)

    def make_reload(self):
        self._make_reload = True

    def open(self):
        if self._dst:
            self._dst.load_mmap(self._filename)
        else:
            self._dst = self._dstclass(self._filename)

    def close(self):
        self._dst.save_mmap(self._filename)

    def do(self, function, *args, **kwargs):
        if self._make_reload:
            try:
                self.open()
            except Exception as e:
                raise TestCrashError(get_tb(), e, "[Loading]")

        try:
            fn = getattr(self._dst, function)
        except KeyError:
            raise TestInternalError("Model lacks function `%s'" % function)

        try:
            ret = fn(*args, **kwargs)
        except Exception as e:
            if type(e) in self._ignored_exceptions:
                raise e
            details = str(args) + str(kwargs)
            for arg in args:
                if isinstance(arg, chirp_common.Memory):
                    details += os.linesep + \
                        os.linesep.join(["%s:%s" % (k, v) for k, v
                                         in list(arg.__dict__.items())])
            raise TestCrashError(get_tb(), e, details)

        if self._make_reload:
            try:
                self.close()
            except Exception as e:
                raise TestCrashError(get_tb(), e, "[Saving]")

        return ret

    def get_id(self):
        return "%s %s %s" % (self._dst.VENDOR,
                             self._dst.MODEL,
                             self._dst.VARIANT)

    def get_radio(self):
        return self._dst


class TestCase:
    def __init__(self, wrapper):
        self._wrapper = wrapper

    def prepare(self):
        pass

    def run(self):
        "Return True or False for Pass/Fail"
        pass

    def cleanup(self):
        pass

    def compare_mem(self, a, b, ignore=None):
        rf = self._wrapper.do("get_features")

        if a.tmode == "Cross":
            tx_mode, rx_mode = a.cross_mode.split("->")

        for k, v in list(a.__dict__.items()):
            if ignore and k in ignore:
                continue
            if k == "power":
                continue  # FIXME
            elif k == "immutable":
                continue
            elif k == "name":
                if not rf.has_name:
                    continue  # Don't complain about name, if not supported
                else:
                    # Name mismatch fair if filter_name() is right
                    v = self._wrapper.do("filter_name", v).rstrip()
            elif k == "tuning_step" and not rf.has_tuning_step:
                continue
            elif k == "rtone" and not (
                        a.tmode == "Tone" or
                        (a.tmode == "TSQL" and not rf.has_ctone) or
                        (a.tmode == "Cross" and tx_mode == "Tone") or
                        (a.tmode == "Cross" and rx_mode == "Tone" and
                         not rf.has_ctone)
                        ):
                continue
            elif k == "ctone" and (not rf.has_ctone or
                                   not (a.tmode == "TSQL" or
                                        (a.tmode == "Cross" and
                                         rx_mode == "Tone"))):
                continue
            elif k == "dtcs" and not (
                    (a.tmode == "DTCS" and not rf.has_rx_dtcs) or
                    (a.tmode == "Cross" and tx_mode == "DTCS") or
                    (a.tmode == "Cross" and rx_mode == "DTCS" and
                     not rf.has_rx_dtcs)):
                continue
            elif k == "rx_dtcs" and (not rf.has_rx_dtcs or
                                     not (a.tmode == "Cross" and
                                          rx_mode == "DTCS")):
                continue
            elif k == "offset" and not a.duplex:
                continue
            elif k == "cross_mode" and a.tmode != "Cross":
                continue

            try:
                if b.__dict__[k] != v:
                    msg = "Field `%s' " % k + \
                        "is `%s', " % b.__dict__[k] + \
                        "expected `%s' " % v
                    # If we set a channel that came back with a duplex
                    # of 'off', we may have been outside the transmit range of
                    # the radio, so we should not fail.
                    if k == "duplex" and b.__dict__[k] == "off":
                        continue
                    details = msg
                    details += os.linesep + "### Wanted:" + os.linesep
                    details += os.linesep.join(["%s:%s" % (k, v) for k, v
                                                in list(a.__dict__.items())])
                    details += os.linesep + "### Got:" + os.linesep
                    details += os.linesep.join(["%s:%s" % (k, v) for k, v
                                                in list(b.__dict__.items())])
                    raise TestFailedError(msg, details)
            except KeyError as e:
                print(sorted(a.__dict__.keys()))
                print(sorted(b.__dict__.keys()))
                raise


class TestCaseCopyAll(TestCase):
    "Copy Memories From CSV"

    def __str__(self):
        return "CopyAll"

    def prepare(self):
        testbase = os.path.dirname(os.path.abspath(__file__))
        source = os.path.join(testbase, 'images', 'Generic_CSV.csv')
        self._src = generic_csv.CSVRadio(source)

    def run(self):
        src_rf = self._src.get_features()
        bounds = src_rf.memory_bounds

        dst_rf = self._wrapper.do("get_features")
        dst_number = dst_rf.memory_bounds[0]

        failures = []

        for number in range(bounds[0], bounds[1]):
            src_mem = self._src.get_memory(number)
            if src_mem.empty:
                continue

            try:
                dst_mem = import_logic.import_mem(self._wrapper.get_radio(),
                                                  src_rf, src_mem,
                                                  overrides={
                                                    "number": dst_number})
                import_logic.import_bank(self._wrapper.get_radio(),
                                         self._src,
                                         dst_mem,
                                         src_mem)
            except import_logic.DestNotCompatible:
                continue
            except import_logic.ImportError as e:
                failures.append(TestFailedError("<%i>: Import Failed: %s" %
                                                (dst_number, e)))
                continue
            except Exception as e:
                raise TestCrashError(get_tb(), e, "[Import]")

            self._wrapper.do("set_memory", dst_mem)
            ret_mem = self._wrapper.do("get_memory", dst_number)

            try:
                self.compare_mem(dst_mem, ret_mem)
            except TestFailedError as e:
                failures.append(
                    TestFailedError("<%i>: %s" % (number, e), e.get_detail()))

        return failures
TESTS["CopyAll"] = TestCaseCopyAll


class TestCaseBruteForce(TestCase):
    def __str__(self):
        return "BruteForce"

    def set_and_compare(self, m):
        msgs = self._wrapper.do("validate_memory", m)
        if msgs:
            # If the radio correctly refuses memories it can't
            # store, don't fail
            return

        self._wrapper.do("set_memory", m)
        ret_m = self._wrapper.do("get_memory", m.number)

        # Damned Baofeng radios don't seem to properly store
        # shift and direction, so be gracious here
        if m.duplex == "split" and ret_m.duplex in ["-", "+"]:
            ret_m.offset = ret_m.freq + \
                (ret_m.offset * int(ret_m.duplex + "1"))
            ret_m.duplex = "split"

        self.compare_mem(m, ret_m)

    def do_tone(self, m, rf):
        self._wrapper.pass_exception_type(errors.UnsupportedToneError)
        for tone in chirp_common.TONES:
            for tmode in rf.valid_tmodes:
                if tmode not in chirp_common.TONE_MODES:
                    continue
                elif tmode in ["DTCS", "DTCS-R", "Cross"]:
                    continue  # We'll test DCS and Cross tones separately

                m.tmode = tmode
                if tmode == "":
                    pass
                elif tmode == "Tone":
                    m.rtone = tone
                elif tmode in ["TSQL", "TSQL-R"]:
                    if rf.has_ctone:
                        m.ctone = tone
                    else:
                        m.rtone = tone
                else:
                    raise TestInternalError("Unknown tone mode `%s'" % tmode)

                try:
                    self.set_and_compare(m)
                except errors.UnsupportedToneError as e:
                    # If a radio doesn't support a particular tone value,
                    # don't punish it
                    pass
        self._wrapper.nopass_exception_type(errors.UnsupportedToneError)

    def do_dtcs(self, m, rf):
        if not rf.has_dtcs:
            return

        m.tmode = "DTCS"
        for code in rf.valid_dtcs_codes:
            m.dtcs = code
            self.set_and_compare(m)

        if not rf.has_dtcs_polarity:
            return

        for pol in rf.valid_dtcs_pols:
            m.dtcs_polarity = pol
            self.set_and_compare(m)

    def do_cross(self, m, rf):
        if not rf.has_cross:
            return

        m.tmode = "Cross"
        # No fair asking a radio to detect two identical tones as Cross instead
        # of TSQL
        m.rtone = 100.0
        m.ctone = 107.2
        m.dtcs = 506
        m.rx_dtcs = 516
        for cross_mode in rf.valid_cross_modes:
            m.cross_mode = cross_mode
            self.set_and_compare(m)

    def do_duplex(self, m, rf):
        for duplex in rf.valid_duplexes:
            if duplex not in ["", "-", "+", "split"]:
                continue
            if duplex == "split" and not rf.can_odd_split:
                raise TestFailedError("Forgot to set rf.can_odd_split!")
            if duplex == "split":
                m.offset = rf.valid_bands[0][1] - 100000
            m.duplex = duplex
            self.set_and_compare(m)

        if rf.can_odd_split and "split" not in rf.valid_duplexes:
            raise TestFailedError("Paste error: rf.can_odd_split defined, but "
                                  "split duplex not supported.")

    def do_skip(self, m, rf):
        for skip in rf.valid_skips:
            m.skip = skip
            self.set_and_compare(m)

    def do_mode(self, m, rf):
        def ensure_urcall(call):
            l = self._wrapper.do("get_urcall_list")
            l[0] = call
            self._wrapper.do("set_urcall_list", l)

        def ensure_rptcall(call):
            l = self._wrapper.do("get_repeater_call_list")
            l[0] = call
            self._wrapper.do("set_repeater_call_list", l)

        def freq_is_ok(freq):
            for lo, hi in rf.valid_bands:
                if freq > lo and freq < hi:
                    return True
            return False

        successes = 0
        for mode in rf.valid_modes:
            tmp = copy.deepcopy(m)
            if mode not in chirp_common.MODES:
                continue
            if mode == "DV":
                tmp = chirp_common.DVMemory()
                try:
                    ensure_urcall(tmp.dv_urcall)
                    ensure_rptcall(tmp.dv_rpt1call)
                    ensure_rptcall(tmp.dv_rpt2call)
                except IndexError:
                    if rf.requires_call_lists:
                        raise
                    else:
                        # This radio may not do call lists at all,
                        # so let it slide
                        pass
            if mode == "FM" and freq_is_ok(tmp.freq + 100000000):
                # Some radios don't support FM below approximately 30MHz,
                # so jump up by 100MHz, if they support that
                tmp.freq += 100000000

            tmp.mode = mode

            if rf.validate_memory(tmp):
                # A result (of error messages) from validate means the radio
                # thinks this is invalid, so don't fail the test
                print('Failed to validate %s: %s' % (tmp, rf.validate_memory(tmp)))
                continue

            self.set_and_compare(tmp)
            successes += 1

        if (not successes) and rf.valid_modes:
            raise TestFailedError("All modes were skipped, "
                                  "something went wrong")

    def run(self):
        rf = self._wrapper.do("get_features")

        def clean_mem():
            m = chirp_common.Memory()
            m.number = rf.memory_bounds[0]
            try:
                m.mode = rf.valid_modes[0]
            except IndexError:
                pass
            if rf.valid_bands:
                m.freq = rf.valid_bands[0][0] + 600000
            else:
                m.freq = 146520000
            if m.freq < 30000000 and "AM" in rf.valid_modes:
                m.mode = "AM"
            return m

        tests = [
            self.do_tone,
            self.do_dtcs,
            self.do_cross,
            self.do_duplex,
            self.do_skip,
            self.do_mode,
        ]
        for test in tests:
            test(clean_mem(), rf)

        if 12.5 in rf.valid_tuning_steps and \
                "split" in rf.valid_duplexes:
            m = clean_mem()
            if rf.valid_bands:
                m.offset = rf.valid_bands[0][1] - 12500
            else:
                m.offset = 151137500
            m.duplex = "split"
            self.set_and_compare(m)

        return []
TESTS["BruteForce"] = TestCaseBruteForce


class TestCaseEdges(TestCase):
    def __str__(self):
        return "Edges"

    def _mem(self, rf):
        m = chirp_common.Memory()
        m.freq = rf.valid_bands[0][0] + 1000000
        if m.freq < 30000000 and "AM" in rf.valid_modes:
            m.mode = "AM"
        else:
            try:
                m.mode = rf.valid_modes[0]
            except IndexError:
                pass

        for i in range(*rf.memory_bounds):
            m.number = i
            if not self._wrapper.do("validate_memory", m):
                return m

        raise TestSkippedError("No mutable memory locations found")

    def do_longname(self, rf):
        m = self._mem(rf)
        m.name = ("X" * 256)  # Should be longer than any radio can handle
        m.name = self._wrapper.do("filter_name", m.name)

        self._wrapper.do("set_memory", m)
        n = self._wrapper.do("get_memory", m.number)

        self.compare_mem(m, n)

    def do_badname(self, rf):
        m = self._mem(rf)

        ascii = "".join([chr(x) for x in range(ord(" "), ord("~")+1)])
        for i in range(0, len(ascii), 4):
            m.name = self._wrapper.do("filter_name", ascii[i:i+4])
            self._wrapper.do("set_memory", m)
            n = self._wrapper.do("get_memory", m.number)
            self.compare_mem(m, n)

    def do_bandedges(self, rf):
        m = self._mem(rf)
        min_step = min(rf.has_tuning_step and rf.valid_tuning_steps or [10])

        for low, high in rf.valid_bands:
            for freq in (low, high - int(min_step * 1000)):
                m.freq = freq
                if self._wrapper.do("validate_memory", m):
                    # Radio doesn't like it, so skip
                    continue

                self._wrapper.do("set_memory", m)
                n = self._wrapper.do("get_memory", m.number)
                self.compare_mem(m, n)

    def do_oddsteps(self, rf):
        odd_steps = {
            145000000: [145856250, 145862500],
            445000000: [445856250, 445862500],
            862000000: [862731250, 862737500],
            }

        m = self._mem(rf)

        for low, high in rf.valid_bands:
            for band, totest in list(odd_steps.items()):
                if band < low or band > high:
                    continue
                for testfreq in totest:
                    step = chirp_common.required_step(testfreq)
                    if step not in rf.valid_tuning_steps:
                        continue

                    m.freq = testfreq
                    m.tuning_step = step
                    self._wrapper.do("set_memory", m)
                    n = self._wrapper.do("get_memory", m.number)
                    self.compare_mem(m, n, ignore=['tuning_step'])

    def do_empty_to_not(self, rf):
        firstband = rf.valid_bands[0]
        testfreq = firstband[0]
        for loc in range(*rf.memory_bounds):
            m = self._wrapper.do('get_memory', loc)
            if m.empty:
                m.empty = False
                m.freq = testfreq
                self._wrapper.do('set_memory', m)
                m = self._wrapper.do('get_memory', loc)
                if m.freq == testfreq:
                    return
                else:
                    raise TestFailedError('Radio failed to set an empty '
                                          'location (%i)' % loc)

    def do_delete_memory(self, rf):
        firstband = rf.valid_bands[0]
        testfreq = firstband[0]
        for loc in range(*rf.memory_bounds):
            if loc == rf.memory_bounds[0]:
                # Some radios will not allow you to delete the first memory
                # /me glares at yaesu
                continue
            m = self._wrapper.do('get_memory', loc)
            if not m.empty:
                m.empty = True
                self._wrapper.do('set_memory', m)
                m = self._wrapper.do('get_memory', loc)
                if not m.empty:
                    raise TestFailedError('Radio refused to delete a memory '
                                          'location (%i)' % loc)
                else:
                    return

    def run(self):
        rf = self._wrapper.do("get_features")

        if not rf.valid_bands:
            raise TestFailedError("Radio does not provide valid bands!")

        self.do_longname(rf)
        self.do_bandedges(rf)
        self.do_oddsteps(rf)
        self.do_badname(rf)
        if rf.can_delete:
            self.do_empty_to_not(rf)
            self.do_delete_memory(rf)

        return []

TESTS["Edges"] = TestCaseEdges


class TestCaseSettings(TestCase):
    def __str__(self):
        return "Settings"

    def do_get_settings(self, rf):
        lst = self._wrapper.do("get_settings")
        if not isinstance(lst, list):
            raise TestFailedError("Invalid Radio Settings")

    def do_same_settings(self, rf):
        o = self._wrapper.do("get_settings")
        self._wrapper.do("set_settings", o)
        n = self._wrapper.do("get_settings")
        list(map(self.compare_settings, o, n))

    @staticmethod
    def compare_settings(a, b):
        try:
            if isinstance(a, settings.RadioSettingValue):
                raise TypeError('Hit bottom')
            list(map(TestCaseSettings.compare_settings, a, b))
        except TypeError:
            if a.get_value() != b.get_value():
                msg = "Field is `%s', " % b + \
                    "expected `%s' " % a
                details = msg
                raise TestFailedError(msg, details)

    def run(self):
        rf = self._wrapper.do("get_features")

        if not rf.has_settings:
            raise TestSkippedError("Settings not supported")

        self.do_get_settings(rf)
        self.do_same_settings(rf)

        return []

TESTS["Settings"] = TestCaseSettings


class TestCaseBanks(TestCase):
    def __str__(self):
        return "Banks"

    def _do_bank_names(self, rf, testname):
        bm = self._wrapper.do("get_bank_model")
        banks = bm.get_mappings()

        for bank in banks:
            name = bank.get_name()
            try:
                bank.set_name(testname)
            except AttributeError:
                return [], []
            except Exception as e:
                if str(e) == "Not implemented":
                    return [], []
                else:
                    raise e

        return banks, bm.get_mappings()

    def do_bank_names(self, rf):
        banks, newbanks = self._do_bank_names(rf, "T")

        for i in range(0, len(banks)):
            if banks[i].get_name() != newbanks[i].get_name():
                raise TestFailedError("Bank names not preserved",
                                      "Tried %s on %i\nGot %s" % (banks[i],
                                                                  i,
                                                                  newbanks[i]))

    def do_bank_names_toolong(self, rf):
        testname = "Not possibly this long"
        banks, newbanks = self._do_bank_names(rf, testname)

        for i in range(0, len(newbanks)):
            # Truncation is allowed, but not failure
            if not testname.lower().startswith(str(newbanks[i]).lower()):
                raise TestFailedError("Bank names not properly truncated",
                                      "Tried: %s on %i\nGot: %s" %
                                      (testname, i, newbanks[i]))

    def do_bank_names_no_trailing_whitespace(self, rf):
        banks, newbanks = self._do_bank_names(rf, "foo  ")

        for bank in newbanks:
            if str(bank) != str(bank).rstrip():
                raise TestFailedError("Bank names stored with " +
                                      "trailing whitespace")

    def do_bank_store(self, rf):
        loc = rf.memory_bounds[0]
        mem = chirp_common.Memory()
        mem.number = loc
        mem.freq = rf.valid_bands[0][0] + 100000

        # Make sure the memory is empty and we create it from scratch
        mem.empty = True
        self._wrapper.do("set_memory", mem)

        mem.empty = False
        self._wrapper.do("set_memory", mem)

        model = self._wrapper.do("get_bank_model")

        # If in your bank model every channel has to be tied to a bank, just
        # add a variable named channelAlwaysHasBank to it and make it True
        try:
            channelAlwaysHasBank = model.channelAlwaysHasBank
        except:
            channelAlwaysHasBank = False

        mem_banks = model.get_memory_mappings(mem)
        if channelAlwaysHasBank:
            if len(mem_banks) == 0:
                raise TestFailedError("Freshly-created memory has no banks " +
                                      "and it should", "Bank: %s" %
                                      str(mem_banks))
        else:
            if len(mem_banks) != 0:
                raise TestFailedError("Freshly-created memory has banks " +
                                      "and should not", "Bank: %s" %
                                      str(mem_banks))

        banks = model.get_mappings()

        def verify(bank):
            if bank not in model.get_memory_mappings(mem):
                return "Memory does not claim bank"

            if loc not in [x.number for x in model.get_mapping_memories(bank)]:
                return "Bank does not claim memory"

            return None

        model.add_memory_to_mapping(mem, banks[0])
        reason = verify(banks[0])
        if reason is not None:
            raise TestFailedError("Setting memory bank does not persist",
                                  "%s\nMemory banks:%s\nBank memories:%s" %
                                  (reason,
                                   model.get_memory_mappings(mem),
                                   model.get_mapping_memories(banks[0])))

        model.remove_memory_from_mapping(mem, banks[0])
        reason = verify(banks[0])
        if reason is None and not channelAlwaysHasBank:
            raise TestFailedError("Memory remains in bank after remove",
                                      reason)

        try:
            model.remove_memory_from_mapping(mem, banks[0])
            did_error = False
        except Exception:
            did_error = True

        if not did_error and not channelAlwaysHasBank:
            raise TestFailedError("Removing memory from non-member bank " +
                                  "did not raise Exception")

    def do_bank_index(self, rf):
        if not rf.has_bank_index:
            return

        loc = rf.memory_bounds[0]
        mem = chirp_common.Memory()
        mem.number = loc
        mem.freq = rf.valid_bands[0][0] + 100000

        self._wrapper.do("set_memory", mem)

        model = self._wrapper.do("get_bank_model")
        banks = model.get_mappings()
        index_bounds = model.get_index_bounds()

        model.add_memory_to_mapping(mem, banks[0])
        for i in range(0, *index_bounds):
            model.set_memory_index(mem, banks[0], i)
            if model.get_memory_index(mem, banks[0]) != i:
                raise TestFailedError("Bank index not persisted")

        suggested_index = model.get_next_mapping_index(banks[0])
        if suggested_index not in list(range(*index_bounds)):
            raise TestFailedError("Suggested bank index not in valid range",
                                  "Got %i, range is %s" % (suggested_index,
                                                           index_bounds))

    def run(self):
        rf = self._wrapper.do("get_features")

        if not rf.has_bank:
            raise TestSkippedError("Banks not supported")

        self.do_bank_names(rf)
        self.do_bank_names_toolong(rf)
        self.do_bank_names_no_trailing_whitespace(rf)
        self.do_bank_store(rf)
        # Again to make sure we clear bank info on delete
        self.do_bank_store(rf)
        self.do_bank_index(rf)

        return []

TESTS["Banks"] = TestCaseBanks


class TestCaseDetect(TestCase):
    def __str__(self):
        return "Detect"

    def run(self):
        if isinstance(self._wrapper._dst, chirp_common.LiveRadio):
            raise TestSkippedError("This is a live radio")

        filename = self._wrapper._filename

        try:
            radio = directory.get_radio_by_image(filename)
        except Exception as e:
            raise TestFailedError("Failed to detect", str(e))

        if radio.__class__.__name__ == 'DynamicRadioAlias':
            # This was detected via metadata and wrapped, which means
            # we found the appropriate class.
            pass
        elif issubclass(self._wrapper._dstclass, radio.__class__):
            pass
        elif issubclass(radio.__class__, self._wrapper._dstclass):
            pass
        elif radio.__class__ != self._wrapper._dstclass:
            raise TestFailedError("%s detected as %s" %
                                  (self._wrapper._dstclass, radio.__class__))
        return []

TESTS["Detect"] = TestCaseDetect


class TestCaseClone(TestCase):
    class SerialNone:
        def __init__(self, isbytes):
            self.isbytes = isbytes
            self.mismatch = False
            self.mismatch_at = None

        def read(self, size):
            if self.isbytes:
                return b""
            else:
                return ""

        def write(self, data):
            expected = self.isbytes and bytes or str
            if six.PY2:
                # One driver uses bytearray() which will trigger this
                # check even though it works fine on py2. So, only
                # do this check for PY3 which is where it matters
                # anyway.
                pass
            elif not self.mismatch and not isinstance(data, expected):
                self.mismatch = True
                self.mismatch_at = ''.join(traceback.format_stack())
            pass

        def setBaudrate(self, rate):
            pass

        def setTimeout(self, timeout):
            pass

        def setParity(self, parity):
            pass

        def __str__(self):
            return self.__class__.__name__.replace("Serial", "")

    class SerialError(SerialNone):
        def read(self, size):
            raise Exception("Foo")

        def write(self, data):
            raise Exception("Bar")

    class SerialGarbage(SerialNone):
        def read(self, size):
            if self.isbytes:
                buf = []
                for i in range(0, size):
                    buf += i % 256
                return bytes(buf)
            else:
                buf = ""
                for i in range(0, size):
                    buf += chr(i % 256)
                return buf

    class SerialShortGarbage(SerialNone):
        def read(self, size):
            if self.isbytes:
                return b'\x00' * (size - 1)
            else:
                return "\x00" * (size - 1)

    def __str__(self):
        return "Clone"

    def _run(self, serial):
        error = None
        live = isinstance(self._wrapper._dst, chirp_common.LiveRadio)
        clone = isinstance(self._wrapper._dst, chirp_common.CloneModeRadio)

        if not clone and not live:
            raise TestSkippedError('Does not support clone')

        try:
            radio = self._wrapper._dst.__class__(serial)
            radio.status_fn = lambda s: True
        except Exception as e:
            error = e

        if not live:
            if error is not None:
                raise TestFailedError("Clone radio tried to read from " +
                                      "serial on init")
        else:
            if not isinstance(error, errors.RadioError):
                raise TestFailedError("Live radio didn't notice serial " +
                                      "was dead on init")
            return []  # Nothing more to test on an error'd live radio

        error = None
        try:
            radio.sync_in()
        except Exception as e:
            error = e

        if error is None:
            raise TestFailedError("Radio did not raise exception " +
                                  "with %s data" % serial,
                                  "On sync_in()")
        elif not isinstance(error, errors.RadioError):
            raise TestFailedError("Radio did not raise RadioError " +
                                  "with %s data" % serial,
                                  "sync_in() Got: %s (%s)\n%s" %
                                  (error.__class__.__name__,
                                   error, get_tb()))

        if radio.NEEDS_COMPAT_SERIAL:
            radio._mmap = memmap.MemoryMap("\x00" * (1024 * 128))
        else:
            radio._mmap = memmap.MemoryMapBytes(bytes(b"\x00") * (1024 * 128))

        error = None
        try:
            radio.sync_out()
        except Exception as e:
            error = e

        if error is None:
            raise TestFailedError("Radio did not raise exception " +
                                  "with %s data" % serial,
                                  "On sync_out()")
        elif not isinstance(error, errors.RadioError):
            raise TestFailedError("Radio did not raise RadioError " +
                                  "with %s data" % serial,
                                  "sync_out(): Got: %s (%s)" %
                                  (error.__class__.__name__, error))

        if serial.mismatch:
            raise TestFailedError("Radio tried to write the wrong "
                                  "type of data to the %s pipe." % (
                                      serial.__class__.__name__),
                                  "TestClone:%s\n%s" % (
                                      serial.__class__.__name__,
                                      serial.mismatch_at))

        return []

    def run(self):
        isbytes = not self._wrapper._dst.NEEDS_COMPAT_SERIAL
        self._run(self.SerialError(isbytes))
        self._run(self.SerialNone(isbytes))
        self._run(self.SerialGarbage(isbytes))
        self._run(self.SerialShortGarbage(isbytes))
        return []

TESTS["Clone"] = TestCaseClone


class TestOutput:
    def __init__(self, output=None):
        if not output:
            output = sys.stdout
        self._out = output

    def prepare(self):
        pass

    def cleanup(self):
        pass

    def _print(self, string):
        print(string, file=self._out)

    def report(self, rclass, tc, msg, e):
        name = ("%s %s" % (rclass.MODEL, rclass.VARIANT))[:13]
        self._print("%9s %-13s %-10s %s %s" % (rclass.VENDOR.split(" ")[0],
                                               name,
                                               tc,
                                               msg, e))


class TestOutputANSI(TestOutput):
    def __init__(self, output=None):
        TestOutput.__init__(self, output)
        self.__counts = {
            "PASSED":  0,
            "FAILED":  0,
            "CRASHED": 0,
            "SKIPPED": 0,
            }
        self.__total = 0

    def report(self, rclass, tc, msg, e):
        self.__total += 1
        self.__counts[msg] += 1
        msg += ":"
        if os.isatty(1):
            if msg == "PASSED:":
                msg = "\033[1;32m%8s\033[0m" % msg
            elif msg == "FAILED:":
                msg = "\033[1;41m%8s\033[0m" % msg
            elif msg == "CRASHED:":
                msg = "\033[1;45m%8s\033[0m" % msg
            elif msg == "SKIPPED:":
                msg = "\033[1;32m%8s\033[0m" % msg
        else:
            msg = "%8s" % msg

        TestOutput.report(self, rclass, tc, msg, e)

    def cleanup(self):
        self._print("-" * 70)
        self._print("Results:")
        self._print("  %-7s: %i" % ("TOTAL", self.__total))
        for t, c in list(self.__counts.items()):
            self._print("  %-7s: %i" % (t, c))


class TestOutputHTML(TestOutput):
    def __init__(self, filename):
        self._filename = filename

    def prepare(self):
        print("Writing to %s" % self._filename, end=' ')
        sys.stdout.flush()
        self._out = file(self._filename, "w")
        s = """
<html>
<head>
<title>Test report for CHIRP version %s</title>
<style>
table.testlist {
  border: thin solid black;
  border-collapse: collapse;
}
td {
  border: thin solid black;
  padding: 2px;
}
th {
  background-color: silver;
  border: thin solid black;
  padding: 2px;
}
td.PASSED {
  background-color: green;
}
td.FAILED {
  background-color: red;
}
td.CRASHED {
  background-color: purple;
}
td.SKIPPED {
  background-color: green;
}
</style>
</head>
<body>
<h1>Test report for CHIRP version %s</h1>
<h3>Generated on %s (%s)</h3>
<table class="testlist">
<tr>
  <th>Vendor</th><th>Model</th><th>Test Case</th>
  <th>Status</th><th>Message</th>
</tr>
""" % (CHIRP_VERSION, CHIRP_VERSION, time.strftime("%x at %X"), os.name)
        print(s, file=self._out)

    def cleanup(self):
        print("</table></body>", file=self._out)
        self._out.close()
        print("Done")

    def report(self, rclass, tc, msg, e):
        s = ("<tr class='%s'>" % msg) + \
            ("<td class='vendor'>%s</td>" % rclass.VENDOR) + \
            ("<td class='model'>%s %s</td>" %
                (rclass.MODEL, rclass.VARIANT)) + \
            ("<td class='tc'>%s</td>" % tc) + \
            ("<td class='%s'>%s</td>" % (msg, msg)) + \
            ("<td class='error'>%s</td>" % e) + \
            "</tr>"
        print(s, file=self._out)
        sys.stdout.write(".")
        sys.stdout.flush()


class TestRunner:
    def __init__(self, images_dir, test_list, test_out):
        self._images_dir = images_dir
        self._test_list = test_list
        self._test_out = test_out
        if not os.path.exists("tmp"):
            os.mkdir("tmp")

    def _make_list(self):
        run_list = []
        images = glob.glob(os.path.join(self._images_dir, "*.img"))
        for image in sorted(images):
            drv_name, _ = os.path.splitext(os.path.basename(image))
            run_list.append((directory.get_radio(drv_name), image))
        return run_list

    def report(self, rclass, tc, msg, e):
        self._test_out.report(rclass, tc, msg, e)

    def log(self, rclass, tc, e):
        fn = "logs/%s_%s.log" % (directory.radio_class_id(rclass), tc)
        log = file(fn, "a")
        print("---- Begin test %s ----" % tc, file=log)
        log.write(e.get_detail())
        print(file=log)
        print("---- End test %s ----" % tc, file=log)
        log.close()

    def nuke_log(self, rclass, tc):
        fn = "logs/%s_%s.log" % (directory.radio_class_id(rclass), tc)
        if os.path.exists(fn):
            os.remove(fn)

    def _run_one(self, rclass, parm, dst=None):
        nfailed = 0
        for tcclass in self._test_list:
            nprinted = 0
            tw = TestWrapper(rclass, parm, dst=dst)
            tc = tcclass(tw)

            self.nuke_log(rclass, tc)

            tc.prepare()

            try:
                failures = tc.run()
                for e in failures:
                    self.report(rclass, tc, "FAILED", e)
                    if e.get_detail():
                        self.log(rclass, tc, e)
                    nfailed += 1
                    nprinted += 1
            except TestFailedError as e:
                self.report(rclass, tc, "FAILED", e)
                if e.get_detail():
                    self.log(rclass, tc, e)
                nfailed += 1
                nprinted += 1
            except TestCrashError as e:
                self.report(rclass, tc, "CRASHED", e)
                self.log(rclass, tc, e)
                nfailed += 1
                nprinted += 1
            except TestSkippedError as e:
                self.report(rclass, tc, "SKIPPED", e)
                self.log(rclass, tc, e)
                nprinted += 1

            tc.cleanup()

            if not nprinted:
                self.report(rclass, tc, "PASSED", "All tests")

        return nfailed

    def run_rclass_image(self, rclass, image, dst=None):
        rid = "%s_%s_" % (rclass.VENDOR, rclass.MODEL)
        rid = rid.replace("/", "_")
        # Do this for things like Generic_CSV, that demand it
        _base, ext = os.path.splitext(image)
        testimage = tempfile.mktemp(ext, rid)
        shutil.copy(image, testimage)

        try:
            tw = TestWrapper(rclass, testimage, dst=dst)
            rf = tw.do("get_features")
            if rf.has_sub_devices:
                devices = tw.do("get_sub_devices")
                failed = 0
                for dev in devices:
                    failed += self.run_rclass_image(dev.__class__, image, dst=dev)
                return failed
            else:
                return self._run_one(rclass, image, dst=dst)
        finally:
            os.remove(testimage)

    def run_list(self, run_list):
        def _key(pair):
            return pair[0].VENDOR + pair[0].MODEL + pair[0].VARIANT
        failed = 0
        for rclass, image in sorted(run_list, key=_key):
            failed += self.run_rclass_image(rclass, image)
        return failed

    def run_all(self):
        run_list = self._make_list()
        return self.run_list(run_list)

    def run_one(self, drv_name):
        return self.run_rclass_image(directory.get_radio(drv_name),
                                     os.path.join("images",
                                                  "%s.img" % drv_name))

    def run_one_live(self, drv_name, port):
        rclass = directory.get_radio(drv_name)
        pipe = Serial(port=port, baudrate=rclass.BAUD_RATE, timeout=0.5)
        tw = TestWrapper(rclass, pipe)
        rf = tw.do("get_features")
        if rf.has_sub_devices:
            devices = tw.do("get_sub_devices")
            failed = 0
            for device in devices:
                failed += self._run_one(device.__class__, pipe)
            return failed
        else:
            return self._run_one(rclass, pipe)

if __name__ == "__main__":
    import sys

    images = glob.glob("images/*.img")
    tests = [os.path.splitext(os.path.basename(img))[0] for img in images]

    op = OptionParser()
    op.add_option("-d", "--driver", dest="driver", default=None,
                  help="Driver to test (omit for all)")
    op.add_option("-t", "--test", dest="test", default=None,
                  help="Test to run (omit for all)")
    op.add_option("-e", "--exclude", dest="exclude", default=None,
                  help="Test to exclude")
    op.add_option("",   "--html", dest="html", default=None,
                  help="Output to HTML file")
    op.add_option("-l", "--live", dest="live", default=None,
                  help="Live radio on this port (requires -d)")
    op.usage = """
Available drivers:
%s
Available tests:
%s
""" % ("\n".join(["  %s" % x for x in sorted(tests)]),
       "\n".join(["  %s" % x for x in sorted(TESTS.keys())]))

    (options, args) = op.parse_args()

    if options.html:
        test_out = TestOutputHTML(options.html)
    else:
        stdout = sys.stdout
        if not os.path.exists("logs"):
            os.mkdir("logs")
        sys.stdout = file("logs/verbose", "w")
        test_out = TestOutputANSI(stdout)

    test_out.prepare()

    if options.exclude:
        del TESTS[options.exclude]

    if options.test:
        tr = TestRunner("images", [TESTS[options.test]], test_out)
    else:
        tr = TestRunner("images", list(TESTS.values()), test_out)

    if options.live:
        if not options.driver:
            print("Live mode requires a driver to be specified")
            sys.exit(1)
        failed = tr.run_one_live(options.driver, options.live)
    elif options.driver:
        failed = tr.run_one(options.driver)
    else:
        failed = tr.run_all()

    test_out.cleanup()

    sys.exit(failed)
