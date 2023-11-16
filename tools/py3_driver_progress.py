#!/usr/bin/python3

import argparse
import csv
import os
import sys
import textwrap

from chirp import directory

directory.import_drivers()


def tester_link(text):
    if text.startswith('@'):
        return '[%s](https://github.com/%s)' % (text, text[1:])
    elif text.startswith('+'):
        assert text[1:] in directory.DRV_TO_RADIO, \
            '%s is not in the driver directory' % text[1:]
        return '[Implied by %s](#user-content-%s)' % (text[1:], text[1:])
    elif text.startswith('*'):
        assert os.path.exists(os.path.join('chirp', 'drivers',
                                           text[1:] + '.py'))
        return ('[Probably works]('
                'https://github.com/kk7ds/chirp'
                '/blob/py3/chirp/drivers/%s.py)' % (
                    text[1:]))
    elif text.startswith('#') and text[1:].isdigit():
        return ('[Reported working]'
                '(https://chirp.danplanet.com/issues/%i)' % int(text[1:]))
    else:
        return text


def read_stats(statsfile):
    with open(statsfile) as f:
        lines = f.readlines()

    models = {}
    total = 0
    skip = ['Repeaterbook', 'Radio Reference', 'CHIRP', 'CSV']
    for line in lines[1:]:
        model, count = line.strip().split('\t')
        model = model.replace(' ', '_').\
            replace('(', '').\
            replace(')', '').\
            replace('/', '_')
        if any(s in model for s in skip):
            continue
        count = int(count)
        models[model] = count
        total += count

    return total, models


def read_testers(testersfile):
    headers = ['Driver', 'Tester', 'Tested']
    line = 0
    testers = {}
    for fields in csv.reader(open(testersfile)):
        line += 1
        if fields[0][0] == '#':
            continue

        if len(fields) != len(headers):
            print('Error on line %i: invalid number of fields in: %s' % (
                line, ','.join(fields)),
                  file=sys.stderr)
            return 1

        if fields[0] in testers:
            print('Error: duplicate driver %r in testers file' % fields[0],
                  file=sys.stderr)
            return 2

        testers[fields[0]] = fields[1:]

    return testers


def get_share_for_radio(stats, stats_total, parent_cls):
    count = 0
    for cls in [parent_cls] + parent_cls.ALIASES:
        driver = directory.radio_class_id(cls)
        simple_driver = '%s_%s' % (cls.VENDOR, cls.MODEL)
        if driver in stats:
            count += stats.pop(driver, 0)
        elif simple_driver in stats:
            count += stats.pop(simple_driver, 0)

    if count == 0:
        share = ''
    else:
        pct = (count * 100 / stats_total)
        share = '%.2f%%' % pct
        if pct > 1:
            share = '**%s**' % share
    return count, share


def main():
    p = argparse.ArgumentParser()
    p.add_argument('testers')
    p.add_argument('stats')
    p.add_argument('-o', '--output', default='-')
    args = p.parse_args()

    testers = read_testers(args.testers)
    stats_total, stats = read_stats(args.stats)

    if args.output == '-':
        output = sys.stdout
    else:
        output = open(args.output, 'w')

    print('## Status', file=output)

    print('| Driver | Tester | Tested | Byte Clean | "Market Share" |',
          file=output)
    print('| ------ | ------ | ------ | ---------- | -------------- |',
          file=output)

    drivers = sorted([ident for ident in directory.DRV_TO_RADIO])
    drvstested = 0
    byteclean = 0
    tested_stats = 0
    for driver in drivers:
        cls = directory.get_radio(driver)
        tester, tested = testers.pop(driver, ('', ''))
        if tester:
            drvstested += 1
        count, share = get_share_for_radio(stats, stats_total, cls)
        if tester:
            tested_stats += count
        if not cls.NEEDS_COMPAT_SERIAL:
            byteclean += 1
        print('| <a name="%s"></a> %s | %s | %s | %s | %s |' % (
            driver, driver, tester_link(tester), tested,
            '' if cls.NEEDS_COMPAT_SERIAL else 'Yes', share),
              file=output)

    print('## Stats', file=output)
    print('\n**Drivers:** %i' % (len(drivers)), file=output)
    print('\n**Tested:** %i%% (%i/%i) (%i%% of usage stats)' % (
        drvstested / len(drivers) * 100,
        drvstested, len(drivers) - drvstested,
        tested_stats * 100 / stats_total),
          file=output)
    print('\n**Byte clean:** %i%% (%i/%i)' % (
        byteclean / len(drivers) * 100,
        byteclean,
        len(drivers) - byteclean),
          file=output)

    print(textwrap.dedent("""
    ## Meaning of this testing

    The goal here is not necessarily to test the drivers themselves in terms of
    actual functionality, but rather to validate the Python 3 conversion
    work required of nearly all drivers. Thus, we are not trying to
    comprehensively test these models so much as make sure they work at least
    as well as they do on the Python 2 branch. Uncovering and reporting new
    bugs is definitely welcome, but for the purpoes of this effort, "no worse
    than the legacy branch" is good enough. There are multiple levels of
    confirmation in the matrix above:
    * Tested with real hardware (i.e. a person listed in the "Tester" column)
      using roughly the procedure below.
    * An "implied by (model)" link means that another model was tested, and it
      is so similar, that the model on that line can be considered tested as
      well.
    * A "probably works" link means that the driver has not been tested with
      real hardware, nor is it substantially similar to another model, but
      shares a common base that entirely provides the cloning routines with
      other drivers that have been tested with real hardware, such that
      confidence is high that it will work. Only drivers with test images in
      the tree (or live drivers) should be marked with this class.
    * A "unit tested" link means that the driver has not been tested with
      real hardware, nor does it share common cloning routines with another
      radio. However, synthetic simulation tests have been added to exercise
      the parts of the cloning routines that are likely to fail under python3.
      This is the lowest-confidence status and a real confirmation is needed.

    If you have a model listed in this matrix with either "implied" or
    "probably works" status, an actual confirmation with real hardware is
    welcome and can replace the weaker reference.

    ## Minimal test procedure
    For the purposes of the Python 3 effort, a "tested" radio means
    at least the following procedure was followed:
    1. Download from the radio
    1. Make some change to a memory
    1. If the radio has settings support, make sure settings load and tweak
       one setting
    1. Upload to the radio
    1. Confirm that the changes stick and look correct, or at least are not a
       regression from the master py2 branch.

    The drivers are all passing the automated tests, but tests with real
    hardware and serial ports is important, especially around bytes-vs-string
    safety.

    To update this document, add/edit entries in `tests/py3_driver_testers.txt`
    and then run `tox -e makesupported`. Commit the result (including the
    changes to this `.md` file) and submit a PR.

    The "Byte Clean" flag refers to whether or not the radio has set the
    `NEEDS_COMPAT_SERIAL = False` flag on the radio class, and thus uses
    `MemoryMapBytes` exclusively internally. Whenever possible, all radios
    that are fixed for py3 should do so with this flag set to False and with
    the byte-native memory map."""),
          file=output)

    for driver, (tester, tested) in testers.items():
        print('Error in testers file; driver %s by %s on %s unknown' % (
            driver, tester, tested), file=sys.stderr)
    if testers:
        return 3


if __name__ == '__main__':
    sys.exit(main())
