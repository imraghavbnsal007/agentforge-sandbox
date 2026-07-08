import json
from pathlib import Path

from app.services.repo_facts import collect_repo_facts, read_text_safely


def _python_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi>=0.1", "sqlalchemy"]\n'
    )
    (root / "requirements-dev.txt").write_text("pytest>=8\n# comment\n")
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("app = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n")
    (root / "README.md").write_text("# My Service\n\nA FastAPI demo service.\n")


def test_python_repo_detection(tmp_path: Path):
    _python_repo(tmp_path)
    facts = collect_repo_facts(tmp_path)

    assert facts.languages[0] == "Python"
    assert facts.package_manager == "pip"
    assert facts.test_command == "python -m pytest -q"
    assert "fastapi" in facts.dependencies
    assert "FastAPI" in facts.frameworks
    assert facts.readme.startswith("# My Service")
    important_paths = [p for p, *_ in facts.important_files]
    assert "README.md" in important_paths
    assert "pyproject.toml" in important_paths


def test_node_repo_detection(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"react": "^19", "next": "^15"},
                "devDependencies": {"typescript": "^5"},
                "scripts": {"test": "jest", "build": "next build"},
            }
        )
    )
    (tmp_path / "yarn.lock").write_text("")
    (tmp_path / "index.ts").write_text("export {};\n")

    facts = collect_repo_facts(tmp_path)
    assert facts.package_manager == "yarn"
    assert facts.test_command == "yarn test"
    assert facts.build_command == "yarn build"
    assert "Next.js" in facts.frameworks and "React" in facts.frameworks


def test_no_test_command_detected(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
        )
    )
    facts = collect_repo_facts(tmp_path)
    assert facts.test_command is None


def test_python_repo_without_manifest_still_detects_pytest(tmp_path: Path):
    (tmp_path / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calculator.py").write_text("def test_x(): pass\n")
    facts = collect_repo_facts(tmp_path)
    assert facts.test_command == "python -m pytest -q"
    assert facts.package_manager is None


def test_safety_filters_skip_secrets_and_junk(tmp_path: Path):
    (tmp_path / ".env").write_text("SECRET=x\n")
    (tmp_path / "credentials.json").write_text("{}")
    (tmp_path / "server.key").write_text("PRIVATE")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("x")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    (tmp_path / "ok.py").write_text("x = 1\n")

    facts = collect_repo_facts(tmp_path)
    assert facts.files == ["logo.png", "ok.py"]  # listed but…
    assert read_text_safely(tmp_path, ".env") is None
    assert read_text_safely(tmp_path, "credentials.json") is None
    assert read_text_safely(tmp_path, "server.key") is None
    assert read_text_safely(tmp_path, "node_modules/pkg.js") is None
    assert read_text_safely(tmp_path, "logo.png") is None  # binary
    assert read_text_safely(tmp_path, "ok.py") == "x = 1\n"
