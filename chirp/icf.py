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


import struct
import re

from chirp import chirp_common, errors, util, memmap
from chirp import ic9x_ll # for magic; may need to move later

CMD_CLONE_OUT = 0xE2
CMD_CLONE_IN  = 0xE3
CMD_CLONE_DAT = 0xE4
CMD_CLONE_END = 0xE5

save_pipe = None

class IcfFrame:
    src = 0
    dst = 0
    cmd = 0

    payload = ""

    def __str__(self):
        addrs = { 0xEE : "PC",
                  0xEF : "Radio"}
        cmds = {0xE0 : "ID",
                0xE1 : "Model",
                0xE2 : "Clone out",
                0xE3 : "Clone in",
                0xE4 : "Clone data",
                0xE5 : "Clone end",
                0xE6 : "Clone result"}

        return "%s -> %s [%s]:\n%s" % (addrs[self.src], addrs[self.dst],
                                       cmds[self.cmd],
                                       util.hexprint(self.payload))

    def __init__(self):
        pass

def parse_frame_generic(data):
    frame = IcfFrame()

    frame.src = ord(data[2])
    frame.dst = ord(data[3])
    frame.cmd = ord(data[4])

    try:
        end = data.index("\xFD")
    except ValueError:
        return None, data

    frame.payload = data[5:end]

    return frame, data[end+1:]

class RadioStream:
    def __init__(self, pipe):
        self.pipe = pipe
        self.data = ""

    def _process_frames(self):
        if not self.data.startswith("\xFE\xFE"):
            raise errors.InvalidDataError("Out of sync with radio")
        elif len(self.data) < 5:
            return [] # Not enough data for a full frame

        frames = []

        while self.data:
            try:
                cmd = ord(self.data[4])
            except IndexError:
                break # Out of data

            try:
                frame, rest = parse_frame_generic(self.data)
                if not frame:
                    break
                elif frame.src == 0xEE:
                    # PC echo, ignore
                    pass
                else:
                    frames.append(frame)

                self.data = rest
            except errors.InvalidDataError, e:
                print "Failed to parse frame (cmd=%i): %s" % (cmd, e)
                return []

        return frames

    def get_frames(self, nolimit=False):
        while True:
            _data = self.pipe.read(64)
            if not _data:
                break
            else:
                self.data += _data

            if not nolimit and len(self.data) > 128 and "\xFD" in self.data:
                break # Give us a chance to do some status

        if not self.data:
            return []

        return self._process_frames()

def get_model_data(pipe, model="\x00\x00\x00\x00"):
    send_clone_frame(pipe, 0xe0, model, raw=True)
    
    stream = RadioStream(pipe)
    frames = stream.get_frames()

    if len(frames) != 1:
        raise errors.RadioError("Unexpected response from radio")

    return frames[0].payload

def get_clone_resp(pipe, length=None):
    def exit_criteria(buf, length):
        if length is None:
            return buf.endswith("\xfd")
        else:
            return len(buf) == length

    resp = ""
    while not exit_criteria(resp, length):
        resp += pipe.read(1)

    return resp

def send_clone_frame(pipe, cmd, data, raw=False, checksum=False):
    cs = 0

    if raw:
        hed = data
    else:
        hed = ""
        for byte in data:
            val = ord(byte)
            hed += "%02X" % val
            cs += val

    if checksum:
        cs = ((cs ^ 0xFFFF) + 1) & 0xFF
        cs = "%02X" % cs
    else:
        cs = ""

    frame = "\xfe\xfe\xee\xef%s%s%s\xfd" % (chr(cmd), hed, cs)

    if save_pipe:
        print "Saving data..."
        save_pipe.write(frame)

    #print "Sending:\n%s" % util.hexprint(frame)
    #print "Sending:\n%s" % util.hexprint(hed[6:])
    if cmd == 0xe4:
        # Uncomment to avoid cloning to the radio
        # return frame
        pass
    
    pipe.write(frame)

    return frame

def process_data_frame(frame, mmap):

    data = frame.payload

    bytes = int(data[4:6], 16)
    fdata = data[6:6+(bytes * 2)]
    saddr = int(data[0:4], 16)
    #eaddr = saddr + bytes
    #try:
    #    checksum = data[6+(bytes * 2)]
    #except IndexError:
    #    print "%i Frame data:\n%s" % (bytes, util.hexprint(data))
    #    raise errors.InvalidDataError("Short frame")

    data = ""
    i = 0
    while i < range(len(fdata)) and i+1 < len(fdata):
        try:
            val = int("%s%s" % (fdata[i], fdata[i+1]), 16)
            i += 2
            data += struct.pack("B", val)
        except ValueError, e:
            print "Failed to parse byte: %s" % e
            break

    mmap[saddr] = data
    return saddr, saddr + bytes

