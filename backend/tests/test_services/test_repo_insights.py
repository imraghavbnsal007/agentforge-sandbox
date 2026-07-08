from pathlib import Path

from app.services.repo_facts import collect_repo_facts
from app.services.repo_insights import (
    UNKNOWN,
    build_repo_map,
    detect_api_routes,
    detect_entry_points,
    detect_project_type,
    score_health,
)
from app.services.sql_analyzer import analyze_sql

DDL = """
CREATE TABLE booking (bookingid NUMBER(7) NOT NULL);
ALTER TABLE booking ADD CONSTRAINT booking_pk PRIMARY KEY ( bookingid );
CREATE OR REPLACE VIEW v1 AS SELECT * FROM booking;
"""


def _sql_repo(root: Path):
    (root / "Project_ddl.sql").write_text(DDL)
    (root / "README.md").write_text("# Burger Shack\n" + "requirements " * 200)


def test_sql_project_type_and_map(tmp_path: Path):
    _sql_repo(tmp_path)
    facts = collect_repo_facts(tmp_path)
    schema = analyze_sql({"Project_ddl.sql": DDL})

    assert detect_project_type(facts, schema) == "SQL database schema project"

    tree = build_repo_map(facts, schema, [])
    database = next(n for n in tree if n["name"] == "Database")
    tables = next(c for c in database["children"] if c["name"] == "Tables")
    assert [t["name"] for t in tables["children"]] == ["booking"]
    views = next(c for c in database["children"] if c["name"] == "Views")
    assert [v["name"] for v in views["children"]] == ["v1"]


def test_empty_repo_type_is_explicit_unknown(tmp_path: Path):
    (tmp_path / "data.bin").write_bytes(b"\x00\x01")
    facts = collect_repo_facts(tmp_path)
    assert detect_project_type(facts, None) == UNKNOWN


def test_fastapi_routes_and_entry_points(tmp_path: Path):
    (tmp_path / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n\n'
        '@app.get("/health")\ndef health(): ...\n\n'
        '@app.post("/api/v1/tasks")\ndef create(): ...\n'
    )
    facts = collect_repo_facts(tmp_path)
    routes = detect_api_routes(tmp_path, facts)
    assert {(r["method"], r["path"]) for r in routes} == {
        ("GET", "/health"),
        ("POST", "/api/v1/tasks"),
    }
    assert detect_entry_points(facts) == ["main.py"]


def test_health_score_structure(tmp_path: Path):
    _sql_repo(tmp_path)
    facts = collect_repo_facts(tmp_path)
    schema = analyze_sql({"Project_ddl.sql": DDL})
    health = score_health(facts, schema, tmp_path)

    assert 0 <= health["overall"] <= 100
    assert set(health["breakdown"]) == {
        "structure", "documentation", "testing", "maintainability", "security",
    }
    for part in health["breakdown"].values():
        assert 0 <= part["score"] <= 100
        assert part["reason"]
    # SQL project with no tests scores low on testing, with the reason saying so.
    assert health["breakdown"]["testing"]["score"] <= 25
    assert "test" in health["breakdown"]["testing"]["reason"].lower()
