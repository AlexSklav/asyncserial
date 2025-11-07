# -*- encoding: utf-8 -*-
import asyncio
import threading

from typing import Callable, Any, Optional
from logging_helpers import _L

from .asyncserial import AsyncSerial


async def wrap_background_loop(func: Callable, serial_loop: asyncio.AbstractEventLoop,
                               *args, **kwargs) -> Any:
    """
    Execute a coroutine function in the background thread and return its result.

    This function allows you to execute an asyncio coroutine function in the background thread
    managed by the given `serial_loop`. It creates a task for the coroutine function and
    waits for its completion. If the coroutine raises an exception, the exception is raised
    in the calling context. Otherwise, the result of the coroutine is returned.

    Parameters
    ----------
    func: Callable
        The coroutine function to execute in the background thread.
    serial_loop: asyncio.AbstractEventLoop
        The event loop in which to execute the background task.
    *args: Any
        Positional arguments to pass to the coroutine function.
    **kwargs: Any
        Keyword arguments to pass to the coroutine function.

    Returns
    -------
    Any
        The result of the coroutine function.

    Raises
    ------
    Exception
        If the coroutine function raises an exception, it is propagated to the calling context.

    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, get the current event loop
        loop = asyncio.get_event_loop()
    
    co_result = asyncio.Event()
    co_result.result = None  # Initialize result attribute

    def co_func() -> None:
        async def _func(*args, **kwargs) -> None:
            try:
                co_result.result = await func(*args, **kwargs)
            except Exception as exception:
                co_result.result = exception
            finally:
                loop.call_soon_threadsafe(co_result.set)

        serial_loop.create_task(_func(*args, **kwargs))

    serial_loop.call_soon_threadsafe(co_func)
    await co_result.wait()
    
    if isinstance(co_result.result, Exception):
        raise co_result.result
    
    return co_result.result


class BackgroundSerialAsync:
    """
    Wrapper for AsyncSerial that runs in a background thread.
    
    This allows using async serial operations from synchronous code by running
    a separate event loop in a background thread.
    """
    
    def __init__(self, *args, **kwargs):
        self._closed = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.device: Optional[AsyncSerial] = None
        self.thread: Optional[threading.Thread] = None
        
        try:
            self.loop = asyncio.new_event_loop()
            # Don't pass 'loop' to AsyncSerial as it's deprecated
            self.device = AsyncSerial(*args, **kwargs)
            self.thread = threading.Thread(target=self._start_loop, daemon=True, name="AsyncSerial-Thread")
            self.thread.start()
        except Exception as exc:
            _L().error(f"Failed to initialize BackgroundSerialAsync: {exc}")
            self._cleanup()
            raise

    def _start_loop(self) -> None:
        """Run the event loop in the background thread."""
        try:
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        except Exception as exc:
            _L().error(f"Error in background event loop: {exc}")
        finally:
            _L().debug("Background event loop stopped")

    def __repr__(self) -> str:
        port = getattr(self.device, 'port', None) if self.device else None
        return f"BackgroundSerialAsync(port={port!r}, is_open={self.is_open})"

    def __str__(self) -> str:
        port = getattr(self.device, 'port', 'Unknown') if self.device else 'Unknown'
        return f"BackgroundSerialAsync on {port}"

    @property
    def is_open(self) -> bool:
        """Check if the serial port is open."""
        return not self._closed and self.device is not None and self.device.is_open

    @property
    def port(self) -> Optional[str]:
        """Get the port name."""
        return self.device.port if self.device else None

    @property
    def baudrate(self) -> int:
        """Current baudrate."""
        if self.device is None:
            raise IOError("Device not initialized")
        return self.device.baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        """Set baudrate."""
        if self.device is None:
            raise IOError("Device not initialized")
        self.device.baudrate = value

    @property
    def in_waiting(self) -> int:
        """Number of bytes waiting in the input buffer."""
        if self.device is None:
            return 0
        return self.device.in_waiting

    @property
    def out_waiting(self) -> int:
        """Number of bytes waiting in the output buffer."""
        if self.device is None:
            return 0
        return self.device.out_waiting

    async def write(self, *args, **kwargs) -> int:
        """Write data to the serial port (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.write, self.loop, *args, **kwargs)

    async def read(self, *args, **kwargs) -> bytes:
        """Read data from the serial port (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.read, self.loop, *args, **kwargs)

    async def read_exactly(self, *args, **kwargs) -> bytes:
        """Read exactly n bytes from the serial port (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.read_exactly, self.loop, *args, **kwargs)

    async def write_exactly(self, *args, **kwargs) -> None:
        """Write all data to the serial port (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.write_exactly, self.loop, *args, **kwargs)

    async def readline(self, separator: bytes = b'\n') -> bytes:
        """Read until a separator byte is found (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.readline, self.loop, separator)

    async def readuntil(self, expected: bytes = b'\n', size: Optional[int] = None) -> bytes:
        """Read until an expected byte sequence is found (async method)."""
        if self._closed or self.device is None:
            raise IOError("Serial port is closed")
        return await wrap_background_loop(self.device.readuntil, self.loop, expected, size)

    def reset_input_buffer(self) -> None:
        """Clear input buffer."""
        if self.device is not None:
            self.device.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        """Clear output buffer."""
        if self.device is not None:
            self.device.reset_output_buffer()

    def flush(self) -> None:
        """Wait until all data is written."""
        if self.device is not None:
            self.device.flush()

    def _cleanup(self) -> None:
        """Internal cleanup method."""
        if self.device is not None:
            try:
                self.device.close()
            except Exception as exc:
                _L().debug(f"Error closing device: {exc}")
        
        if self.loop is not None and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception as exc:
                _L().debug(f"Error stopping loop: {exc}")
        
        if self.thread is not None and self.thread.is_alive():
            try:
                self.thread.join(timeout=2.0)
            except Exception as exc:
                _L().debug(f"Error joining thread: {exc}")

    def close(self) -> None:
        """Close the serial port and stop the background thread."""
        if self._closed:
            return
        
        self._closed = True
        self._cleanup()
        
        # Close the loop after the thread has stopped
        if self.loop is not None:
            try:
                self.loop.close()
            except Exception as exc:
                _L().debug(f"Error closing loop: {exc}")

    def __enter__(self) -> 'BackgroundSerialAsync':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return False  # Propagate exceptions

    def __del__(self) -> None:
        """Cleanup when object is garbage collected."""
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass  # Ignore errors during cleanup in __del__
