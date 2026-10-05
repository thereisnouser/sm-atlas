from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

from .database import SaveDatabase
from .terrain_decode import VOXELS_PER_CHUNK, decode_voxel_records


@dataclass(frozen=True)
class CodecResult:
    name: str
    mode: str
    records: int
    nontrivial_records: int
    exact_records: int
    exact_nontrivial_records: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "mode": self.mode,
            "records": self.records,
            "nontrivial_records": self.nontrivial_records,
            "exact_records": self.exact_records,
            "exact_nontrivial_records": self.exact_nontrivial_records,
            "exact_ratio": (
                round(self.exact_records / self.records, 4)
                if self.records
                else 0.0
            ),
            "exact_nontrivial_ratio": (
                round(
                    self.exact_nontrivial_records
                    / self.nontrivial_records,
                    4,
                )
                if self.nontrivial_records
                else 0.0
            ),
        }


def _pair_rle(
    body: bytes,
    *,
    count_first: bool,
    plus_one: bool,
    zero_means_256: bool,
) -> bool:
    if len(body) % 2:
        return False

    total = 0

    for offset in range(0, len(body), 2):
        a = body[offset]
        b = body[offset + 1]
        count = a if count_first else b

        if zero_means_256 and count == 0:
            count = 256
        elif plus_one:
            count += 1
        elif count == 0:
            return False

        total += count
        if total > VOXELS_PER_CHUNK:
            return False

    return total == VOXELS_PER_CHUNK


def _triple_rle(
    body: bytes,
    *,
    count_first: bool,
    endian: str,
    plus_one: bool,
) -> bool:
    if len(body) % 3:
        return False

    total = 0

    for offset in range(0, len(body), 3):
        if count_first:
            count_bytes = body[offset:offset + 2]
        else:
            count_bytes = body[offset + 1:offset + 3]

        count = int.from_bytes(count_bytes, endian)
        if plus_one:
            count += 1
        elif count == 0:
            return False

        total += count
        if total > VOXELS_PER_CHUNK:
            return False

    return total == VOXELS_PER_CHUNK


def _packbits(body: bytes) -> bool:
    index = 0
    output_size = 0

    while index < len(body):
        control = body[index]
        index += 1

        if control <= 127:
            count = control + 1
            if index + count > len(body):
                return False
            index += count
            output_size += count
        elif control == 128:
            continue
        else:
            count = 257 - control
            if index >= len(body):
                return False
            index += 1
            output_size += count

        if output_size > VOXELS_PER_CHUNK:
            return False

    return output_size == VOXELS_PER_CHUNK


def _highbit_rle(
    body: bytes,
    *,
    high_means_repeat: bool,
) -> bool:
    index = 0
    output_size = 0

    while index < len(body):
        control = body[index]
        index += 1
        is_high = bool(control & 0x80)
        count = (control & 0x7F) + 1
        is_repeat = is_high if high_means_repeat else not is_high

        if is_repeat:
            if index >= len(body):
                return False
            index += 1
        else:
            if index + count > len(body):
                return False
            index += count

        output_size += count
        if output_size > VOXELS_PER_CHUNK:
            return False

    return output_size == VOXELS_PER_CHUNK


def _run_sum(
    body: bytes,
    *,
    plus_one: bool,
    zero_means_256: bool,
) -> bool:
    total = 0

    for raw in body:
        if zero_means_256 and raw == 0:
            count = 256
        elif plus_one:
            count = raw + 1
        elif raw == 0:
            return False
        else:
            count = raw

        total += count
        if total > VOXELS_PER_CHUNK:
            return False

    return total == VOXELS_PER_CHUNK


