"""Mapping internal failures to safe, typed error codes.

The backend stores a code; the frontend turns it into a sentence and a
recommended action. A raw exception message never reaches a user — it can carry
a path, a command, or an upstream response body.

Each code also declares whether retrying could plausibly help, so the UI can
offer the right control instead of inviting a user to retry something that will
fail identically every time.
"""

from dataclasses import dataclass

from app.core.enums import ErrorCode


@dataclass(frozen=True)
class ErrorInfo:
    code: ErrorCode
    #: Shown to the user. No internals, no identifiers they cannot act on.
    message: str
    #: What they should actually do about it.
    action: str
    retryable: bool


ERROR_CATALOGUE: dict[ErrorCode, ErrorInfo] = {
    ErrorCode.authentication_required: ErrorInfo(
        ErrorCode.authentication_required,
        "Your session has expired.",
        "Sign in again to continue.",
        retryable=False,
    ),
    ErrorCode.repository_access_lost: ErrorInfo(
        ErrorCode.repository_access_lost,
        "GitHub App access to this repository is no longer available.",
        "Reinstall or update repository access, then retry.",
        retryable=True,
    ),
    ErrorCode.installation_suspended: ErrorInfo(
        ErrorCode.installation_suspended,
        "The GitHub App installation for this account is suspended.",
        "Unsuspend the installation on GitHub, then retry.",
        retryable=True,
    ),
    ErrorCode.credential_resolution_failed: ErrorInfo(
        ErrorCode.credential_resolution_failed,
        "AgentForge could not obtain credentials for this repository.",
        "Check the GitHub App configuration, then retry.",
        retryable=True,
    ),
    ErrorCode.clone_failed: ErrorInfo(
        ErrorCode.clone_failed,
        "The repository could not be cloned.",
        "Check the repository and default branch still exist, then retry.",
        retryable=True,
    ),
    ErrorCode.provider_unavailable: ErrorInfo(
        ErrorCode.provider_unavailable,
        "The AI provider was unavailable.",
        "Retry in a moment, or choose a different provider.",
        retryable=True,
    ),
    ErrorCode.provider_rate_limited: ErrorInfo(
        ErrorCode.provider_rate_limited,
        "The AI provider rate limit was reached.",
        "Wait a minute and retry, or use a different execution profile.",
        retryable=True,
    ),
    ErrorCode.context_limit_exceeded: ErrorInfo(
        ErrorCode.context_limit_exceeded,
        "The repository context was too large for the selected model.",
        "Retry with a model that has a larger context window, or narrow the "
        "request.",
        retryable=True,
    ),
    ErrorCode.tool_failed: ErrorInfo(
        ErrorCode.tool_failed,
        "An agent tool call failed.",
        "Review the run log, then retry.",
        retryable=True,
    ),
    ErrorCode.test_failed: ErrorInfo(
        ErrorCode.test_failed,
        "The project's tests did not pass on the generated changes.",
        "Review the diff and test output; retry to regenerate.",
        retryable=True,
    ),
    ErrorCode.cancelled: ErrorInfo(
        ErrorCode.cancelled,
        "This run was cancelled.",
        "Retry to start a new run.",
        retryable=True,
    ),
    ErrorCode.worker_interrupted: ErrorInfo(
        ErrorCode.worker_interrupted,
        "The worker stopped before this run finished.",
        "Any changes produced before the interruption are preserved. Retry to "
        "start a fresh run.",
        retryable=True,
    ),
    ErrorCode.push_failed: ErrorInfo(
        ErrorCode.push_failed,
        "The branch could not be pushed to GitHub.",
        "Check repository access, then approve again. Your changes are kept.",
        retryable=True,
    ),
    ErrorCode.pull_request_failed: ErrorInfo(
        ErrorCode.pull_request_failed,
        "The pull request could not be created.",
        "Check repository access, then approve again. Your changes are kept.",
        retryable=True,
    ),
    ErrorCode.internal_error: ErrorInfo(
        ErrorCode.internal_error,
        "Something went wrong inside AgentForge.",
        "Retry; if it persists, check the server logs.",
        retryable=True,
    ),
}


def describe(code: ErrorCode | str | None) -> ErrorInfo:
    """Look up a code, falling back to the generic internal error."""
    if code is None:
        return ERROR_CATALOGUE[ErrorCode.internal_error]
    try:
        return ERROR_CATALOGUE[ErrorCode(str(code))]
    except (ValueError, KeyError):
        return ERROR_CATALOGUE[ErrorCode.internal_error]


def classify(exc: BaseException) -> ErrorCode:
    """Map an exception to a safe code.

    Import-local so this module stays free of service dependencies and can be
    used from anywhere, including the worker.
    """
    from app.llm.types import LLMProviderError, LLMUnavailableError
    from app.services.git_client import GitAuthError, GitError
    from app.services.github_api import GitHubAuthError
    from app.services.github_credentials import RepositoryAccessError
    from app.services.installation_service import InstallationAccessError

    if isinstance(exc, (RepositoryAccessError, InstallationAccessError)):
        return ErrorCode.repository_access_lost
    if isinstance(exc, GitAuthError):
        return ErrorCode.repository_access_lost
    if isinstance(exc, GitHubAuthError):
        return ErrorCode.repository_access_lost
    if isinstance(exc, LLMUnavailableError):
        return ErrorCode.provider_unavailable
    if isinstance(exc, LLMProviderError):
        text = str(exc).lower()
        if "rate limit" in text or "429" in text:
            return ErrorCode.provider_rate_limited
        if "context" in text and ("length" in text or "limit" in text):
            return ErrorCode.context_limit_exceeded
        return ErrorCode.provider_unavailable
    if isinstance(exc, GitError):
        return ErrorCode.clone_failed
    return ErrorCode.internal_error
