# -*- encoding: utf-8 -*-
from nose.tools import raises
import asyncserial
import serial
import serial.tools.list_ports
import asyncio


def get_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        raise RuntimeError('No comports available.')
    return ports


def test_asyncserial_timeout_workaround():
    """
    Test closing event loop to free up device AsyncSerial instance.
    """
    ports = get_ports()

    kwargs = {'port': ports[0].device}

    async def _open_asyncserial():
        with asyncserial.AsyncSerial(**kwargs) as async_device:
            await asyncio.sleep(5)

    def _open_serial(retries=1):
        for i in range(retries):
            try:
                with serial.Serial(**kwargs):
                    pass
                break
            except serial.SerialException as exception:
                pass
        else:
            raise Exception

    _open_serial()

    loop = None
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(_open_asyncserial(), timeout=2))
    except asyncio.TimeoutError:
        pass
    finally:
        # Close event loop.
        if loop is not None:
            loop.close()

    try:
        _open_serial()
    except serial.SerialException:
        _open_serial()


def test_asyncserial_timeout_error():
    """
    Verify serial device AsyncSerial instance is still tied up after closing.

    In Windows, it turns out that the serial port is tied up by an AsyncSerial
    instance until the corresponding event loop is closed.  This test tests
    that this is true.
    """
    ports = get_ports()

    kwargs = {'port': ports[0].device}

    async def _open_asyncserial():
        async with asyncserial.AsyncSerial(**kwargs) as async_device:
            print(async_device.port)
            await asyncio.sleep(5)

    def _open_serial(retries=1):
        for i in range(retries):
            try:
                with serial.Serial(**kwargs):
                    pass
                break
            except serial.SerialException as exception:
                pass
        else:
            raise Exception

    _open_serial()

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(_open_asyncserial(), timeout=2))
    except asyncio.TimeoutError:
        pass

    try:
        _open_serial()
    except serial.SerialException:
        raises(serial.SerialException)(_open_serial)()
