#!/usr/bin/env python3
"""Start project MCP servers and verify their initialize handshakes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import subprocess
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / ".mcp.json"
PROTOCOL_VERSION = "2025-03-26"


def initialize_server(
    name: str,
    config: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    command = [config["command"], *config.get("args", [])]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "psx-kr-mcp-probe", "version": "1"},
        },
    }
    try:
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                [process.stdout],
                [],
                [],
                max(0.0, deadline - time.monotonic()),
            )
            if not ready:
                break
            line = process.stdout.readline()
            if not line:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != 1:
                continue
            if "error" in response:
                raise RuntimeError(f"{name}: {response['error']}")
            result = response["result"]
            return {
                "name": name,
                "ok": True,
                "protocol_version": result.get("protocolVersion"),
                "server_info": result.get("serverInfo", {}),
            }
        raise TimeoutError(f"{name}: initialize timed out after {timeout:g}s")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--server", action="append", help="probe only this server")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))["mcpServers"]
    selected = args.server or list(config)
    unknown = sorted(set(selected) - set(config))
    if unknown:
        parser.error(f"unknown MCP server(s): {', '.join(unknown)}")

    results = []
    failed = False
    for name in selected:
        try:
            results.append(initialize_server(name, config[name], timeout=args.timeout))
        except (FileNotFoundError, KeyError, RuntimeError, TimeoutError) as error:
            failed = True
            results.append({"name": name, "ok": False, "error": str(error)})
    print(json.dumps({"ok": not failed, "servers": results}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
