#!/usr/bin/python

import serial
from repidr import ic9x

s = serial.Serial(port="/dev/ttyUSB1", baudrate=38400, timeout=0.5)

ic9x.send_magic(s)
ic9x.send_magic(s)
#ic9x.print_banks(s)
ic9x.print_memory(s, 1, 0)


#f = IC92MemoryFrame()
#f.set_memory(None)
#f.make_raw()
#frames = send(f._rawdata)
#print_frames(frames)
