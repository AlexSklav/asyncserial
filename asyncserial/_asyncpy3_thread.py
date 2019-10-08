import asyncio
import platform
import threading

from .asyncserial import AsyncSerial


async def wrap_background_loop(func, serial_loop, *args, **kwargs):
    loop = asyncio.get_event_loop()
    co_result = asyncio.Event()

    def co_func():
        async def _func(*args, **kwargs):
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
        loop_started = threading.Event()

        def start():
            if platform.system() == 'Windows':
                # Need to use Proactor (IOCP) event loop for serial port.
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            self.device = AsyncSerial(*args, loop=loop, **kwargs)
            self.loop = loop
            loop.call_soon(loop_started.set)
            loop.run_forever()

        self.thread = threading.Thread(target=start)
        self.thread.daemon = True
        self.thread.start()

        loop_started.wait()

    def write(self, *args, **kwargs):
        return wrap_background_loop(self.device.write, self.loop, *args, **kwargs)

    def read_exactly(self, *args, **kwargs):
        return wrap_background_loop(self.device.read_exactly, self.loop, *args, **kwargs)

    def read(self, *args, **kwargs):
        return wrap_background_loop(self.device.read, self.loop, *args, **kwargs)

    async def readline(self):
        data = b''
        while True:
            data += await self.read(1)
            if data and data[-1] == ord(b'\n'):
                return data

    def close(self):
        self.loop.call_soon_threadsafe(self.device.close)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