def _build_codecs() -> list[tuple[str, Callable[[bytes], bool]]]:
    codecs: list[tuple[str, Callable[[bytes], bool]]] = []

    for count_first in (True, False):
        order = "count-value" if count_first else "value-count"

        codecs.append(
            (
                f"rle8/{order}/count",
                lambda body, cf=count_first: _pair_rle(
                    body,
                    count_first=cf,
                    plus_one=False,
                    zero_means_256=False,
                ),
            )
        )
        codecs.append(
            (
                f"rle8/{order}/count+1",
                lambda body, cf=count_first: _pair_rle(
                    body,
                    count_first=cf,
                    plus_one=True,
                    zero_means_256=False,
                ),
            )
        )
        codecs.append(
            (
                f"rle8/{order}/zero=256",
                lambda body, cf=count_first: _pair_rle(
                    body,
                    count_first=cf,
                    plus_one=False,
                    zero_means_256=True,
                ),
            )
        )

    for count_first in (True, False):
        order = "count-value" if count_first else "value-count"
        for endian in ("big", "little"):
            short = "be" if endian == "big" else "le"

            codecs.append(
                (
                    f"rle16{short}/{order}/count",
                    lambda body, cf=count_first, e=endian: _triple_rle(
                        body,
                        count_first=cf,
                        endian=e,
                        plus_one=False,
                    ),
                )
            )
            codecs.append(
                (
                    f"rle16{short}/{order}/count+1",
                    lambda body, cf=count_first, e=endian: _triple_rle(
                        body,
                        count_first=cf,
                        endian=e,
                        plus_one=True,
                    ),
                )
            )

    codecs.extend(
        [
            ("packbits", _packbits),
            (
                "highbit/1=repeat",
                lambda body: _highbit_rle(
                    body,
                    high_means_repeat=True,
                ),
            ),
            (
                "highbit/0=repeat",
                lambda body: _highbit_rle(
                    body,
                    high_means_repeat=False,
                ),
            ),
            (
                "run-sum/count",
                lambda body: _run_sum(
                    body,
                    plus_one=False,
                    zero_means_256=False,
                ),
            ),
            (
                "run-sum/count+1",
                lambda body: _run_sum(
                    body,
                    plus_one=True,
                    zero_means_256=False,
                ),
            ),
            (
                "run-sum/zero=256",
                lambda body: _run_sum(
                    body,
                    plus_one=False,
                    zero_means_256=True,
                ),
            ),
        ]
    )

    return codecs


def probe_voxel_codecs(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    max_body_offset: int = 4,
) -> dict[str, object]:
    if not 0 <= max_body_offset <= 16:
        raise ValueError("max_body_offset must be between 0 and 16")

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

        if declared != len(body):
            continue

        framed.append((mode, body))

    codecs = _build_codecs()
    results: list[CodecResult] = []

    for mode_filter in (None, 0x04, 0x05):
        selected = [
            body
            for mode, body in framed
            if mode_filter is None or mode == mode_filter
        ]
        nontrivial = [body for body in selected if len(body) > 1]

        for offset in range(max_body_offset + 1):
            offset_selected = [
                body[offset:]
                for body in selected
                if len(body) >= offset
            ]
            offset_nontrivial = [
                body[offset:]
                for body in nontrivial
                if len(body) >= offset
            ]

            for codec_name, decoder in codecs:
                exact = sum(
                    1
                    for body in offset_selected
                    if decoder(body)
                )
                exact_nontrivial = sum(
                    1
                    for body in offset_nontrivial
                    if decoder(body)
                )

                results.append(
                    CodecResult(
                        name=f"{codec_name}@+{offset}",
                        mode=(
                            "all"
                            if mode_filter is None
                            else f"{mode_filter:02x}"
                        ),
                        records=len(offset_selected),
                        nontrivial_records=len(offset_nontrivial),
                        exact_records=exact,
                        exact_nontrivial_records=exact_nontrivial,
                    )
                )

    results.sort(
        key=lambda result: (
            result.exact_nontrivial_records,
            result.exact_records,
        ),
        reverse=True,
    )

    body_byte_histograms: dict[str, dict[str, int]] = {}
    for mode in (0x04, 0x05):
        histogram: Counter[int] = Counter()
        for record_mode, body in framed:
            if record_mode == mode:
                histogram.update(body)

        body_byte_histograms[f"{mode:02x}"] = {
            f"{value:02x}": count
            for value, count in histogram.most_common(32)
        }

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(records),
        "decode_failures": dict(failures.most_common()),
        "framed_records": len(framed),
        "target_voxel_bytes": VOXELS_PER_CHUNK,
        "body_byte_histograms": body_byte_histograms,
        "models": [result.to_dict() for result in results],
    }
