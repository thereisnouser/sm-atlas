from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .database import SaveDatabase
from .formats.lz4 import Lz4BlockError, decompress_block_prefix
from .terrain_decode import (
    VOXELS_PER_CHUNK,
    DecodedVoxelRecord,
    decode_voxel_records,
)


@dataclass(frozen=True)
class InnerLz4Candidate:
    offset: int
    consumed: int
    trailing: int

    def to_dict(self) -> dict[str, int]:
        return {
            "offset": self.offset,
            "consumed": self.consumed,
            "trailing": self.trailing,
        }


def _inner_lz4_candidates(
    payload: bytes,
    *,
    max_offset: int,
) -> list[InnerLz4Candidate]:
    candidates: list[InnerLz4Candidate] = []
    upper_bound = min(max_offset, max(0, len(payload) - 1))

    for offset in range(upper_bound + 1):
        try:
            _, consumed = decompress_block_prefix(
                payload[offset:],
                expected_output_size=VOXELS_PER_CHUNK,
            )
        except (Lz4BlockError, ValueError):
            continue

        candidates.append(
            InnerLz4Candidate(
                offset=offset,
                consumed=consumed,
                trailing=len(payload) - offset - consumed,
            )
        )

    return candidates


def _record_example(
    record: DecodedVoxelRecord,
    candidates: list[InnerLz4Candidate],
) -> dict[str, object]:
    payload = record.payload

    example: dict[str, object] = {
        "id": record.record_id,
        "chunk": {
            "x": record.chunk_x,
            "y": record.chunk_y,
            "z": record.chunk_z,
        },
        "payload_size": len(payload),
        "payload_prefix_hex": payload[:64].hex(),
        "inner_lz4_candidates": [
            candidate.to_dict()
            for candidate in candidates
        ],
    }

    if len(payload) == 4:
        example["u32_be"] = int.from_bytes(payload, "big")
        example["u32_le"] = int.from_bytes(payload, "little")

    return example


def probe_voxel_payloads(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 1000,
    max_offset: int = 16,
    examples: int = 20,
) -> dict[str, object]:
    if not 0 <= max_offset <= 128:
        raise ValueError("max_offset must be between 0 and 128")
    if not 0 <= examples <= 100:
        raise ValueError("examples must be between 0 and 100")

    records, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    payload_sizes = Counter(len(record.payload) for record in records)
    first_bytes = Counter(
        record.payload[:1].hex()
        for record in records
        if record.payload
    )
    first_u16_be = Counter(
        int.from_bytes(record.payload[:2], "big")
        for record in records
        if len(record.payload) >= 2
    )
    prefixes = Counter(
        record.payload[:8].hex()
        for record in records
        if record.payload
    )

    four_byte_values = Counter(
        record.payload.hex()
        for record in records
        if len(record.payload) == 4
    )

    candidate_records: list[
        tuple[DecodedVoxelRecord, list[InnerLz4Candidate]]
    ] = []
    offset_histogram: Counter[int] = Counter()
    exact_inner_lz4 = 0
    inner_lz4_matches = 0

    for record in records:
        candidates = _inner_lz4_candidates(
            record.payload,
            max_offset=max_offset,
        )

        if candidates:
            inner_lz4_matches += 1
            candidate_records.append((record, candidates))

            for candidate in candidates:
                offset_histogram[candidate.offset] += 1

                if candidate.offset == 0 and candidate.trailing == 0:
                    exact_inner_lz4 += 1

    four_byte_examples = [
        (record, [])
        for record in records
        if len(record.payload) == 4
    ]

    other_examples = [
        (record, [])
        for record in records
        if len(record.payload) != 4
    ]

    selected: list[
        tuple[DecodedVoxelRecord, list[InnerLz4Candidate]]
    ] = []

    for group in (
        candidate_records,
        four_byte_examples,
        other_examples,
    ):
        for item in group:
            if len(selected) >= examples:
                break

            record_id = item[0].record_id
            if any(existing[0].record_id == record_id for existing in selected):
                continue

            selected.append(item)

        if len(selected) >= examples:
            break

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(records),
        "decode_failures": dict(failures.most_common()),
        "payload_size_range": (
            {
                "min": min(payload_sizes),
                "max": max(payload_sizes),
            }
            if payload_sizes
            else None
        ),
        "payload_size_histogram": {
            str(size): count
            for size, count in sorted(payload_sizes.items())
        },
        "four_byte_records": sum(four_byte_values.values()),
        "four_byte_values": dict(four_byte_values.most_common(30)),
        "first_byte_histogram": dict(first_bytes.most_common(30)),
        "first_u16_be_histogram": {
            str(value): count
            for value, count in first_u16_be.most_common(30)
        },
        "payload_prefixes": dict(prefixes.most_common(40)),
        "inner_lz4_matches": inner_lz4_matches,
        "inner_lz4_offset_histogram": {
            str(offset): count
            for offset, count in sorted(offset_histogram.items())
        },
        "exact_inner_lz4_records": exact_inner_lz4,
        "expected_inner_output_size": VOXELS_PER_CHUNK,
        "examples": [
            _record_example(record, candidates)
            for record, candidates in selected
        ],
    }
