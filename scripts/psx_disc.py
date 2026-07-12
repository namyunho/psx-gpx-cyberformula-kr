#!/usr/bin/env python3
"""Read-only inspector/extractor for raw PS1 MODE1/MODE2 disc images.

The tool deliberately has no image-writing commands. It supports the subset of
ISO 9660 needed by the current project and reports sector form explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import struct
import zlib


RAW_SECTOR_SIZE = 2352


@dataclass(frozen=True)
class IsoEntry:
    name: str
    lba: int
    size: int
    is_directory: bool


class PsxDisc:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("rb")

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "PsxDisc":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def sector_count(self) -> int:
        size = self.path.stat().st_size
        if size % RAW_SECTOR_SIZE:
            raise ValueError(f"image size is not divisible by {RAW_SECTOR_SIZE}: {size}")
        return size // RAW_SECTOR_SIZE

    def read_sector(self, lba: int) -> tuple[bytes, str]:
        if lba < 0 or lba >= self.sector_count:
            raise ValueError(f"LBA outside this track: {lba}")
        self._file.seek(lba * RAW_SECTOR_SIZE)
        sector = self._file.read(RAW_SECTOR_SIZE)
        if len(sector) != RAW_SECTOR_SIZE:
            raise EOFError(f"short sector at LBA {lba}")
        if sector[:12] != bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00"):
            raise ValueError(f"invalid raw-sector sync pattern at LBA {lba}")
        mode = sector[15]
        if mode == 1:
            return sector[16:2064], "MODE1"
        if mode != 2:
            raise ValueError(f"unsupported sector mode {mode} at LBA {lba}")
        form2 = bool(sector[18] & 0x20)
        if form2:
            return sector[24:2348], "MODE2/FORM2"
        return sector[24:2072], "MODE2/FORM1"

    def read_extent(self, lba: int, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            payload, _ = self.read_sector(lba)
            result.extend(payload)
            lba += 1
        return bytes(result[:size])

    def primary_volume_descriptor(self) -> bytes:
        pvd, sector_type = self.read_sector(16)
        if sector_type not in {"MODE1", "MODE2/FORM1"}:
            raise ValueError(f"PVD is stored in {sector_type}")
        if pvd[0] != 1 or pvd[1:6] != b"CD001" or pvd[6] != 1:
            raise ValueError("ISO 9660 primary volume descriptor not found at LBA 16")
        return pvd

    def root_entries(self) -> list[IsoEntry]:
        pvd = self.primary_volume_descriptor()
        root = pvd[156:190]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        return list(parse_directory(self.read_extent(root_lba, root_size)))


def parse_directory(data: bytes):
    position = 0
    while position < len(data):
        record_size = data[position]
        if record_size == 0:
            position = ((position // 2048) + 1) * 2048
            continue
        record = data[position : position + record_size]
        if len(record) < 34:
            raise ValueError(f"truncated ISO directory record at 0x{position:X}")
        name_size = record[32]
        raw_name = record[33 : 33 + name_size]
        name = raw_name.decode("ascii", "replace")
        if name not in {"\x00", "\x01"}:
            yield IsoEntry(
                name=name.split(";", 1)[0],
                lba=struct.unpack_from("<I", record, 2)[0],
                size=struct.unpack_from("<I", record, 10)[0],
                is_directory=bool(record[25] & 2),
            )
        position += record_size


def file_hashes(path: Path) -> dict[str, str | int]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    crc32 = 0
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
            crc32 = zlib.crc32(chunk, crc32)
    return {
        "size": path.stat().st_size,
        "crc32": f"{crc32 & 0xFFFFFFFF:08X}",
        "md5": md5.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def cmd_info(args: argparse.Namespace) -> None:
    path = Path(args.image)
    with PsxDisc(path) as disc:
        pvd = disc.primary_volume_descriptor()
        result = {
            "path": str(path),
            "sector_size": RAW_SECTOR_SIZE,
            "sector_count": disc.sector_count,
            "system_id": pvd[8:40].decode("ascii", "replace").strip(),
            "volume_id": pvd[40:72].decode("ascii", "replace").strip(),
        }
        if args.hash:
            result.update(file_hashes(path))
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    with PsxDisc(Path(args.image)) as disc:
        print(json.dumps([asdict(entry) for entry in disc.root_entries()], indent=2))


def cmd_extract(args: argparse.Namespace) -> None:
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    with PsxDisc(Path(args.image)) as disc:
        for entry in disc.root_entries():
            if entry.is_directory or entry.lba >= disc.sector_count:
                continue
            if args.name and entry.name.upper() not in {x.upper() for x in args.name}:
                continue
            output = destination / entry.name
            output.write_bytes(disc.read_extent(entry.lba, entry.size))
            print(f"{entry.name}\t{entry.size}\t{output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="show image and ISO metadata")
    info.add_argument("--image", required=True)
    info.add_argument("--hash", action="store_true")
    info.set_defaults(func=cmd_info)

    listing = subparsers.add_parser("list", help="list ISO root entries as JSON")
    listing.add_argument("--image", required=True)
    listing.set_defaults(func=cmd_list)

    extract = subparsers.add_parser("extract", help="extract logical ISO files")
    extract.add_argument("--image", required=True)
    extract.add_argument("--output", required=True)
    extract.add_argument("--name", action="append", help="file to extract; repeatable")
    extract.set_defaults(func=cmd_extract)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
