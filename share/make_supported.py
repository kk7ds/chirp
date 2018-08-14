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


counter = 0

def radio_type(radio):
    for k, v in RADIO_TYPES.items():
        if isinstance(radio, v):
            return k
    return ""


def supported_row(radio):
    global counter
    counter += 1
    odd = counter % 2

    row = '<tr class="%s" title="%s %s %s">' % (odd and "odd" or "even",
                                                radio.VENDOR,
                                                radio.MODEL,
                                                radio.VARIANT)
    row += "<td><a href=\"#%s\" name=\"%s\">%s %s %s</a></td>\n" % (
        'row%04i' % counter,
        'row%04i' % counter,
        radio.VENDOR, radio.MODEL, radio.VARIANT)
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


dest = sys.stdout
if len(sys.argv) > 1:
    dest = open(sys.argv[1], 'w')


def output(string):
    dest.write(string + '\n')


output("""
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
a {
  text-decoration: none;
  color: inherit;
}
</style>
<table>
""")

models = {"Icom": [],
          "Kenwood": [],
          "Yaesu": [],
          "Alinco": [],
          "Baofeng": [],
          "z_Other": [],
          }

models = []

exclude = [directory.DRV_TO_RADIO["Icom_7200"]]

for radio in directory.DRV_TO_RADIO.values():
    if radio in exclude:
        continue

    models.append(radio)
    for alias in radio.ALIASES:
        class DynamicRadioAlias(radio):
            VENDOR = alias.VENDOR
            MODEL = alias.MODEL
            VARIANT = alias.VARIANT
        models.append(DynamicRadioAlias)


def get_key(rc):
    return '%s %s %s' % (rc.VENDOR, rc.MODEL, rc.VARIANT)

for radio in sorted(models, cmp=lambda a, b: get_key(a) < get_key(b) and -1 or 1):
    if counter % 10 == 0:
        output(header_row())
    _radio = radio(None)
    if _radio.get_features().has_sub_devices:
        for __radio in _radio.get_sub_devices():
            output(supported_row(__radio))
    else:
        output(supported_row(_radio))
