import asyncio


class LatestQueue:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=1)
        self.dropped = 0

    def put(self, item):
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(item)

    async def get(self):
        return await self.queue.get()
