"""Deterministic repository insights: project type, entry points, API routes,
logical map, and health score. No LLM involvement — everything is grounded
in files that exist, and unknowns say so explicitly.
"""

import re
from pathlib import Path

from app.services.repo_facts import RepoFacts, read_text_safely
from app.services.sql_analyzer import SqlSchema

UNKNOWN = "Unable to determine from repository."


def detect_project_type(facts: RepoFacts, sql: SqlSchema | None) -> str:
    langs = set(facts.languages)
    fw = set(facts.frameworks)
    if sql and sql.tables and langs <= {"SQL"}:
        return "SQL database schema project"
    if sql and sql.tables and not (langs - {"SQL", "Shell"}):
        return "SQL database schema project"
    if "FastAPI" in fw:
        return "Python web service (FastAPI)"
    if "Django" in fw:
        return "Python web application (Django)"
    if "Flask" in fw:
        return "Python web application (Flask)"
    if "Next.js" in fw:
        return "Next.js web application"
    if "React" in fw:
        return "React application"
    if "Spring Boot" in fw:
        return "Java service (Spring Boot)"
    if any(f.endswith("AndroidManifest.xml") for f in facts.files):
        return "Android application" + (" (Kotlin)" if "Kotlin" in langs else "")
    if "Express" in fw or "NestJS" in fw:
        return "Node.js service"
    if "Python" in langs and facts.test_command:
        return "Python project"
    if langs:
        return f"{facts.languages[0]} project"
    return UNKNOWN


def detect_entry_points(facts: RepoFacts) -> list[str]:
    candidates = (
        "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "index.ts",
        "index.js", "server.js", "main.go", "Main.java", "main.rs",
        "src/main.py", "src/index.ts", "src/index.js", "app/main.py",
    )
    found = []
    for f in facts.files:
        base = f.rsplit("/", 1)[-1]
        if f in candidates or base in ("main.py", "manage.py", "server.js", "main.go"):
            found.append(f)
    return sorted(set(found))[:10]


ROUTE_RE = re.compile(
    r"@(?:app|router|api_router|blueprint|bp)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']"
)
DJANGO_PATH_RE = re.compile(r"\bpath\(\s*[\"']([^\"']*)[\"']")
SPRING_MAPPING_RE = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']"
)


def detect_api_routes(root: Path, facts: RepoFacts) -> list[dict]:
    routes: list[dict] = []
    for rel in facts.files:
        if not rel.endswith((".py", ".java", ".kt")):
            continue
        text = read_text_safely(root, rel)
        if text is None:
            continue
        for m in ROUTE_RE.finditer(text):
            routes.append({"method": m.group(1).upper(), "path": m.group(2), "file": rel})
        if rel.endswith("urls.py"):
            for m in DJANGO_PATH_RE.finditer(text):
                routes.append({"method": "ANY", "path": "/" + m.group(1), "file": rel})
        for m in SPRING_MAPPING_RE.finditer(text):
            routes.append({"method": m.group(1).upper(), "path": m.group(2), "file": rel})
        if len(routes) >= 100:
            break
    return routes


def _node(name: str, children: list | None = None) -> dict:
    node: dict = {"name": name}
    if children:
        node["children"] = children
    return node


def build_repo_map(facts: RepoFacts, sql: SqlSchema | None, routes: list[dict]) -> list[dict]:
    tree: list[dict] = []

    if sql:
        db_children = []
        if sql.tables:
            db_children.append(
                _node("Tables", [_node(t.name) for t in sql.tables])
            )
        if sql.views:
            db_children.append(_node("Views", [_node(v["name"]) for v in sql.views]))
        if sql.procedures or sql.functions:
            db_children.append(
                _node(
                    "Procedures & functions",
                    [_node(p["name"]) for p in sql.procedures + sql.functions],
                )
            )
        if sql.triggers:
            db_children.append(
                _node("Triggers", [_node(t["name"]) for t in sql.triggers])
            )
        if sql.indexes:
            db_children.append(
                _node("Indexes", [_node(i["name"]) for i in sql.indexes])
            )
        if db_children:
            tree.append(_node("Database", db_children))

    if routes:
        by_file: dict[str, list[str]] = {}
        for r in routes[:40]:
            by_file.setdefault(r["file"], []).append(f"{r['method']} {r['path']}")
        tree.append(
            _node(
                "API routes",
                [_node(f, [_node(x) for x in xs]) for f, xs in by_file.items()],
            )
        )

    # React/Next pages and components, when present.
    pages = [f for f in facts.files if re.search(r"(^|/)(pages|app)/.*\.(tsx|jsx)$", f)]
    components = [f for f in facts.files if re.search(r"(^|/)components/.*\.(tsx|jsx)$", f)]
    if pages:
        tree.append(_node("Pages", [_node(p) for p in sorted(pages)[:20]]))
    if components:
        tree.append(_node("Components", [_node(c) for c in sorted(components)[:20]]))

    # Generic top-level structure for whatever remains.
    top: dict[str, list[str]] = {}
    for f in facts.files:
        if f.startswith(".extracted/"):
            continue
        parts = f.split("/")
        if len(parts) == 1:
            top.setdefault("(root files)", []).append(f)
        else:
            top.setdefault(parts[0] + "/", []).append("/".join(parts[1:]))
    structure_children = []
    for folder, children in sorted(top.items()):
        structure_children.append(
            _node(folder, [_node(c) for c in sorted(children)[:12]])
        )
    if structure_children:
        tree.append(_node("Folders", structure_children))

    docs = [f for f in facts.files if f.lower().startswith("readme")]
    if docs:
        tree.append(_node("Documentation", [_node(d) for d in docs]))
    return tree


