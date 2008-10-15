import errors

from chirp import chirp_common

def get_memory(doc, number):
    ctx = doc.xpathNewContext()

    base = "//radio/memory[@location=%i]" % number

    fields = ctx.xpathEval(base)
    if len(fields) > 1:
        raise errors.RadioError("%i memories claiming to be %i" % (len(fields),
                                                                   number))
    elif len(fields) == 0:
        raise errors.InvalidMemoryLocation("%i does not exist" % number)

    memnode = fields[0]

    def _get(ext):
        path = base + ext
        return ctx.xpathEval(path)[0].getContent()

    mem = chirp_common.Memory()
    mem.number = int(memnode.prop("location"))
    mem.name = _get("/longName/text()")
    mem.freq = float(_get("/frequency/text()"))
    mem.rtone = float(_get("/squelch[@id='rtone']/tone/text()"))
    mem.ctone = float(_get("/squelch[@id='ctone']/tone/text()"))
    mem.dtcs = int(_get("/squelch[@id='dtcs']/code/text()"), 10)
    mem.dtcs_polarity = _get("/squelch[@id='dtcs']/polarity/text()")
    
    sql = _get("/squelchSetting/text()")
    if sql == "rtone":
        mem.tmode = "Tone"
    elif sql == "ctone":
        mem.tmode = "TSQL"
    elif sql == "dtcs":
        mem.tmode = "DTCS"
    else:
        mem.tmode = ""

    dmap = {"positive" : "+", "negative" : "-", "none" : ""}
    dupx = _get("/duplex/text()")
    mem.duplex = dmap.get(dupx, "")

    mem.offset = float(_get("/offset/text()"))
    mem.mode = _get("/mode/text()")
    mem.tuning_step = float(_get("/tuningStep/text()"))

    return mem

def set_memory(doc, mem):
    ctx = doc.xpathNewContext()

    base = "//radio/memory[@location=%i]" % mem.number

    fields = ctx.xpathEval(base)
    if len(fields) > 1:
        raise errors.RadioError("%i memories claiming to be %i" % (len(fields),
                                                                   number))
    elif len(fields) == 1:
        fields[0].unlinkNode()

    radio = ctx.xpathEval("//radio")[0]
    memnode = radio.newChild(None, "memory", None)
    memnode.newProp("location", "%i" % mem.number)

    sname = memnode.newChild(None, "shortName", None)
    sname.addContent(mem.name.upper()[:6])

    lname = memnode.newChild(None, "longName", None)
    lname.addContent(mem.name)
    
    freq = memnode.newChild(None, "frequency", None)
    freq.newProp("units", "MHz")
    freq.addContent("%.5f" % mem.freq)
    
    rtone = memnode.newChild(None, "squelch", None)
    rtone.newProp("id", "rtone")
    rtone.newProp("type", "repeater")
    tone = rtone.newChild(None, "tone", None)
    tone.addContent("%.1f" % mem.rtone)

    ctone = memnode.newChild(None, "squelch", None)
    ctone.newProp("id", "ctone")
    ctone.newProp("type", "ctcss")
    tone = ctone.newChild(None, "tone", None)
    tone.addContent("%.1f" % mem.ctone)

    dtcs = memnode.newChild(None, "squelch", None)
    dtcs.newProp("id", "dtcs")
    dtcs.newProp("type", "dtcs")
    code = dtcs.newChild(None, "code", None)
    code.addContent("%03i" % mem.dtcs)
    polr = dtcs.newChild(None, "polarity", None)
    polr.addContent(mem.dtcs_polarity)

    sset = memnode.newChild(None, "squelchSetting", None)
    if mem.tmode == "Tone":
        sset.addContent("rtone")
    elif mem.tmode == "TSQL":
        sset.addContent("ctone")
    elif mem.tmode == "DTCS":
        sset.addContent("dtcs")

    dmap = {"+" : "positive", "-" : "negative", "" : "none"}
    dupx = memnode.newChild(None, "duplex", None)
    dupx.addContent(dmap[mem.duplex])

    oset = memnode.newChild(None, "offset", None)
    oset.newProp("units", "MHz")
    oset.addContent("%.5f" % mem.offset)

    mode = memnode.newChild(None, "mode", None)
    mode.addContent(mem.mode)

    step = memnode.newChild(None, "tuningStep", None)
    step.newProp("units", "MHz")
    step.addContent("%.5f" % mem.tuning_step)
    
def del_memory(doc, number):
    path = "//radio/memory[@location=%i]" % number
    ctx = doc.xpathNewContext()
    fields = ctx.xpathEval(path)

    for field in fields:
        field.unlinkNode()
    
