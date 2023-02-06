from distutils.core import setup
from glob import glob
from setuptools import find_packages

from chirp import CHIRP_VERSION

setup(name='chirp',
      description='A cross-platform cross-radio programming tool',
      packages=find_packages(include=["chirp*"]),
      include_package_data=True,
      version=0,
      url='https://chirp.danplanet.com',
      python_requires=">=3.7,<4",
      install_requires=[
          'pyserial',
          'requests',
          'six',
          'future',
          'importlib-resources;python_version<"3.10"',
          'yattag',
      ],
      extras_require={
          'wx': ['wxPython'],
      },
      entry_points={
          'console_scripts': ["chirp=chirp.wxui:chirpmain",
                              "chirpc=chirp.cli.main:main"],
      },
      )