def clone_from_radio(radio):
    md = get_model_data(radio.pipe)

    if md[0:4] != radio.get_model():
        print "This model: %s" % util.hexprint(md[0:4])
        print "Supp model: %s" % util.hexprint(radio.get_model())
        raise errors.RadioError("I can't talk to this model")

    send_clone_frame(radio.pipe, CMD_CLONE_OUT, radio.get_model(), raw=True)

    stream = RadioStream(radio.pipe)

    addr = 0
    mmap = memmap.MemoryMap(chr(0x00) * radio._memsize)
    last_size = 0
    while True:
        frames = stream.get_frames()
        if not frames:
            break

        for frame in frames:
            if frame.cmd == CMD_CLONE_DAT:
                src, dst = process_data_frame(frame, mmap)
                if last_size != (dst - src):
                    print "ICF Size change from %i to %i at %04x" % (last_size,
                                                                     dst - src,
                                                                     src)
                    last_size = dst - src
                if addr != src:
                    print "ICF GAP %04x - %04x" % (addr, src)
                addr = dst
            elif frame.cmd == CMD_CLONE_END:
                print "End frame:\n%s" % util.hexprint(frame.payload)
                print "Last addr: %04x" % addr

        if radio.status_fn:
            status = chirp_common.Status()
            status.msg = "Cloning from radio"
            status.max = radio.get_memsize()
            status.cur = addr
            radio.status_fn(status)

    return mmap

def send_mem_chunk(radio, start, stop, bs=32):
    mmap = radio.get_mmap()

    status = chirp_common.Status()
    status.msg = "Cloning to radio"
    status.max = radio.get_memsize()

    for i in range(start, stop, bs):
        if i + bs < stop:
            size = bs
        else:
            size = stop - i

        chunk = struct.pack(">HB", i, size) + mmap[i:i+size]

        send_clone_frame(radio.pipe,
                         CMD_CLONE_DAT,
                         chunk,
                         checksum=True)

        if radio.status_fn:
            status.cur = i+bs
            radio.status_fn(status)

    return True

def clone_to_radio(radio):
    global save_pipe

    # Uncomment to save out a capture of what we actually write to the radio
    # save_pipe = file("pipe_capture.log", "w", 0)

    md = get_model_data(radio.pipe)

    if md[0:4] != radio.get_model():
        raise errors.RadioError("I can't talk to this model")

    # This mimics what the Icom software does, but isn't required and just
    # takes longer
    # md = get_model_data(radio.pipe, model=md[0:2]+"\x00\x00")
    # md = get_model_data(radio.pipe, model=md[0:2]+"\x00\x00")

    stream = RadioStream(radio.pipe)

    send_clone_frame(radio.pipe, CMD_CLONE_IN, radio.get_model(), raw=True)

    frames = []

    for start, stop, bs in radio.get_ranges():
        if not send_mem_chunk(radio, start, stop, bs):
            break
        frames += stream.get_frames()

    send_clone_frame(radio.pipe, CMD_CLONE_END, radio.get_endframe(), raw=True)
    frames += stream.get_frames(True)

    if save_pipe:
        save_pipe.close()
        save_pipe = None

    try:
        result = frames[-1]
    except IndexError:
        raise errors.RadioError("Did not get clone result from radio")

    return result.payload[0] == '\x00'

def convert_model(mod_str):
    data = ""
    for i in range(0, len(mod_str), 2):
        hex = mod_str[i:i+2]
        val = int(hex, 16)
        data += chr(val)

    return data

def convert_data_line(line):
    if line.startswith("#"):
        return ""

    pos = int(line[0:4], 16)
    len = int(line[4:6], 16)
    dat = line[6:]

    _mmap = ""
    i = 0
    while i < (len * 2):
        try:
            val = int("%s%s" % (dat[i], dat[i+1]), 16)
            i += 2
            _mmap += struct.pack("B", val)
        except ValueError, e:
            print "Failed to parse byte: %s" % e
            break

    return _mmap

