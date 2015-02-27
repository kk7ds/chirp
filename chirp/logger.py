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


r"""
The chirp.logger module provides the core logging facilties for CHIRP.
It sets up the console and (optionally) a log file.  For early debugging,
it checks the CHIRP_DEBUG, CHIRP_LOG, and CHIRP_LOG_LEVEL environment
variables.
"""

import os
import sys
import logging
import argparse
import platform
from chirp import CHIRP_VERSION


def version_string():
    args = (CHIRP_VERSION,
            platform.get_platform().os_version_string(),
            sys.version.split()[0])
    return "CHIRP %s on %s (Python %s)" % args


class VersionAction(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        print version_string()
        sys.exit(1)


def add_version_argument(parser):
    parser.add_argument("--version", action=VersionAction, nargs=0,
                        help="Print version and exit")

#: Map human-readable logging levels to their internal values.
log_level_names = {"critical": logging.CRITICAL,
                   "error":    logging.ERROR,
                   "warn":     logging.WARNING,
                   "info":     logging.INFO,
                   "debug":    logging.DEBUG,
                   }


class Logger(object):
    def __init__(self):
        # create root logger
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)

        self.LOG = logging.getLogger(__name__)

        # Set CHIRP_DEBUG in environment for early console debugging.
        # It can be a number or a name; otherwise, level is set to 'debug'
        # in order to maintain backward compatibility.
        CHIRP_DEBUG = os.getenv("CHIRP_DEBUG")
        level = logging.WARNING
        if CHIRP_DEBUG:
            try:
                level = int(CHIRP_DEBUG)
            except ValueError:
                try:
                    level = log_level_names[CHIRP_DEBUG]
                except KeyError:
                    level = logging.DEBUG

        self.console = logging.StreamHandler()
        self.console.setLevel(level)
        format_str = '%(levelname)s: %(message)s'
        self.console.setFormatter(logging.Formatter(format_str))
        self.logger.addHandler(self.console)

        # Set CHIRP_LOG in environment to the name of log file.
        logname = os.getenv("CHIRP_LOG")
        self.logfile = None
        if logname is not None:
            self.create_log_file(logname)
            level = os.getenv("CHIRP_LOG_LEVEL")
            if level is not None:
                self.set_log_verbosity(level)
            else:
                self.set_log_level(logging.DEBUG)

    def create_log_file(self, name):
        if self.logfile is None:
            self.logname = name
            lf = file(name, "w")
            print >>lf, version_string()
            lf.close()
            self.logfile = logging.FileHandler(name)
            format_str = '[%(created)s] %(name)s - %(levelname)s: %(message)s'
            self.logfile.setFormatter(logging.Formatter(format_str))
            self.logger.addHandler(self.logfile)

        else:
            self.logger.error("already logging to " + self.logname)

    def set_verbosity(self, level):
        if level > logging.CRITICAL:
            level = logging.CRITICAL
        self.console.setLevel(level)
        self.LOG.debug("verbosity=%d", level)

    def set_log_level(self, level):
        if level > logging.CRITICAL:
            level = logging.CRITICAL
        self.logfile.setLevel(level)
        self.LOG.debug("log level=%d", level)

    def set_log_level_by_name(self, level):
        self.set_log_level(log_level_names[level])

    instance = None

Logger.instance = Logger()


def add_arguments(parser):
    parser.add_argument("-q", "--quiet", action="count", default=0,
                        help="Decrease verbosity")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity")
    parser.add_argument("--log", dest="log_file", action="store", default=0,
                        help="Log messages to a file")
    parser.add_argument("--log-level", action="store", default="debug",
                        help="Log file verbosity (critical, error, warn, " +
                        "info, debug).  Defaults to 'debug'.")


def handle_options(options):
    logger = Logger.instance

    if options.verbose or options.quiet:
        logger.set_verbosity(30 + 10 * (options.quiet - options.verbose))

    if options.log_file:
        logger.create_log_file(options.log_file)
        try:
            level = int(options.log_level)
            logger.set_log_level(level)
        except ValueError:
            logger.set_log_level_by_name(options.log_level)
