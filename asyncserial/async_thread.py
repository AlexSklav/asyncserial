# -*- encoding: utf-8 -*-
import asyncio
import threading

from typing import Callable, Union, Any

from .asyncserial import AsyncSerial


async def wrap_background_loop(func: Callable, serial_loop: asyncio.AbstractEventLoop,
                               *args, **kwargs) -> Union[Exception, Any]:
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
    loop = asyncio.get_event_loop()
    co_result = asyncio.Event()

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
    else:
        return co_result.result


class BackgroundSerialAsync:
    def __init__(self, *args, **kwargs):
        self.loop = asyncio.new_event_loop()
        self.device = AsyncSerial(*args, loop=self.loop, **kwargs)
        self.thread = threading.Thread(target=self._start_loop)
        self.thread.daemon = True
        self.thread.start()

    def _start_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def write(self, *args, **kwargs) -> Union[Exception, Any]:
        return wrap_background_loop(self.device.write, self.loop, *args, **kwargs)

    def read_exactly(self, *args, **kwargs) -> Union[Exception, Any]:
        return wrap_background_loop(self.device.read_exactly, self.loop, *args, **kwargs)

    def read(self, *args, **kwargs) -> Union[Exception, Any]:
        return wrap_background_loop(self.device.read, self.loop, *args, **kwargs)

    async def readline(self) -> bytes:
        data = bytearray()
        while True:
            char = await self.read(1)
            data += char
            if char == b'\n':
                return data

    def close(self) -> None:
        self.device.close()
        self.loop.call_soon_threadsafe(self.loop.stop)

    def __enter__(self) -> 'BackgroundSerialAsync':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
