#!/usr/bin/env python3

import sys
from setuptools import setup
from setuptools import find_packages

install_requires = ["pyserial"]

if sys.version_info[:3] < (3, 5):
    #: .. versionadded:: X.X.X
    #:     Add support for Python 2.7 using trollius.
    install_requires += ['trollius']


setup(
    name="asyncserial",
    version="0.1",
    description="asyncio support for pyserial",
    author="Sebastien Bourdeauducq",
    author_email="sb@m-labs.hk",
    url="https://m-labs.hk",
    download_url="https://github.com/m-labs/asyncserial",
    license="BSD",
    packages=find_packages(),
    install_requires=install_requires,
    platforms=["Any"]
)
