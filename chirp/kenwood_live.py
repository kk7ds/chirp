# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

import threading
import os
import sys
import time

NOCACHE = os.environ.has_key("CHIRP_NOCACHE")

from chirp import chirp_common, errors, directory

DEBUG = True

DUPLEX = { 0 : "", 1 : "+", 2 : "-" }
MODES = { 0 : "FM", 1 : "AM" }
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.append(100.0)

THF6_MODES = ["FM", "WFM", "AM", "LSB", "USB", "CW"]

def rev(hash, value):
    reverse = {}
    for k, v in hash.items():
        reverse[v] = k

    return reverse[value]

LOCK = threading.Lock()

def command(s, command, *args):
    global LOCK

    start = time.time()

    LOCK.acquire()
    cmd = command
    if args:
        cmd += " " + " ".join(args)
    if DEBUG:
        print "PC->RADIO: %s" % cmd
    s.write(cmd + "\r")

    result = ""
    while not result.endswith("\r"):
        result += s.read(8)
        if (time.time() - start) > 0.5:
            print "Timeout waiting for data"
            break

    if DEBUG:
        print "D7->PC: %s" % result.strip()

    LOCK.release()

    return result.strip()

LAST_BAUD = 9600
def get_id(s):
    global LAST_BAUD
    bauds = [9600, 19200, 38400, 57600]
    bauds.remove(LAST_BAUD)
    bauds.insert(0, LAST_BAUD)

    for i in bauds:
        print "Trying ID at baud %i" % i
        s.setBaudrate(i)
        s.write("\r")
        s.read(25)
        r = command(s, "ID")
        if " " in r:
            LAST_BAUD = i
            return r.split(" ")[1]

    raise errors.RadioError("No response from radio")

def get_tmode(tone, ctcss, dcs):
    if dcs and int(dcs) == 1:
        return "DTCS"
    elif int(ctcss):
        return "TSQL"
    elif int(tone):
        return "Tone"
    else:
        return ""

def iserr(result):
    return result in ["N", "?"]

