from chirp import icf, errors, util
from chirp import id800, ic2820, ic2200, icx8x

def icf_to_image(icf_file, img_file):
    mdata, mmap = icf.read_file(icf_file)

    models = [id800.ID800v2Radio,
              ic2820.IC2820Radio,
              ic2200.IC2200Radio,
              icx8x.ICx8xRadio,
              ]

    img_data = None
    for model in models:
        if model._model == mdata:
            img_data = mmap.get_packed()[:model._memsize]
            break

    if not img_data:
        print "Unknown model:"
        print util.hexprint(mdata)
        raise errors.RadioError("Unable to read ICF file (unsupported model)")

    f = file(img_file, "wb")
    f.write(img_data)
    f.close()

if __name__ == "__main__":
    import sys

    icf_to_image(sys.argv[1], sys.argv[2])
