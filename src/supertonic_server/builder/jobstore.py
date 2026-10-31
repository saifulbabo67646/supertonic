"""On-disk job records: ``<root>/<id>/job.json`` written atomically, loaded and pruned at start."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from supertonic_server.builder.models import Job

logger = logging.getLogger(__name__)

REFERENCE = "reference.wav"
WORKING_FILES = (REFERENCE, "style.json", "report.json", "STOP")
"""Files a job needs only while it is queued or running."""
PRUNE_AFTER = timedelta(days=7)
"""Finished jobs older than this are removed from disk at start."""


def now_iso() -> str:
    """The current UTC time, ISO-8601."""
    return datetime.now(UTC).isoformat()


def read_style(folder: Path) -> dict[str, Any]:
    """The worker's ``style.json`` for the job in ``folder``."""
    style: dict[str, Any] = json.loads((folder / "style.json").read_text(encoding="utf-8"))
    return style


def discard_working_files(folder: Path) -> None:
    """Remove :data:`WORKING_FILES`; failures are logged, never raised."""
    for name in WORKING_FILES:
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("job %s: could not remove %s: %s", folder.name, name, exc)


def write_job(folder: Path, job: Job) -> None:
    """Write ``folder/job.json`` atomically (temp file, then rename)."""
    tmp = folder / "job.json.tmp"
    tmp.write_text(json.dumps(job.to_dict(), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / "job.json")


def _mtime(folder: Path) -> datetime:
    """Newest modification time of ``folder`` and its direct entries."""
    stamps = [folder.stat().st_mtime]
    for entry in folder.iterdir():
        try:
            stamps.append(entry.lstat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(max(stamps), UTC)


def _created(job: Job, folder: Path) -> datetime:
    """``created_at`` as an aware time (naive means UTC); unparseable falls back to mtime."""
    try:
        created = datetime.fromisoformat(job.created_at)
    except (TypeError, ValueError):
        return _mtime(folder)
    return created if created.tzinfo is not None else created.replace(tzinfo=UTC)


def _remove(folder: Path, why: str) -> None:
    logger.info("pruning job folder %s (%s)", folder.name, why)
    shutil.rmtree(folder, ignore_errors=True)


def load_jobs(root: Path, max_age: timedelta) -> list[Job]:
    """Read every job under ``root``, removing folders older than ``max_age``.

    Only direct, non-symlink sub-directories of ``root`` are considered, so nothing outside
    it is ever touched. A job's id is its folder name. Unreadable folders are skipped, and
    pruned once their newest file is older than ``max_age``.
    """
    cutoff = datetime.now(UTC) - max_age
    jobs: list[Job] = []
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            data = json.loads((folder / "job.json").read_text(encoding="utf-8"))
            data["id"] = folder.name
            job = Job.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                stale = _mtime(folder) < cutoff
            except OSError:
                stale = False
            if stale:
                _remove(folder, f"unreadable and older than {max_age.days} days")
            else:
                logger.warning("skipping unreadable job folder %s: %s", folder.name, exc)
            continue
        try:
            stale = _created(job, folder) < cutoff
        except OSError:
            stale = False
        if stale:
            _remove(folder, f"older than {max_age.days} days")
            continue
        jobs.append(job)
    return jobs
