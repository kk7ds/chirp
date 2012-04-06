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

import os
import libxml2

from chirp import chirp_common, errors, xml_ll, platform, directory

def validate_doc(doc):
    basepath = platform.get_platform().executable_path()
    path = os.path.abspath(os.path.join(basepath, "chirp.xsd"))
    if not os.path.exists(path):
        path = "/usr/share/chirp/chirp.xsd"         

    try:
        ctx = libxml2.schemaNewParserCtxt(path)
        schema = ctx.schemaParse()
    except libxml2.parserError, e:
        print "Unable to load schema: %s" % e
        print "Path: %s" % path
        raise errors.RadioError("Unable to load schema")

    del ctx

    errs = []
    warnings = []

    def err(msg, arg=None):
        errs.append("ERROR: %s" % msg)

    def wrn(msg, arg=None):
        print "WARNING: %s" % msg
        warnings.append("WARNING: %s" % msg)

    validCtx = schema.schemaNewValidCtxt()
    validCtx.setValidityErrorHandler(err, wrn)
    err = validCtx.schemaValidateDoc(doc)
    print os.linesep.join(warnings)
    if err:
        print "---DOC---\n%s\n------" % doc.serialize(format=1)
        print os.linesep.join(errs)
        raise errors.RadioError("Schema error")

def default_banks():
    banks = []

    for i in range(0, 26):
        banks.append("Bank-%s" % (chr(ord("A") + i)))

    return banks

@directory.register
class XMLRadio(chirp_common.FileBackedRadio, chirp_common.IcomDstarSupport):
    VENDOR = "Generic"
    MODEL = "XML"
    FILE_EXTENSION = "chirp"

    def __init__(self, pipe):
        chirp_common.CloneModeRadio.__init__(self, None)
        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.doc = libxml2.parseFile(self._filename)
            validate_doc(self.doc)
        else:
            self.doc = libxml2.newDoc("1.0")
            radio = self.doc.newChild(None, "radio", None)
            radio.newChild(None, "memories", None)
            radio.newChild(None, "banks", None)
            radio.newProp("version", "0.1.1")

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        #rf.has_bank_index = True
        rf.requires_call_lists = False
        rf.has_implicit_calls = False
        rf.memory_bounds = (0, 1000)
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 999
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        return rf
        
    def load(self, filename=None):
        if not self._filename and not filename:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self.doc = libxml2.parseFile(self._filename)
        validate_doc(self.doc)

    def save(self, filename=None):
        if not self._filename and not filename:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        f = file(self._filename, "w")
        f.write(self.doc.serialize(format=1))
        f.close()

    def get_memories(self, lo=0, hi=999):
        mems = []
        for i in range(lo, hi):
            try:
                mems.append(xml_ll.get_memory(self.doc, i))
            except errors.InvalidMemoryLocation:
                pass

        return mems
    
    def get_memory(self, number):
        mem = xml_ll.get_memory(self.doc, number)

        return mem

    def set_memory(self, mem):
        xml_ll.set_memory(self.doc, mem)

    def erase_memory(self, number):
        xml_ll.del_memory(self.doc, number)

if __name__ == "__main__":
    r = XMLRadio("testmem.chirp")

    print r.get_memory(3)

    m = chirp_common.Memory()
    m.name = "TestMem2"
    m.freq = 123.456
    m.number = 10

    #r.set_memory(m)
    #r.erase_memory(10)
