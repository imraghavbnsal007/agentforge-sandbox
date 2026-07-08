"""Safe extraction of archives found in a cloned repo, for analysis only.

Extracted files land in <root>/.extracted/<archive-name>/ so the fact
collector sees them like ordinary files. The whole clone (extraction
included) is a temp dir that is deleted after analysis — extracted files are
never committed or published.
"""

import logging
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

EXTRACT_DIR_NAME = ".extracted"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024  # compressed
MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
MAX_MEMBERS = 2000

ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")


class ArchiveError(Exception):
    pass


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(ARCHIVE_SUFFIXES)


def _safe_target(dest: Path, member_name: str) -> Path | None:
    """Resolve a member path inside dest; None if it escapes (zip-slip)."""
    target = (dest / member_name).resolve()
    if not target.is_relative_to(dest.resolve()):
        return None
    return target


def _extract_zip(archive: Path, dest: Path) -> int:
    count = 0
    total = 0
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBERS:
            raise ArchiveError(f"{archive.name}: too many members ({len(members)})")
        for member in members:
            if member.is_dir():
                continue
            total += member.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ArchiveError(f"{archive.name}: uncompressed size cap exceeded")
            target = _safe_target(dest, member.filename)
            if target is None:
                logger.warning("Skipping zip-slip path %r in %s", member.filename, archive)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                out.write(src.read())
            count += 1
    return count


def _extract_tar(archive: Path, dest: Path) -> int:
    count = 0
    total = 0
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        if len(members) > MAX_MEMBERS:
            raise ArchiveError(f"{archive.name}: too many members ({len(members)})")
        for member in members:
            if not member.isfile():
                continue  # skip dirs, symlinks, devices
            total += member.size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ArchiveError(f"{archive.name}: uncompressed size cap exceeded")
            target = _safe_target(dest, member.name)
            if target is None:
                logger.warning("Skipping tar-slip path %r in %s", member.name, archive)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with open(target, "wb") as out:
                out.write(src.read())
            count += 1
    return count


def extract_archives(root: Path) -> list[tuple[str, int]]:
    """Extract every supported archive under root (one level; archives inside
    archives are not recursed). Returns [(archive_rel_path, files_extracted)].
    """
    results: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _is_archive(path):
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in (EXTRACT_DIR_NAME, ".git"):
            continue
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            logger.warning("Skipping oversized archive %s", rel)
            continue
        dest = root / EXTRACT_DIR_NAME / rel.as_posix().replace("/", "__")
        dest.mkdir(parents=True, exist_ok=True)
        try:
            if path.name.lower().endswith(".zip"):
                count = _extract_zip(path, dest)
            else:
                count = _extract_tar(path, dest)
        except (zipfile.BadZipFile, tarfile.TarError, ArchiveError, OSError) as exc:
            logger.warning("Could not extract %s: %s", rel, exc)
            continue
        results.append((rel.as_posix(), count))
    return results
