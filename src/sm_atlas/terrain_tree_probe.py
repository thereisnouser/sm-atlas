from __future__ import annotations

from collections import Counter

from .database import SaveDatabase
from .terrain_decode import decode_voxel_records


def _parse_mask_tree(
    body: bytes,
    *,
    max_depth: int,
    one_means_child: bool,
) -> tuple[bool, int, int]:
    index = 0
    nodes = 0
    leaves = 0

    def parse_node(depth: int) -> bool:
        nonlocal index, nodes, leaves

        if index >= len(body):
            return False

        mask = body[index]
        index += 1
        nodes += 1

        if depth >= max_depth:
            leaves += 1
            return True

        child_mask = mask if one_means_child else (~mask & 0xFF)
        child_count = child_mask.bit_count()

        if child_count == 0:
            leaves += 1
            return True

        for _ in range(child_count):
            if not parse_node(depth + 1):
                return False

        return True

    valid = parse_node(0)
    return valid and index == len(body), nodes, leaves


def probe_voxel_tree_encoding(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    max_depth: int = 6,
) -> dict[str, object]:
    if not 1 <= max_depth <= 8:
        raise ValueError("max_depth must be between 1 and 8")

    records, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    models: list[dict[str, object]] = []

    for mode_filter in (None, 0x04, 0x05):
        selected = [
            record
            for record in records
            if (
                len(record.payload) >= 3
                and (
                    mode_filter is None
                    or record.payload[0] == mode_filter
                )
            )
        ]

        for depth in range(1, max_depth + 1):
            for one_means_child in (True, False):
                exact = 0
                exact_nontrivial = 0
                total_nontrivial = 0
                node_counts: Counter[int] = Counter()
                leaf_counts: Counter[int] = Counter()

                for record in selected:
                    body = record.payload[3:]
                    if len(body) > 1:
                        total_nontrivial += 1

                    ok, nodes, leaves = _parse_mask_tree(
                        body,
                        max_depth=depth,
                        one_means_child=one_means_child,
                    )

                    if not ok:
                        continue

                    exact += 1
                    node_counts[nodes] += 1
                    leaf_counts[leaves] += 1

                    if len(body) > 1:
                        exact_nontrivial += 1

                models.append(
                    {
                        "mode": (
                            "all"
                            if mode_filter is None
                            else f"{mode_filter:02x}"
                        ),
                        "depth": depth,
                        "one_means_child": one_means_child,
                        "records": len(selected),
                        "nontrivial_records": total_nontrivial,
                        "exact_records": exact,
                        "exact_nontrivial_records": exact_nontrivial,
                        "exact_ratio": (
                            round(exact / len(selected), 4)
                            if selected
                            else 0.0
                        ),
                        "exact_nontrivial_ratio": (
                            round(
                                exact_nontrivial
                                / total_nontrivial,
                                4,
                            )
                            if total_nontrivial
                            else 0.0
                        ),
                        "node_count_range": (
                            {
                                "min": min(node_counts),
                                "max": max(node_counts),
                            }
                            if node_counts
                            else None
                        ),
                        "leaf_count_range": (
                            {
                                "min": min(leaf_counts),
                                "max": max(leaf_counts),
                            }
                            if leaf_counts
                            else None
                        ),
                    }
                )

    models.sort(
        key=lambda model: (
            model["exact_nontrivial_ratio"],
            model["exact_ratio"],
            model["exact_nontrivial_records"],
        ),
        reverse=True,
    )

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(records),
        "decode_failures": dict(failures.most_common()),
        "models": models,
    }