def read_file(filename):
    f = file(filename)

    mod_str = f.readline()
    dat = f.readlines()
    
    model = convert_model(mod_str.strip())

    _mmap = ""
    for line in dat:
        if not line.startswith("#"):
            _mmap += convert_data_line(line)

    return model, memmap.MemoryMap(_mmap)

def is_9x_icf(filename):
    f = file(filename)
    mdata = f.read(8)
    f.close()

    return mdata in ["30660000", "28880000"]

def is_icf_file(filename):
    f = file(filename)
    data = f.readline()
    data += f.readline()
    f.close()

    data = data.replace("\n", "").replace("\r", "")

    return bool(re.match("^[0-9]{8}#", data))

class IcomBank(chirp_common.Bank):
    # Integral index of the bank (not to be confused with per-memory
    # bank indexes
    index = 0

class IcomBankModel(chirp_common.BankModel):
    """Icom radios all have pretty much the same simple bank model. This
    central implementation can, with a few icom-specific radio interfaces
    serve most/all of them"""

    def get_num_banks(self):
        return self._radio._num_banks

    def get_banks(self):
        banks = []
        
        for i in range(0, self._radio._num_banks):
            index = chr(ord("A") + i)
            bank = self._radio._bank_class(self, index, "BANK-%s" % index)
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_bank(self, memory, bank):
        self._radio._set_bank(memory.number, bank.index)

    def remove_memory_from_bank(self, memory, bank):
        if self._radio._get_bank(memory.number) != bank.index:
            raise Exception("Memory %i not in bank %s. Cannot remove." % \
                                (memory.number, bank))

        self._radio._set_bank(memory.number, None)

    def get_bank_memories(self, bank):
        memories = []
        for i in range(*self._radio.get_features().memory_bounds):
            if self._radio._get_bank(i) == bank.index:
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_banks(self, memory):
        index = self._radio._get_bank(memory.number)
        if index is None:
            return []
        else:
            return [self.get_banks()[index]]
    
class IcomIndexedBankModel(IcomBankModel, chirp_common.BankIndexInterface):
    def get_index_bounds(self):
        return self._radio._bank_index_bounds

    def get_memory_index(self, memory, bank):
        return self._radio._get_bank_index(memory.number)

    def set_memory_index(self, memory, bank, index):
        if bank not in self.get_memory_banks(memory):
            raise Exception("Memory %i is not in bank %s" % (memory.number,
                                                             bank))

        if index not in range(*self._radio._bank_index_bounds):
            raise Exception("Invalid index")
        self._radio._set_bank_index(memory.number, index)

    def get_next_bank_index(self, bank):
        indexes = []
        for i in range(*self._radio.get_features().memory_bounds):
            if self._radio._get_bank(i) == bank.index:
                indexes.append(self._radio._get_bank_index(i))
                
        for i in range(0, 256):
            if i not in indexes:
                return i

        raise errors.RadioError("Out of slots in this bank")
        

class IcomCloneModeRadio(chirp_common.CloneModeRadio):
    VENDOR = "Icom"
    BAUDRATE = 9600

    _model = "\x00\x00\x00\x00"  # 4-byte model string
    _endframe = ""               # Model-unique ending frame
    _ranges = []                 # Ranges of the mmap to send to the radio
    _num_banks = 10              # Most simple Icoms have 10 banks, A-J
    _bank_index_bounds = (0, 99)
    _bank_class = IcomBank

    def get_model(self):
        return self._model

    def get_endframe(self):
        return self._endframe

    def get_ranges(self):
        return self._ranges

    def sync_in(self):
        self._mmap = clone_from_radio(self)
        self.process_mmap()

    def sync_out(self):
        clone_to_radio(self)

    def get_bank_model(self):
        rf = self.get_features()
        if rf.has_bank:
            if rf.has_bank_index:
                return IcomIndexedBankModel(self)
            else:
                return IcomBankModel(self)
        else:
            return None

    # Icom-specific bank routines
    def _get_bank(self, loc):
        """Get the integral bank index of memory @loc, or None"""
        raise Exception("Not implemented")

    def _set_bank(self, loc, index):
        """Set the integral bank index of memory @loc to @index, or
        no bank if None"""
        raise Exception("Not implemented")

class IcomLiveRadio(chirp_common.LiveRadio):
    VENDOR = "Icom"
    BAUD_RATE = 38400

if __name__ == "__main__":
    import sys

    model, mmap = read_file(sys.argv[1])

    print util.hexprint(model)

    f = file("out.img", "w")
    f.write(mmap.get_packed())
    f.close()
