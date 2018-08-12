from __future__ import division, print_function, unicode_literals

from nose.tools import raises
import asyncserial
import serial
import serial.tools.list_ports
import trollius as asyncio


def test_asyncserial_timeout_workaround():
    '''
    Test closing event loop to free up device AsyncSerial instance.
    '''
    ports = serial.tools.list_ports.comports()
    if not ports:
        raise RuntimeError('No comports available.')

    kwargs = {'port': ports[0].device}

    @asyncio.coroutine
    def _open_asyncserial():
        with asyncserial.AsyncSerial(**kwargs) as async_device:
            yield asyncio.From(asyncio.sleep(5))

        raise asyncio.Return(None)

    def _open_serial(retries=1):
        for i in range(retries):
            try:
                with serial.Serial(**kwargs):
                    pass
                break
            except serial.SerialException as exception:
                pass
        else:
            raise exception

    _open_serial()

    try:
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(asyncio.wait_for(_open_asyncserial(),
                                                 timeout=2))
    except asyncio.TimeoutError:
        pass
    finally:
        # Close event loop.
        loop.close()

    try:
        _open_serial()
    except serial.SerialException:
        _open_serial()


def test_asyncserial_timeout_error():
    '''
    Verify serial device AsyncSerial instance is still tied up after closing.

    In Windows, it turns out that the serial port is tied up by an AsyncSerial
    instance until the corresponding event loop is closed.  This test tests
    that this is true.
    '''
    ports = serial.tools.list_ports.comports()
    if not ports:
        raise RuntimeError('No comports available.')

    kwargs = {'port': ports[0].device}

    @asyncio.coroutine
    def _open_asyncserial():
        with asyncserial.AsyncSerial(**kwargs) as async_device:
            yield asyncio.From(asyncio.sleep(5))

        raise asyncio.Return(None)

    def _open_serial(retries=1):
        for i in range(retries):
            try:
                with serial.Serial(**kwargs):
                    pass
                break
            except serial.SerialException as exception:
                pass
        else:
            raise exception

    _open_serial()

    try:
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(asyncio.wait_for(_open_asyncserial(),
                                                 timeout=2))
    except asyncio.TimeoutError:
        pass

    try:
        _open_serial()
    except serial.SerialException:
        raises(serial.SerialException)(_open_serial)()
