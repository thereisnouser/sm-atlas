# SM Atlas

Interactive world and save explorer for **Scrap Mechanic**.

Reads Survival save files locally and never modifies the original save.

## Status

**v0.1 — Save inspection**

- find local Survival saves;
- validate SQLite saves;
- inspect table schemas and sample rows;
- detect known Scrap Mechanic structures.

## Stack

Python 3.12+ · SQLite · pytest

## Run

```bash
pip install -e ".[dev]"
sm-atlas saves
sm-atlas inspect path/to/save.db
sm-atlas schema path/to/save.db GenericData
sm-atlas sample path/to/save.db GenericData
pytest
```

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
