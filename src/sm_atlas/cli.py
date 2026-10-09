from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .database import InvalidSaveFile, SaveDatabase
from .portals import (
    compare_portal_payloads,
    probe_portals,
    summarize_portal_probe,
)
from .discovery import find_survival_saves
from .terrain import summarize_voxel_terrain
from .terrain_chunks import summarize_voxel_chunks
from .terrain_codec_probe import probe_voxel_codecs
from .terrain_decode import probe_decompressed_voxel_terrain
from .terrain_data import decode_terrain_data_candidates
from .terrain_data_probe import probe_terrain_script_data
from .terrain_data_structure import probe_terrain_data_structure
from .terrain_density_probe import probe_density_streams
from .terrain_layout import scan_voxel_terrain_layout
from .terrain_map import write_voxel_chunk_map
from .terrain_mask_probe import probe_voxel_masks
from .terrain_payload import probe_voxel_payloads
from .terrain_probe import probe_voxel_terrain
from .terrain_structure import probe_voxel_terrain_structure
from .terrain_tree_probe import probe_voxel_tree_encoding
from .tile_file import (
    InvalidTileFile,
    probe_tile,
    probe_tile_chunks,
    probe_tile_nodes,
    probe_tile_voxels,
)
from .tile_voxel_space import probe_tile_voxel_space
from .tile_objects import (
    probe_tile_objects,
    placements_near_candidate_route,
)
from .tile_voxel_walk import probe_tile_voxel_walk
from .tile_world import probe_tile_world
from .ground_truth import render_ground_probe_lua, compare_ground_observations
from .ground_hook import survival_hook_operation, load_portal_entrance
from .ground_density import inspect_ground_density
from .ground_hypotheses import compare_trilinear_hypotheses
from .ground_slope_audit import audit_ground_slopes
from .ground_byte_audit import audit_ground_voxel_bytes
from .ground_isovalue_audit import audit_observed_isovalues
from .ground_normal_field_audit import audit_ground_field_normals
from .underground_graph import build_underground_graph
from .underground_layout import summarize_underground_layout
from .underground_map import (
    write_underground_map,
    write_underground_route_map,
)
from .underground_navigation import build_navigation_candidate_graph
from .underground_portals import (
    summarize_saved_tunnel_portals,
    summarize_underground_node,
)
from .underground_routes import find_transit_route
from .underground_tile_catalog import summarize_underground_tiles
from .underground_topology import build_layout_topology
from .underground_tunnels import summarize_underground_tunnels
from .world_graph import build_world_graph
from .worlds import WorldDataError, discover_worlds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sm-atlas",
        description="Inspect Scrap Mechanic save files.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    saves_parser = subparsers.add_parser(
        "saves",
        help="Find local Survival saves.",
    )
    saves_parser.add_argument(
        "--root",
        type=Path,
        help="Override the Scrap Mechanic User directory.",
    )
    saves_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a save database.",
    )
    inspect_parser.add_argument("save", type=Path)
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    worlds_parser = subparsers.add_parser(
        "worlds",
        help="Discover worlds stored in GenericData.",
    )
    worlds_parser.add_argument("save", type=Path)
    worlds_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    graph_parser = subparsers.add_parser(
        "graph",
        help="Show portal connections between worlds.",
    )
    graph_parser.add_argument("save", type=Path)
    graph_parser.add_argument(
        "--underground",
        action="store_true",
        help="Only show connections touching an Underground world.",
    )
    graph_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tile_probe_parser = subparsers.add_parser(
        "tile-probe",
        help="Inspect a Scrap Mechanic .tile header and chunk inventory.",
    )
    tile_probe_parser.add_argument("tile", type=Path)
    tile_probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tile_nodes_parser = subparsers.add_parser(
        "tile-nodes",
        help="Decode TUNNEL node sockets from a Scrap Mechanic .tile file.",
    )
    tile_nodes_parser.add_argument("tile", type=Path)
    tile_nodes_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tile_voxel_probe_parser = subparsers.add_parser(
        "tile-voxel-probe",
        help="Inspect fixed-size voxel terrain records from a .tile file.",
    )
    tile_voxel_probe_parser.add_argument("tile", type=Path)
    tile_voxel_probe_parser.add_argument(
        "--cell",
        type=int,
        help="Only inspect one tile cell.",
    )
    tile_voxel_probe_parser.add_argument(
        "--examples",
        type=int,
        default=20,
        help="Number of voxel records to print per chunk.",
    )
    tile_voxel_probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tile_world_parser = subparsers.add_parser(
        "tile-world-probe",
        help="Map local .tile sockets into a saved underground world instance.",
    )
    tile_world_parser.add_argument("save", type=Path)
    tile_world_parser.add_argument("tile", type=Path)
    tile_world_parser.add_argument("--world", type=int, required=True)
    tile_world_parser.add_argument(
        "--node", type=int, required=True,
        help="Layout node ID of this exact tile instance, e.g. 322.",
    )
    tile_world_parser.add_argument(
        "--edge", nargs=2, metavar=("FROM_XYZ", "TO_XYZ"),
        help="Optional adjacent local foot voxels (e.g. 4,35,19 3,35,20).",
    )
    tile_world_parser.add_argument(
        "--density-bits", type=int, choices=(4, 5), default=5,
    )
    tile_world_parser.add_argument(
        "--match-tolerance", type=float, default=1.0,
        help="Max residual in metres to match saved tunnels to sockets.",
    )
    tile_world_parser.add_argument("--json", action="store_true")
    tile_world_parser.add_argument(
        "--output", type=Path,
        help="Write JSON plan as UTF-8 instead of shell redirection (requires --json).",
    )

    ground_lua_parser = subparsers.add_parser(
        "tile-ground-lua",
        help="Generate non-installed Lua raycast fragment from tile-world-probe JSON.",
    )
    ground_lua_parser.add_argument("plan", type=Path)
    ground_lua_parser.add_argument("--output", type=Path, required=True)

    ground_hook_parser = subparsers.add_parser(
        "tile-ground-survival",
        help="Preview or explicitly install/remove one-shot Survival Lua hook.",
    )
    ground_hook_parser.add_argument("plan", type=Path)
    ground_hook_parser.add_argument("game_script", type=Path)
    ground_hook_parser.add_argument(
        "--lua", type=Path, required=True,
        help="Exact atlas_ground_probe.lua generated from this plan.",
    )
    ground_hook_parser.add_argument(
        "--navigation-save", type=Path,
        help="Read-only save to resolve a verified portal approach position.",
    )
    ground_hook_parser.add_argument(
        "--portal-id", type=int,
        help="Saved portal ID to navigate to before entering the target world.",
    )
    ground_action = ground_hook_parser.add_mutually_exclusive_group()
    ground_action.add_argument(
        "--install", action="store_true",
        help="Back up and patch the local SurvivalGame.lua (close game first).",
    )
    ground_action.add_argument(
        "--remove", action="store_true",
        help="Back up and remove only the marked SM Atlas block.",
    )

    ground_compare_parser = subparsers.add_parser(
        "tile-ground-compare",
        help="Compare logged in-game terrain raycasts to the saved-world plan.",
    )
    ground_compare_parser.add_argument("plan", type=Path)
    ground_compare_parser.add_argument("log", type=Path)
    ground_compare_parser.add_argument("--json", action="store_true")

    ground_profile_parser = subparsers.add_parser(
        "tile-ground-profile",
        help="Read-only raw tile voxel columns beside logged game ground hits.",
    )
    ground_profile_parser.add_argument("plan", type=Path)
    ground_profile_parser.add_argument("log", type=Path)
    ground_profile_parser.add_argument("tile", type=Path)
    ground_profile_parser.add_argument("--z-margin", type=int, default=3)
    ground_profile_parser.add_argument("--json", action="store_true")

    ground_hypotheses_parser = subparsers.add_parser(
        "tile-ground-hypotheses",
        help="Read-only comparison of 4/5-bit trilinear surface hypotheses.",
    )
    ground_hypotheses_parser.add_argument("plan", type=Path)
    ground_hypotheses_parser.add_argument("log", type=Path)
    ground_hypotheses_parser.add_argument("tile", type=Path)
    ground_hypotheses_parser.add_argument("--json", action="store_true")
    ground_hypotheses_parser.add_argument(
        "--include-6-bit", action="store_true",
        help="Opt in to a separate unverified 6-bit voxel-byte hypothesis.",
    )

    byte_audit_parser = subparsers.add_parser(
        "tile-ground-byte-audit",
        help="Inspect raw voxel bytes next to verified in-game ground heights.",
    )
    byte_audit_parser.add_argument("plan", type=Path)
    byte_audit_parser.add_argument("log", type=Path)
    byte_audit_parser.add_argument("tile", type=Path)
    byte_audit_parser.add_argument(
        "--radius", type=int, default=1,
        help="Extra nearby voxel columns in XY (0..3, default=1).",
    )
    byte_audit_parser.add_argument("--json", action="store_true")

    isovalue_parser = subparsers.add_parser(
        "tile-ground-isovalue-audit",
        help="Check interpolated byte densities at real game-hit positions.",
    )
    isovalue_parser.add_argument("plan", type=Path)
    isovalue_parser.add_argument("log", type=Path)
    isovalue_parser.add_argument("tile", type=Path)
    isovalue_parser.add_argument("--include-6-bit", action="store_true")
    isovalue_parser.add_argument("--json", action="store_true")

    normals_parser = subparsers.add_parser(
        "tile-ground-normal-audit",
        help="Compare modeled raw-density gradients against in-game surface normals.",
    )
    normals_parser.add_argument("plan", type=Path)
    normals_parser.add_argument("log", type=Path)
    normals_parser.add_argument("tile", type=Path)
    normals_parser.add_argument("--include-6-bit", action="store_true")
    normals_parser.add_argument("--json", action="store_true")

    slope_audit_parser = subparsers.add_parser(
        "tile-ground-slope-audit",
        help="Corroborate raycast slopes with normals and rank modelled rises.",
    )
    slope_audit_parser.add_argument("plan", type=Path)
    slope_audit_parser.add_argument("log", type=Path)
    slope_audit_parser.add_argument("tile", type=Path)
    slope_audit_parser.add_argument("--json", action="store_true")
    slope_audit_parser.add_argument(
        "--include-6-bit", action="store_true",
        help="Also compare 8 unverified 6-bit density hypotheses (24 total).",
    )

    tile_voxel_space_parser = subparsers.add_parser(
        "tile-voxel-space",
        help="Find candidate connected voids and classify tile tunnel sockets.",
    )
    tile_voxel_space_parser.add_argument("tile", type=Path)
    tile_voxel_space_parser.add_argument(
        "--density-bits", type=int, choices=(4, 5), default=4,
        help="Experimental density-bit hypothesis (default=4 legacy).",
    )
    tile_voxel_space_parser.add_argument(
        "--density-threshold", type=int, default=None,
        help="Candidate void cutoff (default=half of selected density range).",
    )
    tile_voxel_space_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tile_object_parser = subparsers.add_parser(
        "tile-object-probe",
        help="Inspect placement transforms and UUIDs in tile object chunks.",
    )
    tile_object_parser.add_argument("tile", type=Path)
    tile_object_parser.add_argument(
        "--examples", type=int, default=12,
        help="Number of object placements to print.",
    )
    tile_object_parser.add_argument(
        "--json", action="store_true",
        help="Print full placement inventory as JSON.",
    )
    tile_object_parser.add_argument(
        "--from-socket",
        help="Optional socket at start of candidate route.",
    )
    tile_object_parser.add_argument(
        "--to-socket",
        help="Optional socket at end of candidate route.",
    )
    tile_object_parser.add_argument(
        "--radius",
        type=float,
        default=5.0,
        help="Distance from placement origin to candidate footpath (metres).",
    )
    tile_object_parser.add_argument(
        "--density-bits", type=int, choices=(4, 5), default=4,
        help="Candidate density model for route proximity (default=4 legacy).",
    )

    tile_voxel_walk_parser = subparsers.add_parser(
        "tile-voxel-walk",
        help="Experimental floor/headroom candidate routes inside a tile.",
    )
    tile_voxel_walk_parser.add_argument("tile", type=Path)
    tile_voxel_walk_parser.add_argument(
        "--from-socket",
        help="Starting socket identifier, e.g. cell0:node7.",
    )
    tile_voxel_walk_parser.add_argument(
        "--to-socket",
        help="Destination socket identifier, e.g. cell0:node6.",
    )
    tile_voxel_walk_parser.add_argument(
        "--density-bits", type=int, choices=(4, 5), default=4,
        help="Experimental density-bit hypothesis (default=4 legacy).",
    )
    tile_voxel_walk_parser.add_argument(
        "--density-threshold", type=int, default=None,
        help="Candidate void cutoff (default=half of selected density range).",
    )
    tile_voxel_walk_parser.add_argument(
        "--headroom",
        type=int,
        default=2,
        help="Required clear vertical voxel cells above the floor.",
    )
    tile_voxel_walk_parser.add_argument(
        "--socket-radius",
        type=float,
        default=5.0,
        help="Maximum distance from socket to selected major floor (m).",
    )
    tile_voxel_walk_parser.add_argument(
        "--max-surface-gradient",
        type=float,
        default=None,
        help="EXPERIMENTAL: separately check candidate path with a maximum "
             "density-isosurface height change per horizontal metre.",
    )
    tile_voxel_walk_parser.add_argument(
        "--max-step",
        type=int,
        default=1,
        help="Maximum allowed elevation change per horizontal voxel (0..2).",
    )
    tile_voxel_walk_parser.add_argument(
        "--json",
        action="store_true",
        help="Print full route and results as machine-readable JSON.",
    )
    tile_voxel_walk_parser.add_argument(
        "--elevation-details",
        action="store_true",
        help="Show position and support-density data for every rise/drop.",
    )

    tile_chunk_probe_parser = subparsers.add_parser(
        "tile-chunk-probe",
        help="Decompress and inspect selected chunks from a .tile file.",
    )
    tile_chunk_probe_parser.add_argument("tile", type=Path)
    tile_chunk_probe_parser.add_argument(
        "--kind",
        required=True,
        help="Chunk kind to inspect, for example node or voxel_terrain.",
    )
    tile_chunk_probe_parser.add_argument(
        "--cell",
        type=int,
        help="Only inspect chunks belonging to one cell index.",
    )
    tile_chunk_probe_parser.add_argument(
        "--full-hex",
        action="store_true",
        help="Include the full decompressed chunk as hex.",
    )
    tile_chunk_probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    portal_probe_parser = subparsers.add_parser(
        "portal-probe",
        help="Inspect raw Portal rows and probe the serialized portal blob.",
    )
    portal_probe_parser.add_argument("save", type=Path)
    portal_probe_parser.add_argument(
        "--world",
        type=int,
        help="Only portals touching this world ID.",
    )
    portal_probe_parser.add_argument(
        "--id",
        type=int,
        dest="portal_id",
        help="Only inspect a specific portal ID.",
    )
    portal_probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    portal_compare_parser = subparsers.add_parser(
        "portal-compare",
        help="Compare serialized portal payloads sharing the same world/cell side.",
    )
    portal_compare_parser.add_argument("save", type=Path)
    portal_compare_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID used for grouping.",
    )
    portal_compare_parser.add_argument(
        "--side",
        choices=("a", "b"),
        default="a",
        help="Portal side to group by (default: a).",
    )
    portal_compare_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    terrain_parser = subparsers.add_parser(
        "terrain",
        help="Summarize saved voxel terrain by world.",
    )
    terrain_parser.add_argument("save", type=Path)
    terrain_parser.add_argument(
        "--underground",
        action="store_true",
        help="Only show Underground worlds.",
    )
    terrain_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    probe_parser = subparsers.add_parser(
        "terrain-probe",
        help="Probe VoxelTerrain blobs for embedded LZ4 voxel chunks.",
    )
    probe_parser.add_argument("save", type=Path)
    probe_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    probe_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum records to scan (1-5000).",
    )
    probe_parser.add_argument(
        "--max-offset",
        type=int,
        default=96,
        help="Maximum blob offset to test for an LZ4 block.",
    )
    probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    structure_parser = subparsers.add_parser(
        "terrain-structure",
        help="Probe VoxelTerrain record structure and candidate chunk coordinates.",
    )
    structure_parser.add_argument("save", type=Path)
    structure_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    structure_parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum records to scan (1-5000).",
    )
    structure_parser.add_argument(
        "--examples",
        type=int,
        default=30,
        help="Maximum example records to include (0-200).",
    )
    structure_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    layout_parser = subparsers.add_parser(
        "terrain-layout",
        help="Scan VoxelTerrain blobs for coordinate layout candidates.",
    )
    layout_parser.add_argument("save", type=Path)
    layout_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    layout_parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum records to scan (1-5000).",
    )
    layout_parser.add_argument(
        "--min-offset",
        type=int,
        default=8,
        help="Minimum offset relative to the embedded record ID.",
    )
    layout_parser.add_argument(
        "--max-offset",
        type=int,
        default=64,
        help="Maximum offset relative to the embedded record ID.",
    )
    layout_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of highest-scoring layouts to show.",
    )
    layout_parser.add_argument(
        "--z-limit",
        type=int,
        default=128,
        help="Absolute Z value considered plausible.",
    )
    layout_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    chunks_parser = subparsers.add_parser(
        "terrain-chunks",
        help="Decode confident voxel chunk coordinates from save records.",
    )
    chunks_parser.add_argument("save", type=Path)
    chunks_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    chunks_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    chunks_parser.add_argument(
        "--examples",
        type=int,
        default=25,
        help="Maximum decoded records to include (0-200).",
    )
    chunks_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    map_parser = subparsers.add_parser(
        "terrain-map",
        help="Render decoded voxel chunk occupancy as SVG slices.",
    )
    map_parser.add_argument("save", type=Path)
    map_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to render.",
    )
    map_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="SVG output path.",
    )
    map_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )

    decode_parser = subparsers.add_parser(
        "terrain-decode",
        help="Decompress VoxelTerrain records and validate voxel chunk layout.",
    )
    decode_parser.add_argument("save", type=Path)
    decode_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    decode_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    decode_parser.add_argument(
        "--examples",
        type=int,
        default=10,
        help="Maximum decoded records to include (0-100).",
    )
    decode_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    payload_parser = subparsers.add_parser(
        "terrain-payload",
        help="Inspect the variable payload inside decompressed voxel records.",
    )
    payload_parser.add_argument("save", type=Path)
    payload_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    payload_parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum records to scan (1-5000).",
    )
    payload_parser.add_argument(
        "--max-offset",
        type=int,
        default=16,
        help="Maximum payload offset to test for an inner LZ4 block.",
    )
    payload_parser.add_argument(
        "--examples",
        type=int,
        default=20,
        help="Maximum example payloads to include (0-100).",
    )
    payload_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    tree_parser = subparsers.add_parser(
        "terrain-tree-probe",
        help="Test recursive 8-way mask-tree hypotheses for voxel payload bodies.",
    )
    tree_parser.add_argument("save", type=Path)
    tree_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    tree_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    tree_parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Maximum recursive depth to test (1-8).",
    )
    tree_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of best-scoring models to print.",
    )
    tree_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    codec_parser = subparsers.add_parser(
        "terrain-codec-probe",
        help="Test common RLE and PackBits hypotheses for voxel bodies.",
    )
    codec_parser.add_argument("save", type=Path)
    codec_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    codec_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    codec_parser.add_argument(
        "--max-body-offset",
        type=int,
        default=4,
        help="Maximum body prefix length to skip while testing codecs.",
    )
    codec_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of best-scoring codec models to print.",
    )
    codec_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    mask_parser = subparsers.add_parser(
        "terrain-mask-probe",
        help="Test sparse bitmask and packed-value hypotheses for voxel bodies.",
    )
    mask_parser.add_argument("save", type=Path)
    mask_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    mask_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    mask_parser.add_argument(
        "--max-offset",
        type=int,
        default=8,
        help="Maximum body prefix length to skip before a 4913-bit mask.",
    )
    mask_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of best-scoring mask models to print.",
    )
    mask_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    density_parser = subparsers.add_parser(
        "terrain-density-probe",
        help="Test packed 6-bit density streams using shared chunk faces.",
    )
    density_parser.add_argument("save", type=Path)
    density_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    density_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    density_parser.add_argument(
        "--max-byte-offset",
        type=int,
        default=4,
        help="Maximum body byte prefix to skip before density bits.",
    )
    density_parser.add_argument(
        "--max-pairs",
        type=int,
        default=600,
        help="Maximum neighboring chunk-face pairs to compare per mode.",
    )
    density_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of best-scoring density models to print.",
    )
    density_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    data_parser = subparsers.add_parser(
        "terrain-data-probe",
        help="Find LZ4-wrapped LUA terrain data in ScriptData.",
    )
    data_parser.add_argument("save", type=Path)
    data_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    data_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    data_parser.add_argument(
        "--examples",
        type=int,
        default=20,
        help="Maximum decoded rows to print (0-100).",
    )
    data_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    terrain_data_parser = subparsers.add_parser(
        "terrain-data",
        help="Decode saved LUA terrain tables from ScriptData.",
    )
    terrain_data_parser.add_argument("save", type=Path)
    terrain_data_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    terrain_data_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    terrain_data_parser.add_argument(
        "--examples",
        type=int,
        default=10,
        help="Maximum terrain candidates to print (0-100).",
    )
    terrain_data_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    terrain_structure_parser = subparsers.add_parser(
        "terrain-data-structure",
        help="Inspect nested shapes inside the saved terrain LUA table.",
    )
    terrain_structure_parser.add_argument("save", type=Path)
    terrain_structure_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    terrain_structure_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    terrain_structure_parser.add_argument(
        "--examples",
        type=int,
        default=3,
        help="Examples to show per terrain field (0-20).",
    )
    terrain_structure_parser.add_argument(
        "--depth",
        type=int,
        default=4,
        help="Maximum nested preview depth (1-8).",
    )
    terrain_structure_parser.add_argument(
        "--max-items",
        type=int,
        default=8,
        help="Maximum items per previewed table (1-50).",
    )
    terrain_structure_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_parser = subparsers.add_parser(
        "underground-tunnels",
        help="Summarize saved underground tunnel polylines.",
    )
    underground_parser.add_argument("save", type=Path)
    underground_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_map_parser = subparsers.add_parser(
        "underground-map",
        help="Render saved underground tunnel polylines as SVG.",
    )
    underground_map_parser.add_argument("save", type=Path)
    underground_map_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to render.",
    )
    underground_map_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="SVG output path.",
    )
    underground_map_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )

    underground_graph_parser = subparsers.add_parser(
        "underground-graph",
        help="Build a conservative 3D connectivity graph for an underground world.",
    )
    underground_graph_parser.add_argument("save", type=Path)
    underground_graph_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_graph_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_graph_parser.add_argument(
        "--region-tolerance",
        type=float,
        default=4.0,
        help="Maximum 3D endpoint/spawner distance to a region in meters.",
    )
    underground_graph_parser.add_argument(
        "--endpoint-tolerance",
        type=float,
        default=6.0,
        help="Maximum 3D distance for clustering free tunnel endpoints.",
    )
    underground_graph_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of highest-degree graph nodes to show.",
    )
    underground_graph_parser.add_argument(
        "--json",
        action="store_true",
        help="Print full machine-readable graph JSON.",
    )

    underground_tiles_parser = subparsers.add_parser(
        "underground-tiles",
        help="Resolve underground tile UUIDs to semantic tile names.",
    )
    underground_tiles_parser.add_argument("save", type=Path)
    underground_tiles_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_tiles_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_tiles_parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Number of most-used tile placements to show (1-200).",
    )
    underground_tiles_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_layout_parser = subparsers.add_parser(
        "underground-layout",
        help="Reconstruct logical underground structures and validate tile dimensions.",
    )
    underground_layout_parser.add_argument("save", type=Path)
    underground_layout_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_layout_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_layout_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_topology_parser = subparsers.add_parser(
        "underground-topology",
        help="Build a 3D face-contact graph of reconstructed underground tiles.",
    )
    underground_topology_parser.add_argument("save", type=Path)
    underground_topology_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_topology_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_topology_parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of highest-degree layout nodes to show.",
    )
    underground_topology_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_portals_parser = subparsers.add_parser(
        "underground-portals",
        help="Infer observed tile portals from saved tunnel endpoints.",
    )
    underground_portals_parser.add_argument("save", type=Path)
    underground_portals_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_portals_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_portals_parser.add_argument(
        "--attach-tolerance",
        type=float,
        default=4.0,
        help="Maximum endpoint-to-tile distance in meters.",
    )
    underground_portals_parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Number of tile/rotation portal profiles to show.",
    )
    underground_portals_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_node_parser = subparsers.add_parser(
        "underground-node",
        help="Inspect one reconstructed underground node and its portal endpoints.",
    )
    underground_node_parser.add_argument("save", type=Path)
    underground_node_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID containing the node.",
    )
    underground_node_parser.add_argument(
        "--node",
        type=int,
        required=True,
        help="Reconstructed underground node ID.",
    )
    underground_node_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_node_parser.add_argument(
        "--attach-tolerance",
        type=float,
        default=4.0,
        help="Maximum tunnel endpoint-to-tile distance in meters.",
    )
    underground_node_parser.add_argument(
        "--tile",
        type=Path,
        help="Original .tile file used by this node; enables exact socket matching.",
    )
    underground_node_parser.add_argument(
        "--socket-match-tolerance",
        type=float,
        default=2.0,
        help="Maximum socket-to-saved-endpoint distance in meters.",
    )
    underground_node_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_navigation_parser = subparsers.add_parser(
        "underground-navigation",
        help="Build a conservative portal-matched navigation candidate graph.",
    )
    underground_navigation_parser.add_argument("save", type=Path)
    underground_navigation_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    underground_navigation_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    underground_navigation_parser.add_argument(
        "--attach-tolerance",
        type=float,
        default=4.0,
        help="Maximum tunnel endpoint-to-tile distance in meters.",
    )
    underground_navigation_parser.add_argument(
        "--min-template-placements",
        type=int,
        default=2,
        help="Independent placements required to learn a portal template.",
    )
    underground_navigation_parser.add_argument(
        "--cluster-step",
        type=float,
        default=4.0,
        help="Canonical portal clustering grid in meters.",
    )
    underground_navigation_parser.add_argument(
        "--match-tolerance",
        type=float,
        default=4.1,
        help="Maximum distance between opposing learned portals.",
    )
    underground_navigation_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of highest-degree navigation nodes to show.",
    )
    underground_navigation_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_route_parser = subparsers.add_parser(
        "underground-route",
        help="Find a shortest candidate route through the underground transit graph.",
    )
    underground_route_parser.add_argument("save", type=Path)
    underground_route_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to route through.",
    )
    underground_route_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    route_target = underground_route_parser.add_mutually_exclusive_group(
        required=True,
    )
    route_target.add_argument(
        "--node",
        type=int,
        help="Route to a specific transit node ID.",
    )
    route_target.add_argument(
        "--tag",
        help="Route to the nearest transit tile matching a semantic tag/name.",
    )
    route_target.add_argument(
        "--tunnel",
        help="Route to the nearest saved tunnel of this type.",
    )
    underground_route_parser.add_argument(
        "--include-vertical-contacts",
        action="store_true",
        help="Allow direct Z face contacts in addition to X/Y contacts and tunnels.",
    )
    underground_route_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    underground_route_map_parser = subparsers.add_parser(
        "underground-route-map",
        help="Render an underground map with a highlighted candidate route.",
    )
    underground_route_map_parser.add_argument("save", type=Path)
    underground_route_map_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to route through.",
    )
    underground_route_map_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="SVG output path.",
    )
    underground_route_map_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum ScriptData rows to scan (1-5000).",
    )
    route_map_target = (
        underground_route_map_parser.add_mutually_exclusive_group(
            required=True,
        )
    )
    route_map_target.add_argument(
        "--node",
        type=int,
        help="Route to a specific transit node ID.",
    )
    route_map_target.add_argument(
        "--tag",
        help="Route to the nearest transit tile matching a semantic tag/name.",
    )
    route_map_target.add_argument(
        "--tunnel",
        help="Route to the nearest saved tunnel of this type.",
    )
    underground_route_map_parser.add_argument(
        "--include-vertical-contacts",
        action="store_true",
        help="Allow direct Z face contacts in addition to X/Y contacts and tunnels.",
    )

    schema_parser = subparsers.add_parser(
        "schema",
        help="Show columns for a save table.",
    )
    schema_parser.add_argument("save", type=Path)
    schema_parser.add_argument("table")

    sample_parser = subparsers.add_parser(
        "sample",
        help="Show safe sample rows from a save table.",
    )
    sample_parser.add_argument("save", type=Path)
    sample_parser.add_argument("table")
    sample_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of rows to show (1-100).",
    )

    return parser


