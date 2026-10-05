from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from .database import SaveDatabase
from .terrain_decode import VOXELS_PER_CHUNK, decode_voxel_records

MASK_BYTES = (VOXELS_PER_CHUNK + 7) // 8


@dataclass(frozen=True)
class MaskModelScore:
    mode: str
    offset: int
    selected_bits: str
    value_bits: int
    records: int
    candidates: int
    exact_records: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "offset": self.offset,
            "selected_bits": self.selected_bits,
            "value_bits": self.value_bits,
            "records": self.records,
            "candidates": self.candidates,
            "exact_records": self.exact_records,
            "exact_ratio": (
                round(self.exact_records / self.candidates, 4)
                if self.candidates
                else 0.0
            ),
        }


def _valid_mask_bits(mask: bytes) -> tuple[int, int]:
    ones = 0

    for bit_index in range(VOXELS_PER_CHUNK):
        byte = mask[bit_index // 8]
        bit = 7 - (bit_index % 8)
        ones += (byte >> bit) & 1

    return ones, VOXELS_PER_CHUNK - ones


def _packed_bytes(symbols: int, bits_per_symbol: int) -> int:
    return ceil(symbols * bits_per_symbol / 8)


def probe_voxel_masks(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    max_offset: int = 8,
) -> dict[str, object]:
    if not 0 <= max_offset <= 32:
        raise ValueError("max_offset must be between 0 and 32")

    records, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    framed: list[tuple[int, bytes]] = []
    for record in records:
        if len(record.payload) < 3:
            continue

        mode = record.payload[0]
        declared = int.from_bytes(record.payload[1:3], "big")
        body = record.payload[3:]

        if declared == len(body):
            framed.append((mode, body))

    scores: list[MaskModelScore] = []

    for mode_filter in (None, 0x04, 0x05):
        selected = [
            body
            for mode, body in framed
            if mode_filter is None or mode == mode_filter
        ]

        mode_name = (
            "all"
            if mode_filter is None
            else f"{mode_filter:02x}"
        )

        for offset in range(max_offset + 1):
            eligible = [
                body[offset:]
                for body in selected
                if len(body) >= offset + MASK_BYTES
            ]

            mask_stats = []
            for body in eligible:
                mask = body[:MASK_BYTES]
                tail_size = len(body) - MASK_BYTES
                ones, zeros = _valid_mask_bits(mask)
                mask_stats.append((tail_size, ones, zeros))

            for selected_bits in ("ones", "zeros"):
                for value_bits in range(1, 9):
                    exact = 0

                    for tail_size, ones, zeros in mask_stats:
                        symbols = (
                            ones
                            if selected_bits == "ones"
                            else zeros
                        )
                        expected = _packed_bytes(
                            symbols,
                            value_bits,
                        )

                        if tail_size == expected:
                            exact += 1

                    scores.append(
                        MaskModelScore(
                            mode=mode_name,
                            offset=offset,
                            selected_bits=selected_bits,
                            value_bits=value_bits,
                            records=len(selected),
                            candidates=len(mask_stats),
                            exact_records=exact,
                        )
                    )

    scores.sort(
        key=lambda score: (
            score.exact_records,
            score.candidates,
        ),
        reverse=True,
    )

    packed_width_sizes = {
        str(bits): _packed_bytes(VOXELS_PER_CHUNK, bits)
        for bits in range(1, 9)
    }

    direct_width_matches: dict[str, dict[str, int]] = {}

    for mode_filter in (0x04, 0x05):
        mode_name = f"{mode_filter:02x}"
        mode_bodies = [
            body
            for mode, body in framed
            if mode == mode_filter
        ]

        direct_width_matches[mode_name] = {
            str(bits): sum(
                1
                for body in mode_bodies
                if len(body) == packed_width_sizes[str(bits)]
            )
            for bits in range(1, 9)
        }

    plane_size = MASK_BYTES
    plane_buckets: dict[str, dict[str, int]] = {}

    for mode_filter in (0x04, 0x05):
        mode_name = f"{mode_filter:02x}"
        mode_bodies = [
            body
            for mode, body in framed
            if mode == mode_filter
        ]

        plane_buckets[mode_name] = {
            f"<= {planes} planes": sum(
                1
                for body in mode_bodies
                if len(body) <= planes * plane_size
            )
            for planes in range(1, 9)
        }

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(records),
        "decode_failures": dict(failures.most_common()),
        "framed_records": len(framed),
        "voxel_count": VOXELS_PER_CHUNK,
        "mask_bytes": MASK_BYTES,
        "packed_width_sizes": packed_width_sizes,
        "direct_width_matches": direct_width_matches,
        "plane_buckets": plane_buckets,
        "models": [score.to_dict() for score in scores],
    }
