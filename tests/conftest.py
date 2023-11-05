import os

import pytest


def pytest_collection_modifyitems(config, items):
    xfails = os.path.join(os.path.dirname(__file__), 'xfails.txt')
    with open(xfails) as f:
        lines = [x.strip() for x in f.readlines() if not x.startswith('#')]
    msg = ('Test marked for XFAIL in tests/xfails.txt, but did not fail. '
           'If this test is now fixed, remove it from the file.')
    for item in items:
        if item.nodeid in lines:
            mark = pytest.mark.xfail(reason=msg)
            item.add_marker(mark)
