# -*- encoding: utf-8 -*-
from .asyncserial import *
from .async_thread import BackgroundSerialAsync

from ._version import get_versions

__version__ = get_versions()['version']
del get_versions
