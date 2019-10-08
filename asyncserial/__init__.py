from __future__ import absolute_import
import sys

from asyncserial.asyncserial import *

if sys.version_info[0] >= 3:
    from ._asyncpy3_thread import BackgroundSerialAsync
