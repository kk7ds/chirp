#!/usr/bin/env python
#
#  cpep8.py - Check Python source files for PEP8 compliance.
#
# Copyright 2015  Zachary T Welch  <zach@mandolincreekfarm.com>
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

import warnings

import os
import sys
import argparse
import subprocess

# pep8 has a FutureWarning about nested sets. This isn't our problem, so
# squelch it here during import.
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import pep8


parser = argparse.ArgumentParser()
parser.add_argument("-a", "--all", action="store_true",
                    help="Check all files, ignoring blacklist")
parser.add_argument("-d", "--dir", action="append", default=['chirp', 'tests'],
                    help="Root directory of source tree")
parser.add_argument("-s", "--stats", action="store_true",
                    help="Only show statistics")
parser.add_argument("--strict", action="store_true",
                    help="Ignore listed exceptions")
parser.add_argument("-S", "--scan", action="store_true",
                    help="Scan for additional files")
parser.add_argument("-u", "--update", action="store_true",
                    help="Update manifest/blacklist files")
parser.add_argument("-v", "--verbose", action="store_true",
                    help="Display list of checked files")
parser.add_argument("files", metavar="file", nargs='*',
                    help="List of files to check (if none, check all)")
args = parser.parse_args()


def file_to_lines(name):
    fh = open(name, "r")
    lines = fh.read().split("\n")
    lines.pop()
    fh.close()
    return [x for x in lines if not x.startswith('#')]


scriptdir = os.path.dirname(sys.argv[0])
manifest_filename = os.path.join(scriptdir, "cpep8.manifest")
blacklist_filename = os.path.join(scriptdir, "cpep8.blacklist")
exceptions_filename = os.path.join(scriptdir, "cpep8.exceptions")

cpep8_manifest = set(file_to_lines(manifest_filename))
flake8_manifest = set()
for src_dir in [os.path.join('.', d) for d in args.dir]:
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            filename = os.path.join(root, f)
            if filename.replace('\\', '/') in cpep8_manifest:
                continue
            if f.endswith('.py'):
                flake8_manifest.add(filename)
                continue
            with open(filename, "rb") as fh:
                shebang = fh.readline()
                if shebang.startswith(b"#!/usr/bin/env python"):
                    flake8_manifest.add(filename)


# unless we are being --strict, load per-file style exceptions
exceptions = {}
if not args.strict:
    exception_lines = file_to_lines(exceptions_filename)
    exception_lists = [x.split('\t')
                       for x in exception_lines if not x.startswith('#')]
    for filename, codes in exception_lists:
        exceptions[filename] = codes


def get_exceptions(f):
    try:
        ignore = exceptions[f]
    except KeyError:
        ignore = None
    return ignore


if args.files:
    old_files = cpep8_manifest
    cpep8_manifest = []
    flake8_manifest = []
    for fn in args.files:
        if not fn.startswith('./'):
            fn = './' + fn
        if fn in old_files:
            cpep8_manifest.append(fn)
        else:
            flake8_manifest.append(fn)

# read the blacklisted source files
blacklist = file_to_lines(blacklist_filename)

check_list = []
for f in cpep8_manifest:
    if args.all or f.replace('\\', '/') not in blacklist:
        check_list.append(f)
check_list = sorted(check_list)

total_errors = 0
for f in check_list:
    if args.verbose:
        print("Checking %s" % f)

    checker = pep8.Checker(f, quiet=args.stats, ignore=get_exceptions(f))
    results = checker.check_all()
    if args.stats:
        checker.report.print_statistics()
    total_errors += results

flake8_manifest = [f for f in flake8_manifest
                   if f.replace('\\', '/') not in blacklist]

for i in range(0, len(flake8_manifest), 10):
    files = flake8_manifest[i:i + 10]
    if args.verbose:
        print('Checking %s' % files)
    r = subprocess.call(['flake8', '--builtins=_,ngettext'] + files)
    if r != 0:
        total_errors += r

sys.exit(total_errors and 1 or 0)
