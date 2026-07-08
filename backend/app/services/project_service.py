from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AnalysisStatus
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Project, ProjectAnalysis
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
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProjectRepository(session)

    async def create_project(self, data: ProjectCreate) -> Project:
        if await self.repo.get_by_name(data.name) is not None:
            raise ConflictError(f"Project named {data.name!r} already exists")
        project = Project(**data.model_dump())
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def register_project(
        self, data: ProjectRegister, git: GitClient | None = None
    ) -> Project:
        """Lightweight registration: validate URL + allowlist + reachability, save.

        No cloning, no analysis, no AI calls — analysis runs only when the
        user clicks Analyze or creates the project's first task.
        """
        owner, repo = parse_github_url(data.repo_url)
        check_repo_allowed(owner, repo)
        name = f"{owner}/{repo}"
        if await self.repo.get_by_name(name) is not None:
            raise ConflictError(f"Project {name!r} is already registered")
        # Dedup by repo identity too — an older project may use a different name.
        existing = await self.repo.get_by_github_repo(owner, repo)
        if existing is not None:
            raise ConflictError(
                f"Repo {owner}/{repo} is already registered as project "
                f"{existing.name!r} (id {existing.id})"
            )

        canonical_url = f"https://github.com/{owner}/{repo}.git"
        git = git or GitClient(token=settings.github_token)
        try:
            await git.ls_remote(canonical_url, data.default_branch)
        except GitError as exc:
            raise InvalidInputError(
                f"Repository validation failed: {exc}. Check the URL, the "
                "branch name, and (for private repos) that GITHUB_TOKEN has access."
            ) from exc

        project = Project(
            name=name,
            description="",
            repo_path="",
            repo_url=canonical_url,
            default_branch=data.default_branch,
            github_owner=owner,
            github_repo=repo,
        )
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def start_analysis(self, project_id: int, queue: JobQueue) -> ProjectAnalysis:
        project = await self.repo.get_with_analyses(project_id)
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
        return await self.repo.list()

    async def get_project_detail(self, project_id: int) -> Project:
        project = await self.repo.get_with_analyses(project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return project

    async def update_settings(self, project_id: int, data) -> Project:
        from app.llm.base import all_providers
        from app.llm.profiles import get_profiles

        project = await self.repo.get(project_id)
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
