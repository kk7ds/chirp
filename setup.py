from distutils.core import setup
from glob import glob
from setuptools import find_packages

from chirp import CHIRP_VERSION

desktop_files = glob("share/*.desktop")
image_files = glob("images/*")
stock_configs = glob("stock_configs/*")

setup(name='chirp',
      descrption='A cross-platform cross-radio programming tool',
      packages=find_packages(),
      version=CHIRP_VERSION,
      url='https://chirp.danplanet.com',
      python_requires=">=3.3,<4",
      install_required=['wxPython', 'serial'],
      entry_points={
          'console_scripts': ["chirp=chirp.wxui:chirpmain"],
      },
      data_files=[('share/applications', desktop_files),
                  ('share/chirp/images', image_files),
                  ('share/doc/chirp', ['COPYING']),
                  ('share/pixmaps', ['share/chirp.png']),
                  ('share/man/man1', ["share/chirpw.1"]),
                  ('share/chirp/stock_configs', stock_configs),
                  ])