def score_health(facts: RepoFacts, sql: SqlSchema | None, root: Path) -> dict:
    """Five deterministic sub-scores with explicit reasons."""
    breakdown: dict[str, dict] = {}

    # Structure
    dirs = {f.split("/")[0] for f in facts.files if "/" in f and not f.startswith(".extracted/")}
    root_files = [f for f in facts.files if "/" not in f]
    if len(dirs) >= 2:
        structure, why = 80, f"Code is organized into {len(dirs)} top-level folders."
    elif len(dirs) == 1:
        structure, why = 65, "One top-level folder; most files grouped."
    elif len(root_files) <= 6:
        structure, why = 55, f"Flat layout with {len(root_files)} root files — acceptable for a small project."
    else:
        structure, why = 35, f"{len(root_files)} files sit at the repository root with no folder structure."
    breakdown["structure"] = {"score": structure, "reason": why}

    # Documentation
    readme_len = len(facts.readme)
    if readme_len > 1500:
        doc, why = 80, f"README present with substantial content ({readme_len} chars)."
    elif readme_len > 300:
        doc, why = 60, f"README present but brief ({readme_len} chars)."
    elif readme_len > 0:
        doc, why = 40, "README exists but is minimal."
    else:
        doc, why = 15, "No README found."
    breakdown["documentation"] = {"score": doc, "reason": why}

    # Testing
    test_files = [f for f in facts.files if re.search(r"(^|/)tests?/|test_|_test\.", f)]
    if facts.test_command and test_files:
        testing, why = 80, f"{len(test_files)} test file(s) and a runnable test command ({facts.test_command})."
    elif facts.test_command:
        testing, why = 55, f"A test command exists ({facts.test_command}) but few recognizable test files."
    elif sql and sql.tables:
        testing, why = 20, "No automated tests: SQL schema has no test harness or verification scripts."
    else:
        testing, why = 20, "No automated test command or test files detected."
    breakdown["testing"] = {"score": testing, "reason": why}

    # Maintainability
    big_files = 0
    for rel in facts.files[:100]:
        text = read_text_safely(root, rel)
        if text and text.count("\n") > 600:
            big_files += 1
    if sql and sql.tables:
        checks = sum(len(t.checks) for t in sql.tables)
        fks = sum(len(t.foreign_keys) for t in sql.tables)
        pks = sum(1 for t in sql.tables if t.primary_key)
        maint = min(85, 35 + pks * 5 + min(fks, 6) * 3 + min(checks, 6) * 3)
        why = (
            f"Schema integrity: {pks}/{len(sql.tables)} tables have primary keys, "
            f"{fks} foreign keys, {checks} CHECK constraints."
        )
    elif big_files:
        maint, why = 45, f"{big_files} file(s) exceed 600 lines — consider splitting."
    else:
        maint, why = 70, "Files are reasonably sized; no oversized modules detected."
    breakdown["maintainability"] = {"score": maint, "reason": why}

    # Security
    risky = [
        f for f in facts.files
        if re.search(r"(^|/)\.env|secret|credential|\.pem$|\.key$", f.lower())
    ]
    grants = False
    if sql:
        for rel in facts.files:
            if rel.endswith(".sql"):
                text = read_text_safely(root, rel) or ""
                if re.search(r"(?i)\bGRANT\s+ALL\b|IDENTIFIED\s+BY\s+\S+", text):
                    grants = True
    if risky:
        sec, why = 25, f"Potential secret-bearing files committed: {', '.join(risky[:3])}."
    elif grants:
        sec, why = 45, "SQL contains GRANT ALL or hardcoded credentials (IDENTIFIED BY)."
    else:
        sec, why = 75, "No committed secrets or obvious credential patterns detected."
    breakdown["security"] = {"score": sec, "reason": why}

    overall = round(sum(v["score"] for v in breakdown.values()) / len(breakdown))
    return {"overall": overall, "breakdown": breakdown}
