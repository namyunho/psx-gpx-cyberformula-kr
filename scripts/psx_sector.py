#!/usr/bin/env python3
"""Validate and rebuild raw PlayStation MODE2/Form1 sector integrity fields."""

from __future__ import annotations

from dataclasses import dataclass


RAW_SECTOR_SIZE = 2352
SYNC_PATTERN = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")
MODE_OFFSET = 15
SUBHEADER_OFFSET = 16
SUBHEADER_SIZE = 8
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048
EDC_OFFSET = USER_DATA_OFFSET + USER_DATA_SIZE
EDC_SIZE = 4
ECC_OFFSET = EDC_OFFSET + EDC_SIZE
ECC_P_SIZE = 172
ECC_Q_SIZE = 104
ECC_SIZE = ECC_P_SIZE + ECC_Q_SIZE


def _build_tables() -> tuple[bytes, bytes, tuple[int, ...]]:
    forward = bytearray(256)
    backward = bytearray(256)
    edc_table: list[int] = []
    for value in range(256):
        doubled = (value << 1) ^ (0x11D if value & 0x80 else 0)
        doubled &= 0xFF
        forward[value] = doubled
        backward[value ^ doubled] = value

        edc = value
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
        edc_table.append(edc)
    return bytes(forward), bytes(backward), tuple(edc_table)


ECC_FORWARD, ECC_BACKWARD, EDC_TABLE = _build_tables()


@dataclass(frozen=True)
class Mode2Form1Integrity:
    edc_valid: bool
    zero_address_ecc_valid: bool
    sector_address_ecc_valid: bool

    @property
    def valid(self) -> bool:
        return self.edc_valid and (
            self.zero_address_ecc_valid
            or self.sector_address_ecc_valid
        )

    @property
    def ecc_address_mode(self) -> str:
        if self.zero_address_ecc_valid and not self.sector_address_ecc_valid:
            return "zero"
        if self.sector_address_ecc_valid and not self.zero_address_ecc_valid:
            return "sector"
        if self.zero_address_ecc_valid and self.sector_address_ecc_valid:
            return "zero-or-sector"
        return "invalid"


def validate_mode2_form1_structure(sector: bytes | bytearray) -> None:
    if len(sector) != RAW_SECTOR_SIZE:
        raise ValueError(
            f"raw sector must be {RAW_SECTOR_SIZE} bytes, got {len(sector)}"
        )
    if sector[:12] != SYNC_PATTERN:
        raise ValueError("raw sector sync pattern differs")
    if sector[MODE_OFFSET] != 2:
        raise ValueError(f"sector mode is {sector[MODE_OFFSET]}, expected 2")
    if sector[SUBHEADER_OFFSET : SUBHEADER_OFFSET + 4] != sector[
        SUBHEADER_OFFSET + 4 : SUBHEADER_OFFSET + 8
    ]:
        raise ValueError("MODE2 duplicated subheader differs")
    if sector[SUBHEADER_OFFSET + 2] & 0x20:
        raise ValueError("sector is MODE2/Form2, not Form1")


def compute_edc(data: bytes | bytearray) -> bytes:
    value = 0
    for byte in data:
        value = (value >> 8) ^ EDC_TABLE[(value ^ byte) & 0xFF]
    return value.to_bytes(4, "little")


def compute_ecc(
    address: bytes,
    source: bytes | bytearray,
    *,
    major_count: int,
    minor_count: int,
    major_mult: int,
    minor_inc: int,
) -> bytes:
    if len(address) != 4:
        raise ValueError("ECC address must contain four bytes")
    population = major_count * minor_count
    if len(source) < population - 4:
        raise ValueError("ECC source is shorter than the declared population")

    result = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            value = address[index] if index < 4 else source[index - 4]
            index += minor_inc
            if index >= population:
                index -= population
            ecc_a ^= value
            ecc_b ^= value
            ecc_a = ECC_FORWARD[ecc_a]
        ecc_a = ECC_BACKWARD[ECC_FORWARD[ecc_a] ^ ecc_b]
        result[major] = ecc_a
        result[major + major_count] = ecc_a ^ ecc_b
    return bytes(result)


def calculate_mode2_form1_ecc(
    sector: bytes | bytearray,
    *,
    address_mode: str,
) -> bytes:
    validate_mode2_form1_structure(sector)
    if address_mode == "zero":
        address = b"\0\0\0\0"
    elif address_mode == "sector":
        address = bytes(sector[12:16])
    else:
        raise ValueError(f"unknown ECC address mode: {address_mode!r}")

    # P covers address + subheader + user data + EDC.
    p_source = sector[SUBHEADER_OFFSET:ECC_OFFSET]
    p = compute_ecc(
        address,
        p_source,
        major_count=86,
        minor_count=24,
        major_mult=2,
        minor_inc=86,
    )

    # Q additionally covers the freshly computed P parity.
    q_source = bytes(p_source) + p
    q = compute_ecc(
        address,
        q_source,
        major_count=52,
        minor_count=43,
        major_mult=86,
        minor_inc=88,
    )
    return p + q


def inspect_mode2_form1(sector: bytes | bytearray) -> Mode2Form1Integrity:
    validate_mode2_form1_structure(sector)
    expected_edc = compute_edc(sector[SUBHEADER_OFFSET:EDC_OFFSET])
    stored_edc = bytes(sector[EDC_OFFSET:ECC_OFFSET])
    stored_ecc = bytes(sector[ECC_OFFSET:])
    return Mode2Form1Integrity(
        edc_valid=stored_edc == expected_edc,
        zero_address_ecc_valid=(
            stored_ecc
            == calculate_mode2_form1_ecc(sector, address_mode="zero")
        ),
        sector_address_ecc_valid=(
            stored_ecc
            == calculate_mode2_form1_ecc(sector, address_mode="sector")
        ),
    )


def rebuild_mode2_form1(
    sector: bytes | bytearray,
    *,
    address_mode: str,
) -> bytes:
    validate_mode2_form1_structure(sector)
    rebuilt = bytearray(sector)
    rebuilt[EDC_OFFSET:ECC_OFFSET] = compute_edc(
        rebuilt[SUBHEADER_OFFSET:EDC_OFFSET]
    )
    rebuilt[ECC_OFFSET:] = calculate_mode2_form1_ecc(
        rebuilt,
        address_mode=address_mode,
    )
    return bytes(rebuilt)
