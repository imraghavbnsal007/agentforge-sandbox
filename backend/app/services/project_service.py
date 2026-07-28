"""Project operations for one owner.

Two registration paths, chosen by AUTH_MODE:

  local      — paste a GitHub URL, validated against GITHUB_ALLOWED_REPOS and
               reachability with the shared PAT. The original single-user
               workflow, unchanged.
  github_app — pick from repositories the user's own installations grant. No
               URL is accepted at all, so a caller cannot register a
               repository by editing an owner/repo value in a request.

As with TaskService, the user is held on the service so no query can run
unscoped.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AnalysisStatus
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Project, ProjectAnalysis, User
from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectRegister
from app.services.git_client import GitClient, GitError
from app.services.github_config import (
    check_repo_allowed,
    is_github_project,
    parse_github_url,
)
from app.worker.queue import JobQueue


class ProjectService:
    def __init__(self, session: AsyncSession, user: User) -> None:
        self.session = session
        self.user = user
        self.repo = ProjectRepository(session)

    async def create_project(self, data: ProjectCreate) -> Project:
        if await self.repo.get_by_name(data.name, self.user.id) is not None:
            raise ConflictError(f"Project named {data.name!r} already exists")
        project = Project(**data.model_dump(), user_id=self.user.id)
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def register_project(
        self, data: ProjectRegister, git: GitClient | None = None
    ) -> Project:
        """URL-based registration — AUTH_MODE=local only.

        In github_app mode this path is closed: repository access comes from
        installations, and accepting a URL would bypass that entirely.
        """
        if settings.is_github_app_mode():
            raise InvalidInputError(
                "Register repositories from your GitHub App installations "
                "instead of a URL. Open Repositories to choose one."
            )

        owner, repo = parse_github_url(data.repo_url)
        check_repo_allowed(owner, repo)
        name = f"{owner}/{repo}"
        await self._assert_not_registered(name, owner, repo)

        canonical_url = f"https://github.com/{owner}/{repo}.git"
        git = git or GitClient(token=settings.github_token)
        try:
            await git.ls_remote(canonical_url, data.default_branch)
        except GitError as exc:
            raise InvalidInputError(
                f"Repository validation failed: {exc}. Check the URL, the "
                "branch name, and (for private repos) that GITHUB_TOKEN has access."
            ) from exc

        return await self._create_registered(
            name=name,
            repo_url=canonical_url,
            default_branch=data.default_branch,
            owner=owner,
            repo=repo,
        )

    async def register_from_installation(
        self, github_repository_id: int, discovery
    ) -> Project:
        """Installation-based registration — the github_app mode path.

        `discovery.find_granted` is the authorisation gate: it refuses unless
        the repository is currently granted to one of *this user's* active
        installations, so an arbitrary repository id cannot be registered.
        """
        repository, installation = await discovery.find_granted(
            self.user, github_repository_id
        )
        await self._assert_not_registered(
            repository.full_name,
            repository.owner,
            repository.name,
            github_repository_id=github_repository_id,
        )
        return await self._create_registered(
            name=repository.full_name,
            repo_url=f"https://github.com/{repository.full_name}.git",
            default_branch=repository.default_branch,
            owner=repository.owner,
            repo=repository.name,
            installation_id=installation.id,
            github_repository_id=github_repository_id,
        )

    async def _assert_not_registered(
        self,
        name: str,
        owner: str,
        repo: str,
        github_repository_id: int | None = None,
    ) -> None:
        """Duplicate checks are per-owner: another user having this repo is
        irrelevant."""
        if await self.repo.get_by_name(name, self.user.id) is not None:
            raise ConflictError(f"Project {name!r} is already registered")
        if github_repository_id is not None:
            existing = await self.repo.get_by_github_repository_id(
                github_repository_id, self.user.id
            )
            if existing is not None:
                raise ConflictError(
                    f"Repo {name} is already registered as project "
                    f"{existing.name!r} (id {existing.id})"
                )
        existing = await self.repo.get_by_github_repo(owner, repo, self.user.id)
        if existing is not None:
            raise ConflictError(
                f"Repo {owner}/{repo} is already registered as project "
                f"{existing.name!r} (id {existing.id})"
            )

    async def _create_registered(
        self,
        name: str,
        repo_url: str,
        default_branch: str,
        owner: str,
        repo: str,
        installation_id: int | None = None,
        github_repository_id: int | None = None,
    ) -> Project:
        project = Project(
            user_id=self.user.id,
            name=name,
            description="",
            repo_path="",
            repo_url=repo_url,
            default_branch=default_branch,
            github_owner=owner,
            github_repo=repo,
            github_installation_id=installation_id,
            github_repository_id=github_repository_id,
        )
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def start_analysis(self, project_id: int, queue: JobQueue) -> ProjectAnalysis:
        project = await self.repo.get_with_analyses(project_id, self.user.id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        if not is_github_project(project):
            raise InvalidInputError(
                "Analysis is only available for GitHub-registered projects"
            )
        if any(
            a.status in (AnalysisStatus.pending, AnalysisStatus.running)
            for a in project.analyses
        ):
            raise ConflictError("An analysis is already pending or running")

        analysis = ProjectAnalysis(
            project_id=project.id, file_summaries=[], suggestions=[]
        )
        self.session.add(analysis)
        await self.session.commit()
        # Refresh only the server-generated column; a full refresh would
        # unload the (empty) relationship collections.
        await self.session.refresh(analysis, attribute_names=["started_at"])
        await queue.enqueue_analyze_project(analysis.id)
        return analysis

    async def list_projects(self) -> list[Project]:
        return await self.repo.list(self.user.id)

    async def get_project_detail(self, project_id: int) -> Project:
        project = await self.repo.get_with_analyses(project_id, self.user.id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return project

    async def update_settings(self, project_id: int, data) -> Project:
        from app.llm.base import all_providers
        from app.llm.profiles import get_profiles

        project = await self.repo.get(project_id, self.user.id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        if data.preferred_provider and data.preferred_provider not in all_providers():
            raise InvalidInputError(
                f"Unknown LLM provider {data.preferred_provider!r}"
            )
        if (
            data.preferred_execution_profile
            and data.preferred_execution_profile not in get_profiles()
        ):
            raise InvalidInputError(
                f"Unknown execution profile {data.preferred_execution_profile!r}"
            )
        project.preferred_provider = data.preferred_provider
        project.preferred_model = data.preferred_model
        project.preferred_execution_profile = data.preferred_execution_profile
        await self.session.commit()
        await self.session.refresh(project)
        return project
