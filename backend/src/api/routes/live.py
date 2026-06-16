from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import get_compreface_client
from core.config import get_settings
from realtime.connection_manager import ConnectionManager
from realtime.session_orchestrator import LiveSessionOrchestrator

router = APIRouter()
manager = ConnectionManager()


@router.websocket("/sessions/{session_id}")
async def live_session(websocket: WebSocket, session_id: str) -> None:
    await manager.connect(session_id, websocket)
    orchestrator = LiveSessionOrchestrator(
        session_id=session_id,
        compreface=get_compreface_client(get_settings()),
    )
    await manager.send(session_id, orchestrator.ready_message())
    try:
        while True:
            message = await websocket.receive_json()
            response = await orchestrator.handle_message(message)
            if response is not None:
                await manager.send(session_id, response)
            if message.get("type") == "session.stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)
