import errors
import ic9x_ll

def hexprint(data):
    col = 0

    line_sz = 8

    lines = len(data) / line_sz
    
    if (len(data) % line_sz) != 0:
        lines += 1
        data += "\x00" * ((lines * line_sz) - len(data))

    out = ""
        
    for i in range(0, (len(data)/line_sz)):
        out += "%03i: " % (i * line_sz)

        left = len(data) - (i * line_sz)
        if left < line_sz:
            limit = left
        else:
            limit = line_sz
            
        for j in range(0,limit):
            out += "%02x " % ord(data[(i * line_sz) + j])

        out += "  "

        for j in range(0,limit):
            char = data[(i * line_sz) + j]

            if ord(char) > 0x20 and ord(char) < 0x7E:
                out += "%s" % char
            else:
                out += "."

        out += "\n"

    return out

def parse_frames(buf):
    frames = []

    while "\xfe\xfe" in buf:
        try:
            start = buf.index("\xfe\xfe")
            end = buf[start:].index("\xfd") + start + 1
        except Exception, e:
            print "No trailing bit"
            break

        frame = buf[start:end]
        buf = buf[end:]

        try:
            f = ic9x_ll.IC92Frame()
            f.from_raw(frame)
            frames.append(f)
        except errors.InvalidDataError, e:
            print "Broken frame: %s" % e

        #print "Parsed %i frames" % len(frames)

    return frames

def print_frames(frames):
    c = 0
    for i in frames:
        print "Frame %i:" % c
        print i
        c += 1

def write_in_place(mem, start, data):
    return mem[:start] + data + mem[start+len(data):]

