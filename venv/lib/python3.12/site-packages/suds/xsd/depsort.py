# This program is free software; you can redistribute it and/or modify it under
# the terms of the (LGPL) GNU Lesser General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Library Lesser General Public License
# for more details at ( http://www.gnu.org/licenses/lgpl.html ).
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# written by: Jeff Ortel ( jortel@redhat.com )

"""
Dependency/topological sort implementation.

"""

from suds import *

from logging import getLogger
log = getLogger(__name__)


def dependency_sort(dependency_tree):
    """
    Sorts items 'dependencies first' in a given dependency tree.

    A dependency tree is a dictionary mapping an object to a collection its
    dependency objects.

    Result is a properly sorted list of items, where each item is a 2-tuple
    containing an object and its dependency list, as given in the input
    dependency tree.

    If B is directly or indirectly dependent on A and they are not both a part
    of the same dependency cycle (i.e. then A is neither directly nor
    indirectly dependent on B) then A needs to come before B.

    If A and B are a part of the same dependency cycle, i.e. if they are both
    directly or indirectly dependent on each other, then it does not matter
    which comes first.

    Any entries found listed as dependencies, but that do not have their own
    dependencies listed as well, are logged & ignored.

    @return: The sorted items.
    @rtype: list

    """
    sorted = []
    processed = set()
    for key, deps in dependency_tree.items():
        _sort_r(sorted, processed, key, deps, dependency_tree)
    return sorted


def _sort_r(sorted, processed, key, deps, dependency_tree):
    """Recursive topological sort implementation."""
    if key in processed:
        return
    processed.add(key)
    for dep_key in deps:
        dep_deps = dependency_tree.get(dep_key)
        if dep_deps is None:
            log.debug('"%s" not found, skipped', Repr(dep_key))
            continue
        _sort_r(sorted, processed, dep_key, dep_deps, dependency_tree)
    sorted.append((key, deps))
