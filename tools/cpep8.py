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

import os
import sys
import logging
import argparse
import pep8

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--all", action="store_true",
                    help="Check all files, ignoring blacklist")
parser.add_argument("-d", "--dir", action="store", default=".",
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
    fh = file(name, "r")
    lines = fh.read().split("\n")
    lines.pop()
    fh.close()
    return lines


scriptdir = os.path.dirname(sys.argv[0])
manifest_filename = os.path.join(scriptdir, "cpep8.manifest")
blacklist_filename = os.path.join(scriptdir, "cpep8.blacklist")
exceptions_filename = os.path.join(scriptdir, "cpep8.exceptions")

manifest = []
if args.scan:
    for root, dirs, files in os.walk(args.dir):
        for f in files:
            filename = os.path.join(root, f)
            if f.endswith('.py'):
                manifest.append(filename)
                continue
            with file(filename, "r") as fh:
                shebang = fh.readline()
                if shebang.startswith("#!/usr/bin/env python"):
                    manifest.append(filename)
else:
    manifest += file_to_lines(manifest_filename)


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

if args.update:
    print "Starting update of %d files" % len(manifest)
    bad = []
    for f in manifest:
        checker = pep8.StyleGuide(quiet=True, ignore=get_exceptions(f))
        results = checker.check_files([f])
        if results.total_errors:
            bad.append(f)
        print "%s: %s" % (results.total_errors and "FAIL" or "PASS", f)

    with file(blacklist_filename, "w") as fh:
        print >>fh, """\
# cpep8.blacklist: The list of files that do not meet PEP8 standards.
# DO NOT ADD NEW FILES!!  Instead, fix the code to be compliant.
# Over time, this list should shrink and (eventually) be eliminated."""
        print >>fh, "\n".join(sorted(bad))

    if args.scan:
        with file(manifest_filename, "w") as fh:
            print >>fh, "\n".join(sorted(manifest))
    sys.exit(0)

if args.files:
    manifest = args.files

# read the blacklisted source files
blacklist = file_to_lines(blacklist_filename)

check_list = []
for f in manifest:
    if args.all or f not in blacklist:
        check_list.append(f)
check_list = sorted(check_list)

total_errors = 0
for f in check_list:
    if args.verbose:
        print "Checking %s" % f

    checker = pep8.Checker(f, quiet=args.stats, ignore=get_exceptions(f))
    results = checker.check_all()
    if args.stats:
        checker.report.print_statistics()
    total_errors += results

sys.exit(total_errors and 1 or 0)
