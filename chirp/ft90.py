# Copyright 2011 Dan Smith <dsmith@danplanet.com>
# Copyright 2013 Jens Jensen <kd4tjx@yahoo.com>
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

from chirp import chirp_common, bitwise, memmap, directory, errors, util, yaesu_clone
import time, os, traceback, string

CHIRP_DEBUG=False
CMD_ACK = chr(0x06)

FT90_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
FT90_MODES = ["AM", "FM", "Auto"]
FT90_TMODES = ["", "Tone", "TSQL", "", "DTCS"] # idx 3 (Bell) not supported yet
FT90_TONES = list(chirp_common.TONES)
for tone in [ 165.5, 171.3, 177.3 ]:
    FT90_TONES.remove(tone)
FT90_POWER_LEVELS = ["Hi", "Mid1", "Mid2", "Low"]
FT90_DUPLEX = ["", "-", "+", "split"]
FT90_CWID_CHARS = list(string.digits) + list(string.uppercase)

@directory.register
class FT90Radio(yaesu_clone.YaesuCloneModeRadio):
    VENDOR = "Yaesu"
    MODEL = "FT-90"
    ID = "\x8E\xF6"

    _memsize = 4063
    # block 03 (200 Bytes long) repeats 18 times; channel memories
    _block_lengths = [ 2, 232, 24, 200, 205]
    
    mem_format = """
	#seekto 0x22;	
	struct {
		u8	dtmf_active;
		u8	dtmf1_len;
		u8	dtmf2_len;
		u8	dtmf3_len;
		u8	dtmf4_len;
		u8	dtmf5_len;
		u8	dtmf6_len;
		u8	dtmf7_len;
		u8	dtmf8_len;
		bbcd dtmf1[8];
		bbcd dtmf2[8];
		bbcd dtmf3[8];
		bbcd dtmf4[8];			
		bbcd dtmf5[8];
		bbcd dtmf6[8];
		bbcd dtmf7[8];	
		bbcd dtmf8[8];
		char cwid[7];
		u8 	unk1;
		u8 	unk2:2,
			beep:1,
			unk3:1,
			rfsqlvl:4;
		u8	cwid_en:1,
			unk4:3,
			txnarrow:1,
			dtmfspeed:1,
			pttlock:2;
		u8	dtmftxdelay:3,
			fancontrol:2,
			unk5:3;
		u8	dimmer:3,
			unk6:1,
			lcdcontrast:4;
		u8	tot;
		u8	unk8:1,
			ars:1,
			lock:1,
			txpwrsave:1,
			apo:4;
		u8	key_rt;
		u8	key_lt;
		u8	key_p1;
		u8	key_p2;
		u8	key_acc;
		char	demomsg1[32];
		char	demomsg2[32];
		
	} settings;
	
    struct mem_struct {
      u8 mode:2,
         isUhf1:1,
         unknown1:2,
         step:3;
      u8 artsmode:2,
         unknown2:1,
         isUhf2:1
         power:2,
         shift:2;
      u8 skip:1,
         showname:1,
         unknown3:1,
         isUhfHi:1,
         unknown4:1,
         tmode:3;
      u32 rxfreq;
      u32 txfreqoffset;
      u8 UseDefaultName:1,
         ars:1,
         tone:6;
      u8 packetmode:1,
         unknown5:1,
         dcstone:6;
      char name[7];
    };

	#seekto 0x86;
	struct mem_struct vfo_v;
	struct mem_struct call_v;
	struct mem_struct vfo_u;
	struct mem_struct call_u;
	
	#seekto 0x102;
    struct mem_struct memory[180];

	#seekto 0xf12;
	struct mem_struct pms_1L;
	struct mem_struct pms_1U;
	struct mem_struct pms_2L;	
	struct mem_struct pms_2U;
    """

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_ctone = False
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.has_dtcs = True
        rf.valid_modes = FT90_MODES
        rf.valid_tmodes = FT90_TMODES
        rf.valid_duplexes = FT90_DUPLEX
        rf.valid_tuning_steps = FT90_STEPS
        rf.valid_power_levels = FT90_POWER_LEVELS
        rf.valid_name_length = 7
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_skips = ["", "S"]
        rf.memory_bounds = (1, 180)
        rf.valid_bands = [(100000000, 230000000), 
            (300000000, 530000000), (810000000, 999975000)]

        return rf

    def _read(self, blocksize, blocknum):
        data = self.pipe.read(blocksize+2)
        
        # chew echo'd ack
        self.pipe.write(CMD_ACK)
        time.sleep(0.02)
        self.pipe.read(1) # chew echoed ACK from 1-wire serial
        
        if len(data) == blocksize+2 and data[0] == chr(blocknum):
            checksum = yaesu_clone.YaesuChecksum(1, blocksize)
            if checksum.get_existing(data) != checksum.get_calculated(data):
                raise Exception("Checksum Failed [%02X<>%02X] block %02X, data len: %i" %
                                    (checksum.get_existing(data),
                                    checksum.get_calculated(data), blocknum, len(data) ))
            data = data[1:blocksize+1] # Chew blocknum and checksum
            
        else:
            raise Exception("Unable to read blocknum %02X expected blocksize %i got %i." %
                                (blocknum, blocksize+2, len(data)))

        return data        
    
    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.setTimeout(4)
        start = time.time()
    
        data = ""
        blocknum = 0
        status = chirp_common.Status()
        status.msg = "Cloning from radio.\nPut radio into clone mode then\npress SET to send"
        self.status_fn(status)
        status.max = len(self._block_lengths) + 18
        for blocksize in self._block_lengths:
            if blocksize == 200:
                # repeated read of 200 block same size (memory area)
                repeat = 18
            else:
                repeat = 1
            for _i in range(0, repeat): 
                data += self._read(blocksize, blocknum)

                blocknum += 1
                status.cur = blocknum
                self.status_fn(status)
                
        status.msg = "Clone completed."
        self.status_fn(status)

        print "Clone completed in %i seconds, blocks read: %i" % (time.time() - start, blocknum)
    
        return memmap.MemoryMap(data)
    
    def _clone_out(self):
        delay = 0.2
        start = time.time()
    
        blocknum = 0
        pos = 0
        status = chirp_common.Status()
        status.msg = "Cloning to radio.\nPut radio into clone mode and press DISP/SS\n to start receive within 3 secs..."
        self.status_fn(status)
        # radio likes to have port open 
        self.pipe.open()
        time.sleep(3)
        status.max = len(self._block_lengths) + 18


        for blocksize in self._block_lengths:
            if blocksize == 200:
                # repeat channel blocks
                repeat = 18
            else:
                repeat = 1
            for _i in range(0, repeat):
                time.sleep(0.1)
                checksum = yaesu_clone.YaesuChecksum(pos, pos+blocksize-1)
                blocknumbyte = chr(blocknum)
                payloadbytes = self.get_mmap()[pos:pos+blocksize]
                checksumbyte = chr(checksum.get_calculated(self.get_mmap()))
                if os.getenv("CHIRP_DEBUG") or CHIRP_DEBUG:
                    print "Block %i - will send from %i to %i byte " % \
                        (blocknum, pos, pos + blocksize)
                    print util.hexprint(blocknumbyte)
                    print util.hexprint(payloadbytes)
                    print util.hexprint(checksumbyte)
                # send wrapped bytes
                self.pipe.write(blocknumbyte)
                self.pipe.write(payloadbytes)
                self.pipe.write(checksumbyte)
                tmp = self.pipe.read(blocksize+2)  #chew echo
                if os.getenv("CHIRP_DEBUG") or CHIRP_DEBUG:                
                    print "bytes echoed: "
                    print util.hexprint(tmp)
                # radio is slow to write/ack:
                time.sleep(0.9) 
                buf = self.pipe.read(1)
                if os.getenv("CHIRP_DEBUG") or CHIRP_DEBUG:                
                    print "ack recd:"
                    print util.hexprint(buf)
                if buf != CMD_ACK:
                    raise Exception("Radio did not ack block %i" % blocknum)
                pos += blocksize
                blocknum += 1
                status.cur = blocknum
                self.status_fn(status)
    
        print "Clone completed in %i seconds" % (time.time() - start)
    
    def sync_in(self):
        try:
            self._mmap = self._clone_in()
        except errors.RadioError:
            raise
        except Exception, e:
            trace = traceback.format_exc()
            raise errors.RadioError("Failed to communicate with radio: %s" % trace)
        self.process_mmap()

    def sync_out(self):
        try:
            self._clone_out()
        except errors.RadioError:
            raise
        except Exception, e:
            trace = traceback.format_exc()
            raise errors.RadioError("Failed to communicate with radio: %s" % trace)

    def process_mmap(self):
        self._memobj = bitwise.parse(self.mem_format, self._mmap)

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = _mem.rxfreq * 10      
        mem.offset = _mem.txfreqoffset * 10
        if not _mem.tmode < len(FT90_TMODES):
            _mem.tmode = 0
        mem.tmode = FT90_TMODES[_mem.tmode]
        mem.rtone = FT90_TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcstone]
        mem.mode = FT90_MODES[_mem.mode]
        mem.duplex = FT90_DUPLEX[_mem.shift]
        mem.power = FT90_POWER_LEVELS[_mem.power]
        # radio has a known bug with 5khz step and squelch
        if _mem.step == 0:
            _mem.step = 2
        mem.tuning_step = FT90_STEPS[_mem.step]
        mem.skip = _mem.skip and "S" or ""
        mem.name = _mem.name
        return mem

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])
    
    def set_memory(self, mem):

        _mem = self._memobj.memory[mem.number - 1]
        _mem.skip = mem.skip == "S"
        # radio has a known bug with 5khz step and dead squelch
        if not mem.tuning_step or mem.tuning_step == FT90_STEPS[0]:
            _mem.step = 2
        else:
            _mem.step = FT90_STEPS.index(mem.tuning_step)
        _mem.rxfreq = mem.freq / 10
        # vfo will unlock if not in right band?
        if mem.freq > 300000000: 
            # uhf
            _mem.isUhf1 = 1
            _mem.isUhf2 = 1
            if mem.freq > 810000000:
                # uhf hiband
                _mem.isUhfHi = 1
            else:
                _mem.isUhfHi = 0
        else:
            # vhf
            _mem.isUhf1 = 0
            _mem.isUhf2 = 0
            _mem.isUhfHi = 0
        _mem.txfreqoffset = mem.offset / 10
        _mem.tone = FT90_TONES.index(mem.rtone)
        _mem.tmode = FT90_TMODES.index(mem.tmode)
        _mem.mode = FT90_MODES.index(mem.mode)
        _mem.shift = FT90_DUPLEX.index(mem.duplex)    
        _mem.dcstone = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.step = FT90_STEPS.index(mem.tuning_step)
        _mem.shift = FT90_DUPLEX.index(mem.duplex)
        if mem.power:
            _mem.power = FT90_POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 3  # default to low power
        _mem.name = mem.name.ljust(7)
 