def run_tile_probe(
    tile: Path,
    as_json: bool,
) -> int:
    try:
        result = probe_tile(tile)
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['path']}")
    print(
        f"Header: version={result['version']} "
        f"uuid={result['uuid_hex']} "
        f"size={result['width']}x{result['height']} cells "
        f"file={result['file_size']} bytes"
    )
    print(
        f"Cell headers: offset={result['cell_header_offset']} "
        f"size={result['cell_header_size']} "
        f"cells={result['cells']}"
    )
    print(f"Content: {result['content']}")

    if result["invalid_chunk_ranges"]:
        print(
            "WARNING: invalid chunk ranges: "
            f"{len(result['invalid_chunk_ranges'])}"
        )

    print("Chunks:")
    for chunk in result["chunks"]:
        level = (
            ""
            if chunk["level"] is None
            else f"[{chunk['level']}]"
        )
        print(
            f"  cell={chunk['cell']} "
            f"{chunk['kind']}{level} "
            f"count={chunk['count']} "
            f"index={chunk['index']} "
            f"compressed={chunk['compressed_size']} "
            f"size={chunk['uncompressed_size']}"
        )

    return 0


def run_tile_nodes(
    tile: Path,
    as_json: bool,
) -> int:
    try:
        result = probe_tile_nodes(tile)
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['path']}")
    print(
        f"Tile cells: {result['width']}x{result['height']} "
        f"decoded_nodes={result['nodes']}"
    )
    for chunk in result["node_chunks"]:
        print(
            f"cell={chunk['cell']} "
            f"offset=({chunk['cell_x']}, {chunk['cell_y']}) "
            f"nodes={len(chunk['nodes'])}"
        )
        for node in chunk["nodes"]:
            params = node["params"]
            tunnel_type = (
                params.get("tunnel", {}).get("type")
                if isinstance(params, dict)
                else None
            )
            print(
                f"  node={node['index']} "
                f"pos={tuple(round(v, 6) for v in node['position'])} "
                f"tile_pos={tuple(round(v, 6) for v in node['tile_position'])} "
                f"rot={tuple(round(v, 6) for v in node['rotation'])} "
                f"scale={tuple(round(v, 6) for v in node['scale'])} "
                f"tags={node['tags']} "
                f"tunnel_type={tunnel_type} "
                f"record_size={node['record_size']}"
            )

    return 0


