"""Structured logging: correlation, formatting and redaction.

A log line is the easiest place to leak a token by accident, so redaction is
asserted from several angles.
"""

import json
import logging

import pytest

from app.core.logging_config import (
    CORRELATION_FIELDS,
    CorrelationFilter,
    DevFormatter,
    JSONFormatter,
    bind,
    current_context,
    log_context,
    new_request_id,
)

TOKEN = "ghs_installation_token_should_never_be_logged"
PAT = "ghp_personal_access_token_value_here"


def _record(message: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        "app.test", logging.INFO, "f.py", 1, message, (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    CorrelationFilter().filter(record)
    return record


# -- correlation context ----------------------------------------------------


def test_context_starts_empty():
    assert current_context() == {}


def test_log_context_scopes_fields_and_restores_them():
    with log_context(request_id="abc", task_id=7):
        assert current_context()["request_id"] == "abc"
        assert current_context()["task_id"] == 7
    assert current_context() == {}


def test_nested_contexts_merge():
    with log_context(request_id="abc"):
        with log_context(task_id=7):
            ctx = current_context()
            assert ctx["request_id"] == "abc" and ctx["task_id"] == 7
        assert "task_id" not in current_context()


def test_none_values_are_not_bound():
    """An absent correlation id must not appear as a null field."""
    with log_context(request_id="abc", job_id=None):
        assert "job_id" not in current_context()


def test_bind_adds_to_the_current_context():
    with log_context(request_id="abc"):
        bind(run_id=3)
        assert current_context()["run_id"] == 3


def test_request_ids_are_unique():
    assert new_request_id() != new_request_id()


def test_the_filter_copies_context_onto_records():
    with log_context(request_id="abc", task_id=7):
        record = _record()
    assert record.request_id == "abc"
    assert record.task_id == 7


# -- JSON formatting --------------------------------------------------------


def test_json_output_is_one_parseable_object():
    payload = json.loads(JSONFormatter().format(_record("started")))
    assert payload["message"] == "started"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"


def test_json_includes_every_correlation_field_present():
    with log_context(
        request_id="r1",
        job_id="j1",
        user_id=1,
        project_id=2,
        task_id=3,
        run_id=4,
        stage="cloning",
        provider="google",
        model="gemini-3.1-flash-lite",
        duration_ms=120,
        error_code="clone_failed",
    ):
        payload = json.loads(JSONFormatter().format(_record()))

    for field in CORRELATION_FIELDS:
        assert field in payload, field


def test_json_omits_correlation_that_is_absent():
    payload = json.loads(JSONFormatter().format(_record()))
    assert "task_id" not in payload


def test_json_reports_the_exception_type_not_a_traceback():
    """A full traceback can carry paths and arguments."""
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app.test", logging.ERROR, "f.py", 1, "failed", (), sys.exc_info()
        )
        payload = json.loads(JSONFormatter().format(record))

    assert payload["exception"] == "ValueError"
    assert "Traceback" not in json.dumps(payload)


# -- redaction --------------------------------------------------------------


def test_a_token_in_the_message_is_redacted():
    payload = json.loads(JSONFormatter().format(_record(f"clone failed {TOKEN}")))
    assert TOKEN not in json.dumps(payload)


def test_a_pat_in_the_message_is_redacted():
    payload = json.loads(JSONFormatter().format(_record(f"using {PAT}")))
    assert PAT not in json.dumps(payload)


@pytest.mark.parametrize(
    "field",
    ["token", "authorization", "private_key", "client_secret", "prompt",
     "diff", "command", "env"],
)
def test_credential_shaped_extras_are_dropped_by_name(field: str):
    payload = json.loads(
        JSONFormatter().format(_record("ok", **{field: "sensitive value"}))
    )
    assert field not in payload
    assert "sensitive value" not in json.dumps(payload)


def test_a_token_inside_an_allowed_extra_is_still_redacted():
    """Belt and braces: allowed by name, but the value is still scrubbed."""
    payload = json.loads(JSONFormatter().format(_record("ok", detail=TOKEN)))
    assert TOKEN not in json.dumps(payload)


def test_safe_extras_survive():
    payload = json.loads(JSONFormatter().format(_record("ok", files_changed=3)))
    assert payload["files_changed"] == 3


# -- development formatting -------------------------------------------------


def test_dev_output_is_readable_and_carries_correlation():
    with log_context(task_id=7, stage="testing"):
        line = DevFormatter().format(_record("running tests"))
    assert "running tests" in line
    assert "task_id=7" in line
    assert "stage=testing" in line


def test_dev_output_redacts_secrets_too():
    line = DevFormatter().format(_record(f"failed {TOKEN}"))
    assert TOKEN not in line


def test_dev_output_without_correlation_has_no_empty_brackets():
    assert DevFormatter().format(_record("plain")).endswith("plain")
