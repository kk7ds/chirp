#!/usr/bin/env Python3

import os
import subprocess
import sys

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
driver_modules -= live_drivers

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
else:
    driver_exp = ' or '.join(f for f in driver_modules)

args = ['pytest']
if driver_exp:
    args += ['-k', driver_exp]
args += sys.argv[1:]
print(args)
subprocess.call(args)