def run_tile_voxel_probe(
    tile: Path,
    cell: int | None,
    examples: int,
    as_json: bool,
) -> int:
    try:
        result = probe_tile_voxels(
            tile,
            cell=cell,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['path']}")
    print(
        f"Voxel records: {result['records']} "
        f"record_size={result['record_size']} "
        f"payload={result['payload_size']} "
        f"unique_headers={result['unique_headers']}"
    )
    print(f"Header bounds: {result['header_bounds']}")
    print(
        "Legacy, UNVERIFIED 4-bit packing shown below: "
        "material=value>>4, density=value&0x0F; "
        "also consider 5-bit density=value&0x1F."
    )
    print(f"Global top values: {result['global_top_values']}")
    for chunk in result["chunks"]:
        print(
            f"cell={chunk['cell']} records={chunk['records']} "
            f"decoded={chunk['decoded_size']} "
            f"header_min={chunk['headers_min']} "
            f"header_max={chunk['headers_max']}"
        )
        for item in chunk["examples"]:
            print(
                f"  record={item['index']} "
                f"header_i32={item['header_i32']} "
                f"header_hex={item['header_hex']} "
                f"min={item['payload_min']} "
                f"max={item['payload_max']} "
                f"unique={item['unique_values']} "
                f"zero={item['zero_count']} "
                f"ff={item['ff_count']} "
                f"top={item['top_values']} "
                f"materials={item['material_histogram']} "
                f"densities={item['density_histogram']}"
            )

    return 0


def run_tile_voxel_space(
    tile: Path,
    density_threshold: int | None,
    as_json: bool,
    density_bits: int = 4,
) -> int:
    try:
        result = probe_tile_voxel_space(
            tile,
            density_threshold=density_threshold,
            density_bits=density_bits,
        )
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['tile']}")
    print(
        f"Candidate voxel space: dims={result['dimensions_m']} "
        f"density_bits={result['density_bits']} "
        f"density_threshold={result['density_threshold']} "
        f"components={result['component_count']} "
        f"unknown={result['unknown_voxels']}"
    )
    for component in result["major_components"][:20]:
        print(
            f"  component={component['id']} "
            f"voxels={component['voxels']} "
            f"bounds={component['min']}..{component['max']}"
        )
    print("Tunnel socket -> candidate void component:")
    for socket in result["sockets"]:
        near = socket["nearest"]
        detail = (
            "unmatched"
            if near is None
            else (
                f"component={near['component']} "
                f"dist={near['distance_m']}m"
            )
        )
        print(
            f"  {socket['socket']} type={socket['type']} "
            f"pos={socket['tile_position']} -> {detail}"
        )
    print("WARNING: voxel candidate connectivity is not a walkable-path test.")
    return 0


def run_tile_object_probe(
    tile: Path,
    examples: int,
    as_json: bool,
    from_socket: str | None = None,
    to_socket: str | None = None,
    radius: float = 5.0,
    density_bits: int = 4,
) -> int:
    try:
        if (from_socket is None) != (to_socket is None):
            raise ValueError("both from_socket and to_socket are required")
        if radius <= 0:
            raise ValueError("radius must be positive")
        result = probe_tile_objects(tile, examples=examples)
        if from_socket is not None:
            route = probe_tile_voxel_walk(
                tile, from_socket=from_socket, to_socket=to_socket,
                density_bits=density_bits,
            )["route"]
            result["selected_route"] = {
                "from_socket": from_socket,
                "to_socket": to_socket,
                "status": route["status"],
                "radius_m": radius,
                "density_bits": density_bits,
            }
            candidate_path = (
                route["path"]["foot_voxels"]
                if route["path"] is not None
                else []
            )
            result["near_route"] = placements_near_candidate_route(
                result["placements"], candidate_path, radius_m=radius,
            )
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['path']}")
    print(
        f"Placement inventory: total={result['total_placements']} "
        f"by_kind={result['by_kind']}"
    )
    print("Object UUID groups (identity only, no collision model):")
    for group in result["groups"]:
        print(
            f"  kind={group['kind']} "
            f"uuid={group['uuid_hex']} count={group['count']}"
        )
    for item in result["examples"]:
        print(
            f"  {item['kind']} cell={item['cell']} "
            f"index={item['index']} "
            f"pos={item['tile_position']} "
            f"scale={item['scale']} "
            f"uuid={item['uuid_hex']}"
        )
    if "selected_route" in result:
        route = result["selected_route"]
        print(
            f"Candidate route: {route['from_socket']} -> "
            f"{route['to_socket']} status={route['status']} "
            f"radius={route['radius_m']}m "
            f"density_bits={route['density_bits']}"
        )
        for item in result["near_route"]:
            print(
                f"  nearby {item['kind']} index={item['index']} "
                f"uuid={item['uuid_hex']} "
                f"pos={item['tile_position']} "
                f"origin_distance={item['distance_to_footpath_m']}m"
            )
    print(
        "WARNING: record transforms/UUIDs do not identify mesh, "
        "solid collision or ramps."
    )
    return 0


def run_tile_ground_survival(
    plan: Path,
    lua_file: Path,
    game_script: Path,
    install: bool,
    remove: bool,
    navigation_save: Path | None = None,
    portal_id: int | None = None,
) -> int:
    try:
        if (navigation_save is None) != (portal_id is None):
            raise ValueError(
                "--navigation-save and --portal-id must be provided together"
            )
        plan_data = json.loads(plan.read_text(encoding="utf-8-sig"))
        entrance = None
        if navigation_save is not None and not remove:
            entrance = load_portal_entrance(
                navigation_save,
                destination_world_id=plan_data["world_id"],
                portal_id=portal_id,
            )
        result = survival_hook_operation(
            game_script,
            plan_data,
            lua_text=lua_file.read_text(encoding="utf-8-sig"),
            action="install" if install else ("remove" if remove else "preview"),
            entrance=entrance,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 1
    print(
        f"Survival Lua hook: action={result['action']} "
        f"installed={result['already_installed']} "
        f"changed={result['will_modify']}"
    )
    print(f"Target: {result['target']}")
    if result.get("backup"):
        print(f"Backup: {result['backup']}")
    print(result["note"])
    if result["action"] == "preview":
        print(
            "No file changed. Completely exit Scrap Mechanic first, "
            "then run again with --install if you want this diagnostic."
        )
    else:
        print(
            "Restart Scrap Mechanic. Enter world 23 and approach within "
            "40m of the target voxel area; the hook will probe once. "
            "After capturing logs, run again with --remove."
        )
    return 0


def run_tile_ground_lua(plan: Path, output: Path) -> int:
    try:
        plan_data = json.loads(plan.read_text(encoding="utf-8-sig"))
        generated = render_ground_probe_lua(plan_data)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(generated, encoding="utf-8")
    except (
        OSError, ValueError, json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}")
        return 1
    print(f"Generated Lua probe: {output}")
    print(
        "This is a callable Lua fragment, NOT an installed mod. "
        "Run smAtlasGroundProbe(actualWorldUserdata) from a permitted "
        "game script in the correct loaded underground world."
    )
    print(
        "Collect ATLAS_GROUND log lines and compare with "
        "'sm-atlas tile-ground-compare'."
    )
    return 0


def run_tile_ground_profile(
    plan: Path, log: Path, tile: Path, z_margin: int, as_json: bool,
) -> int:
    try:
        result = inspect_ground_density(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"), tile,
            z_margin=z_margin,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Ground voxel profile world={result['world_id']} "
        f"hits={result['hits']}/{result['planned_points']} "
        f"columns={len(result['columns'])} "
        f"local_Z={result['observed_local_z_range']} "
        f"column_window={result['column_z_window']}"
    )
    for column in result["columns"]:
        print(
            f"  XY local={tuple(column['local_xy'])} "
            f"sample_indexes={column['sample_indexes']} "
            f"candidate_z_4bit={column['candidate_vertical_crossings_world_z']['4']} "
            f"candidate_z_5bit={column['candidate_vertical_crossings_world_z']['5']}"
        )
        for item in column["raw_vertical_bytes"]:
            print(
                f"    z={item['z']:>2} raw=0x{item['raw_hex']} "
                f"low4={item['low4']} low5={item['low5']}"
            )
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_hypotheses(
    plan: Path, log: Path, tile: Path, as_json: bool,
    include_six_bit: bool = False,
) -> int:
    try:
        result = compare_trilinear_hypotheses(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"), tile,
            include_six_bit=include_six_bit,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Ground hypotheses world={result['world_id']} "
        f"measured_hits={result['hits_from_game']} "
        f"fixed_models={result['models_evaluated']}"
    )
    print(
        f"  recorded_FF_voxels={result['written_ff_voxels_in_tile']} "
        f"missing_voxels={result['unknown_voxels_in_tile']}"
    )
    for model in result["models"]:
        print(
            f"  bits={model['bits']} origin={model['lattice_origin_shift_xyz']} "
            f"FF_sensitive={model['ff_sensitive_samples']} "
            f"single={model['single_candidates']} "
            f"missing={model['no_candidates']} "
            f"ambiguous={model['ambiguous_samples']} "
            f"rmse={model['rmse_m']}m "
            f"rmse_after_bias={model['rmse_after_median_offset_m']}m"
        )
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_byte_audit(
    plan: Path, log: Path, tile: Path, radius: int, as_json: bool,
) -> int:
    try:
        result = audit_ground_voxel_bytes(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"),
            tile,
            radius_voxels=radius,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Voxel byte forensic audit world={result['world_id']} "
        f"game_hits={result['game_ray_hits']} "
        f"unique_columns={result['unique_voxel_columns']} "
        f"radius={result['radius_voxels']} "
        f"missing_voxels={result['absent_voxels_in_tile']} "
        f"recorded_FF={result['written_ff_voxels_in_tile']}"
    )
    for shift in result["shifts"]:
        print(
            f"  sample_z_shift={shift['sample_origin_shift_z']} "
            f"recorded_pairs={shift['recorded_pairs']}/"
            f"{shift['candidate_columns']}"
        )
        for mask in shift["masked_midpoint_checks"]:
            print(
                f"    bits={mask['bits']} "
                f"solid_below_air_above={mask['solid_below_air_above']} "
                f"air_below_solid_above={mask['air_below_solid_above']} "
                f"both_high={mask['both_above_threshold']} "
                f"both_low={mask['both_below_threshold']}"
            )
        print("    bit transitions, low to high Z (bit: 1->0 / 0->1):")
        print("      " + " ".join(
            f"{bit['bit']}:{bit['set_to_clear']}/{bit['clear_to_set']}"
            for bit in shift["bit_transitions"]
        ))
        print("    Most common raw byte pairs (below->above): " + (
            ", ".join(
                f"{p['below_hex']}->{p['above_hex']} x{p['count']}"
                for p in shift["common_raw_pairs"][:8]
            ) or "none"
        ))
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_isovalue_audit(
    plan: Path, log: Path, tile: Path, as_json: bool,
    include_six_bit: bool = False,
) -> int:
    try:
        result = audit_observed_isovalues(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"), tile,
            include_six_bit=include_six_bit,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Measured-ground isovalue audit world={result['world_id']} "
        f"game_hits={result['game_ray_hits']} "
        f"models={result['models_evaluated']}"
    )
    for model in result["models"]:
        print(
            f"  bits={model['bits']} "
            f"origin={model['lattice_origin_shift_xyz']} "
            f"sampled={model['samples_scored']}/{model['samples_expected']} "
            f"falling={model['falling_density_samples']} "
            f"rising={model['rising_density_samples']} "
            f"flat={model['flat_density_samples']} "
            f"midpoint={model['fixed_midpoint_normalized']} "
            f"observed_median={model['median_observed_normalized_density']} "
            f"fixed_error={model['mean_abs_distance_from_fixed_midpoint']} "
            f"fitted_spread={model['mean_abs_spread_around_sample_median']}"
        )
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_normal_audit(
    plan: Path, log: Path, tile: Path, as_json: bool,
    include_six_bit: bool = False,
) -> int:
    try:
        result = audit_ground_field_normals(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"), tile,
            include_six_bit=include_six_bit,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Ground normal audit world={result['world_id']} "
        f"game_hits={result['measured_hits']} "
        f"models={result['models_evaluated']}"
    )
    for model in result["models_ranked_by_normal_angle"]:
        print(
            f"  bits={model['bits']} "
            f"origin={model['lattice_origin_shift_xyz']} "
            f"normal_samples={model['samples_scored']}/{model['samples_expected']} "
            f"at_grid_plane={model['grid_plane_samples_scored']} "
            f"non_falling={model['density_not_falling_upward']} "
            f"unavailable={model['flat_or_unavailable_samples']} "
            f"mean_angle_error_deg={model['mean_normal_angle_error_degrees']} "
            f"max_angle_error_deg={model['max_normal_angle_error_degrees']}"
        )
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_slope_audit(
    plan: Path, log: Path, tile: Path, as_json: bool,
    include_six_bit: bool = False,
) -> int:
    try:
        result = audit_ground_slopes(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"),
            tile, include_six_bit=include_six_bit,
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, InvalidTileFile) as exc:
        print(f"error: {exc}")
        return 1
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Ground slope audit world={result['world_id']} "
        f"measured_hits={result['measured_hits']} "
        f"models={result['models_evaluated']}"
    )
    print(f"  recorded_FF_voxels={result['written_ff_voxels_in_tile']}")
    for lane in result["lanes"]:
        print(
            f"  lane={lane['lateral_offset_m']}m "
            f"rise={lane['observed_end_to_end_rise_m']}m "
            f"normal_checks={len(lane['adjacent_normal_checks'])} "
            f"normal_grade_disagreement="
            f"{lane['mean_normal_grade_disagreement']}"
        )
    print(
        "  2D patch-grade models (coverage first; directional grades are m/m):"
    )
    for model in result["models_ranked_by_patch_grade_error"]:
        print(
            f"  bits={model['bits']} "
            f"origin={model['lattice_origin_shift_xyz']} "
            f"FF_sensitive={model['ff_sensitive_samples']} "
            f"patch={model['patch_segments_scored']}/"
            f"{model['measured_patch_segments']} "
            f"patch_mae={model['mean_absolute_patch_grade_error']} "
            f"along_mae={model['mean_absolute_local_grade_error']} "
            f"cross_mae={model['mean_absolute_cross_track_grade_error']} "
            f"normal_mae={model['mean_absolute_patch_normal_grade_error']} "
            f"rise_mae={model['mean_absolute_rise_error_m']}m "
            f"height_rmse={model['rmse_height_m']}m"
        )
    # This is NOT a correction of the candidate surface: a constant
    # tilt is fitted to the same game observations merely to identify
    # systematic versus irregular mismatch.
    top_model = result["models_ranked_by_patch_grade_error"][0]
    print("  Leading model: signed tilt error vs local irregularity (m/m):")
    for direction, key in (
        ("along", "along_direction_bias"),
        ("cross", "cross_direction_bias"),
    ):
        diagnostic = top_model[key]
        print(
            f"    {direction} "
            f"game_mean={diagnostic['observed_mean_grade']} "
            f"model_mean={diagnostic['model_mean_grade']} "
            f"mean_error={diagnostic['mean_signed_grade_error']} "
            f"error_after_tilt_diagnostic="
            f"{diagnostic['mae_after_constant_tilt_diagnostic']}"
        )
    print("WARNING: " + result["warning"])
    return 0


