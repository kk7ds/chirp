#!/usr/bin/python3

import argparse
import csv
import sys

from chirp import directory

directory.safe_import_drivers()


def tester_link(text):
    if text.startswith('@'):
        return '[%s](https://github.com/%s)' % (text, text[1:])
    elif text.startswith('+'):
        assert text[1:] in directory.DRV_TO_RADIO, \
            '%s is not in the driver directory' % text[1:]
        return '[Implied by %s](#user-content-%s)' % (text[1:], text[1:])
    else:
        return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument('testers')
    p.add_argument('-o', '--output', default='-')
    args = p.parse_args()

    headers = ['Driver', 'Tester', 'Tested']
    testers = {}

    if args.output == '-':
        output = sys.stdout
    else:
        output = open(args.output, 'w')

    line = 0
    for fields in csv.reader(open(args.testers)):
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

    print('| Driver | Tester | Tested | Byte Clean |', file=output)
    print('| ------ | ------ | ------ | ---------- |', file=output)

    drivers = sorted([ident for ident in directory.DRV_TO_RADIO])
    for driver in drivers:
        cls = directory.get_radio(driver)
        tester, tested = testers.pop(driver, ('', ''))
        print('| <a name="%s"></a> %s | %s | %s | %s |' % (
            driver, driver, tester_link(tester), tested,
            '' if cls.NEEDS_COMPAT_SERIAL else 'Yes'),
              file=output)

    for driver, (tester, tested) in testers.items():
        print('Error in testers file; driver %s by %s on %s unknown' % (
            driver, tester, tested), file=sys.stderr)
    if testers:
        return 3


if __name__ == '__main__':
    sys.exit(main())