class KenwoodLiveRadio(chirp_common.LiveRadio):
    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = ""

    _vfo = 0
    _upper = 200

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)

        self.__memcache = {}

        if self.pipe:
            self.pipe.setTimeout(0.1)
            radio_id = get_id(self.pipe)
            if radio_id != self.MODEL:
                raise Exception("Radio reports %s (not %s)" % (radio_id,
                                                               self.MODEL))

            command(self.pipe, "AI", "0")

    def _cmd_get_memory(self, number):
        return "MR", "%i,0,%03i" % (self._vfo, number)

    def _cmd_get_memory_name(self, number):
        return "MNA", "%i,%03i" % (self._vfo, number)

    def _cmd_set_memory(self, number, spec):
        if spec:
            spec = "," + spec
        return "MW", "%i,0,%03i%s" % (self._vfo, number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%i,%03i,%s" % (self._vfo, number, name)

    def get_raw_memory(self, number):
        return command(self.pipe, *self._cmd_get_memory(number))

    def get_memory(self, number):
        if number < 0 or number > self._upper:
            raise errors.InvalidMemoryLocation( \
                "Number must be between 0 and %i" % self._upper)
        if self.__memcache.has_key(number) and not NOCACHE:
            return self.__memcache[number]

        result = command(self.pipe, *self._cmd_get_memory(number))
        if result == "N":
            mem = chirp_common.Memory()
            mem.number = number
            mem.empty = True
            self.__memcache[mem.number] = mem
            return mem
        elif " " not in result:
            print "Not sure what to do with this: `%s'" % result
            raise errors.RadioError("Unexpected result returned from radio")

        value = result.split(" ")[1]
        spec = value.split(",")

        mem = self._parse_mem_spec(spec)
        self.__memcache[mem.number] = mem

        result = command(self.pipe, *self._cmd_get_memory_name(number))
        if " " in result:
            value = result.split(" ", 1)[1]
            if value.count(",") == 2:
                zero, loc, mem.name = value.split(",")
            else:
                loc, mem.name = value.split(",")
 
        return mem

    def _make_mem_spec(self, mem):
        pass

    def _parse_mem_spec(self, spec):
        pass

    def set_memory(self, memory):
        if memory.number < 0 or memory.number > self._upper:
            raise errors.InvalidMemoryLocation( \
                "Number must be between 0 and %i" % self._upper)

        spec = self._make_mem_spec(memory)
        spec = ",".join(spec)
        r1 = command(self.pipe, *self._cmd_set_memory(memory.number, spec))
        if not iserr(r1):
            import time
            time.sleep(0.5)
            r2 = command(self.pipe, *self._cmd_set_memory_name(memory.number,
                                                               memory.name))
            if not iserr(r2):
                self.__memcache[memory.number] = memory
            else:
                raise errors.InvalidDataError("Radio refused name %i: %s" %\
                                                  (memory.number,
                                                   repr(memory.name)))
        else:
            raise errors.InvalidDataError("Radio refused %i" % memory.number)

    def erase_memory(self, number):
        if not self.__memcache.has_key(number):
            return

        r = command(self.pipe, *self._cmd_set_memory(number, ""))
        if iserr(r):
            raise errors.RadioError("Radio refused delete of %i" % number)
        del self.__memcache[number]

@directory.register
class THD7Radio(KenwoodLiveRadio):
    MODEL = "TH-D7"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = True
        rf.has_tuning_step = False
        rf.valid_modes = MODES.values()
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 7
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        spec = ( \
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % rev(DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "", # DCS Flag
            "%02i" % (chirp_common.TONES.index(mem.rtone) + 1),
            "", # DCS Code
            "%02i" % (chirp_common.TONES.index(mem.ctone) + 1),
            "%09i" % mem.offset,
            "%i" % rev(MODES, mem.mode),
            "%i" % ((mem.skip == "S") and 1 or 0))

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[2])
        mem.freq = int(spec[3], 10)
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        mem.tmode = get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = chirp_common.TONES[int(spec[10]) - 1]
        mem.ctone = chirp_common.TONES[int(spec[12]) - 1]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        else:
            print "Unknown or invalid DCS: %s" % spec[11]
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = MODES[int(spec[14])]
        mem.skip = int(spec[15]) and "S" or ""

        return mem

@directory.register
class THD7GRadio(THD7Radio):
    MODEL = "TH-D7G"

@directory.register
class TMD700Radio(KenwoodLiveRadio):
    MODEL = "TM-D700"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = False
        rf.has_tuning_step = False
        rf.valid_modes = ["FM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 8
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        spec = ( \
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % rev(DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "%i" % (mem.tmode == "DTCS"),
            "%02i" % (chirp_common.TONES.index(mem.rtone) + 1),
            "%03i0" % (chirp_common.DTCS_CODES.index(mem.dtcs) + 1),
            "%02i" % (chirp_common.TONES.index(mem.ctone) + 1),
            "%09i" % mem.offset,
            "%i" % rev(MODES, mem.mode),
            "%i" % ((mem.skip == "S") and 1 or 0))

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[2])
        mem.freq = int(spec[3])
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        mem.tmode = get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = chirp_common.TONES[int(spec[10]) - 1]
        mem.ctone = chirp_common.TONES[int(spec[12]) - 1]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        else:
            print "Unknown or invalid DCS: %s" % spec[11]
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = MODES[int(spec[14])]
        mem.skip = int(spec[15]) and "S" or ""

        return mem

@directory.register
class TMV7Radio(KenwoodLiveRadio):
    MODEL = "TM-V7"

    mem_upper_limit = 200 # Will be updated

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = False
        rf.has_tuning_step = False
        rf.valid_modes = ["FM"]
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 7
        rf.has_sub_devices = True
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        spec = ( \
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % rev(DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "0",
            "%02i" % (chirp_common.TONES.index(mem.rtone) + 1),
            "000",
            "%02i" % (chirp_common.TONES.index(mem.ctone) + 1),
            "",
            "0")

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()
        mem.number = int(spec[2])
        mem.freq = int(spec[3])
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        if int(spec[7]):
            mem.tmode = "Tone"
        elif int(spec[8]):
            mem.tmode = "TSQL"
        mem.rtone = chirp_common.TONES[int(spec[10]) - 1]
        mem.ctone = chirp_common.TONES[int(spec[12]) - 1]

        return mem

    def get_sub_devices(self):
        return [TMV7RadioVHF(self.pipe), TMV7RadioUHF(self.pipe)]

    def __test_location(self, loc):
        mem = self.get_memory(loc)
        if not mem.empty:
            # Memory was not empty, must be valid
            return True

        # Mem was empty (or invalid), try to set it
        if self._vfo == 0:
            mem.freq = 144000000
        else:
            mem.freq = 440000000
        mem.empty = False
        try:
            self.set_memory(mem)
        except:
            # Failed, so we're past the limit
            return False

        # Erase what we did
        try:
            self.erase_memory(loc)
        except:
            pass # V7A Can't delete just yet

        return True

    def _detect_split(self):
        return 50

class TMV7RadioSub(TMV7Radio):
    def __init__(self, pipe):
        KenwoodLiveRadio.__init__(self, pipe)
        self._detect_split()

class TMV7RadioVHF(TMV7RadioSub):
    VARIANT = "VHF"
    _vfo = 0

class TMV7RadioUHF(TMV7RadioSub):
    VARIANT = "UHF"
    _vfo = 1

if __name__ == "__main__":
    import serial
    import sys

    s = serial.Serial(port=sys.argv[1], baudrate=9600, xonxoff=True, timeout=1)

    print get_id(s)
    print get_memory(s, int(sys.argv[2]))

THF6A_STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]

THF6A_DUPLEX = dict(DUPLEX)
THF6A_DUPLEX[3] = "split"

@directory.register
class THF6ARadio(KenwoodLiveRadio):
    MODEL = "TH-F6"

    _upper = 399

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_modes = list(THF6_MODES)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_tuning_steps = list(THF6A_STEPS)
        rf.valid_bands = [(1000, 1300000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_duplexes = THF6A_DUPLEX.values()
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 8
        rf.memory_bounds = (0, self._upper)
        return rf

    def _cmd_set_memory(self, number, spec):
        if spec:
            spec = "," + spec
        return "MW", "0,%03i%s" % (number, spec)

    def _cmd_get_memory(self, number):
        return "MR", "0,%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MNA", "%03i" % number

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%03i,%s" % (number, name)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[1])
        mem.freq = int(spec[2])
        mem.tuning_step = THF6A_STEPS[int(spec[3], 16)]
        mem.duplex = THF6A_DUPLEX[int(spec[4])]
        mem.tmode = get_tmode(spec[6], spec[7], spec[8])
        mem.rtone = chirp_common.TONES[int(spec[9])]
        mem.ctone = chirp_common.TONES[int(spec[10])]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11])]
        else:
            print "Unknown or invalid DCS: %s" % spec[11]
        if spec[11]:
            mem.offset = int(spec[12])
        else:
            mem.offset = 0
        mem.mode = THF6_MODES[int(spec[13])]
        if spec[14] == "1":
            mem.skip = "S"

        return mem

    def _make_mem_spec(self, mem):
        spec = ( \
            "%011i" % mem.freq,
            "%X" % THF6A_STEPS.index(mem.tuning_step),
            "%i" % rev(THF6A_DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "%i" % (mem.tmode == "DTCS"),
            "%02i" % (chirp_common.TONES.index(mem.rtone)),
            "%02i" % (chirp_common.TONES.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "%09i" % mem.offset,
            "%i" % (THF6_MODES.index(mem.mode)),
            "%i" % (mem.skip == "S"))

        return spec

@directory.register
class THF7ERadio(THF6ARadio):
    MODEL = "TH-F7"

D710_DUPLEX = ["", "+", "-", "split"]
D710_MODES = ["FM", "NFM", "AM"]
D710_SKIP = ["", "S"]
D710_STEPS = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]
D710_TONES = list(chirp_common.TONES)
D710_TONES.remove(159.8)
D710_TONES.remove(165.5)
D710_TONES.remove(171.3)
D710_TONES.remove(177.3)
D710_TONES.remove(183.5)
D710_TONES.remove(189.9)
D710_TONES.remove(196.6)
D710_TONES.remove(199.5)

@directory.register
class TMD710Radio(KenwoodLiveRadio):
    MODEL = "TM-D710"
    
    _upper = 999
    _kenwood_valid_tones = list(D710_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = D710_MODES
        rf.valid_duplexes = D710_DUPLEX
        rf.valid_tuning_steps = D710_STEPS
        rf.valid_characters = chirp_common.CHARSET_ASCII.replace(',','')
        rf.valid_name_length = 8
        rf.valid_skips = D710_SKIP
        rf.memory_bounds = (0, 999)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%03i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%03i,%s" % (number, name)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        mem.tuning_step = D710_STEPS[int(spec[2], 16)]
        mem.duplex = D710_DUPLEX[int(spec[3])]
        # Reverse
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = chirp_common.TONES[int(spec[8])]
        mem.ctone = chirp_common.TONES[int(spec[9])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[10])]
        mem.offset = int(spec[11])
        mem.mode = D710_MODES[int(spec[12])]
        # TX Frequency
        if int(spec[13]):
            mem.duplex = "split"
            mem.offset = int(spec[13])
        # Unknown
        mem.skip = D710_SKIP[int(spec[15])] # Memory Lockout

        return mem

    def _make_mem_spec(self, mem):
        print "Index %i for step %.2f" % (chirp_common.TUNING_STEPS.index(mem.tuning_step), mem.tuning_step)
        spec = ( \
            "%010i" % mem.freq,
            "%X" % D710_STEPS.index(mem.tuning_step),
            "%i" % (0 if mem.duplex == "split" else D710_DUPLEX.index(mem.duplex)),
            "0", # Reverse
            "%i" % (mem.tmode == "Tone" and 1 or 0),
            "%i" % (mem.tmode == "TSQL" and 1 or 0),
            "%i" % (mem.tmode == "DTCS" and 1 or 0),
            "%02i" % (chirp_common.TONES.index(mem.rtone)),
            "%02i" % (chirp_common.TONES.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "%08i" % (0 if mem.duplex == "split" else mem.offset), # Offset
            "%i" % D710_MODES.index(mem.mode),
            "%010i" % (mem.offset if mem.duplex == "split" else 0), # TX Frequency
            "0", # Unknown
            "%i" % D710_SKIP.index(mem.skip), # Memory Lockout
            )

        return spec

@directory.register
class THD72Radio(TMD710Radio):
    MODEL = "TH-D72"
    HARDWARE_FLOW = sys.platform == "darwin" # only OS X driver needs hw flow

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        mem.tuning_step = D710_STEPS[int(spec[2], 16)]
        mem.duplex = D710_DUPLEX[int(spec[3])]
        # Reverse
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = chirp_common.TONES[int(spec[9])]
        mem.ctone = chirp_common.TONES[int(spec[10])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[11])]
        mem.offset = int(spec[13])
        mem.mode = D710_MODES[int(spec[14])]
        # TX Frequency
        if int(spec[15]):
            mem.duplex = "split"
            mem.offset = int(spec[15])
        # Lockout
        mem.skip = D710_SKIP[int(spec[17])] # Memory Lockout

        return mem

    def _make_mem_spec(self, mem):
        print "Index %i for step %.2f" % (chirp_common.TUNING_STEPS.index(mem.tuning_step), mem.tuning_step)
        spec = ( \
            "%010i" % mem.freq,
            "%X" % D710_STEPS.index(mem.tuning_step),
            "%i" % (0 if mem.duplex == "split" else D710_DUPLEX.index(mem.duplex)),
            "0", # Reverse
            "%i" % (mem.tmode == "Tone" and 1 or 0),
            "%i" % (mem.tmode == "TSQL" and 1 or 0),
            "%i" % (mem.tmode == "DTCS" and 1 or 0),
            "0",
            "%02i" % (chirp_common.TONES.index(mem.rtone)),
            "%02i" % (chirp_common.TONES.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "0",
            "%08i" % (0 if mem.duplex == "split" else mem.offset), # Offset
            "%i" % D710_MODES.index(mem.mode),
            "%010i" % (mem.offset if mem.duplex == "split" else 0), # TX Frequency
            "0", # Unknown
            "%i" % D710_SKIP.index(mem.skip), # Memory Lockout
            )

        return spec

@directory.register
class TMV71Radio(TMD710Radio):
	MODEL = "TM-V71"	

THK2_DUPLEX = ["", "+", "-"]
THK2_MODES = ["FM", "NFM"]
THK2_TONES = list(chirp_common.TONES)
THK2_TONES.remove(159.8) # ??
THK2_TONES.remove(165.5) # ??
THK2_TONES.remove(171.3) # ??
THK2_TONES.remove(177.3) # ??
THK2_TONES.remove(183.5) # ??
THK2_TONES.remove(189.9) # ??
THK2_TONES.remove(196.6) # ??
THK2_TONES.remove(199.5) # ??

THK2_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "-/"

@directory.register
class THK2Radio(KenwoodLiveRadio):
    MODEL = "TH-K2"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = THK2_MODES
        rf.valid_duplexes = THK2_DUPLEX
        rf.valid_characters = THK2_CHARS
        rf.valid_name_length = 6
        rf.valid_bands = [(136000000, 173990000)]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = [5.0]
        rf.memory_bounds = (1, 50)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%02i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%02i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%02i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%02i,%s" % (number, name)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        #mem.tuning_step = 
        mem.duplex = THK2_DUPLEX[int(spec[3])]
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = THK2_TONES[int(spec[8])]
        mem.ctone = THK2_TONES[int(spec[9])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[10])]
        mem.offset = int(spec[11])
        mem.mode = THK2_MODES[int(spec[12])]
        mem.skip = int(spec[16]) and "S" or ""
        return mem

    def _make_mem_spec(self, mem):
        try:
            rti = THK2_TONES.index(mem.rtone)
            cti = THK2_TONES.index(mem.ctone)
        except ValueError:
            raise errors.UnsupportedToneError()

        spec = ( \
            "%010i" % mem.freq,
            "0",
            "%i"    % THK2_DUPLEX.index(mem.duplex),
            "0",
            "%i"    % int(mem.tmode == "Tone"),
            "%i"    % int(mem.tmode == "TSQL"),
            "%i"    % int(mem.tmode == "DTCS"),
            "%02i"  % rti,
            "%02i"  % cti,
            "%03i"  % chirp_common.DTCS_CODES.index(mem.dtcs),
            "%08i"  % mem.offset,
            "%i"    % THK2_MODES.index(mem.mode),
            "0",
            "%010i" % 0,
            "0",
            "%i"    % int(mem.skip == "S")
            )
        return spec
            

@directory.register
class TM271Radio(THK2Radio):
    MODEL = "TM-271"
    
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = THK2_MODES
        rf.valid_duplexes = THK2_DUPLEX
        rf.valid_characters = THK2_CHARS
        rf.valid_name_length = 6
        rf.valid_bands = [(137000000, 173990000)]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = [5.0]
        rf.memory_bounds = (0, 99)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%03i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%03i,%s" % (number, name)
