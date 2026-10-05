# SM Atlas

Interactive world and save explorer for **Scrap Mechanic**.

Reads Survival save files locally and never modifies the original save.

## Status

**v0.1 — Save inspection**

- validate SQLite saves;
- inspect tables and row counts;
- detect known Scrap Mechanic structures;
- inspect saves through a CLI.

## Stack

Python 3.12+ · SQLite · pytest

## Run

```bash
pip install -e ".[dev]"
sm-atlas inspect path/to/save.db
pytest
```

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
