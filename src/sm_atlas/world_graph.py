from __future__ import annotations

from dataclasses import dataclass

from .database import SaveDatabase
from .portals import PortalInfo, discover_portals
from .worlds import WorldInfo, discover_worlds

UNKNOWN_WORLD_ID = 65535


@dataclass(frozen=True)
class GraphEndpoint:
    world_id: int
    label: str
    kind: str
    known: bool
    x: int
    y: int
    position: tuple[float, float, float] | None = None
    rotation: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "label": self.label,
            "kind": self.kind,
            "known": self.known,
            "x": self.x,
            "y": self.y,
            "position": (
                None
                if self.position is None
                else list(self.position)
            ),
            "rotation": (
                None
                if self.rotation is None
                else list(self.rotation)
            ),
        }


@dataclass(frozen=True)
class GraphConnection:
    portal_id: int
    a: GraphEndpoint
    b: GraphEndpoint
    dimensions: tuple[float, float, float] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "dimensions": (
                None
                if self.dimensions is None
                else list(self.dimensions)
            ),
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
        }


@dataclass(frozen=True)
class WorldGraph:
    worlds: list[WorldInfo]
    connections: list[GraphConnection]

    def to_dict(self) -> dict[str, object]:
        return {
            "worlds": [world.to_dict() for world in self.worlds],
            "connections": [
                connection.to_dict()
                for connection in self.connections
            ],
        }


def _endpoint(
    world_map: dict[int, WorldInfo],
    world_id: int,
    x: int,
    y: int,
    position: tuple[float, float, float] | None = None,
    rotation: tuple[float, float, float, float] | None = None,
) -> GraphEndpoint:
    world = world_map.get(world_id)

    if world is None:
        label = (
            "unresolved"
            if world_id == UNKNOWN_WORLD_ID
            else f"World {world_id}"
        )
        return GraphEndpoint(
            world_id=world_id,
            label=label,
            kind="unknown",
            known=False,
            x=x,
            y=y,
            position=position,
            rotation=rotation,
        )

    return GraphEndpoint(
        world_id=world_id,
        label=world.label,
        kind=world.kind,
        known=True,
        x=x,
        y=y,
        position=position,
        rotation=rotation,
    )


def build_world_graph(
    database: SaveDatabase,
    *,
    underground_only: bool = False,
) -> WorldGraph:
    worlds = discover_worlds(database)
    world_map = {world.world_id: world for world in worlds}
    portals = discover_portals(database)

    connections: list[GraphConnection] = []

    for portal in portals:
        decoded = portal.decoded
        position_a = (
            None
            if decoded is None
            else decoded.position_a
        )
        rotation_a = (
            None
            if decoded is None
            else decoded.rotation_a
        )
        position_b = (
            None
            if decoded is None
            else decoded.position_b
        )
        rotation_b = (
            None
            if decoded is None
            else decoded.rotation_b
        )

        connection = GraphConnection(
            portal_id=portal.portal_id,
            dimensions=(
                None
                if decoded is None
                else decoded.dimensions
            ),
            a=_endpoint(
                world_map,
                portal.world_id_a,
                portal.x_a,
                portal.y_a,
                position_a,
                rotation_a,
            ),
            b=_endpoint(
                world_map,
                portal.world_id_b,
                portal.x_b,
                portal.y_b,
                position_b,
                rotation_b,
            ),
        )

        if underground_only and (
            connection.a.kind != "underground"
            and connection.b.kind != "underground"
        ):
            continue

        connections.append(connection)

    return WorldGraph(
        worlds=worlds,
        connections=connections,
    )
