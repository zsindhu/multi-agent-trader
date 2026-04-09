"""
Breadth Checkpoint — Backfill checkpoint file management.

Stores the set of symbols that have been successfully backfilled so
the process can resume after interruption. Uses atomic file writes
(write to temp, then rename) to avoid corruption.
"""
import json
import os
import tempfile
from loguru import logger


def load_checkpoint(path: str) -> set[str]:
    """Read the checkpoint file and return the set of completed symbols."""
    try:
        with open(path) as f:
            data = json.load(f)
        symbols = set(data) if isinstance(data, list) else set()
        return symbols
    except FileNotFoundError:
        return set()
    except Exception as e:
        logger.warning(f"[Checkpoint] Failed to load {path}: {e}")
        return set()


def save_checkpoint(path: str, completed_symbols: set[str]) -> None:
    """Write the set of completed symbols to the checkpoint file atomically."""
    try:
        dir_name = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(sorted(completed_symbols), f)
            os.replace(tmp_path, path)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error(f"[Checkpoint] Failed to save {path}: {e}")


def clear_checkpoint(path: str) -> None:
    """Delete the checkpoint file if it exists."""
    try:
        os.unlink(path)
        logger.info(f"[Checkpoint] Cleared {path}")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"[Checkpoint] Failed to clear {path}: {e}")