def run_tile_ground_compare(plan: Path, log: Path, as_json: bool) -> int:
    try:
        result = compare_ground_observations(
            json.loads(plan.read_text(encoding="utf-8-sig")),
            log.read_text(encoding="utf-8-sig"),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(
        f"Ground comparison world={result['world_id']} "
        f"logged={result['logged_points']}/{result['planned_points']} "
        f"terrain_surface={result['terrain_surface_hits']} "
        f"non_upward={result['non_upward_terrain_surface_hits']} "
        f"other_or_miss={result['other_hits_or_misses']} "
        f"not_sampled={result['not_sampled']}"
    )
    errors = result["measured_minus_predicted"]
    print(
        f"  Height difference: median_bias={errors['median_offset_m']}m "
        f"mean_error={errors['mean_error_m']}m "
        f"rmse={errors['rmse_m']}m "
        f"max_error={errors['max_absolute_error_m']}m "
        f"max_after_bias={errors['max_residual_after_median_offset_m']}m"
    )
    for track in result["track_summaries"]:
        print(
            f"  track lateral={track['lateral_offset_m']}m "
            f"terrain_hits={track['terrain_surface_hits']} "
            f"adjacent_segments={track['adjacent_measured_segments']} "
            f"max_observed_gradient={track['max_observed_absolute_gradient']}"
        )
    if result["terrain_surface_hits"] < result["planned_points"]:
        print(
            "WARNING: incomplete ground hits. Cave ceiling, unloaded cell, "
            "asset intercept or wrong cast interval may be responsible. "
            "Do not infer walkability."
        )
    print(
        "WARNING: physics raycast hits are observations, not proof "
        "of character movement or capsule clearance."
    )
    return 0


def run_tile_world_probe(
    save: Path,
    tile: Path,
    world_id: int,
    node_id: int,
    edge: list[str] | None,
    density_bits: int,
    match_tolerance: float,
    as_json: bool,
    output: Path | None = None,
) -> int:
    try:
        if output is not None and not as_json:
            raise ValueError("--output requires --json")
        result = probe_tile_world(
            SaveDatabase(save), tile,
            world_id=world_id, node_id=node_id,
            edge=tuple(edge) if edge is not None else None,
            density_bits=density_bits, tolerance_m=match_tolerance,
        )
    except (
        FileNotFoundError, InvalidSaveFile, InvalidTileFile,
        sqlite3.DatabaseError, OSError, ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        rendered = json.dumps(result, indent=2, ensure_ascii=False)
        if output is not None:
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            except OSError as exc:
                print(f"error: {exc}")
                return 1
            print(f"Wrote UTF-8 tile ground plan: {output}")
        else:
            print(rendered)
        return 0

    print(f"World: {result['world_id']} layout node: {result['node_id']}")
    print(
        f"Tile: {result['tile_name']} uuid={result['tile_uuid']} "
        f"kind={result['layout_kind']}"
    )
    print(
        f"Placement: rotation={result['layout_rotation_quarter_turns']}*90deg "
        f"world_min={result['world_bounds']['min']} "
        f"world_max={result['world_bounds']['max']}"
    )
    print("Saved .tile sockets -> world coordinates:")
    for socket in result["sockets"]:
        print(
            f"  {socket['socket']} "
            f"local={socket['tile_position']} "
            f"world={socket['world_position']}"
        )
    alignment = result["alignment"]
    print(
        f"Tunnel anchor alignment: {alignment['status']} "
        f"sockets={alignment['distinct_sockets']} "
        f"tunnels={alignment['distinct_tunnels']} "
        f"max_residual={alignment['max_match_residual_m']}m"
    )
    for match in result["saved_tunnel_matches"]:
        print(
            f"  #{match['tunnel_id']} {match['end']} -> "
            f"{match['socket']} residual={match['residual_m']}m "
            f"saved={match['saved_world_position']}"
        )

    critical = result.get("critical_edge")
    if critical is not None:
        print(
            f"Candidate edge gradient={critical['estimated_absolute_gradient']} "
            f"(unverified voxel iso-surface)"
        )
        for endpoint in critical["endpoints"]:
            print(
                f"  foot {endpoint['tile_foot_voxel']} "
                f"-> world reference={endpoint['world_foot_voxel_reference']}"
            )
        print(
            "In-game terrain raycast candidates "
            "(XY exact under saved placement; Z is unverified estimate):"
        )
        for sample in critical["world_samples"]:
            print(
                f"  offset={sample['lateral_offset_m']} "
                f"t={sample['fraction']} "
                f"world_xy={sample['world_xy']} "
                f"surface_z_guess={sample['estimated_surface_world_z']}"
            )
    print(
        "WARNING: matching saved tunnel endpoints does not prove "
        "actual game physics/collision; tile-local voxel sample origin "
        "and cave raycast frame still need in-game verification."
    )
    return 0


def run_tile_voxel_walk(
    tile: Path,
    from_socket: str | None,
    to_socket: str | None,
    density_threshold: int | None,
    headroom: int,
    max_step: int,
    as_json: bool,
    elevation_details: bool = False,
    density_bits: int = 4,
    socket_radius: float = 5.0,
    max_surface_gradient: float | None = None,
) -> int:
    try:
        result = probe_tile_voxel_walk(
            tile,
            from_socket=from_socket,
            to_socket=to_socket,
            density_threshold=density_threshold,
            density_bits=density_bits,
            headroom=headroom,
            max_step=max_step,
            socket_radius=socket_radius,
            max_surface_gradient=max_surface_gradient,
        )
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['tile']}")
    print(
        f"Experimental candidate floor graph: "
        f"points={result['candidate_foot_positions']} "
        f"components={result['components']} "
        f"unknown={result['unknown_voxels']}"
    )
    print(
        f"Settings: density_bits={result['density_bits']} "
        f"density<{result['density_threshold']} "
        f"headroom={result['headroom_m']}m "
        f"max_step={result['max_step_m']}m "
        f"socket_radius={result['socket_radius_m']}m"
    )
    for component in result["major_components"][:10]:
        print(
            f"  component={component['id']} "
            f"candidate_foot_positions={component['voxels']}"
        )
    for socket in result["sockets"]:
        near = socket["nearest_foot"]
        detail = (
            "no major floor within radius"
            if near is None
            else (
                f"component={near['component']} "
                f"foot={near['foot_voxel']} "
                f"offset={near['distance_m']}m"
            )
        )
        print(f"  {socket['socket']} -> {detail}")
        air = socket["nearest_candidate_air"]
        if air is not None:
            print(
                f"    nearest candidate-free voxel={air['voxel']} "
                f"offset={air['offset_m']}m raw={air['raw']} "
                f"(not validated as walkable)"
            )
        extended = socket["nearest_major_floor_beyond_radius"]
        if extended is not None:
            print(
                f"    CAUTION: major floor just outside {result['socket_radius_m']}m "
                f"socket radius: {extended['foot_voxel']} "
                f"component={extended['component']} "
                f"offset={extended['distance_m']}m "
                f"(searched within {socket['extended_search_radius_m']}m; "
                f"not an attached entrance)"
            )
        entry = socket["inward_terrain_probe"]
        straight = entry["straight_to_major_floor"]
        ray_status = (
            "unavailable" if straight is None else straight["status"]
        )
        sample_values = [
            sample["raw"] for sample in entry["samples"]
        ]
        print(
            f"    inward terrain: face={entry['face']} "
            f"first_candidate_open={entry['first_open_voxel']} "
            f"offset_cells={entry['first_open_offset_cells']} "
            f"reblocked={entry['reblocked_after_first_open']} "
            f"raw={sample_values}"
        )
        if straight is not None:
            print(
                f"    candidate centreline to selected floor: "
                f"{ray_status}"
                + (
                    f" blocker={straight['first_blocker']}"
                    if straight["first_blocker"] is not None
                    else ""
                )
            )
        closest = socket["nearest_any_foot"]
        if closest is not None and (
            near is None
            or closest["component"] != near["component"]
        ):
            print(
                f"    CAUTION: closer isolated floor at "
                f"{closest['foot_voxel']} "
                f"component={closest['component']} "
                f"offset={closest['distance_m']}m; "
                f"socket attachment is unverified"
            )

    route = result.get("route")
    if route is not None:
        print(
            f"Candidate route {route['from_socket']} -> "
            f"{route['to_socket']}: {route['status']}"
        )
        for role, bridge in route.get(
            "candidate_air_attachments", {}
        ).items():
            print(
                f"  {role} socket-to-floor candidate air bridge: "
                f"{bridge['status']}"
            )
            if bridge["status"] == "candidate_air_path_found":
                print(
                    f"    air_steps={bridge['steps']} "
                    f"standing_candidates={bridge['positions_with_candidate_foot']} "
                    f"unsupported_positions={bridge['positions_without_candidate_foot']} "
                    f"rises={bridge['rises']} drops={bridge['drops']} "
                    f"z_range={bridge['min_z']}..{bridge['max_z']} "
                    f"(AIR ONLY; NOT A WALKABLE CONNECTION)"
                )
        grade_probe = route.get("surface_gradient_probe")
        if grade_probe is not None:
            print(
                f"  experimental surface gradient probe: "
                f"limit={grade_probe['limit']} "
                f"status={grade_probe['status']}"
            )
            bottleneck = grade_probe.get("minimum_bottleneck")
            if bottleneck is not None:
                print(
                    f"    minimum bottleneck: status={bottleneck['status']} "
                    f"required_gradient="
                    f"{bottleneck.get('minimum_required_gradient', 'n/a')}"
                )
                for edge in bottleneck.get("critical_edges", [])[:5]:
                    print(
                        f"    critical {edge['from_foot']} -> "
                        f"{edge['to_foot']} "
                        f"gradient={edge['absolute_gradient']}"
                    )
            alternative = grade_probe.get("alternative_path")
            if alternative is not None:
                print(
                    f"    constrained candidate route: "
                    f"grid_length={alternative['length_m']}m "
                    f"grid_steps={alternative['grid_steps']}"
                )
                surface = alternative.get("interpolated_surface")
                if surface is not None and surface.get("estimated_length_m") is not None:
                    print(
                        f"    constrained density-surface length="
                        f"{surface['estimated_length_m']}m"
                    )
            else:
                print(
                    "    No alternative candidate floor route satisfies "
                    "the selected experimental limit."
                )
        gap = route.get("gap_diagnostics")
        if gap is not None:
            print(
                f"  rejected adjacent floor links: "
                f"{gap['reason_counts']}"
            )
            for reason, entries in gap["examples"].items():
                for entry in entries[:2]:
                    print(
                        f"    {reason}: "
                        f"{entry['from_foot']} -> "
                        f"{entry['to_foot']} "
                        f"dz={entry['delta_z_m']}m"
                        + (
                            f" blocker={entry['blocker']}"
                            if "blocker" in entry
                            else ""
                        )
                    )
        if route["path"] is not None:
            item = route["path"]
            print(
                f"  grid_steps={item['grid_steps']} "
                f"length={item['length_m']}m "
                f"climb={item['climb_m']}m "
                f"descent={item['descent_m']}m "
                f"z_range={item['min_z']}..{item['max_z']}"
            )
            print(
                f"  edges: level={item['level_steps']} "
                f"rises={item['rise_steps']} "
                f"drops={item['drop_steps']} "
                f"unverified_elevation={item['unverified_elevation_edges']} "
                f"rise_ceiling_checked={item['rise_clearance_checked']}"
            )
            attachment = route.get("socket_attachment")
            if attachment is not None:
                print(
                    f"  socket-to-floor offsets: "
                    f"start={attachment['source_offset_m']}m "
                    f"end={attachment['target_offset_m']}m "
                    f"connection_validated={attachment['validated_connection']}"
                )
            surface = item.get("interpolated_surface")
            if surface is not None:
                print(
                    f"  experimental density surface: "
                    f"status={surface['status']}"
                )
                if surface["status"] == "experimental_vertical_iso_interpolation":
                    print(
                        f"    estimated_length={surface['estimated_length_m']}m "
                        f"max_gradient={surface['max_absolute_gradient']} "
                        f"mean_gradient={surface['mean_absolute_gradient']} "
                        f"gradient>1={surface['segments_with_gradient_gt_1']} "
                        f"gradient>0.5={surface['segments_with_gradient_gt_0_5']} "
                        f"(not actual game mesh/collision)"
                    )
                    if elevation_details:
                        for segment in surface["segment_samples"]:
                            if (
                                abs(segment["height_change_m"]) > 0.5
                                or segment["absolute_gradient"] > 1
                            ):
                                print(
                                    f"    interpolated step={segment['step_index']} "
                                    f"{segment['from_foot']} -> {segment['to_foot']} "
                                    f"height_delta={segment['height_change_m']}m "
                                    f"gradient={segment['absolute_gradient']}"
                                )
            summary = item.get("elevation_support_summary")
            if summary is not None:
                print(
                    f"  elevation support density: "
                    f"partial={summary['partial_density_edges']} "
                    f"full={summary['both_full_density_edges']} "
                    f"sampled={summary['edges_sampled']}"
                )
            if elevation_details:
                for edge in item.get("elevation_edge_samples", []):
                    print(
                        f"    step={edge['step_index']} "
                        f"{edge['from_foot']} -> {edge['to_foot']} "
                        f"dz={edge['delta_z_m']} "
                        f"support_density="
                        f"{edge['from_support_density']}/"
                        f"{edge['to_support_density']} "
                        f"partial={edge['has_partial_support_density']}"
                    )
            print(
                "  Full foot-voxel path: use --json "
                "to retrieve every waypoint."
            )
    print(
        "WARNING: entrance centreline is not player clearance or "
        "proof of socket-to-floor attachment. A 1m rise is not "
        "evidence of a traversable ramp/stair; assets and physics "
        "are not modelled."
    )
    return 0


def run_tile_chunk_probe(
    tile: Path,
    kind: str,
    cell: int | None,
    full_hex: bool,
    as_json: bool,
) -> int:
    try:
        result = probe_tile_chunks(
            tile,
            kind=kind,
            cell=cell,
            full_hex=full_hex,
        )
    except (
        FileNotFoundError,
        InvalidTileFile,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Tile: {result['path']}")
    print(f"Chunk kind: {result['kind']}")
    for chunk in result["chunks"]:
        level = (
            ""
            if chunk["level"] is None
            else f"[{chunk['level']}]"
        )
        print(
            f"cell={chunk['cell']} "
            f"{chunk['kind']}{level} "
            f"count={chunk['count']} "
            f"compressed={chunk['compressed_size']} "
            f"decoded={chunk['decoded_size']} "
            f"sha256={chunk['sha256']}"
        )
        print(f"  hex_prefix={chunk['hex_prefix']}")
        print(f"  hex_suffix={chunk['hex_suffix']}")
        print(f"  ascii_strings={chunk['ascii_strings']}")
        print(
            "  float32_le_candidates="
            f"{chunk['float32_le_candidates']}"
        )
        if full_hex:
            print(f"  hex={chunk['hex']}")

    return 0


def run_portal_probe(
    save: Path,
    world_id: int | None,
    portal_id: int | None,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_portal_probe(
            probe_portals(
                database,
                world_id=world_id,
                portal_id=portal_id,
            )
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if not result:
        print("No matching portals.")
        return 0

    for portal in result:
        world_a = portal["world_a"]
        world_b = portal["world_b"]
        print(
            f"Portal {portal['id']}: "
            f"world {world_a['id']} cell={tuple(world_a['cell'])} "
            f"<-> world {world_b['id']} cell={tuple(world_b['cell'])}"
        )
        print(
            f"  blob_size={portal['blob_size']} "
            f"header_matches_columns={portal['header_matches_columns']}"
        )
        print(f"  header={portal['header']}")
        decoded = portal["decoded"]
        print(
            "  decoded_matches_columns="
            f"{portal['decoded_matches_columns']}"
        )
        if decoded is not None:
            print(
                f"  complete={decoded['complete']} "
                f"dimensions={tuple(decoded['dimensions'])}"
            )
            for side_name in ("side_a", "side_b"):
                side = decoded[side_name]
                if side is None:
                    print(f"  {side_name}: unresolved")
                    continue
                print(
                    f"  {side_name}: "
                    f"prefix={side['prefix']} "
                    f"world={side['world_id']} "
                    f"cell={tuple(side['cell'])} "
                    f"position={tuple(side['position'])} "
                    f"rotation={tuple(side['rotation'])}"
                )
            print(
                f"  tail_bit_offset={decoded['tail_bit_offset']} "
                f"tail_bits={decoded['tail_bits']}"
            )
        print(f"  blob_hex={portal['blob_hex']}")

    return 0


def run_portal_compare(
    save: Path,
    world_id: int,
    side: str,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = compare_portal_payloads(
            database,
            world_id=world_id,
            side=side,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if not result:
        print("No matching portal groups.")
        return 0

    for group in result:
        print(
            f"Side {group['side'].upper()} world={group['world_id']} "
            f"cell={tuple(group['cell'])} "
            f"portals={group['count']}"
        )
        if group["opening_a_position_candidate"] is not None:
            print(
                "  opening_a_position_candidate="
                f"{tuple(group['opening_a_position_candidate'])}"
            )
        print(
            "  payload common prefix: "
            f"{group['payload_common_prefix_bytes']} bytes"
        )
        print(
            "  payload common suffix: "
            f"{group['payload_common_suffix_bytes']} bytes"
        )
        print(
            "  prefix_hex="
            f"{group['payload_common_prefix_hex']}"
        )
        print(
            "  suffix_hex="
            f"{group['payload_common_suffix_hex']}"
        )
        print("  members:")
        for member in group["portals"]:
            print(
                f"    id={member['id']} "
                f"other_world={member['other_world']} "
                f"other_cell={tuple(member['other_cell'])} "
                f"blob_size={member['blob_size']}"
            )

    return 0


def run_saves(root: Path | None, as_json: bool) -> int:
    saves = find_survival_saves(root)

    if as_json:
        print(
            json.dumps(
                [save.to_dict() for save in saves],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not saves:
        print("No Scrap Mechanic Survival saves found.")
        return 0

    for index, save in enumerate(saves, start=1):
        size_mb = save.size_bytes / (1024 * 1024)
        print(
            f"[{index}] {save.path.stem} "
            f"({size_mb:.1f} MB)\n    {save.path}"
        )

    return 0


def run_inspect(save: Path, as_json: bool) -> int:
    database = SaveDatabase(save)

    try:
        result = database.inspect()
    except (FileNotFoundError, InvalidSaveFile, sqlite3.DatabaseError) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Save: {result['path']}")
    print(f"Size: {result['size_bytes']} bytes")
    print(f"SQLite user_version: {result['user_version']}")
    print(f"Scrap Mechanic signal: {result['sm_signal']}")
    print()

    for table, count in result["tables"].items():
        marker = "*" if table in result["known_tables"] else " "
        print(f"{marker} {table}: {count}")

    return 0


def run_worlds(save: Path, as_json: bool) -> int:
    database = SaveDatabase(save)

    try:
        worlds = discover_worlds(database)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(
            json.dumps(
                [world.to_dict() for world in worlds],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not worlds:
        print("No world definitions found.")
        return 0

    for world in worlds:
        extra = f" depth={world.depth}" if world.depth is not None else ""
        print(
            f"[{world.world_id}] {world.label} "
            f"({world.kind}{extra})\n"
            f"    class: {world.classname}\n"
            f"    seed: {world.seed}\n"
            f"    file: {world.filename}"
        )

    return 0


def run_graph(
    save: Path,
    underground_only: bool,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        graph = build_world_graph(
            database,
            underground_only=underground_only,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if not graph.connections:
        print("No matching portal connections found.")
        return 0

    for connection in graph.connections:
        a_position = (
            ""
            if connection.a.position is None
            else f" pos={tuple(round(value, 3) for value in connection.a.position)}"
        )
        b_position = (
            ""
            if connection.b.position is None
            else f" pos={tuple(round(value, 3) for value in connection.b.position)}"
        )
        print(
            f"[portal {connection.portal_id}] "
            f"{connection.a.label} #{connection.a.world_id} "
            f"({connection.a.x}, {connection.a.y}){a_position} "
            f"-> "
            f"{connection.b.label} #{connection.b.world_id} "
            f"({connection.b.x}, {connection.b.y}){b_position}"
        )

    return 0


def run_terrain(
    save: Path,
    underground_only: bool,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        summaries = summarize_voxel_terrain(
            database,
            underground_only=underground_only,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(
            json.dumps(
                [summary.to_dict() for summary in summaries],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not summaries:
        print("No matching voxel terrain records found.")
        return 0

    for summary in summaries:
        print(
            f"[{summary.world_id}] {summary.label} "
            f"({summary.kind})\n"
            f"    records: {summary.records}\n"
            f"    unique coordinates: {summary.unique_coordinates}\n"
            f"    bounds: x={summary.min_x}..{summary.max_x}, "
            f"y={summary.min_y}..{summary.max_y}\n"
            f"    blob bytes: {summary.total_blob_bytes}"
        )

    return 0


def run_terrain_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_offset: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_terrain(
            database,
            world_id=world_id,
            limit=limit,
            max_offset=max_offset,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"LZ4 matches: {result['matched_records']}")
    print(f"Offset histogram: {result['offset_histogram']}")

    for record in result["records"]:
        if not record["lz4_candidates"]:
            continue

        print(
            f"[{record['id']}] ({record['x']}, {record['y']}) "
            f"{record['blob_size']} bytes -> "
            f"{record['lz4_candidates']}"
        )

    return 0


def run_terrain_structure(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_terrain_structure(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Marker matches: {result['marker_matches']}")
    print(f"ID matches: {result['id_matches']}")
    print(f"Sentinel matches: {result['sentinel_matches']}")
    print(
        "Direct coordinate candidates: "
        f"{result['direct_coordinate_candidates']}"
    )
    print(f"Exact cell matches: {result['exact_cell_matches']}")
    print(f"Boundary cell matches: {result['boundary_cell_matches']}")
    print(f"Marker offsets: {result['marker_offsets']}")
    print(f"ID offsets: {result['id_offsets']}")
    print(f"Prefix signatures: {result['prefix_signatures']}")
    print(f"Candidate Z range: {result['candidate_z_range']}")

    return 0


def run_terrain_layout(
    save: Path,
    world_id: int,
    limit: int,
    min_offset: int,
    max_offset: int,
    top: int,
    z_limit: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = scan_voxel_terrain_layout(
            database,
            world_id=world_id,
            limit=limit,
            min_relative_offset=min_offset,
            max_relative_offset=max_offset,
            top=top,
            z_limit=z_limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Records with embedded ID: {result['records_with_id']}")
    print(f"Marker offsets: {result['marker_offsets']}")
    print()
    print("Top layouts:")

    for score in result["top_layouts"]:
        print(
            f"  {score['endian']:>6} "
            f"{score['axis_order']:>3} "
            f"factor={score['factor']} "
            f"offset=+{score['relative_offset']}: "
            f"xy={score['exact_xy_matches']} "
            f"z={score['plausible_z_matches']} "
            f"m1={score['marker_1_matches']} "
            f"m2={score['marker_2_matches']} "
            f"zrange={score['z_range']}"
        )

    print()
    print("Big-endian/ZYX/factor=4 offset peaks:")

    for score in result["big_zyx_factor4_offsets"]:
        print(
            f"  offset=+{score['relative_offset']}: "
            f"xy={score['exact_xy_matches']} "
            f"z={score['plausible_z_matches']} "
            f"m1={score['marker_1_matches']} "
            f"m2={score['marker_2_matches']} "
            f"zrange={score['z_range']}"
        )

    return 0


def run_terrain_chunks(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_voxel_chunks(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Unresolved records: {result['unresolved_records']}")
    print(f"Decode ratio: {result['decode_ratio']:.1%}")
    print(
        "Unique chunk coordinates: "
        f"{result['unique_chunk_coordinates']}"
    )
    print(
        "Duplicate coordinate records: "
        f"{result['duplicate_coordinate_records']}"
    )
    print(
        "Coordinates with duplicates: "
        f"{result['duplicate_coordinates']}"
    )
    print(f"Failures: {result['failures']}")
    print(f"Chunk bounds: {result['chunk_bounds']}")
    print(f"Z histogram: {result['z_histogram']}")
    print(f"Payload sizes: {result['payload_size_histogram']}")
    print(f"Payload prefixes: {result['payload_prefixes']}")

    return 0


def run_terrain_map(
    save: Path,
    world_id: int,
    output: Path,
    limit: int,
) -> int:
    database = SaveDatabase(save)

    try:
        result = write_voxel_chunk_map(
            database,
            world_id=world_id,
            output=output,
            limit=limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(f"World: {result['world_id']}")
    print(f"Decoded chunks: {result['decoded_chunks']}")
    print(f"Bounds: {result['bounds']}")
    print(f"Levels: {result['levels']}")
    print(f"SVG: {result['output']}")

    return 0


def run_terrain_decode(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_decompressed_voxel_terrain(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode ratio: {result['decode_ratio']:.1%}")
    print(f"Failures: {result['failures']}")
    print(
        "Decompressed sizes: "
        f"{result['decompressed_size_histogram']}"
    )
    print(
        "Payload sizes: "
        f"{result['payload_size_histogram']}"
    )
    print(
        "Exact 17^3 voxel payloads: "
        f"{result['exact_voxel_payload_records']}"
    )
    print(
        "Unique chunk coordinates: "
        f"{result['unique_chunk_coordinates']}"
    )
    print(
        "Duplicate coordinate records: "
        f"{result['duplicate_coordinate_records']}"
    )
    print(f"Chunk bounds: {result['chunk_bounds']}")

    return 0


def run_terrain_payload(
    save: Path,
    world_id: int,
    limit: int,
    max_offset: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_payloads(
            database,
            world_id=world_id,
            limit=limit,
            max_offset=max_offset,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Payload size range: {result['payload_size_range']}")
    print(f"Four-byte records: {result['four_byte_records']}")
    print(f"Four-byte values: {result['four_byte_values']}")
    print(f"First byte histogram: {result['first_byte_histogram']}")
    print(f"First u16 BE histogram: {result['first_u16_be_histogram']}")
    print(f"Frame: {result['frame']}")
    print(f"Format groups: {result['format_groups']}")
    print(f"Payload prefixes: {result['payload_prefixes']}")
    print(f"Inner LZ4 matches: {result['inner_lz4_matches']}")
    print(
        "Inner LZ4 offsets: "
        f"{result['inner_lz4_offset_histogram']}"
    )
    print(
        "Exact inner LZ4 records: "
        f"{result['exact_inner_lz4_records']}"
    )

    if result["examples"]:
        print()
        print("Payload examples:")

        for example in result["examples"]:
            chunk = example["chunk"]
            print(
                f"  id={example['id']} "
                f"chunk=({chunk['x']},{chunk['y']},{chunk['z']}) "
                f"size={example['payload_size']} "
                f"prefix={example['payload_prefix_hex']}"
            )

    return 0


def run_terrain_tree_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_depth: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_tree_encoding(
            database,
            world_id=world_id,
            limit=limit,
            max_depth=max_depth,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print("Top tree hypotheses:")

    for model in result["models"][:top]:
        direction = (
            "1=child"
            if model["one_means_child"]
            else "0=child"
        )
        print(
            f"  mode={model['mode']} "
            f"depth={model['depth']} "
            f"{direction}: "
            f"exact={model['exact_records']}/{model['records']} "
            f"({model['exact_ratio']:.1%}), "
            f"nontrivial="
            f"{model['exact_nontrivial_records']}/"
            f"{model['nontrivial_records']} "
            f"({model['exact_nontrivial_ratio']:.1%})"
        )

    return 0


def run_terrain_codec_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_body_offset: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_codecs(
            database,
            world_id=world_id,
            limit=limit,
            max_body_offset=max_body_offset,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Framed records: {result['framed_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Target voxel bytes: {result['target_voxel_bytes']}")
    print(f"Body byte histograms: {result['body_byte_histograms']}")
    print("Top codec hypotheses:")

    for model in result["models"][:top]:
        print(
            f"  mode={model['mode']} "
            f"{model['name']}: "
            f"exact={model['exact_records']}/{model['records']} "
            f"({model['exact_ratio']:.1%}), "
            f"nontrivial="
            f"{model['exact_nontrivial_records']}/"
            f"{model['nontrivial_records']} "
            f"({model['exact_nontrivial_ratio']:.1%})"
        )

    return 0


def run_terrain_mask_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_offset: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_masks(
            database,
            world_id=world_id,
            limit=limit,
            max_offset=max_offset,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Framed records: {result['framed_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Voxel count: {result['voxel_count']}")
    print(f"Mask bytes: {result['mask_bytes']}")
    print(f"Packed width sizes: {result['packed_width_sizes']}")
    print(f"Direct width matches: {result['direct_width_matches']}")
    print(f"Plane buckets: {result['plane_buckets']}")
    print("Top mask hypotheses:")

    for model in result["models"][:top]:
        print(
            f"  mode={model['mode']} "
            f"offset=+{model['offset']} "
            f"{model['selected_bits']} "
            f"value_bits={model['value_bits']}: "
            f"exact={model['exact_records']}/"
            f"{model['candidates']} "
            f"({model['exact_ratio']:.1%})"
        )

    return 0


def run_terrain_density_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_byte_offset: int,
    max_pairs: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_density_streams(
            database,
            world_id=world_id,
            limit=limit,
            max_byte_offset=max_byte_offset,
            max_pairs=max_pairs,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Density bits: {result['density_bits']}")
    print(f"Voxel order: {result['voxel_order']}")
    print(f"Face sample axis: {result['face_sample_axis']}")
    print(f"Neighbor pairs: {result['neighbor_pairs']}")
    print("Top density hypotheses:")

    for model in result["models"][:top]:
        print(
            f"  mode={model['mode']} "
            f"byte=+{model['byte_offset']} "
            f"bit=+{model['bit_offset']} "
            f"order={model['bit_order']} "
            f"fill={model['fill']}: "
            f"observed-active="
            f"{model['observed_active_exact_samples']}/"
            f"{model['observed_active_samples']} "
            f"({model['observed_active_exact_ratio']:.1%}), "
            f"observed="
            f"{model['observed_exact_samples']}/"
            f"{model['observed_samples']} "
            f"({model['observed_exact_ratio']:.1%}), "
            f"coverage={model['observed_coverage']:.1%}, "
            f"active="
            f"{model['active_exact_samples']}/"
            f"{model['active_samples']} "
            f"({model['active_exact_ratio']:.1%}), "
            f"all={model['exact_ratio']:.1%}"
        )

    return 0


def run_terrain_data_probe(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_terrain_script_data(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned ScriptData rows: {result['scanned_records']}")
    print(f"Decoded envelopes: {result['decoded_envelopes']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Raw prefixes: {result['raw_prefixes']}")
    print(f"LUA records: {result['lua_records']}")

    if result["largest_lua_records"]:
        print()
        print("Largest LUA records:")
        for item in result["largest_lua_records"]:
            print(
                f"  rowid={item['row_id']} "
                f"raw={item['raw_size']} "
                f"compressed={item['compressed_size']} "
                f"flags={item['envelope_flags']} "
                f"key={item['envelope_key_hex']} "
                f"prefix={item['raw_prefix_hex']}"
            )

    return 0


def run_terrain_data(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = decode_terrain_data_candidates(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned ScriptData rows: {result['scanned_records']}")
    print(f"Decoded LUA tables: {result['decoded_tables']}")
    print(f"Envelope failures: {result['envelope_failures']}")
    print(f"LUA failures: {result['lua_failures']}")
    print(f"Terrain candidates: {result['terrain_candidates']}")

    if result["candidates"]:
        print()
        print("Terrain candidates:")
        for candidate in result["candidates"]:
            print(
                f"  rowid={candidate['row_id']} "
                f"raw={candidate['raw_size']} "
                f"key={candidate['sql_key_hex']}"
            )
            print(
                "    signals: "
                + ", ".join(candidate["signal_keys"])
            )
            print(
                "    keys: "
                + ", ".join(candidate["keys"])
            )
            for key, field in candidate["fields"].items():
                print(f"    {key}: {field}")

    return 0


def run_terrain_data_structure(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    depth: int,
    max_items: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_terrain_data_structure(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
            depth=depth,
            max_items=max_items,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned ScriptData rows: {result['scanned_records']}")
    print(f"Failures: {result['failures']}")

    candidate = result["candidate"]
    if candidate is None:
        print("Terrain candidate: none")
        return 0

    print(
        "Terrain candidate: "
        f"rowid={candidate['row_id']} "
        f"raw={candidate['raw_size']} "
        f"key={candidate['sql_key_hex']}"
    )
    print(f"Root keys: {candidate['root_keys']}")
    print(f"Scalar root: {candidate['scalar_root']}")

    for name, profile in candidate["fields"].items():
        print()
        print(f"[{name}]")
        print(f"  type: {profile['type']}")

        if profile["type"] != "table":
            print(f"  value: {profile.get('value')}")
            continue

        print(f"  items: {profile['items']}")
        print(f"  key types: {profile['key_types']}")
        print(f"  value types: {profile['value_types']}")
        print(
            "  nested signatures: "
            f"{profile['nested_signatures']}"
        )

        for example in profile["examples"]:
            print(
                f"  example key={example['key']} "
                f"type={example['value_type']}: "
                f"{example['value']}"
            )

    return 0


def run_underground_tunnels(
    save: Path,
    world_id: int,
    limit: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_underground_tunnels(
            database,
            world_id=world_id,
            limit=limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Terrain row: {result['row_id']}")
    print(f"Depth: {result['depth']}")
    print(f"World path: {result['world_path']}")
    print(f"Seed: {result['seed']}")
    print(f"Tunnels: {result['tunnels']}")
    print(f"Points: {result['points']}")
    print(f"Total 3D length: {result['total_length']:.1f} m")
    print(f"Tunnel types: {result['tunnel_types']}")
    print(f"Geometry bounds: {result.get('geometry_bounds')}")

    return 0


def run_underground_map(
    save: Path,
    world_id: int,
    output: Path,
    limit: int,
) -> int:
    database = SaveDatabase(save)

    try:
        result = write_underground_map(
            database,
            world_id=world_id,
            output=output,
            limit=limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(f"World: {result['world_id']}")
    print(f"Tunnels: {result['tunnels']}")
    print(f"Points: {result['points']}")
    print(f"Total 3D length: {result['total_length']:.1f} m")
    print(f"Tunnel types: {result['tunnel_types']}")
    print(f"Caves: {result['caves']['count']}")
    print(f"Pockets: {result['pockets']['count']}")
    print(f"Spawners: {result['spawners']['count']}")
    print(f"Spawner tags: {result['spawners']['tags']}")
    print(f"Tunnel bounds: {result.get('geometry_bounds')}")
    print(
        "Combined bounds: "
        f"{result.get('combined_geometry_bounds')}"
    )
    print(f"SVG: {result['output']}")

    return 0


def run_underground_graph(
    save: Path,
    world_id: int,
    limit: int,
    region_tolerance: float,
    endpoint_tolerance: float,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        graph = build_underground_graph(
            database,
            world_id=world_id,
            limit=limit,
            region_tolerance=region_tolerance,
            endpoint_tolerance=endpoint_tolerance,
        )
        result = (
            graph.to_dict()
            if as_json
            else graph.summary(top_hubs=top)
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Regions: {result['regions']}")
    print(f"Nodes: {result['nodes']}")
    print(f"Edges: {result['edges']}")
    print(f"Node kinds: {result['node_kinds']}")
    print(f"Tunnel types: {result['tunnel_types']}")
    print(f"Edge roles: {result['edge_roles']}")
    print(
        "Graph semantics: "
        f"corridors={result['corridor_edges']}, "
        f"veins={result['vein_edges']}, "
        f"unknown={result['unknown_edges']}"
    )
    print(
        "Navigation graph ready: "
        f"{result['navigation_graph_ready']}"
    )
    print(
        "Endpoint attachment: "
        f"regions={result['region_endpoints']}, "
        f"free={result['free_endpoints']}"
    )
    print(
        "Spawners: "
        f"attached={result['attached_spawners']}, "
        f"unattached={result['unattached_spawners']}"
    )
    print(
        "Connectivity: "
        f"all_components={result['connected_components']}, "
        f"active_components={result['active_components']}, "
        f"active_nodes={result['active_nodes']}, "
        f"largest_active={result['largest_active_component_nodes']} nodes, "
        f"isolated={result['isolated_nodes']}, "
        f"dead_ends={result['dead_ends']}, "
        f"self_loops={result['self_loops']}"
    )
    print(
        "Active component sizes: "
        f"{result['active_component_size_histogram']}"
    )
    print(f"Degree histogram: {result['degree_histogram']}")

    if result["top_hubs"]:
        print("Top graph hubs:")
        for node in result["top_hubs"]:
            print(
                f"  node={node['id']} "
                f"kind={node['kind']} "
                f"degree={node['degree']} "
                f"xyz=({node['x']}, {node['y']}, {node['z']}) "
                f"caves={node['caves']} "
                f"pockets={node['pockets']} "
                f"spawners={node['spawners']}"
            )

    return 0


def run_underground_tiles(
    save: Path,
    world_id: int,
    limit: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_underground_tiles(
            database,
            world_id=world_id,
            limit=limit,
            top=top,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Terrain row: {result['row_id']}")
    print(f"Catalog entries: {result['catalog_entries']}")
    print(
        "Tile list coverage: "
        f"{result['known_tile_list_entries']}/"
        f"{result['tile_list_entries']} known "
        f"({result['unknown_tile_list_entries']} unknown)"
    )
    print(
        "Placement coverage: "
        f"{result['known_placements']}/"
        f"{result['placements']} known "
        f"({result['unknown_placements']} unknown)"
    )
    print(f"Families: {result['family_counts']}")
    print(f"Name tags: {result['name_tag_counts']}")

    if result["notable_tiles"]:
        print()
        print("Notable tiles:")
        for tile in result["notable_tiles"]:
            tags = ",".join(tile["name_tags"]) or "-"
            print(
                f"  index={tile['tile_index']} "
                f"family={tile['family']} "
                f"tags={tags} "
                f"name={tile['name']} "
                f"uuid={tile['uuid']}"
            )

    if result["top_tiles"]:
        print()
        print("Most-used placements:")
        for tile in result["top_tiles"]:
            tags = ",".join(tile["name_tags"]) or "-"
            name = tile["name"] or "<unknown>"
            print(
                f"  count={tile['placements']} "
                f"index={tile['tile_index']} "
                f"kind={tile['piece_kind']} "
                f"family={tile['family'] or '-'} "
                f"tags={tags} "
                f"name={name}"
            )

    if result["unknown_tile_list"]:
        print()
        print("Unknown tile-list entries:")
        for tile in result["unknown_tile_list"]:
            print(
                f"  index={tile['tile_index']} "
                f"uuid={tile['uuid']}"
            )

    return 0


def run_underground_layout(
    save: Path,
    world_id: int,
    limit: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_underground_layout(
            database,
            world_id=world_id,
            limit=limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Terrain row: {result['row_id']}")
    print(f"Cave fragments: {result['cave_fragments']}")
    print(f"Logical structures: {result['logical_structures']}")
    print(f"Structure families: {result['structure_families']}")
    print(
        "Complete structures: "
        f"{result['complete_structures']}/"
        f"{result['logical_structures']}"
    )
    print(
        "Dimension-matched structures: "
        f"{result['dimension_matched_structures']}/"
        f"{result['logical_structures']}"
    )

    pocket_reconstruction = result["pocket_reconstruction"]
    print(f"Pocket fragments: {pocket_reconstruction['fragments']}")
    print(
        "Logical pocket placements: "
        f"{pocket_reconstruction['logical_placements']}"
    )
    print(
        "Split pocket placements: "
        f"{pocket_reconstruction['split_placements']}"
    )
    print(
        "Complete pocket placements: "
        f"{pocket_reconstruction['complete']}/"
        f"{pocket_reconstruction['logical_placements']}"
    )
    print(
        "Pocket source coverage: "
        f"{pocket_reconstruction['source_complete']}/"
        f"{pocket_reconstruction['logical_placements']}"
    )
    print(
        "Pocket dimension matches: "
        f"{pocket_reconstruction['dimensions_match']}/"
        f"{pocket_reconstruction['logical_placements']}"
    )
    print(
        "Pocket fragment histogram: "
        f"{pocket_reconstruction['fragment_count_histogram']}"
    )
    print(
        "Explicit passage placements: "
        f"{pocket_reconstruction['explicit_passage_placements']}"
    )
    print(
        "Pocket semantic counts: "
        f"{pocket_reconstruction['semantic_counts']}"
    )

    if result["structures"]:
        print()
        print("Logical cave/elevator structures:")
        for structure in result["structures"]:
            print(
                f"  id={structure['id']} "
                f"family={structure['family']} "
                f"name={structure['name']} "
                f"fragments={structure['fragments']}/"
                f"{structure['expected_fragments']} "
                f"rotation={structure['rotation']} "
                f"complete={structure['complete']} "
                f"dimensions_match={structure['dimensions_match']} "
                f"size={structure['size']} "
                f"bounds={structure['bounds']}"
            )

    if pocket_reconstruction["failure_examples"]:
        print()
        print("Pocket reconstruction failures:")
        for failure in pocket_reconstruction["failure_examples"]:
            print(
                f"  id={failure['id']} "
                f"name={failure['name']} "
                f"rotation={failure['rotation']} "
                f"fragments={failure['fragments']} "
                f"source_complete={failure['source_complete']} "
                f"source_overlap_chunks={failure['source_overlap_chunks']} "
                f"dimensions_match={failure['dimensions_match']} "
                f"origin_chunks={failure['origin_chunks']}"
            )

    return 0


def run_underground_topology(
    save: Path,
    world_id: int,
    limit: int,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        topology = build_layout_topology(
            database,
            world_id=world_id,
            limit=limit,
        )
        result = topology.summary(top=top)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Logical nodes: {result['nodes']}")
    print(f"Face contacts: {result['contacts']}")
    print(f"Families: {result['families']}")
    print(f"Semantic roles: {result['roles']}")
    print(f"Contact axes: {result['contact_axes']}")
    print(f"Contact pairs: {result['contact_pairs']}")
    print(
        "Face-contact connectivity: "
        f"components={result['components']}, "
        f"largest={result['largest_component']} nodes, "
        f"isolated={result['isolated_nodes']}"
    )
    print(f"Face-contact degree histogram: {result['degree_histogram']}")
    print(
        "Saved tunnel links: "
        f"{result['tunnel_links']} "
        f"types={result['tunnel_types']}"
    )
    print(f"Tunnel endpoint roles: {result['tunnel_pairs']}")
    print(
        "Tunnel endpoint attachment: "
        f"attached={result['attached_tunnel_endpoints']}, "
        f"unattached={result['unattached_tunnel_endpoints']}"
    )
    print(
        "Combined candidate connectivity: "
        f"components={result['combined_components']}, "
        f"largest={result['combined_largest_component']} nodes, "
        f"isolated={result['combined_isolated_nodes']}"
    )
    print(
        "Combined degree histogram: "
        f"{result['combined_degree_histogram']}"
    )
    print(
        "Horizontal-only face connectivity: "
        f"components={result['horizontal_components']}, "
        f"largest={result['horizontal_largest_component']} nodes, "
        f"isolated={result['horizontal_isolated_nodes']}"
    )
    print(
        "Horizontal + tunnels connectivity: "
        f"components={result['horizontal_combined_components']}, "
        f"largest={result['horizontal_combined_largest_component']} nodes, "
        f"isolated={result['horizontal_combined_isolated_nodes']}"
    )
    print(f"Elevator nodes: {result['elevator_nodes']}")
    print(
        "Elevator face-contact components: "
        f"{result['elevator_components']}"
    )
    print(
        "Elevator combined components: "
        f"{result['combined_elevator_components']}"
    )
    print(
        "Elevator reachable: "
        f"{result['elevator_reachable_nodes']} nodes "
        f"roles={result['elevator_reachable_roles']}"
    )

    if result["combined_isolated"]:
        print("Combined isolated nodes:")
        for node in result["combined_isolated"]:
            tags = ",".join(node["tags"]) or "-"
            print(
                f"  node={node['id']} "
                f"role={node['role']} "
                f"family={node['family']} "
                f"tags={tags} "
                f"center={node['center']} "
                f"name={node['name']}"
            )

    if result["top_hubs"]:
        print("Top layout hubs:")
        for node in result["top_hubs"]:
            print(
                f"  node={node['id']} "
                f"role={node['role']} "
                f"degree={node['degree']} "
                f"component={node['component']} "
                f"center={node['center']} "
                f"name={node['name']}"
            )

    return 0


def run_underground_portals(
    save: Path,
    world_id: int,
    limit: int,
    attach_tolerance: float,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_saved_tunnel_portals(
            database,
            world_id=world_id,
            limit=limit,
            attach_tolerance=attach_tolerance,
            top=top,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Logical nodes: {result['logical_nodes']}")
    print(f"Observed tunnel endpoints: {result['observed_endpoints']}")
    print(f"Nodes with endpoints: {result['nodes_with_endpoints']}")
    print(f"Inference methods: {result['methods']}")
    print(f"World exit faces: {result['world_faces']}")
    print(f"Canonical faces: {result['canonical_faces']}")
    print(f"Ray-distance buckets: {result['ray_distance_buckets']}")
    print(
        "Old nearest-face buckets: "
        f"{result['nearest_distance_buckets']}"
    )
    print(f"Endpoint roles: {result['endpoint_roles']}")

    if result["profiles"]:
        print()
        print("Canonical portal profiles:")
        for profile in result["profiles"]:
            tags = ",".join(profile["tags"]) or "-"
            print(
                f"  endpoints={profile['endpoints']} "
                f"placements={profile['placements_with_endpoints']} "
                f"rotations={profile['rotations']} "
                f"family={profile['family']} "
                f"tags={tags} "
                f"faces={profile['canonical_faces']} "
                f"name={profile['tile_name']}"
            )
            print(
                "    clusters4m: "
                f"{profile['portal_clusters_4m']}"
            )
            if profile["repeated_clusters_4m"]:
                print(
                    "    repeated4m: "
                    f"{profile['repeated_clusters_4m']}"
                )

    if result["furthest_ray_examples"]:
        print()
        print("Furthest endpoint-to-exit examples:")
        for endpoint in result["furthest_ray_examples"]:
            print(
                f"  tunnel={endpoint['tunnel_id']}:{endpoint['side']} "
                f"node={endpoint['node_id']} "
                f"method={endpoint['method']} "
                f"world_face={endpoint['world_face']} "
                f"canonical_face={endpoint['canonical_face']} "
                f"ray_distance={endpoint['ray_distance']} "
                f"canonical_uv=("
                f"{endpoint['canonical_u']}, "
                f"{endpoint['canonical_v']}) "
                f"rotation={endpoint['rotation']} "
                f"name={endpoint['tile_name']}"
            )

    return 0


def run_underground_node(
    save: Path,
    world_id: int,
    node_id: int,
    limit: int,
    attach_tolerance: float,
    tile: Path | None,
    socket_match_tolerance: float,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_underground_node(
            database,
            world_id=world_id,
            node_id=node_id,
            limit=limit,
            attach_tolerance=attach_tolerance,
            tile_path=tile,
            socket_match_tolerance=socket_match_tolerance,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    node = result["node"]
    print(
        f"World {result['world_id']} node {node['id']}: "
        f"role={node['role']} family={node['family']} "
        f"rotation={node['rotation']}"
    )
    print(f"  name={node['name']}")
    print(f"  uuid={node['tile_uuid']}")
    print(f"  tags={node['tags']}")
    print(f"  bounds={node['bounds']}")
    print(f"  center={node['center']}")

    print("  saved world portals:")
    if not result["saved_world_portals"]:
        print("    none")
    for portal in result["saved_world_portals"]:
        print(
            f"    portal={portal['portal_id']}:{portal['side']} "
            f"position={portal['position']} "
            f"rotation={portal['rotation']} "
            f"dimensions={portal['dimensions']}"
        )

    print("  observed tunnel endpoints:")
    if not result["observed_tunnel_endpoints"]:
        print("    none")
    for endpoint in result["observed_tunnel_endpoints"]:
        print(
            f"    tunnel={endpoint['tunnel_id']}:{endpoint['side']} "
            f"method={endpoint['method']} "
            f"endpoint={endpoint['endpoint']} "
            f"portal={endpoint['portal']} "
            f"world_face={endpoint['world_face']} "
            f"canonical={endpoint['canonical_face']} "
            f"uv=({endpoint['canonical_u']}, "
            f"{endpoint['canonical_v']}) "
            f"ray_distance={endpoint['ray_distance']}"
        )

    socket_matches = result["tile_socket_matches"]
    if socket_matches is not None:
        print("  tile socket matching:")
        print(
            f"    sockets={socket_matches['sockets']} "
            f"saved_endpoints={socket_matches['saved_endpoints']} "
            f"matched={socket_matches['matched']} "
            f"exact={socket_matches['exact_matches']} "
            f"near={socket_matches['near_matches']} "
            f"tolerance={socket_matches['socket_match_tolerance']}m"
        )
        for match in socket_matches["matches"]:
            print(
                f"    tunnel={match['tunnel_id']}:{match['tunnel_side']} "
                f"<-> cell={match['cell']} node={match['node']} "
                f"type={match['socket_type']} "
                f"tile_pos={match['tile_position']} "
                f"world_pos={match['world_position']} "
                f"error={match['distance']}m "
                f"quality={match['quality']}"
            )
        if socket_matches["unmatched_sockets"]:
            print(
                "    unmatched tile sockets="
                f"{len(socket_matches['unmatched_sockets'])}"
            )
        if socket_matches["unmatched_saved_endpoints"]:
            print(
                "    unmatched saved endpoints="
                f"{len(socket_matches['unmatched_saved_endpoints'])}"
            )

    return 0


def run_underground_navigation(
    save: Path,
    world_id: int,
    limit: int,
    attach_tolerance: float,
    min_template_placements: int,
    cluster_step: float,
    match_tolerance: float,
    top: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        graph = build_navigation_candidate_graph(
            database,
            world_id=world_id,
            limit=limit,
            attach_tolerance=attach_tolerance,
            min_template_placements=min_template_placements,
            cluster_step=cluster_step,
            match_tolerance=match_tolerance,
        )
        result = graph.summary(top=top)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Logical nodes: {result['nodes']}")
    print(f"Raw face contacts: {result['face_contacts']}")
    print(
        "Learned portal templates: "
        f"{result['learned_templates']} "
        f"across {result['learned_tile_types']} tile types"
    )
    print(
        "Portal-matched contacts: "
        f"{result['portal_matched_contacts']} "
        f"({result['portal_matches']} portal matches)"
    )
    print(f"Portal pair roles: {result['portal_pair_roles']}")
    print(
        "Edge evidence: "
        f"saved_tunnel_pairs={result['saved_tunnel_pairs']}, "
        f"portal_only={result['portal_only_pairs']}, "
        f"tunnel_only={result['tunnel_only_pairs']}, "
        f"both={result['both_pair_types']}, "
        f"navigation_pairs={result['navigation_pairs']}"
    )
    diagnostics = result["contact_diagnostics"]
    print(
        "Template coverage on face contacts: "
        f"both_tiles={diagnostics['both_tile_templates']}, "
        f"one_tile={diagnostics['one_tile_template']}, "
        f"none={diagnostics['no_tile_templates']}"
    )
    print(
        "Contact-face template coverage: "
        f"left={diagnostics['left_face_templates']}, "
        f"right={diagnostics['right_face_templates']}, "
        f"both={diagnostics['both_face_templates']}"
    )
    print(
        "Opposing portal min-distance buckets: "
        f"{diagnostics['min_distance_buckets']}"
    )
    print(
        "Both-face role pairs: "
        f"{diagnostics['both_face_roles']}"
    )

    transit_horizontal = result["transit_horizontal"]
    print(
        "Transit candidate (X/Y contacts + tunnels): "
        f"nodes={transit_horizontal['nodes']}, "
        f"contacts={transit_horizontal['contact_pairs']}, "
        f"tunnels={transit_horizontal['saved_tunnel_pairs']}, "
        f"pairs={transit_horizontal['candidate_pairs']}, "
        f"components={transit_horizontal['components']}, "
        f"largest={transit_horizontal['largest_component']}, "
        f"isolated={transit_horizontal['isolated_nodes']}"
    )
    print(
        "Transit elevator reach (X/Y): "
        f"{transit_horizontal['elevator_reachable_nodes']}/"
        f"{transit_horizontal['nodes']} "
        f"roles={transit_horizontal['elevator_reachable_roles']} "
        f"unreachable={transit_horizontal['elevator_unreachable_roles']}"
    )

    transit_all = result["transit_all_faces"]
    print(
        "Transit candidate (all face contacts + tunnels): "
        f"nodes={transit_all['nodes']}, "
        f"contacts={transit_all['contact_pairs']}, "
        f"tunnels={transit_all['saved_tunnel_pairs']}, "
        f"pairs={transit_all['candidate_pairs']}, "
        f"components={transit_all['components']}, "
        f"largest={transit_all['largest_component']}, "
        f"isolated={transit_all['isolated_nodes']}"
    )
    print(
        "Transit elevator reach (all faces): "
        f"{transit_all['elevator_reachable_nodes']}/"
        f"{transit_all['nodes']} "
        f"roles={transit_all['elevator_reachable_roles']} "
        f"unreachable={transit_all['elevator_unreachable_roles']}"
    )

    if diagnostics["closest_unmatched"]:
        print("Closest unmatched face contacts:")
        for contact in diagnostics["closest_unmatched"]:
            print(
                f"  nodes={contact['left']}<->{contact['right']} "
                f"axis={contact['axis']} "
                f"roles={contact['roles']} "
                f"faces={contact['left_face']}<->{contact['right_face']} "
                f"distance={contact['distance']} "
                f"left={contact['left_name']} "
                f"right={contact['right_name']}"
            )

    print(
        "Navigation candidate connectivity: "
        f"components={result['components']}, "
        f"largest={result['largest_component']} nodes, "
        f"isolated={result['isolated_nodes']}"
    )
    print(f"Elevator nodes: {result['elevator_nodes']}")
    print(
        "Elevator reachable: "
        f"{result['elevator_reachable_nodes']} nodes "
        f"roles={result['elevator_reachable_roles']}"
    )

    if result["isolated"]:
        print("Navigation-isolated nodes:")
        for node in result["isolated"]:
            tags = ",".join(node["tags"]) or "-"
            print(
                f"  node={node['id']} "
                f"role={node['role']} "
                f"family={node['family']} "
                f"tags={tags} "
                f"center={node['center']} "
                f"name={node['name']}"
            )

    if result["top_hubs"]:
        print("Top navigation hubs:")
        for node in result["top_hubs"]:
            print(
                f"  node={node['id']} "
                f"degree={node['degree']} "
                f"role={node['role']} "
                f"center={node['center']} "
                f"name={node['name']}"
            )

    return 0


def run_underground_route(
    save: Path,
    world_id: int,
    limit: int,
    target_node: int | None,
    target_tag: str | None,
    target_tunnel: str | None,
    include_vertical_contacts: bool,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        route, lookup = find_transit_route(
            database,
            world_id=world_id,
            limit=limit,
            include_vertical_contacts=include_vertical_contacts,
            target_node=target_node,
            target_tag=target_tag,
            target_tunnel_type=target_tunnel,
        )
        result = route.to_dict(lookup)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    mode = (
        "X/Y/Z contacts + saved tunnels"
        if include_vertical_contacts
        else "X/Y contacts + saved tunnels"
    )
    print(f"World: {result['world_id']}")
    print(f"Route model: {mode}")
    print(f"Start elevator node: {result['start_node']}")
    print(
        f"Start source: {result['start_source']} "
        f"point={result['start_point']} "
        f"portal={result['start_portal']}"
    )
    print(
        "Target: "
        f"{result['target_kind']}={result['target_value']} "
        f"node={result['target_node']}"
    )
    if result["target_tunnel"] is not None:
        tunnel = result["target_tunnel"]
        print(
            "Target tunnel: "
            f"id={tunnel['id']} "
            f"type={tunnel['type']} "
            f"length={tunnel['length']}m "
            f"entry_node={tunnel['entry_node']} "
            f"other_node={tunnel['other_node']}"
        )
    print(
        "Route evidence: "
        f"{result['route_evidence']} "
        f"(candidate_contacts={result['candidate_contacts']})"
    )
    print(
        "Candidate route cost to target entrance: "
        f"{result['total_cost']}m "
        f"segments={len(result['segments'])} "
        f"kinds={result['edge_kinds']} "
        f"breakdown={result['cost_breakdown']}"
    )

    print("Route segments:")
    for index, segment in enumerate(
        result["segments"],
        start=1,
    ):
        if segment["kind"] == "tunnel":
            detail = (
                f"tunnel id={segment['tunnel_id']} "
                f"type={segment['tunnel_type']}"
            )
        elif segment["kind"] == "intra_tile":
            detail = (
                f"inside tile node="
                f"{segment['layout_node_id']} (proxy)"
            )
        else:
            detail = (
                f"direct contact axis={segment['axis']}"
            )

        print(
            f"  [{index}] {detail} "
            f"cost={segment['weight']}m "
            f"from={segment['from_point']} "
            f"to={segment['to_point']}"
        )

    if result["target_tunnel"] is not None:
        tunnel = result["target_tunnel"]
        print(
            "Target entrance reached: "
            f"node={tunnel['entry_node']}. "
            f"Enter tunnel id={tunnel['id']} "
            f"type={tunnel['type']} "
            f"toward node={tunnel['other_node']}."
        )
        print(
            "If traversed end-to-end: "
            f"candidate cost={tunnel['full_traverse_cost']}m"
        )

    return 0


def run_underground_route_map(
    save: Path,
    world_id: int,
    output: Path,
    limit: int,
    target_node: int | None,
    target_tag: str | None,
    target_tunnel: str | None,
    include_vertical_contacts: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = write_underground_route_map(
            database,
            world_id=world_id,
            output=output,
            limit=limit,
            include_vertical_contacts=include_vertical_contacts,
            target_node=target_node,
            target_tag=target_tag,
            target_tunnel_type=target_tunnel,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(f"World: {result['world_id']}")
    print(f"Route map: {result['output']}")
    print(
        "Target: "
        f"{result['target_kind']}={result['target_value']} "
        f"node={result['target_node']}"
    )
    if result["target_tunnel"] is not None:
        tunnel = result["target_tunnel"]
        print(
            "Target tunnel: "
            f"id={tunnel['id']} "
            f"type={tunnel['type']} "
            f"entry_node={tunnel['entry_node']} "
            f"other_node={tunnel['other_node']}"
        )
    print(
        "Route evidence: "
        f"{result['route_evidence']} "
        f"(candidate_contacts={result['candidate_contacts']})"
    )
    print(
        "Candidate route cost to target entrance: "
        f"{result['total_cost']}m "
        f"segments={len(result['segments'])} "
        f"kinds={result['edge_kinds']} "
        f"breakdown={result['cost_breakdown']}"
    )
    return 0


def run_schema(save: Path, table: str) -> int:
    database = SaveDatabase(save)

    try:
        result = database.schema(table)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def run_sample(save: Path, table: str, limit: int) -> int:
    database = SaveDatabase(save)

    try:
        result = database.sample(table, limit)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "saves":
        raise SystemExit(run_saves(args.root, args.json))

    if args.command == "inspect":
        raise SystemExit(run_inspect(args.save, args.json))

    if args.command == "tile-probe":
        raise SystemExit(
            run_tile_probe(
                args.tile,
                args.json,
            )
        )

    if args.command == "tile-nodes":
        raise SystemExit(
            run_tile_nodes(
                args.tile,
                args.json,
            )
        )

    if args.command == "tile-voxel-probe":
        raise SystemExit(
            run_tile_voxel_probe(
                args.tile,
                args.cell,
                args.examples,
                args.json,
            )
        )

    if args.command == "tile-ground-survival":
        raise SystemExit(
            run_tile_ground_survival(
                args.plan, args.lua, args.game_script,
                args.install, args.remove, args.navigation_save, args.portal_id,
            )
        )

    if args.command == "tile-ground-lua":
        raise SystemExit(
            run_tile_ground_lua(args.plan, args.output)
        )

    if args.command == "tile-ground-compare":
        raise SystemExit(
            run_tile_ground_compare(args.plan, args.log, args.json)
        )

    if args.command == "tile-ground-profile":
        raise SystemExit(
            run_tile_ground_profile(
                args.plan, args.log, args.tile, args.z_margin, args.json,
            )
        )

    if args.command == "tile-ground-hypotheses":
        raise SystemExit(
            run_tile_ground_hypotheses(
                args.plan, args.log, args.tile, args.json,
                args.include_6_bit,
            )
        )

    if args.command == "tile-ground-byte-audit":
        raise SystemExit(
            run_tile_ground_byte_audit(
                args.plan, args.log, args.tile, args.radius, args.json,
            )
        )

    if args.command == "tile-ground-isovalue-audit":
        raise SystemExit(
            run_tile_ground_isovalue_audit(
                args.plan, args.log, args.tile,
                args.json, args.include_6_bit,
            )
        )

    if args.command == "tile-ground-normal-audit":
        raise SystemExit(
            run_tile_ground_normal_audit(
                args.plan, args.log, args.tile, args.json,
                args.include_6_bit,
            )
        )

    if args.command == "tile-ground-slope-audit":
        raise SystemExit(
            run_tile_ground_slope_audit(
                args.plan, args.log, args.tile, args.json,
                args.include_6_bit,
            )
        )

    if args.command == "tile-world-probe":
        raise SystemExit(
            run_tile_world_probe(
                args.save, args.tile, args.world, args.node,
                args.edge, args.density_bits, args.match_tolerance,
                args.json, args.output,
            )
        )

    if args.command == "tile-voxel-space":
        raise SystemExit(
            run_tile_voxel_space(
                args.tile,
                args.density_threshold,
                args.json,
                args.density_bits,
            )
        )

    if args.command == "tile-object-probe":
        raise SystemExit(
            run_tile_object_probe(
                args.tile,
                args.examples,
                args.json,
                args.from_socket,
                args.to_socket,
                args.radius,
                args.density_bits,
            )
        )

    if args.command == "tile-voxel-walk":
        raise SystemExit(
            run_tile_voxel_walk(
                args.tile,
                args.from_socket,
                args.to_socket,
                args.density_threshold,
                args.headroom,
                args.max_step,
                args.json,
                args.elevation_details,
                args.density_bits,
                args.socket_radius,
                args.max_surface_gradient,
            )
        )

    if args.command == "tile-chunk-probe":
        raise SystemExit(
            run_tile_chunk_probe(
                args.tile,
                args.kind,
                args.cell,
                args.full_hex,
                args.json,
            )
        )

    if args.command == "portal-probe":
        raise SystemExit(
            run_portal_probe(
                args.save,
                args.world,
                args.portal_id,
                args.json,
            )
        )

    if args.command == "portal-compare":
        raise SystemExit(
            run_portal_compare(
                args.save,
                args.world,
                args.side,
                args.json,
            )
        )

    if args.command == "worlds":
        raise SystemExit(run_worlds(args.save, args.json))

    if args.command == "graph":
        raise SystemExit(
            run_graph(
                args.save,
                args.underground,
                args.json,
            )
        )

    if args.command == "terrain":
        raise SystemExit(
            run_terrain(
                args.save,
                args.underground,
                args.json,
            )
        )

    if args.command == "terrain-probe":
        raise SystemExit(
            run_terrain_probe(
                args.save,
                args.world,
                args.limit,
                args.max_offset,
                args.json,
            )
        )

    if args.command == "terrain-structure":
        raise SystemExit(
            run_terrain_structure(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-layout":
        raise SystemExit(
            run_terrain_layout(
                args.save,
                args.world,
                args.limit,
                args.min_offset,
                args.max_offset,
                args.top,
                args.z_limit,
                args.json,
            )
        )

    if args.command == "terrain-chunks":
        raise SystemExit(
            run_terrain_chunks(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-map":
        raise SystemExit(
            run_terrain_map(
                args.save,
                args.world,
                args.output,
                args.limit,
            )
        )

    if args.command == "terrain-decode":
        raise SystemExit(
            run_terrain_decode(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-payload":
        raise SystemExit(
            run_terrain_payload(
                args.save,
                args.world,
                args.limit,
                args.max_offset,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-tree-probe":
        raise SystemExit(
            run_terrain_tree_probe(
                args.save,
                args.world,
                args.limit,
                args.max_depth,
                args.top,
                args.json,
            )
        )

    if args.command == "terrain-codec-probe":
        raise SystemExit(
            run_terrain_codec_probe(
                args.save,
                args.world,
                args.limit,
                args.max_body_offset,
                args.top,
                args.json,
            )
        )

    if args.command == "terrain-mask-probe":
        raise SystemExit(
            run_terrain_mask_probe(
                args.save,
                args.world,
                args.limit,
                args.max_offset,
                args.top,
                args.json,
            )
        )

    if args.command == "terrain-density-probe":
        raise SystemExit(
            run_terrain_density_probe(
                args.save,
                args.world,
                args.limit,
                args.max_byte_offset,
                args.max_pairs,
                args.top,
                args.json,
            )
        )

    if args.command == "terrain-data-probe":
        raise SystemExit(
            run_terrain_data_probe(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-data":
        raise SystemExit(
            run_terrain_data(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-data-structure":
        raise SystemExit(
            run_terrain_data_structure(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.depth,
                args.max_items,
                args.json,
            )
        )

    if args.command == "underground-tunnels":
        raise SystemExit(
            run_underground_tunnels(
                args.save,
                args.world,
                args.limit,
                args.json,
            )
        )

    if args.command == "underground-map":
        raise SystemExit(
            run_underground_map(
                args.save,
                args.world,
                args.output,
                args.limit,
            )
        )

    if args.command == "underground-graph":
        raise SystemExit(
            run_underground_graph(
                args.save,
                args.world,
                args.limit,
                args.region_tolerance,
                args.endpoint_tolerance,
                args.top,
                args.json,
            )
        )

    if args.command == "underground-tiles":
        raise SystemExit(
            run_underground_tiles(
                args.save,
                args.world,
                args.limit,
                args.top,
                args.json,
            )
        )

    if args.command == "underground-layout":
        raise SystemExit(
            run_underground_layout(
                args.save,
                args.world,
                args.limit,
                args.json,
            )
        )

    if args.command == "underground-topology":
        raise SystemExit(
            run_underground_topology(
                args.save,
                args.world,
                args.limit,
                args.top,
                args.json,
            )
        )

    if args.command == "underground-portals":
        raise SystemExit(
            run_underground_portals(
                args.save,
                args.world,
                args.limit,
                args.attach_tolerance,
                args.top,
                args.json,
            )
        )

    if args.command == "underground-node":
        raise SystemExit(
            run_underground_node(
                args.save,
                args.world,
                args.node,
                args.limit,
                args.attach_tolerance,
                args.tile,
                args.socket_match_tolerance,
                args.json,
            )
        )

    if args.command == "underground-navigation":
        raise SystemExit(
            run_underground_navigation(
                args.save,
                args.world,
                args.limit,
                args.attach_tolerance,
                args.min_template_placements,
                args.cluster_step,
                args.match_tolerance,
                args.top,
                args.json,
            )
        )

    if args.command == "underground-route":
        raise SystemExit(
            run_underground_route(
                args.save,
                args.world,
                args.limit,
                args.node,
                args.tag,
                args.tunnel,
                args.include_vertical_contacts,
                args.json,
            )
        )

    if args.command == "underground-route-map":
        raise SystemExit(
            run_underground_route_map(
                args.save,
                args.world,
                args.output,
                args.limit,
                args.node,
                args.tag,
                args.tunnel,
                args.include_vertical_contacts,
            )
        )

    if args.command == "schema":
        raise SystemExit(run_schema(args.save, args.table))

    if args.command == "sample":
        raise SystemExit(run_sample(args.save, args.table, args.limit))


if __name__ == "__main__":
    main()