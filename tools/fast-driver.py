#!/usr/bin/env Python3

import glob
import os
import subprocess
import sys


def parse_import_line(line):
    pieces = line.split()
    if line.startswith('from'):
        base = pieces[1]
        if 'drivers.' in base:
            imports = [base.split('.')[-1]]
            return imports
        else:
            imports = pieces[3:]
        if pieces[-1].endswith(','):
            raise Exception('Failed to parse multi-line import')
        return [x.strip().strip(',') for x in imports]
    elif 'drivers' in line:
        raise Exception('Unhandled bare import driver line: %s' % line)
    else:
        return []


def find_imports(of_modules):
    driver_imports = []
    for fn in glob.glob('chirp/drivers/*.py'):
        with open(fn) as f:
            lines = [ln for ln in f.readlines()
                     if 'import ' in ln and 'drivers' in ln]
        imports = []
        for line in lines:
            imports.extend(parse_import_line(line))
        if set(imports) & of_modules:
            driver_imports.append(os.path.splitext(os.path.basename(fn))[0])
    return driver_imports


files = subprocess.check_output(
    ['git', 'diff', 'origin/master', '--name-only', '.']).decode().split()

# A list of modules and their parent [(chirp/drivers, tk8180)]
files_by_module = [x.rsplit('/', 1) for x in files if '/' in x and '.py' in x]

# Grab just the drivers
driver_modules = set([os.path.splitext(os.path.basename(mod))[0]
                     for parent, mod in files_by_module
                     if parent == 'chirp/drivers'])

# Determine which are live drivers that we don't test with these tests
live_drivers = set()
for driver in driver_modules:
    try:
        with open(os.path.join('chirp', 'drivers', '%s.py' % driver)) as f:
            content = f.read()
    except FileNotFoundError:
        # File must have been removed
        continue
    if 'LiveRadio' in content:
        live_drivers.add(driver)

print('Touched drivers: %s' % ','.join(driver_modules))
# Find deps before we remove live modules in case there are any changed
# modules that depend on the bases that have live drivers in them (i.e. icf or
# kenwood_live)
deps = find_imports(driver_modules)
print('Found deps of touched modules: %s' % ','.join(deps))
# Remove live drivers from driver_modules before we add in the deps of changed
# modules, as they may imply some shared code (like icf)
driver_modules -= live_drivers
driver_modules.update(set(deps))

# Determine if any base modules have been changed that would necessitate
# running all the driver tests
exclude_mods = ('chirp/wxui', 'chirp/cli', 'chirp/sources', 'chirp/drivers',
                'chirp/locale', 'chirp/share', 'chirp/stock_configs',
                'tools')
base_modules = [mod for parent, mod in files_by_module
                if parent not in exclude_mods]

if base_modules:
    print('Base modules touched; running all drivers: %s' % base_modules)
    driver_exp = []
elif driver_modules:
    driver_exp = ' or '.join(f for f in driver_modules)
else:
    print('No driver tests necessary for changes in %s' % ','.join(
        files))
    sys.exit(0)

args = ['pytest']
if driver_exp:
    args += ['-k', driver_exp]
args += sys.argv[1:]
print(args)
rc = subprocess.call(args)
if rc == 5:
    # This means no tests were found likely because we generated a bad
    # tag, so just run the full set
    print('Running full driver set')
    rc = subprocess.call(['pytest'] + sys.argv[1:])
sys.exit(rc)
