from trollius import BlockingIOError
import trollius as asyncio
import os
import serial


__all__ = ["AsyncSerialPy27Mixin", "BlockingIOError"]


class AsyncSerialPy27Mixin:
    @asyncio.coroutine
    def read_exactly(self, n):
        data = bytearray()
        while len(data) < n:
            remaining = n - len(data)
            data += yield asyncio.From(self.read(remaining))
        raise asyncio.Return(data)

    @asyncio.coroutine
    def write_exactly(self, data):
        while data:
            res = yield asyncio.From(self.write(data))
            data = data[res:]
