import tarfile
import zipfile
from pathlib import Path

from app.services.archive_extractor import extract_archives
from app.services.repo_facts import collect_repo_facts


def test_zip_extraction_feeds_fact_collection(tmp_path: Path):
    (tmp_path / "README.md").write_text("# SQL project\n")
    with zipfile.ZipFile(tmp_path / "DataBase Project.zip", "w") as zf:
        zf.writestr("project/schema.sql", "CREATE TABLE t (id INT PRIMARY KEY);")
        zf.writestr("project/notes.txt", "hello")

    results = extract_archives(tmp_path)
    assert results == [("DataBase Project.zip", 2)]

    facts = collect_repo_facts(tmp_path)
    extracted_sql = [f for f in facts.files if f.endswith("schema.sql")]
    assert extracted_sql and extracted_sql[0].startswith(".extracted/")
    assert "SQL" in facts.languages


def test_tar_gz_extraction(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.sql").write_text("CREATE TABLE x (id INT);")
    with tarfile.open(tmp_path / "bundle.tar.gz", "w:gz") as tf:
        tf.add(src / "a.sql", arcname="inner/a.sql")

    results = extract_archives(tmp_path)
    assert ("bundle.tar.gz", 1) in results
    assert (tmp_path / ".extracted" / "bundle.tar.gz" / "inner" / "a.sql").is_file()


def test_zip_slip_is_blocked(tmp_path: Path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", "pwned")
        zf.writestr("ok.txt", "fine")

    results = extract_archives(tmp_path)
    # Only the safe member is extracted; nothing escapes tmp_path.
    assert results == [("evil.zip", 1)]
    assert not (tmp_path.parent / "escape.txt").exists()
    assert not (tmp_path.parent.parent / "escape.txt").exists()


def test_corrupt_archive_is_skipped(tmp_path: Path):
    (tmp_path / "broken.zip").write_bytes(b"this is not a zip")
    assert extract_archives(tmp_path) == []
