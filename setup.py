#!/usr/bin/env python3
from setuptools import setup
from setuptools import find_packages

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
    install_requires=["pyserial"],
    platforms=["Any"]
)
