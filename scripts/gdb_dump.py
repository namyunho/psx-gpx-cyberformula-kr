#!/usr/bin/env python3
"""Dump PS1 RAM from DuckStation's GDB server with reconnect/retry support."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import time


class RemoteGdb:
    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self.buffer = bytearray()

    def connect(self) -> None:
        self.close()
        self.socket = socket.create_connection((self.host, self.port), self.timeout)
        self.socket.settimeout(self.timeout)
        self.buffer.clear()

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            finally:
                self.socket = None

    def _fill_buffer(self) -> None:
        assert self.socket is not None
        chunk = self.socket.recv(65536)
        if not chunk:
            raise ConnectionError("GDB server closed the connection")
        self.buffer.extend(chunk)

    def _read_exact(self, size: int) -> bytes:
        while len(self.buffer) < size:
            self._fill_buffer()
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def _read_until(self, marker: int) -> bytes:
        while True:
            try:
                index = self.buffer.index(marker)
            except ValueError:
                self._fill_buffer()
                continue
            result = bytes(self.buffer[:index])
            del self.buffer[: index + 1]
            return result

    def _receive_packet(self, first: bytes = b"") -> bytes:
        if first != b"$":
            self._read_until(ord("$"))
        payload = self._read_until(ord("#"))
        received_checksum = int(self._read_exact(2), 16)
        actual_checksum = sum(payload) & 0xFF
        if received_checksum != actual_checksum:
            assert self.socket is not None
            self.socket.sendall(b"-")
            raise ValueError("GDB response checksum mismatch")
        assert self.socket is not None
        self.socket.sendall(b"+")
        return payload

    def command(self, command: str) -> bytes:
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        raw = command.encode("ascii")
        packet = b"$" + raw + b"#" + f"{sum(raw) & 0xFF:02x}".encode("ascii")
        self.socket.sendall(packet)
        while True:
            current = self._read_exact(1)
            if current == b"+":
                return self._receive_packet()
            if current == b"$":
                return self._receive_packet(current)

    def interrupt(self) -> bytes:
        """Halt a running target and return its stop reply."""
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        self.socket.sendall(b"\x03")
        return self._receive_packet()

    def resume(self) -> None:
        """Resume the target without waiting for its next stop reply."""
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        raw = b"c"
        packet = b"$" + raw + b"#" + f"{sum(raw) & 0xFF:02x}".encode("ascii")
        self.socket.sendall(packet)
        acknowledgement = self._read_exact(1)
        if acknowledgement != b"+":
            raise RuntimeError(f"unexpected GDB acknowledgement: {acknowledgement!r}")

    def write_memory(self, address: int, data: bytes) -> None:
        response = self.command(f"M{address:x},{len(data):x}:{data.hex()}")
        if response != b"OK":
            raise RuntimeError(f"GDB memory write failed: {response.decode()}")

    def read_memory(self, address: int, size: int, retries: int = 3) -> bytes:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = self.command(f"m{address:x},{size:x}")
                if response.startswith(b"E"):
                    raise RuntimeError(f"GDB memory error: {response.decode()}")
                result = bytes.fromhex(response.decode("ascii"))
                if len(result) != size:
                    raise ValueError(f"short GDB memory response: {len(result)} != {size}")
                return result
            except (ConnectionError, OSError, TimeoutError, ValueError) as error:
                last_error = error
                self.close()
                if attempt + 1 < retries:
                    time.sleep(0.1)
                    self.connect()
        assert last_error is not None
        raise last_error


def dump_memory(
    client: RemoteGdb,
    address: int,
    size: int,
    chunk_size: int,
    reconnect_interval: int,
) -> bytes:
    output = bytearray()
    for index, offset in enumerate(range(0, size, chunk_size)):
        if index and reconnect_interval and index % reconnect_interval == 0:
            client.connect()
        current_size = min(chunk_size, size - offset)
        output.extend(client.read_memory(address + offset, current_size, retries=1))
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3333)
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x80000000)
    parser.add_argument("--size", type=lambda value: int(value, 0), default=0x200000)
    parser.add_argument("--chunk", type=lambda value: int(value, 0), default=0x400)
    parser.add_argument("--reconnect-interval", type=int, default=128)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    client = RemoteGdb(args.host, args.port)
    try:
        client.connect()
        data = dump_memory(
            client,
            args.address,
            args.size,
            args.chunk,
            args.reconnect_interval,
        )
    finally:
        client.close()
    Path(args.output).write_bytes(data)
    print(f"address=0x{args.address:08X} size={len(data)} output={args.output}")


if __name__ == "__main__":
    main()
