"""GitHub project configuration checks shared by run, publish, and analysis flows."""

import re

from app.core.config import settings
from app.core.exceptions import ForbiddenError, InvalidInputError
from app.models import Project

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class PublishError(Exception):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    """Returns (owner, repo) or raises InvalidInputError."""
    match = GITHUB_URL_RE.match(url.strip())
    if not match:
        raise InvalidInputError(
            "Invalid GitHub repository URL — expected https://github.com/<owner>/<repo>"
        )
    return match.group("owner"), match.group("repo")


def check_repo_allowed(owner: str, repo: str) -> None:
    allowed = settings.allowed_repos()
    full_name = f"{owner}/{repo}"
    if allowed is not None and full_name not in allowed:
        raise ForbiddenError(
            f"Repo {full_name} is not in GITHUB_ALLOWED_REPOS — registration refused"
        )


def is_github_project(project: Project) -> bool:
    return bool(project.repo_url or project.github_owner or project.github_repo)


def validate_github_project(project: Project) -> None:
    """Raises PublishError unless the project is fully and legally configured."""
    if not (project.repo_url and project.github_owner and project.github_repo):
        raise PublishError(
            f"Project {project.name!r} is not GitHub-configured "
            "(repo_url, github_owner and github_repo are all required)"
        )
    if not settings.github_token:
        raise PublishError(
            "GITHUB_TOKEN is not set — required to publish pull requests. "
            "Add it to .env and restart the backend and worker."
        )
    allowed = settings.allowed_repos()
    full_name = f"{project.github_owner}/{project.github_repo}"
    if allowed is not None and full_name not in allowed:
        raise PublishError(
            f"Repo {full_name} is not in GITHUB_ALLOWED_REPOS — publishing refused"
        )
