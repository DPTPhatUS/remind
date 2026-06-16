from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id] = websocket

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    async def send(self, session_id: str, message: dict) -> None:
        websocket = self._connections.get(session_id)
        if websocket is not None:
            await websocket.send_json(message)
