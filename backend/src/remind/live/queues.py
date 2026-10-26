import asyncio


class LatestQueue[T]:
    def __init__(self):
        self.queue: asyncio.Queue[T] = asyncio.Queue(maxsize=1)
        self.dropped = 0

    def put(self, item: T) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(item)

    async def get(self) -> T:
        return await self.queue.get()
