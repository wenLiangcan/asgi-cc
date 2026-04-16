from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from http import HTTPStatus
from typing import Iterable
from urllib.parse import splitquery, urlsplit


CRANKER_V3 = "cranker_3.0"


class MessageType(IntEnum):
    DATA = 0
    HEADER = 1
    RST_STREAM = 3
    WINDOW_UPDATE = 8


FLAG_STREAM_END = 0x01
FLAG_HEADER_END = 0x04
FRAME_PREFIX_SIZE = 6


@dataclass(slots=True)
class Frame:
    message_type: MessageType
    flags: int
    request_id: int
    payload: bytes

    @property
    def is_stream_end(self) -> bool:
        return bool(self.flags & FLAG_STREAM_END)

    @property
    def is_header_end(self) -> bool:
        return bool(self.flags & FLAG_HEADER_END)


@dataclass(slots=True)
class ParsedRequestHead:
    method: str
    dest: str
    http_version: str
    header_lines: list[str]

    @property
    def path(self) -> str:
        path, _ = splitquery(self.dest)
        return path or "/"

    @property
    def query_string(self) -> bytes:
        _, query = splitquery(self.dest)
        return (query or "").encode("ascii")

    @property
    def raw_path(self) -> bytes:
        path = urlsplit(self.dest).path or "/"
        return path.encode("ascii")


def decode_frame(data: bytes) -> Frame:
    if len(data) < FRAME_PREFIX_SIZE:
        raise ValueError("Frame shorter than 6-byte prefix")
    message_type = MessageType(data[0])
    flags = data[1]
    request_id = int.from_bytes(data[2:6], byteorder="big", signed=True)
    return Frame(message_type=message_type, flags=flags, request_id=request_id, payload=data[6:])


def encode_data_frame(request_id: int, payload: bytes = b"", *, stream_end: bool = False) -> bytes:
    flags = FLAG_STREAM_END if stream_end else 0
    return _encode_frame(MessageType.DATA, flags, request_id, payload)


def encode_header_frame(
    request_id: int,
    text_payload: str,
    *,
    header_end: bool,
    stream_end: bool,
) -> bytes:
    flags = 0
    if stream_end:
        flags |= FLAG_STREAM_END
    if header_end:
        flags |= FLAG_HEADER_END
    return _encode_frame(MessageType.HEADER, flags, request_id, text_payload.encode("utf-8"))


def encode_window_update_frame(request_id: int, size: int) -> bytes:
    return _encode_frame(
        MessageType.WINDOW_UPDATE,
        0,
        request_id,
        int(size).to_bytes(4, byteorder="big", signed=True),
    )


def encode_rst_stream_frame(request_id: int, error_code: int, message: str = "") -> bytes:
    payload = int(error_code).to_bytes(4, byteorder="big", signed=True) + message.encode("utf-8")
    return _encode_frame(MessageType.RST_STREAM, 0, request_id, payload)


def split_header_text(text: str, *, max_chunk_bytes: int = 16000) -> list[str]:
    if max_chunk_bytes <= 0:
        raise ValueError("max_chunk_bytes must be positive")
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0

    for char in text:
        encoded = char.encode("utf-8")
        char_size = len(encoded)
        if char_size > max_chunk_bytes:
            raise ValueError("single UTF-8 character exceeds max_chunk_bytes")
        if current and current_bytes + char_size > max_chunk_bytes:
            chunks.append("".join(current))
            current = [char]
            current_bytes = char_size
        else:
            current.append(char)
            current_bytes += char_size

    if current:
        chunks.append("".join(current))
    if not chunks:
        chunks.append("")
    return chunks


def build_request_head(method: str, dest: str, http_version: str, headers: Iterable[tuple[bytes, bytes]]) -> str:
    lines = [f"{method} {dest} {http_version}"]
    for name, value in headers:
        lines.append(f"{name.decode('latin-1')}:{value.decode('latin-1')}")
    return "\n".join(lines)


def parse_request_head(text: str) -> ParsedRequestHead:
    lines = text.split("\n")
    if not lines or not lines[0]:
        raise ValueError("empty request head")
    parts = lines[0].split(" ")
    if len(parts) < 3:
        raise ValueError(f"invalid request line: {lines[0]!r}")
    method, dest, http_version = parts[0], parts[1], parts[2]
    return ParsedRequestHead(method=method, dest=dest, http_version=http_version, header_lines=lines[1:])


def build_response_head(status: int, reason: str, headers: Iterable[tuple[bytes, bytes]]) -> str:
    lines = [f"HTTP/1.1 {status} {reason}"]
    for name, value in headers:
        if name.startswith(b":"):
            continue
        lines.append(f"{name.decode('latin-1')}:{value.decode('latin-1')}")
    return "\n".join(lines)


def default_reason_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _encode_frame(message_type: MessageType, flags: int, request_id: int, payload: bytes) -> bytes:
    return b"".join(
        [
            bytes((int(message_type), flags)),
            int(request_id).to_bytes(4, byteorder="big", signed=True),
            payload,
        ]
    )
