"""Mapping exceptions onto codes a user can act on.

The recurring bug this guards against is a code asserting a cause it does not
actually know — the reaper's "the worker stopped", and every git failure being
reported as a failed clone.
"""

# -- git failures are not all clone failures --------------------------------


def test_git_failures_are_told_apart():
    """Every GitError used to be reported as clone_failed, which sent people
    checking repository access when the clone had worked perfectly and it was
    applying the diff that broke."""
    from app.core.enums import ErrorCode
    from app.core.error_codes import classify
    from app.services.git_client import GitError

    assert classify(GitError("git apply failed: No valid patches in input")) == (
        ErrorCode.patch_failed
    )
    assert classify(GitError("push failed: rejected")) == ErrorCode.push_failed
    assert classify(GitError("clone failed: not found")) == ErrorCode.clone_failed


def test_every_error_code_has_a_description():
    """A code with no entry would render as a blank message to the user."""
    from app.core.enums import ErrorCode
    from app.core.error_codes import describe

    for code in ErrorCode:
        info = describe(code)
        assert info.message and info.action
