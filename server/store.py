"""JSON files in server/data/, written atomically. Standard library only."""

import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent / "data")
MEDIA_DIR = DATA_DIR / "media"

# One lock for every data file: the files are small and writes are rare.
LOCK = threading.RLock()


def read_json(name, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name, value):
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def exists(name):
    return (DATA_DIR / name).exists()
