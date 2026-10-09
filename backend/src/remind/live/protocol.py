import json
import math
import struct


def decode_packet(data):
    if len(data) < 5 or len(data) > 2 * 1024 * 1024 + 8196:
        raise ValueError("Invalid packet size")
    length = struct.unpack(">I", data[:4])[0]
    if length > 8192 or length + 4 >= len(data):
        raise ValueError("Invalid packet header")
    try:
        header = json.loads(data[4 : 4 + length])
        if header["version"] != 1 or not isinstance(header["generation"], str):
            raise ValueError("Unsupported packet")
        if not isinstance(header["sequence"], int) or header["sequence"] < 0:
            raise ValueError("Invalid sequence")
        if (
            not isinstance(header["capture_ms"], (int, float))
            or not math.isfinite(header["capture_ms"])
            or header["capture_ms"] < 0
        ):
            raise ValueError("Invalid timestamp")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid header") from exc
    return header, data[4 + length :]
