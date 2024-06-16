# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import time
import threading
import logging
import uuid

from chirp.drivers import ic9x_ll, icf
from chirp import chirp_common, errors, util, directory
from chirp import bitwise

LOG = logging.getLogger(__name__)

IC9XA_SPECIAL = {}
IC9XB_SPECIAL = {}

for i in range(0, 25):
    idA = "%iA" % i
    idB = "%iB" % i
    Anum = 800 + i * 2
    Bnum = 400 + i * 2

    IC9XA_SPECIAL[idA] = Anum
    IC9XA_SPECIAL[idB] = Bnum

    IC9XB_SPECIAL[idA] = Bnum
    IC9XB_SPECIAL[idB] = Bnum + 1

IC9XA_SPECIAL["C0"] = IC9XB_SPECIAL["C0"] = -1
IC9XA_SPECIAL["C1"] = IC9XB_SPECIAL["C1"] = -2

IC9X_SPECIAL = {
    0: {},
    1: IC9XA_SPECIAL,
    2: IC9XB_SPECIAL,
}

CHARSET = chirp_common.CHARSET_ALPHANUMERIC + \
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


class Lock:
    """Maintains the state of an ic9x

    This makes sure that only one RadioThread accesses the radio at one
    time. It also keeps track of the last successful unlock of the radio
    so that we know when to re-send the magic wakeup sequence.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.id = str(uuid.uuid4())
        self._last = 0

    def __enter__(self):
        LOG.debug('%s locking', self.id)
        self.lock.acquire()
        LOG.debug('%s locked', self.id)

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.lock.release()
        if exc_type is None:
            self._last = time.time()
        LOG.debug('%s unlocked success=%s', self.id, exc_type is None)

    def __repr__(self):
        return '<IC9x Lock %s>' % self.id

    @property
    def stale(self):
        return time.time() - self._last > 4


def locked(fn):
    """Decorator for operations that talk to the radio.

    Runs them with the lock and sends the magic wakeup if the timer is
    expired.
    """
    def _lock(self, *a, **k):
        with self._lock:
            LOG.debug('Locked for %s', fn.__name__)
            if self._lock.stale:
                LOG.debug('Doing wakeup')
                self._init()
            r = fn(self, *a, **k)
            return r
    return _lock


class IC9xBank(icf.IcomNamedBank):
    """Icom 9x Bank"""
    def get_name(self):
        banks = self._model._radio._ic9x_get_banks()
        return banks[self.index]

    def set_name(self, name):
        banks = self._model._radio._ic9x_get_banks()
        banks[self.index] = name
        self._model._radio._ic9x_set_banks(banks)


@directory.register
class IC9xRadio(icf.IcomLiveRadio):
    """Base class for Icom IC-9x radios"""
    MODEL = "IC-91/92AD"

    _model = "ic9x"    # Fake model info for detect.py
    vfo = 0
    _upper = 300

    _num_banks = 26
    _bank_class = IC9xBank

    def _get_bank(self, loc):
        mem = self.get_memory(loc)
        return mem._bank

    def _set_bank(self, loc, bank):
        mem = self.get_memory(loc)
        mem._bank = bank
        self.set_memory(mem)

    def _get_bank_index(self, loc):
        mem = self.get_memory(loc)
        return mem._bank_index

    def _set_bank_index(self, loc, index):
        mem = self.get_memory(loc)
        mem._bank_index = index
        self.set_memory(mem)

    def _init(self):
        """Does the magic wakeup dance"""
        self.pipe.baudrate = 4800
        self.pipe.timeout = 1
        for i in range(5):
            buf = (b'\xfe' * 8) * 20 + (
                b'\xfe\xfe\x01\x80\x19\xfd')
            self.pipe.write(buf)
            time.sleep(0.1)
            resp = self.pipe.read(5)
            if b'\x80\x01\x19' in resp:
                LOG.debug('Radio responded to wakeup attempt %i' % (i + 1))
                self.pipe.baudrate = 38400
                while True:
                    r = ic9x_ll.ic9x_recv(self.pipe)
                    if not r:
                        break
                    LOG.debug('Got post-wakeup response: %r' % r)
                return
            time.sleep(1)
        LOG.warning('Made %i attempts to wake radio', i + 1)
        raise errors.RadioError('Radio not responding')

    def __init__(self, *args, **kwargs):
        if 'lock' in kwargs:
            self._lock = kwargs.pop('lock')
        else:
            self._lock = Lock()
        super().__init__(*args, **kwargs)

        self.__memcache = {}
        self.__bankcache = {}

    @locked
    def get_memory(self, number):
        if isinstance(number, str):
            try:
                number = IC9X_SPECIAL[self.vfo][number]
            except KeyError:
                raise errors.InvalidMemoryLocation(
                        "Unknown channel %s" % number)

        if number < -2 or number > 999:
            raise errors.InvalidValueError("Number must be between 0 and 999")

        if number in self.__memcache:
            return self.__memcache[number]

        try:
            mem = ic9x_ll.get_memory(self.pipe, self.vfo, number)
        except errors.InvalidMemoryLocation:
            mem = chirp_common.Memory()
            mem.number = number
            if number < self._upper:
                mem.empty = True

        if number > self._upper or number < 0:
            mem.extd_number = util.get_dict_rev(IC9X_SPECIAL,
                                                [self.vfo][number])
            mem.immutable = ["number", "skip", "bank", "bank_index",
                             "extd_number"]

        self.__memcache[mem.number] = mem

        return mem

    @locked
    def get_raw_memory(self, number):
        mframe = ic9x_ll.get_memory_frame(self.pipe, self.vfo, number)
        return repr(bitwise.parse(ic9x_ll.MEMORY_FRAME_FORMAT, mframe))

    def get_memories(self, lo=0, hi=None):
        if hi is None:
            hi = self._upper

        memories = []

        for i in range(lo, hi + 1):
            try:
                LOG.debug("Getting %i" % i)
                mem = self.get_memory(i)
                if mem:
                    memories.append(mem)
                LOG.debug("Done: %s" % mem)
            except errors.InvalidMemoryLocation:
                pass
            except errors.InvalidDataError as e:
                LOG.error("Error talking to radio: %s" % e)
                break

        return memories

    @locked
    def set_memory(self, _memory):
        # Make sure we mirror the DV-ness of the new memory we're
        # setting, and that we capture the Bank value of any currently
        # stored memory (unless the special type is provided) and
        # communicate that to the low-level routines with the special
        # subclass
        if isinstance(_memory, ic9x_ll.IC9xMemory) or \
                 isinstance(_memory, ic9x_ll.IC9xDVMemory):
            memory = _memory
        else:
            if isinstance(_memory, chirp_common.DVMemory):
                memory = ic9x_ll.IC9xDVMemory()
            else:
                memory = ic9x_ll.IC9xMemory()
            try:
                memory.clone(ic9x_ll.get_memory(self.pipe, self.vfo,
                                                _memory.number))
            except errors.InvalidMemoryLocation:
                pass
            memory.clone(_memory)

        if memory.empty:
            ic9x_ll.erase_memory(self.pipe, self.vfo, memory.number)
        else:
            ic9x_ll.set_memory(self.pipe, self.vfo, memory)
            memory = ic9x_ll.get_memory(self.pipe, self.vfo, memory.number)

        self.__memcache[memory.number] = memory

    @locked
    def _ic9x_get_banks(self):
        if len(list(self.__bankcache.keys())) == 26:
            return [self.__bankcache[k] for k in
                    sorted(self.__bankcache.keys())]

        banks = ic9x_ll.get_banks(self.pipe, self.vfo)

        i = 0
        for bank in banks:
            self.__bankcache[i] = bank
            i += 1

        return banks

    @locked
    def _ic9x_set_banks(self, banks):

        if len(banks) != len(list(self.__bankcache.keys())):
            raise errors.InvalidDataError("Invalid bank list length (%i:%i)" %
                                          (len(banks),
                                           len(list(self.__bankcache.keys()))))

        cached_names = [str(self.__bankcache[x])
                        for x in sorted(self.__bankcache.keys())]

        need_update = False
        for i in range(0, 26):
            if banks[i] != cached_names[i]:
                need_update = True
                self.__bankcache[i] = banks[i]
                LOG.dbeug("Updating %s: %s -> %s" %
                          (chr(i + ord("A")), cached_names[i], banks[i]))

        if need_update:
            ic9x_ll.set_banks(self.pipe, self.vfo, banks)

    def get_sub_devices(self):
        return [IC9xRadioA(self.pipe, lock=self._lock),
                IC9xRadioB(self.pipe, lock=self._lock)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_sub_devices = True
        rf.valid_special_chans = list(IC9X_SPECIAL[self.vfo].keys())

        return rf


class IC9xRadioA(IC9xRadio):
    """IC9x Band A subdevice"""
    VARIANT = "Band A"
    vfo = 1
    _upper = 849

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.memory_bounds = (0, self._upper)
        rf.valid_modes = ["FM", "WFM", "AM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(500000, 9990000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 8
        return rf


class IC9xRadioB(IC9xRadio, chirp_common.IcomDstarSupport):
    """IC9x Band B subdevice"""
    VARIANT = "Band B"
    vfo = 2
    _upper = 399

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 61)
    RPTCALL_LIMIT = (1, 61)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.requires_call_lists = False
        rf.memory_bounds = (0, self._upper)
        rf.valid_modes = ["FM", "NFM", "AM", "DV"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(118000000, 174000000), (350000000, 470000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 8
        return rf

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__rcalls = []
        self.__mcalls = []
        self.__ucalls = []

    @locked
    def __get_call_list(self, cache, cstype, ulimit):
        if cache:
            return cache

        calls = []

        for i in range(ulimit - 1):
            call = ic9x_ll.get_call(self.pipe, cstype, i+1)
            calls.append(call)

        return calls

    @locked
    def __set_call_list(self, cache, cstype, ulimit, calls):
        for i in range(ulimit - 1):
            blank = " " * 8

            try:
                acall = cache[i]
            except IndexError:
                acall = blank

            try:
                bcall = calls[i]
            except IndexError:
                bcall = blank

            if acall == bcall:
                continue    # No change to this one

            ic9x_ll.set_call(self.pipe, cstype, i + 1, calls[i])

        return calls

    def get_mycall_list(self):
        self.__mcalls = self.__get_call_list(self.__mcalls,
                                             ic9x_ll.IC92MyCallsignFrame,
                                             self.MYCALL_LIMIT[1])
        return self.__mcalls

    def get_urcall_list(self):
        self.__ucalls = self.__get_call_list(self.__ucalls,
                                             ic9x_ll.IC92YourCallsignFrame,
                                             self.URCALL_LIMIT[1])
        return self.__ucalls

    def get_repeater_call_list(self):
        self.__rcalls = self.__get_call_list(self.__rcalls,
                                             ic9x_ll.IC92RepeaterCallsignFrame,
                                             self.RPTCALL_LIMIT[1])
        return self.__rcalls

    def set_mycall_list(self, calls):
        self.__mcalls = self.__set_call_list(self.__mcalls,
                                             ic9x_ll.IC92MyCallsignFrame,
                                             self.MYCALL_LIMIT[1],
                                             calls)

    def set_urcall_list(self, calls):
        self.__ucalls = self.__set_call_list(self.__ucalls,
                                             ic9x_ll.IC92YourCallsignFrame,
                                             self.URCALL_LIMIT[1],
                                             calls)

    def set_repeater_call_list(self, calls):
        self.__rcalls = self.__set_call_list(self.__rcalls,
                                             ic9x_ll.IC92RepeaterCallsignFrame,
                                             self.RPTCALL_LIMIT[1],
                                             calls)


def _test():
    import serial
    ser = IC9xRadioB(serial.Serial(port="/dev/ttyUSB1",
                                   baudrate=38400, timeout=0.1))
    print(ser.get_urcall_list())
    print("-- FOO --")
    ser.set_urcall_list(["K7TAY", "FOOBAR", "BAZ"])


if __name__ == "__main__":
    _test()
