#!/usr/bin/env python3
"""Write and verify a binary fragment in PS1 RAM through DuckStation GDB."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.gdb_dump import RemoteGdb
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from gdb_dump import RemoteGdb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3333)
    parser.add_argument("--address", type=lambda value: int(value, 0), required=True)
    parser.add_argument(
        "--interrupt",
        action="store_true",
        help="send a remote break packet; DuckStation normally must be UI-paused",
    )
    parser.add_argument("--leave-paused", action="store_true")
    args = parser.parse_args()

    data = args.input.read_bytes()
    if not data:
        parser.error("input must not be empty")

    client = RemoteGdb(args.host, args.port)
    resumed = False
    try:
        client.connect()
        stop_reply = client.interrupt() if args.interrupt else b"UI-paused"
        client.write_memory(args.address, data)
        actual = client.read_memory(args.address, len(data), retries=1)
        if actual != data:
            raise RuntimeError("RAM verification failed after GDB write")
        if not args.leave_paused:
            client.resume()
            resumed = True
    finally:
        client.close()

    print(
        f"address=0x{args.address:08X} size={len(data)} "
        f"verified=yes resumed={'yes' if resumed else 'no'} "
        f"stop_reply={stop_reply.decode('ascii', errors='replace')}"
    )


if __name__ == "__main__":
    main()
