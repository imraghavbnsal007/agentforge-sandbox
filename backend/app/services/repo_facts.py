"""Deterministic repository fact collection: languages, package manager,
frameworks, build/test commands, important files. No API calls, no secrets.
"""

import fnmatch
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".next", ".nuxt",
    "target", ".tox", "coverage", ".idea", ".vscode", "vendor", ".terraform",
}
SKIP_FILE_PATTERNS = [
    ".env", ".env.*", "*.env", "*secret*", "*credential*", "id_rsa*",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", ".npmrc", ".pypirc",
    ".netrc", "*.tfstate*",
]
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".mov",
    ".pyc", ".so", ".dylib", ".dll", ".exe", ".bin", ".wasm", ".jar", ".class",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".lock",  # lockfiles read separately
}
LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".c": "C", ".cpp": "C++", ".swift": "Swift",
    ".sh": "Shell", ".sql": "SQL", ".html": "HTML", ".css": "CSS",
}
KNOWN_FRAMEWORKS = {
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "starlette": "Starlette", "sqlalchemy": "SQLAlchemy", "celery": "Celery",
    "arq": "ARQ", "pytest": "pytest", "react": "React", "next": "Next.js",
    "vue": "Vue", "svelte": "Svelte", "express": "Express", "nestjs": "NestJS",
    "@nestjs/core": "NestJS", "tailwindcss": "Tailwind CSS", "rails": "Rails",
    "spring-boot": "Spring Boot", "gin": "Gin", "axum": "Axum",
}
IMPORTANT_FILE_HINTS = {
    "readme": ("docs", 90, "Project overview and usage documentation"),
    "package.json": ("config", 85, "Node package manifest: dependencies and scripts"),
    "pyproject.toml": ("config", 85, "Python project configuration"),
    "requirements.txt": ("config", 80, "Python dependency list"),
    "docker-compose": ("infra", 75, "Multi-service container orchestration"),
    "dockerfile": ("infra", 70, "Container image definition"),
    "makefile": ("config", 65, "Task shortcuts for building/testing/running"),
    "main.py": ("entrypoint", 80, "Likely application entry point"),
    "app.py": ("entrypoint", 80, "Likely application entry point"),
    "index.ts": ("entrypoint", 75, "Likely application entry point"),
    "index.js": ("entrypoint", 75, "Likely application entry point"),
    ".github/workflows": ("ci", 60, "CI workflow definition"),
}
MAX_FILE_BYTES = 50_000
MAX_FILES = 400


@dataclass
class RepoFacts:
    files: list[str] = field(default_factory=list)
    truncated: bool = False
    languages: list[str] = field(default_factory=list)
    package_manager: str | None = None
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    build_command: str | None = None
    test_command: str | None = None
    important_files: list[tuple[str, str, int, str]] = field(default_factory=list)
    readme: str = ""


def _is_skipped(rel: Path) -> bool:
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    name = rel.name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SKIP_FILE_PATTERNS)


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(1024)
    except OSError:
        return True


def read_text_safely(root: Path, rel_path: str) -> str | None:
    """Read a file only if it passes the safety filters; None otherwise."""
    rel = Path(rel_path)
    full = root / rel
    if _is_skipped(rel) or not full.is_file() or _is_binary(full):
        return None
    if full.stat().st_size > MAX_FILE_BYTES:
        return None
    return full.read_text(errors="replace")


def _safe_json(text: str) -> dict:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}


def _detect_python(root: Path, facts: RepoFacts) -> None:
    deps: list[str] = []
    pyproject_text = read_text_safely(root, "pyproject.toml")
    if pyproject_text:
        try:
            data = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            data = {}
        deps += data.get("project", {}).get("dependencies", [])
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        deps += [d for d in poetry if d != "python"]
    for req_name in ("requirements.txt", "requirements-dev.txt"):
        req = read_text_safely(root, req_name)
        if req:
            deps += [
                re.split(r"[<>=!\[;]", line.strip())[0]
                for line in req.splitlines()
                if line.strip() and not line.strip().startswith(("#", "-"))
            ]
    has_manifest = (root / "pyproject.toml").exists() or (
        root / "requirements.txt"
    ).exists()
    if not deps and not has_manifest and "Python" not in facts.languages:
        return

    normalized = {
        re.split(r"[<>=!~\[; ]", d.strip())[0].lower() for d in deps if d.strip()
    }
    facts.dependencies += sorted(d for d in normalized if d)
    if deps or has_manifest:
        if (root / "poetry.lock").exists():
            facts.package_manager = facts.package_manager or "poetry"
        elif (root / "uv.lock").exists():
            facts.package_manager = facts.package_manager or "uv"
        else:
            facts.package_manager = facts.package_manager or "pip"

    has_test_files = any(
        fnmatch.fnmatch(f.rsplit("/", 1)[-1], "test_*.py")
        or fnmatch.fnmatch(f.rsplit("/", 1)[-1], "*_test.py")
        for f in facts.files
    )
    if has_test_files or "pytest" in facts.dependencies:
        facts.test_command = facts.test_command or "python -m pytest -q"


def _detect_node(root: Path, facts: RepoFacts) -> None:
    pkg_text = read_text_safely(root, "package.json")
    if not pkg_text:
        return
    pkg = _safe_json(pkg_text)
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    facts.dependencies += sorted(d.lower() for d in deps)
    if (root / "pnpm-lock.yaml").exists():
        facts.package_manager = "pnpm"
    elif (root / "yarn.lock").exists():
        facts.package_manager = "yarn"
    else:
        facts.package_manager = "npm"
    scripts = pkg.get("scripts", {})
    test_script = scripts.get("test", "")
    if test_script and "no test specified" not in test_script:
        runner = {"pnpm": "pnpm test", "yarn": "yarn test"}.get(
            facts.package_manager, "npm test"
        )
        facts.test_command = facts.test_command or runner
    if scripts.get("build"):
        runner = {"pnpm": "pnpm run build", "yarn": "yarn build"}.get(
            facts.package_manager, "npm run build"
        )
        facts.build_command = facts.build_command or runner


def _detect_go(root: Path, facts: RepoFacts) -> None:
    if (root / "go.mod").exists():
        facts.package_manager = facts.package_manager or "go modules"
        if any(f.endswith("_test.go") for f in facts.files):
            facts.test_command = facts.test_command or "go test ./..."
        facts.build_command = facts.build_command or "go build ./..."


def collect_repo_facts(root: Path) -> RepoFacts:
    facts = RepoFacts()
    lang_counts: dict[str, int] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_skipped(rel):
            continue
        if len(facts.files) >= MAX_FILES:
            facts.truncated = True
            break
        facts.files.append(rel.as_posix())
        lang = LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

    facts.languages = [
        lang for lang, _ in sorted(lang_counts.items(), key=lambda kv: -kv[1])
    ]

    _detect_python(root, facts)
    _detect_node(root, facts)
    _detect_go(root, facts)
    facts.dependencies = sorted(set(facts.dependencies))
    facts.frameworks = sorted(
        {
            label
            for dep, label in KNOWN_FRAMEWORKS.items()
            if dep in facts.dependencies
        }
    )

    for rel_path in facts.files:
        lowered = rel_path.lower()
        for hint, (ftype, score, purpose) in IMPORTANT_FILE_HINTS.items():
            if hint in lowered:
                facts.important_files.append((rel_path, ftype, score, purpose))
                break

    for candidate in ("README.md", "README.rst", "README.txt", "readme.md"):
        text = read_text_safely(root, candidate)
        if text:
            facts.readme = text[:4000]
            break

    return facts
