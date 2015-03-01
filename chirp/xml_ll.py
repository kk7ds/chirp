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

import re

from chirp import chirp_common, errors


def get_memory(doc, number):
    """Extract a Memory object from @doc"""
    ctx = doc.xpathNewContext()

    base = "//radio/memories/memory[@location=%i]" % number

    fields = ctx.xpathEval(base)
    if len(fields) > 1:
        raise errors.RadioError("%i memories claiming to be %i" % (len(fields),
                                                                   number))
    elif len(fields) == 0:
        raise errors.InvalidMemoryLocation("%i does not exist" % number)

    memnode = fields[0]

    def _get(ext):
        path = base + ext
        result = ctx.xpathEval(path)
        if result:
            return result[0].getContent()
        else:
            return ""

    if _get("/mode/text()") == "DV":
        mem = chirp_common.DVMemory()
        mem.dv_urcall = _get("/dv/urcall/text()")
        mem.dv_rpt1call = _get("/dv/rpt1call/text()")
        mem.dv_rpt2call = _get("/dv/rpt2call/text()")
        try:
            mem.dv_code = _get("/dv/digitalCode/text()")
        except ValueError:
            mem.dv_code = 0
    else:
        mem = chirp_common.Memory()

    mem.number = int(memnode.prop("location"))
    mem.name = _get("/longName/text()")
    mem.freq = chirp_common.parse_freq(_get("/frequency/text()"))
    mem.rtone = float(_get("/squelch[@id='rtone']/tone/text()"))
    mem.ctone = float(_get("/squelch[@id='ctone']/tone/text()"))
    mem.dtcs = int(_get("/squelch[@id='dtcs']/code/text()"), 10)
    mem.dtcs_polarity = _get("/squelch[@id='dtcs']/polarity/text()")

    try:
        sql = _get("/squelchSetting/text()")
        if sql == "rtone":
            mem.tmode = "Tone"
        elif sql == "ctone":
            mem.tmode = "TSQL"
        elif sql == "dtcs":
            mem.tmode = "DTCS"
        else:
            mem.tmode = ""
    except IndexError:
        mem.tmode = ""

    dmap = {"positive": "+", "negative": "-", "none": ""}
    dupx = _get("/duplex/text()")
    mem.duplex = dmap.get(dupx, "")

    mem.offset = chirp_common.parse_freq(_get("/offset/text()"))
    mem.mode = _get("/mode/text()")
    mem.tuning_step = float(_get("/tuningStep/text()"))

    skip = _get("/skip/text()")
    if skip == "none":
        mem.skip = ""
    else:
        mem.skip = skip

    # FIXME: bank support in .chirp files needs to be re-written
    # bank_id = _get("/bank/@bankId")
    # if bank_id:
    #     mem.bank = int(bank_id)
    #     bank_index = _get("/bank/@bankIndex")
    #     if bank_index:
    #         mem.bank_index = int(bank_index)

    return mem


def set_memory(doc, mem):
    """Set @mem in @doc"""
    ctx = doc.xpathNewContext()

    base = "//radio/memories/memory[@location=%i]" % mem.number

    fields = ctx.xpathEval(base)
    if len(fields) > 1:
        raise errors.RadioError("%i memories claiming to be %i" % (len(fields),
                                                                   mem.number))
    elif len(fields) == 1:
        fields[0].unlinkNode()

    radio = ctx.xpathEval("//radio/memories")[0]
    memnode = radio.newChild(None, "memory", None)
    memnode.newProp("location", "%i" % mem.number)

    sname_filter = "[^A-Z0-9/ >-]"
    sname = memnode.newChild(None, "shortName", None)
    sname.addContent(re.sub(sname_filter, "", mem.name.upper()[:6]))

    lname_filter = "[^.A-Za-z0-9/ >-]"
    lname = memnode.newChild(None, "longName", None)
    lname.addContent(re.sub(lname_filter, "", mem.name[:16]))

    freq = memnode.newChild(None, "frequency", None)
    freq.newProp("units", "MHz")
    freq.addContent(chirp_common.format_freq(mem.freq))

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

    dmap = {"+": "positive", "-": "negative", "": "none"}
    dupx = memnode.newChild(None, "duplex", None)
    dupx.addContent(dmap[mem.duplex])

    oset = memnode.newChild(None, "offset", None)
    oset.newProp("units", "MHz")
    oset.addContent(chirp_common.format_freq(mem.offset))

    mode = memnode.newChild(None, "mode", None)
    mode.addContent(mem.mode)

    step = memnode.newChild(None, "tuningStep", None)
    step.newProp("units", "kHz")
    step.addContent("%.5f" % mem.tuning_step)

    if mem.skip:
        skip = memnode.newChild(None, "skip", None)
        skip.addContent(mem.skip)

    # FIXME: .chirp bank support needs to be redone
    # if mem.bank is not None:
    #     bank = memnode.newChild(None, "bank", None)
    #     bank.newProp("bankId", str(int(mem.bank)))
    #     if mem.bank_index >= 0:
    #         bank.newProp("bankIndex", str(int(mem.bank_index)))

    if isinstance(mem, chirp_common.DVMemory):
        dv = memnode.newChild(None, "dv", None)

        ur = dv.newChild(None, "urcall", None)
        ur.addContent(mem.dv_urcall)

        r1 = dv.newChild(None, "rpt1call", None)
        if mem.dv_rpt1call and mem.dv_rpt1call != "*NOTUSE*":
            r1.addContent(mem.dv_rpt1call)

        r2 = dv.newChild(None, "rpt2call", None)
        if mem.dv_rpt2call and mem.dv_rpt2call != "*NOTUSE*":
            r2.addContent(mem.dv_rpt2call)

        dc = dv.newChild(None, "digitalCode", None)
        dc.addContent(str(mem.dv_code))


def del_memory(doc, number):
    """Remove memory @number from @doc"""
    path = "//radio/memories/memory[@location=%i]" % number
    ctx = doc.xpathNewContext()
    fields = ctx.xpathEval(path)

    for field in fields:
        field.unlinkNode()


def _get_bank(node):
    bank = chirp_common.Bank(node.prop("label"))
    ident = int(node.prop("id"))

    return ident, bank


def get_banks(doc):
    """Return a list of banks from @doc"""
    path = "//radio/banks/bank"
    ctx = doc.xpathNewContext()
    fields = ctx.xpathEval(path)

    banks = []
    for field in fields:
        banks.append(_get_bank(field))

    def _cmp(itema, itemb):
        return itema[0] - itemb[0]

    banks.sort(cmp=_cmp)

    return [x[1] for x in banks]


def set_banks(doc, banklist):
    """Set the list of banks in @doc"""
    path = "//radio/banks/bank"
    ctx = doc.xpathNewContext()
    fields = ctx.xpathEval(path)

    for field in fields:
        field.unlinkNode()

    path = "//radio/banks"
    ctx = doc.xpathNewContext()
    banks = ctx.xpathEval(path)[0]

    i = 0
    for bank in banklist:
        banknode = banks.newChild(None, "bank", None)
        banknode.newProp("id", "%i" % i)
        banknode.newProp("label", "%s" % bank)
        i += 1
