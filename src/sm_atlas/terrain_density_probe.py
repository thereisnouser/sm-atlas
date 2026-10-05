from __future__ import annotations

from dataclasses import dataclass

from .database import SaveDatabase
from .terrain_decode import (
    VOXELS_PER_CHUNK_AXIS,
    DecodedVoxelRecord,
    decode_voxel_records,
)

DENSITY_BITS = 6
MAX_DENSITY = 63
FACE_SAMPLE_AXIS = tuple(range(0, VOXELS_PER_CHUNK_AXIS, 2))


@dataclass(frozen=True)
class DensityModelScore:
    mode: str
    byte_offset: int
    bit_offset: int
    bit_order: str
    fill: int
    face_pairs: int
    samples: int
    exact_samples: int
    active_samples: int
    active_exact_samples: int
    observed_samples: int
    observed_exact_samples: int
    observed_active_samples: int
    observed_active_exact_samples: int
    absolute_error: int
    active_absolute_error: int
    observed_absolute_error: int
    observed_active_absolute_error: int

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    @staticmethod
    def _mae(error: int, samples: int) -> float:
        return round(error / samples, 4) if samples else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "byte_offset": self.byte_offset,
            "bit_offset": self.bit_offset,
            "bit_order": self.bit_order,
            "fill": self.fill,
            "face_pairs": self.face_pairs,
            "samples": self.samples,
            "exact_samples": self.exact_samples,
            "exact_ratio": self._ratio(
                self.exact_samples,
                self.samples,
            ),
            "active_samples": self.active_samples,
            "active_exact_samples": self.active_exact_samples,
            "active_exact_ratio": self._ratio(
                self.active_exact_samples,
                self.active_samples,
            ),
            "observed_samples": self.observed_samples,
            "observed_exact_samples": self.observed_exact_samples,
            "observed_exact_ratio": self._ratio(
                self.observed_exact_samples,
                self.observed_samples,
            ),
            "observed_active_samples": self.observed_active_samples,
            "observed_active_exact_samples": (
                self.observed_active_exact_samples
            ),
            "observed_active_exact_ratio": self._ratio(
                self.observed_active_exact_samples,
                self.observed_active_samples,
            ),
            "mean_absolute_error": self._mae(
                self.absolute_error,
                self.samples,
            ),
            "active_mean_absolute_error": self._mae(
                self.active_absolute_error,
                self.active_samples,
            ),
            "observed_mean_absolute_error": self._mae(
                self.observed_absolute_error,
                self.observed_samples,
            ),
            "observed_active_mean_absolute_error": self._mae(
                self.observed_active_absolute_error,
                self.observed_active_samples,
            ),
            "observed_coverage": self._ratio(
                self.observed_samples,
                self.samples,
            ),
        }


def _voxel_index(x: int, y: int, z: int) -> int:
    axis = VOXELS_PER_CHUNK_AXIS
    return z + axis * y + axis * axis * x


