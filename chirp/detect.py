import serial

from chirp import ic9x, id800, ic2820, ic2200, icx8x, id880
from chirp import chirp_common, errors, idrp, util, icf

DRIVERS = { 
    "id800" : id800.ID800v2Radio,
    "id880" : id880.ID880Radio,
    "ic2820": ic2820.IC2820Radio,
    "ic2200": ic2200.IC2200Radio,
    "icx8x" : icx8x.ICx8xRadio,
    #"idrpv" : idrp.IDRPx000V,
}

def detect_radio(port):
    s = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    md = icf.get_model_data(s)

    for rtype, rclass in DRIVERS.items():
        if rclass._model[:4] == md[:4]:
            print "Auto-detected radio `%s' on port `%s'" % (rtype, port)
            return rtype

    s.close()

    raise errors.RadioError("Unknown radio type %02x%02x%02x%02x" % (md[0],
                                                                     md[1],
                                                                     md[2],
                                                                     md[3]))

if __name__ == "__main__":
    import sys

    print "Found %s" % detect_radio(sys.argv[1])
