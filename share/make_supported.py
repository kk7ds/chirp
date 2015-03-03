#!/usr/bin/env python

import sys
import serial

sys.path.insert(0, ".")
sys.path.insert(0, "..")

tmp = sys.stdout
sys.stdout = sys.stderr
from chirp import *
from chirp.drivers import *
sys.stdout = tmp

RF = chirp_common.RadioFeatures()
KEYS = [x for x in sorted(RF.__dict__.keys())
        if "_" in x and not x.startswith("_")]

RADIO_TYPES = {
    'Clone': chirp_common.CloneModeRadio,
    'File':  chirp_common.FileBackedRadio,
    'Live':  chirp_common.LiveRadio,
}


def radio_type(radio):
    for k, v in RADIO_TYPES.items():
        if isinstance(radio, v):
            return k
    return ""


def supported_row(radio, odd):
    row = '<tr class="%s" title="%s %s %s">' % (odd and "odd" or "even",
                                                radio.VENDOR,
                                                radio.MODEL,
                                                radio.VARIANT)
    row += "<td>%s %s %s</td>\n" % (radio.VENDOR, radio.MODEL, radio.VARIANT)
    rf = radio.get_features()
    for key in KEYS:
        value = rf.__dict__[key]
        if key == "valid_bands":
            value = ["%s-%s MHz" % (chirp_common.format_freq(x),
                                    chirp_common.format_freq(y))
                     for x, y in value]

        if key in ["valid_bands", "valid_modes", "valid_power_levels",
                   "valid_tuning_steps"]:
            try:
                value = ", ".join([str(x) for x in value
                                   if not str(x).startswith("?")])
            except Exception, e:
                raise

        if key == "memory_bounds":
            value = "%i-%i" % value

        if key == "requires_call_lists":
            if "DV" not in rf.valid_modes:
                value = None
            elif value:
                value = "Required"
            else:
                value = "Optional"

        if value is None:
            row += '<td class="%s"><span class="False">N/A</span></td>' % key
        elif isinstance(value, bool):
            row += '<td class="%s"><span class="%s">%s</span></td>' % \
                (key,
                 value,
                 value and "Yes" or "No")
        else:
            row += '<td class="%s">%s</td>' % (key, value)
    row += '<td class="radio_type">%s</td>' % radio_type(radio)
    row += "</tr>\n"
    return row


def header_row():
    row = "<thead><tr>"
    row += "<th>Radio</th>\n"
    for key in KEYS:
        Key = key.split("_", 1)[1].title().replace("_", " ")
        row += '<th title="%s">%s</th>' % (RF.get_doc(key), Key)
    row += '<th title="Radio programming type">Type</th>\n'
    row += "</tr></thead>\n"
    return row


print """
<style>
td {
  white-space: nowrap;
  border-right: thin solid black;
  padding: 3px;
}
tr.odd {
  background: #E8E8E8;'
}
tr.odd:hover, tr.even:hover {
  background-color: #FFCCFF;
}
th {
  border-right: thin solid black;
}
table {
  border-collapse: collapse;
}
th {
  border-bottom: thick solid black;
}
span.false {
  color: grey;
}
</style>
<table>
"""

models = {"Icom": [],
          "Kenwood": [],
          "Yaesu": [],
          "Alinco": [],
          "z_Other": [],
          }

exclude = [directory.DRV_TO_RADIO["Icom_7200"]]

for radio in directory.DRV_TO_RADIO.values():
    if radio in exclude:
        continue
    if radio.VENDOR in models.keys():
        models[radio.VENDOR].append(radio)
    else:
        models["z_Other"].append(radio)

count = 0
for vendor, radios in sorted(models.items(), key=lambda t: t[0]):
    print header_row()
    for radio in sorted(radios, key=lambda r: r.VENDOR+r.MODEL):
        _radio = radio(None)
        if _radio.get_features().has_sub_devices:
            for __radio in _radio.get_sub_devices():
                print supported_row(__radio, count % 2)
                count += 1
        else:
            print supported_row(_radio, count % 2)
            count += 1
