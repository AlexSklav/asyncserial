# -*- encoding: utf-8 -*-
import os
import errno
import serial
import asyncio

from typing import Union, Optional
from logging_helpers import _L

__all__ = ["AsyncSerial"]


class AsyncSerialBase:
    def __init__(self, port: str = None, loop: asyncio.AbstractEventLoop = None, **kwargs):
        self._closed = False

        # Note: 'loop' parameter is deprecated in modern asyncio but kept for compatibility
        if loop is not None:
            _L().warning("The 'loop' parameter is deprecated and will be ignored")

        if any(key in kwargs for key in ['timeout', 'write_timeout', 'inter_byte_timeout']):
            [kwargs.pop(key, None) for key in ['timeout', 'write_timeout', 'inter_byte_timeout']]
            _L().warning("Asynchronous I/O requires non-blocking devices, setting timeouts to `None`")
        
        try:
            self._serial = serial.serial_for_url(port, **kwargs)
        except Exception as exc:
            _L().error(f"Failed to open serial port {port}: {exc}")
            raise
        
        if self._serial.is_open:
            self.port = self._serial.port
        else:
            self.port = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False  # Propagate exceptions

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()
        return False  # Propagate exceptions
    
    def _has_event_loop(self) -> bool:
        """Check if there's a running event loop."""
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(port={self.port!r}, is_open={self.is_open})"

    def __str__(self) -> str:
        return f"{self.__class__.__name__} on {self.port}"

    @property
    def is_open(self) -> bool:
        return self._serial.is_open and not self._closed

    @property
    def in_waiting(self) -> int:
        """Number of bytes waiting in the input buffer."""
        return self._serial.in_waiting

    @property
    def out_waiting(self) -> int:
        """Number of bytes waiting in the output buffer."""
        try:
            return self._serial.out_waiting
        except AttributeError:
            return 0

    @property
    def baudrate(self) -> int:
        """Current baudrate."""
        return self._serial.baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        """Set baudrate."""
        self._serial.baudrate = value

    def reset_input_buffer(self) -> None:
        """Clear input buffer, discarding all that is in the buffer."""
        if not self._closed:
            self._serial.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        """Clear output buffer, aborting the current output."""
        if not self._closed:
            self._serial.reset_output_buffer()

    def flush(self) -> None:
        """Wait until all data is written (output buffer is empty)."""
        if not self._closed:
            self._serial.flush()

    async def read_exactly(self, n: int) -> bytes:
        """Read exactly n bytes from the serial port."""
        data = bytearray()
        while len(data) < n:
            if self._closed:
                raise IOError("Serial port is closed")
            remaining = n - len(data)
            chunk = await self.read(remaining)
            if not chunk:
                raise IOError("Serial port closed or no data available")
            data += chunk
        return bytes(data)

    async def write_exactly(self, data: Union[bytes, bytearray, str]) -> None:
        """Write all data to the serial port."""
        data_bytes = data.encode('utf-8') if isinstance(data, str) else bytes(data)
        total_written = 0
        while total_written < len(data_bytes):
            if self._closed:
                raise IOError("Serial port is closed")
            res = await self.write(data_bytes[total_written:])
            total_written += res

    async def readline(self, separator: bytes = b'\n') -> bytes:
        """
        Read until a separator byte is found or EOF.
        
        Args:
            separator: The byte sequence to look for (default: newline)
        
        Returns:
            All data up to and including the separator
        """
        data = bytearray()
        while True:
            if self._closed:
                raise IOError("Serial port is closed")
            chunk = await self.read(1)
            if not chunk:
                # EOF or port closed
                break
            data += chunk
            if data.endswith(separator):
                break
        return bytes(data)

    async def readuntil(self, expected: bytes = b'\n', size: Optional[int] = None) -> bytes:
        """
        Read until an expected byte sequence is found or size limit is reached.
        
        Args:
            expected: The byte sequence to look for
            size: Maximum number of bytes to read (None = no limit)
        
        Returns:
            All data up to and including the expected sequence
        
        Raises:
            IOError: If size limit is reached without finding expected sequence
        """
        data = bytearray()
        while True:
            if self._closed:
                raise IOError("Serial port is closed")
            if size and len(data) >= size:
                raise IOError(f"Size limit ({size}) reached without finding expected sequence")
            
            chunk = await self.read(1)
            if not chunk:
                raise IOError("EOF reached without finding expected sequence")
            
            data += chunk
            if data.endswith(expected):
                break
        return bytes(data)


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
        """Setup platform-specific configurations."""
        if os.name == "nt":
            try:
                handle = self.fileno()
                if handle is None:
                    raise IOError("Cannot get file handle for serial port")

                # Configure behavior similar to unix read() - non-blocking
                timeouts = serial.win32.COMMTIMEOUTS()
                timeouts.ReadIntervalTimeout = serial.win32.MAXDWORD
                timeouts.ReadTotalTimeoutMultiplier = serial.win32.MAXDWORD
                timeouts.ReadTotalTimeoutConstant = 0
                serial.win32.SetCommTimeouts(handle, ctypes.byref(timeouts))

                self.handle_wrapper = HandleWrapper(handle)
            except Exception as exc:
                _L().error(f"Failed to setup Windows serial port: {exc}")
                raise

    def check_data(self, data: Union[bytes, bytearray, str]) -> bytes:
        """
        Ensure data is always bytes.
        
        Args:
            data: Input data to convert
            
        Returns:
            Data as bytes
            
        Raises:
            TypeError: If data type cannot be converted to bytes
        """
        if isinstance(data, bytes):
            return data
        elif isinstance(data, bytearray):
            return bytes(data)
        elif isinstance(data, str):
            return data.encode('utf-8')
        else:
            raise TypeError(f'Cannot convert {type(data).__name__} to bytes. '
                          f'Expected bytes, bytearray, or str.')

    if os.name == "nt":
        def fileno(self) -> Optional[int]:
            try:
                return self._serial._port_handle
            except AttributeError:
                try:
                    return self._serial.hComPort
                except AttributeError:
                    return None

        async def read(self, n: int) -> bytes:
            """Read up to n bytes from the serial port."""
            if self._closed:
                raise IOError("Serial port is closed")
            if n == 0:
                return b""
            try:
                return await asyncio.get_running_loop()._proactor.recv(self.handle_wrapper, n)
            except Exception as exc:
                _L().error(f"Error reading from serial port: {exc}")
                raise

        async def write(self, data: Union[bytes, bytearray, str]) -> int:
            """Write data to the serial port and return number of bytes written."""
            if self._closed:
                raise IOError("Serial port is closed")
            data_bytes = self.check_data(data)
            if len(data_bytes) == 0:
                return 0
            try:
                return await asyncio.get_running_loop()._proactor.send(self.handle_wrapper, data_bytes)
            except Exception as exc:
                _L().error(f"Error writing to serial port: {exc}")
                raise

        def close(self) -> None:
            """Close the serial port."""
            if self._closed:
                return
            self._closed = True
            try:
                if self._serial and self._serial.is_open:
                    self._serial.close()
            except OSError as e:
                # Handle case where file descriptor is already closed/invalid
                if e.errno in (errno.EBADF, 9):  # Bad file descriptor
                    _L().debug("Serial port already closed")
                else:
                    raise
            except Exception as exc:
                _L().error(f"Error closing serial port: {exc}")
                raise
    else:
        def fileno(self) -> Optional[int]:
            try:
                return self._serial.fd if hasattr(self._serial, 'fd') else None
            except AttributeError:
                return None

        def _read_ready(self, n: int) -> None:
            """Callback when data is ready to be read."""
            loop = asyncio.get_running_loop()
            fd = self.fileno()
            
            if fd is not None:
                try:
                    loop.remove_reader(fd)
                except (OSError, ValueError) as exc:
                    _L().debug(f"Error removing reader: {exc}")
            
            if self.read_future and not self.read_future.cancelled():
                try:
                    if fd is None:
                        self.read_future.set_exception(IOError("Serial port closed"))
                    else:
                        res = os.read(fd, n)
                        self.read_future.set_result(res)
                except OSError as exc:
                    if exc.errno == errno.EBADF:
                        self.read_future.set_exception(IOError("Serial port closed"))
                    else:
                        self.read_future.set_exception(exc)
                except Exception as exc:
                    self.read_future.set_exception(exc)
            self.read_future = None

        async def read(self, n: int) -> bytes:
            """Read up to n bytes from the serial port."""
            if self._closed:
                raise IOError("Serial port is closed")
            
            if self.read_future and not self.read_future.cancelled():
                raise RuntimeError("Concurrent read operation already in progress")
            
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            if n == 0:
                future.set_result(b"")
                return await future

            fd = self.fileno()
            if fd is None:
                raise IOError("Serial port not available")

            try:
                res = os.read(fd, n)
            except BlockingIOError:
                # No data available, wait for it
                self.read_future = future
                loop.add_reader(fd, self._read_ready, n)
            except OSError as exc:
                if exc.errno == errno.EBADF:
                    future.set_exception(IOError("Serial port closed"))
                else:
                    future.set_exception(exc)
            except Exception as exc:
                future.set_exception(exc)
            else:
                if res:
                    future.set_result(res)
                else:
                    # EOF or no data, wait for more
                    self.read_future = future
                    loop.add_reader(fd, self._read_ready, n)

            return await future

        def _write_ready(self, data: bytes) -> None:
            """Callback when the serial port is ready to accept more data."""
            loop = asyncio.get_running_loop()
            fd = self.fileno()
            
            if fd is not None:
                try:
                    loop.remove_writer(fd)
                except (OSError, ValueError) as exc:
                    _L().debug(f"Error removing writer: {exc}")
            
            if self.write_future and not self.write_future.cancelled():
                try:
                    if fd is None:
                        self.write_future.set_exception(IOError("Serial port closed"))
                    else:
                        res = os.write(fd, data)
                        self.write_future.set_result(res)
                except OSError as exc:
                    if exc.errno == errno.EBADF:
                        self.write_future.set_exception(IOError("Serial port closed"))
                    else:
                        self.write_future.set_exception(exc)
                except Exception as exc:
                    self.write_future.set_exception(exc)
            self.write_future = None

        async def write(self, data: Union[bytes, bytearray, str]) -> int:
            """Write data to the serial port and return number of bytes written."""
            if self._closed:
                raise IOError("Serial port is closed")
            
            data_bytes = self.check_data(data)
            
            if self.write_future and not self.write_future.cancelled():
                raise RuntimeError("Concurrent write operation already in progress")
            
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            if len(data_bytes) == 0:
                future.set_result(0)
                return await future

            fd = self.fileno()
            if fd is None:
                raise IOError("Serial port not available")

            try:
                res = os.write(fd, data_bytes)
            except BlockingIOError:
                # Serial port buffer is full, wait for it to be ready
                self.write_future = future
                loop.add_writer(fd, self._write_ready, data_bytes)
            except OSError as exc:
                if exc.errno == errno.EBADF:
                    future.set_exception(IOError("Serial port closed"))
                else:
                    future.set_exception(exc)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(res)

            return await future

        def close(self) -> None:
            """Close the serial port and clean up resources."""
            if self._closed:
                return
            self._closed = True
            
            fd = self.fileno()
            has_loop = self._has_event_loop()
            
            # Cancel and clean up pending read operations
            if self.read_future is not None:
                if not self.read_future.done():
                    try:
                        self.read_future.cancel()
                    except Exception as exc:
                        _L().debug(f"Error cancelling read future: {exc}")
                
                if fd is not None and has_loop:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.remove_reader(fd)
                    except (OSError, ValueError, RuntimeError) as exc:
                        _L().debug(f"Error removing reader: {exc}")
                self.read_future = None
            
            # Cancel and clean up pending write operations
            if self.write_future is not None:
                if not self.write_future.done():
                    try:
                        self.write_future.cancel()
                    except Exception as exc:
                        _L().debug(f"Error cancelling write future: {exc}")
                
                if fd is not None and has_loop:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.remove_writer(fd)
                    except (OSError, ValueError, RuntimeError) as exc:
                        _L().debug(f"Error removing writer: {exc}")
                self.write_future = None
            
            # Close the underlying serial port
            try:
                if self._serial and self._serial.is_open:
                    self._serial.close()
            except OSError as e:
                # Handle case where file descriptor is already closed/invalid
                if e.errno in (errno.EBADF, 9):  # Bad file descriptor
                    _L().debug("Serial port already closed")
                else:
                    raise
            except Exception as exc:
                _L().error(f"Error closing serial port: {exc}")
                raise
