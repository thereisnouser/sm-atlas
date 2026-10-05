# SM Atlas

Interactive world and save explorer for **Scrap Mechanic**.

Reads Survival save files locally and never modifies the original save.

## Status

**v0.1 — Save inspection**

- find local Survival saves;
- discover worlds and portal connections;
- decode confident voxel chunk coordinates;
- render voxel chunk occupancy maps;
- inspect table schemas and sample rows.

## Stack

Python 3.12+ · SQLite · pytest

## Run

```bash
pip install -e ".[dev]"
sm-atlas saves
sm-atlas worlds path/to/save.db
sm-atlas graph path/to/save.db
sm-atlas terrain path/to/save.db
sm-atlas terrain-map path/to/save.db --world 23 --output d6.svg
pytest
```

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
