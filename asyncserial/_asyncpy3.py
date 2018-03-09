class AsyncSerialPy3Mixin:
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
