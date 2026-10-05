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


def _payload_frame(payload: bytes) -> tuple[int, int, bytes] | None:
    if len(payload) < 3:
        return None

    mode = payload[0]
    declared_size = int.from_bytes(payload[1:3], "big")
    body = payload[3:]
    return mode, declared_size, body


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

    format_group_sizes: dict[str, list[int]] = {}
    format_group_four_byte: Counter[str] = Counter()
    frame_modes: Counter[int] = Counter()
    frame_mode_body_sizes: dict[int, list[int]] = {}
    frame_mode_single_zero: Counter[int] = Counter()
    frame_declared_size_matches = 0
    frame_declared_size_mismatches = 0
    frame_too_short = 0
    body_first_bytes: dict[int, Counter[str]] = {}

    for record in records:
        frame = _payload_frame(record.payload)
        if frame is None:
            frame_too_short += 1
        else:
            mode, declared_size, body = frame
            frame_modes[mode] += 1
            frame_mode_body_sizes.setdefault(mode, []).append(len(body))
            body_first_bytes.setdefault(mode, Counter())

            if body:
                body_first_bytes[mode][body[:1].hex()] += 1

            if declared_size == len(body):
                frame_declared_size_matches += 1
            else:
                frame_declared_size_mismatches += 1

            if body == b"\x00":
                frame_mode_single_zero[mode] += 1

        if len(record.payload) < 2:
            continue

        signature = record.payload[:2].hex()
        format_group_sizes.setdefault(signature, []).append(
            len(record.payload)
        )

        if len(record.payload) == 4:
            format_group_four_byte[signature] += 1

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

    candidates_by_id = {
        record.record_id: candidates
        for record, candidates in candidate_records
    }

    selected: list[
        tuple[DecodedVoxelRecord, list[InnerLz4Candidate]]
    ] = []
    selected_ids: set[int] = set()

    def add_record(record: DecodedVoxelRecord) -> None:
        if len(selected) >= examples:
            return
        if record.record_id in selected_ids:
            return

        selected_ids.add(record.record_id)
        selected.append(
            (
                record,
                candidates_by_id.get(record.record_id, []),
            )
        )

    for record, _ in candidate_records:
        add_record(record)

    four_byte_seen: set[str] = set()
    for record in records:
        if len(record.payload) != 4:
            continue

        signature = record.payload.hex()
        if signature in four_byte_seen:
            continue

        four_byte_seen.add(signature)
        add_record(record)

    group_records: dict[str, list[DecodedVoxelRecord]] = {}
    for record in records:
        if len(record.payload) < 2:
            continue
        group_records.setdefault(
            record.payload[:2].hex(),
            [],
        ).append(record)

    for signature, group in sorted(
        group_records.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        if len(selected) >= examples:
            break

        group_by_size = sorted(
            group,
            key=lambda record: (
                len(record.payload),
                record.record_id,
            ),
        )

        add_record(group_by_size[0])
        if len(selected) >= examples:
            break

        add_record(group_by_size[-1])

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
        "frame": {
            "too_short": frame_too_short,
            "declared_size_matches": frame_declared_size_matches,
            "declared_size_mismatches": frame_declared_size_mismatches,
            "modes": {
                f"{mode:02x}": {
                    "count": count,
                    "min_body_size": min(frame_mode_body_sizes[mode]),
                    "max_body_size": max(frame_mode_body_sizes[mode]),
                    "avg_body_size": round(
                        sum(frame_mode_body_sizes[mode])
                        / len(frame_mode_body_sizes[mode]),
                        2,
                    ),
                    "single_zero_body_records": (
                        frame_mode_single_zero[mode]
                    ),
                    "body_first_bytes": dict(
                        body_first_bytes[mode].most_common(20)
                    ),
                }
                for mode, count in sorted(frame_modes.items())
            },
        },
        "format_groups": {
            signature: {
                "count": len(sizes),
                "min_size": min(sizes),
                "max_size": max(sizes),
                "avg_size": round(sum(sizes) / len(sizes), 2),
                "four_byte_records": format_group_four_byte[signature],
            }
            for signature, sizes in sorted(
                format_group_sizes.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
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