def _read_density(
    body: bytes,
    *,
    voxel_index: int,
    byte_offset: int,
    bit_offset: int,
    bit_order: str,
    fill: int,
) -> tuple[int, bool]:
    start_bit = (
        byte_offset * 8
        + bit_offset
        + voxel_index * DENSITY_BITS
    )
    end_bit = start_bit + DENSITY_BITS

    if end_bit > len(body) * 8:
        return fill, False

    value = 0

    if bit_order == "msb":
        for bit_index in range(start_bit, end_bit):
            byte = body[bit_index // 8]
            shift = 7 - (bit_index % 8)
            value = (value << 1) | ((byte >> shift) & 1)
    elif bit_order == "lsb":
        for bit_index in range(start_bit, end_bit):
            byte = body[bit_index // 8]
            shift = bit_index % 8
            value |= ((byte >> shift) & 1) << (bit_index - start_bit)
    else:
        raise ValueError(f"unsupported bit order: {bit_order}")

    return value, True


def _face_indices(axis: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    edge = VOXELS_PER_CHUNK_AXIS - 1

    if axis == "x":
        for y in FACE_SAMPLE_AXIS:
            for z in FACE_SAMPLE_AXIS:
                pairs.append(
                    (
                        _voxel_index(edge, y, z),
                        _voxel_index(0, y, z),
                    )
                )
    elif axis == "y":
        for x in FACE_SAMPLE_AXIS:
            for z in FACE_SAMPLE_AXIS:
                pairs.append(
                    (
                        _voxel_index(x, edge, z),
                        _voxel_index(x, 0, z),
                    )
                )
    elif axis == "z":
        for x in FACE_SAMPLE_AXIS:
            for y in FACE_SAMPLE_AXIS:
                pairs.append(
                    (
                        _voxel_index(x, y, edge),
                        _voxel_index(x, y, 0),
                    )
                )
    else:
        raise ValueError(f"unsupported axis: {axis}")

    return pairs


FACE_INDICES = {
    axis: _face_indices(axis)
    for axis in ("x", "y", "z")
}


def _framed_body(
    record: DecodedVoxelRecord,
) -> tuple[int, bytes] | None:
    if len(record.payload) < 3:
        return None

    mode = record.payload[0]
    declared_size = int.from_bytes(record.payload[1:3], "big")
    body = record.payload[3:]

    if declared_size != len(body):
        return None

    return mode, body


def _neighbor_pairs(
    records: list[DecodedVoxelRecord],
    *,
    mode_filter: int,
    max_pairs: int,
) -> list[tuple[str, bytes, bytes]]:
    by_coordinate = {
        record.coordinate: record
        for record in records
    }

    result: list[tuple[str, bytes, bytes]] = []

    for record in records:
        framed = _framed_body(record)
        if framed is None or framed[0] != mode_filter:
            continue

        x, y, z = record.coordinate

        for axis, neighbor_coordinate in (
            ("x", (x + 1, y, z)),
            ("y", (x, y + 1, z)),
            ("z", (x, y, z + 1)),
        ):
            neighbor = by_coordinate.get(neighbor_coordinate)
            if neighbor is None:
                continue

            neighbor_framed = _framed_body(neighbor)
            if (
                neighbor_framed is None
                or neighbor_framed[0] != mode_filter
            ):
                continue

            result.append(
                (
                    axis,
                    framed[1],
                    neighbor_framed[1],
                )
            )

            if len(result) >= max_pairs:
                return result

    return result


def probe_density_streams(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    max_byte_offset: int = 4,
    max_pairs: int = 600,
) -> dict[str, object]:
    if not 0 <= max_byte_offset <= 16:
        raise ValueError("max_byte_offset must be between 0 and 16")
    if not 1 <= max_pairs <= 5000:
        raise ValueError("max_pairs must be between 1 and 5000")

    records, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    scores: list[DensityModelScore] = []
    pair_counts: dict[str, int] = {}

    for mode in (0x04, 0x05):
        pairs = _neighbor_pairs(
            records,
            mode_filter=mode,
            max_pairs=max_pairs,
        )
        pair_counts[f"{mode:02x}"] = len(pairs)

        for byte_offset in range(max_byte_offset + 1):
            for bit_offset in range(DENSITY_BITS):
                for bit_order in ("msb", "lsb"):
                    for fill in (0, MAX_DENSITY):
                        samples = 0
                        exact_samples = 0
                        active_samples = 0
                        active_exact_samples = 0
                        observed_samples = 0
                        observed_exact_samples = 0
                        observed_active_samples = 0
                        observed_active_exact_samples = 0
                        absolute_error = 0
                        active_absolute_error = 0
                        observed_absolute_error = 0
                        observed_active_absolute_error = 0

                        for axis, left_body, right_body in pairs:
                            for (
                                left_index,
                                right_index,
                            ) in FACE_INDICES[axis]:
                                left, left_observed = _read_density(
                                    left_body,
                                    voxel_index=left_index,
                                    byte_offset=byte_offset,
                                    bit_offset=bit_offset,
                                    bit_order=bit_order,
                                    fill=fill,
                                )
                                right, right_observed = _read_density(
                                    right_body,
                                    voxel_index=right_index,
                                    byte_offset=byte_offset,
                                    bit_offset=bit_offset,
                                    bit_order=bit_order,
                                    fill=fill,
                                )

                                samples += 1
                                error = abs(left - right)
                                absolute_error += error
                                exact = left == right

                                if exact:
                                    exact_samples += 1

                                active = left != 0 or right != 0
                                if active:
                                    active_samples += 1
                                    active_absolute_error += error
                                    if exact:
                                        active_exact_samples += 1

                                observed = (
                                    left_observed
                                    and right_observed
                                )
                                if observed:
                                    observed_samples += 1
                                    observed_absolute_error += error
                                    if exact:
                                        observed_exact_samples += 1

                                    if active:
                                        observed_active_samples += 1
                                        observed_active_absolute_error += (
                                            error
                                        )
                                        if exact:
                                            observed_active_exact_samples += 1

                        scores.append(
                            DensityModelScore(
                                mode=f"{mode:02x}",
                                byte_offset=byte_offset,
                                bit_offset=bit_offset,
                                bit_order=bit_order,
                                fill=fill,
                                face_pairs=len(pairs),
                                samples=samples,
                                exact_samples=exact_samples,
                                active_samples=active_samples,
                                active_exact_samples=active_exact_samples,
                                observed_samples=observed_samples,
                                observed_exact_samples=observed_exact_samples,
                                observed_active_samples=observed_active_samples,
                                observed_active_exact_samples=(
                                    observed_active_exact_samples
                                ),
                                absolute_error=absolute_error,
                                active_absolute_error=active_absolute_error,
                                observed_absolute_error=observed_absolute_error,
                                observed_active_absolute_error=(
                                    observed_active_absolute_error
                                ),
                            )
                        )

    scores.sort(
        key=lambda score: (
            score.observed_active_samples >= 100,
            (
                score.observed_active_exact_samples
                / score.observed_active_samples
                if score.observed_active_samples
                else 0.0
            ),
            score.observed_active_samples,
            (
                score.observed_exact_samples
                / score.observed_samples
                if score.observed_samples
                else 0.0
            ),
        ),
        reverse=True,
    )

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(records),
        "decode_failures": dict(failures.most_common()),
        "density_bits": DENSITY_BITS,
        "voxel_order": "z + 17*y + 17^2*x",
        "face_sample_axis": list(FACE_SAMPLE_AXIS),
        "neighbor_pairs": pair_counts,
        "models": [score.to_dict() for score in scores],
    }
