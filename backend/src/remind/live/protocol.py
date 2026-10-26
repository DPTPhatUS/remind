import json
import math
import struct
from typing import TypedDict


class FrameHeader(TypedDict):
    version: int
    generation: str
    sequence: int
    capture_ms: float


def decode_packet(data: bytes) -> tuple[FrameHeader, bytes]:
    if len(data) < 5 or len(data) > 2 * 1024 * 1024 + 8196:
        raise ValueError("Invalid packet size")
    length = struct.unpack(">I", data[:4])[0]
    if length > 8192 or length + 4 >= len(data):
        raise ValueError("Invalid packet header")
    try:
        header = json.loads(data[4 : 4 + length])
        if not isinstance(header, dict):
            raise ValueError("Invalid packet header")
        if type(header["version"]) is not int or header["version"] != 1:
            raise ValueError("Unsupported packet")
        if not isinstance(header["generation"], str):
            raise ValueError("Invalid generation")
        if type(header["sequence"]) is not int or header["sequence"] < 0:
            raise ValueError("Invalid sequence")
        if (
            type(header["capture_ms"]) not in (int, float)
            or not math.isfinite(header["capture_ms"])
            or header["capture_ms"] < 0
        ):
            raise ValueError("Invalid timestamp")
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid header") from exc
    return {
        "version": 1,
        "generation": header["generation"],
        "sequence": header["sequence"],
        "capture_ms": header["capture_ms"],
    }, data[4 + length :]
