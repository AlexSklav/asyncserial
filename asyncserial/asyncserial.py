import os
import asyncio
import serial
import logging

from typing import Union

__all__ = ["AsyncSerial"]


class AsyncSerialBase:
    def __init__(self, port: str = None, loop: asyncio.AbstractEventLoop = None, **kwargs):
        self.logger = logging.getLogger(__name__)

        if any(key in kwargs for key in ['timeout', 'write_timeout', 'inter_byte_timeout']):
            [kwargs.pop(key, None) for key in ['timeout', 'write_timeout', 'inter_byte_timeout']]
            self.logger.warning("Asynchronous I/O requires non-blocking devices, setting timeouts to `None`")
        self._serial = serial.serial_for_url(port, **kwargs)
        if self._serial.is_open:
            self.port = self._serial.port
        else:
            self.port = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    async def __aenter__(self):
        import warnings
        warnings.warn('Not Implemented, returns self synchronously')
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def is_open(self) -> bool:
        return self._serial.is_open

    @property
    def in_waiting(self) -> int:
        return self._serial.in_waiting

    async def read_exactly(self, n):
        data = bytearray()
        while len(data) < n:
            remaining = n - len(data)
            data += await self.read(remaining)
        return data

    async def write_exactly(self, data):
        while data:
            res = await self.write(data)
            data = data[res:]


if os.name == "nt":
    import ctypes


    class HandleWrapper:
        """Wrapper for an overlapped handle which is vaguely file-object like
        (sic).

        The IOCP event loop can use these instead of socket objects.
        """

        def __init__(self, handle):
            self._handle = handle

        @property
        def handle(self):
            return self._handle

        def fileno(self):
            return self._handle

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, t, v, tb):
            pass


class AsyncSerial(AsyncSerialBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.write_future = None
        self.read_future = None
        self.handle_wrapper = None
        self.setup()

    def setup(self):
        if os.name == "nt":
            handle = self.fileno()

            # configure behavior similar to unix read()
            timeouts = serial.win32.COMMTIMEOUTS()
            timeouts.ReadIntervalTimeout = serial.win32.MAXDWORD
            timeouts.ReadTotalTimeoutMultiplier = serial.win32.MAXDWORD
            timeouts.ReadTotalTimeoutConstant = 0
            serial.win32.SetCommTimeouts(handle, ctypes.byref(timeouts))

            self.handle_wrapper = HandleWrapper(handle)

    def check_data(self, data: Union[bytes, bytearray, str]) -> bytes:
        """Ensure data is always bytes"""
        if isinstance(data, (bytes, bytearray)):
            return data
        elif isinstance(data, str):
            return data.encode('utf-8')
        else:
            raise TypeError('Unknown data type')

    if os.name == "nt":
        def fileno(self):
            try:
                return self._serial._port_handle
            except AttributeError:
                return self._serial.hComPort

        def read(self, n: int) -> asyncio.ProactorEventLoop:
            return asyncio.get_running_loop()._proactor.recv(self.handle_wrapper, n)

        def write(self, data: bytes) -> asyncio.ProactorEventLoop:
            data = self.check_data(data)
            return asyncio.get_running_loop()._proactor.send(self.handle_wrapper, data)

        def close(self) -> None:
            self._serial.close()
    else:
        def fileno(self):
            return self._serial.fd

        def _read_ready(self, n: int) -> None:
            asyncio.get_running_loop().remove_reader(self.fileno())
            if not self.read_future.cancelled():
                try:
                    res = os.read(self.fileno(), n)
                except Exception as exc:
                    self.read_future.set_exception(exc)
                else:
                    self.read_future.set_result(res)
            self.read_future = None

        def read(self, n):
            assert self.read_future is None or self.read_future.cancelled()
            loop = asyncio.get_running_loop()
            future = asyncio.Future(loop=loop)

            if n == 0:
                future.set_result(b"")
            else:
                try:
                    res = os.read(self.fileno(), n)
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    if res:
                        future.set_result(res)
                    else:
                        self.read_future = future
                        loop.add_reader(self.fileno(), self._read_ready, n)

            return future

        def _write_ready(self, data: bytes) -> None:
            asyncio.get_running_loop().remove_writer(self.fileno())
            if not self.write_future.cancelled():
                try:
                    res = os.write(self.fileno(), data)
                except Exception as exc:
                    self.write_future.set_exception(exc)
                else:
                    self.write_future.set_result(res)
            self.write_future = None

        def write(self, data: bytes) -> asyncio.Future:
            data = self.check_data(data)
            assert self.write_future is None or self.write_future.cancelled()
            loop = asyncio.get_running_loop()
            future = asyncio.Future(loop=loop)

            if len(data) == 0:
                future.set_result(0)
            else:
                try:
                    res = os.write(self.fileno(), data)
                except BlockingIOError:
                    self.write_future = future
                    loop.add_writer(self.fileno(), self._write_ready, data)
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(res)

            return future

        def close(self) -> None:
            if self.fileno() is not None:
                if self.read_future is not None:
                    self.read_future.get_loop().remove_reader(self.fileno())
                if self.write_future is not None:
                    self.write_future.get_loop().remove_writer(self.fileno())

            if self._serial.is_open:
                self._serial.close()
