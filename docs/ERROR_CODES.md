# Error Codes

The backend stores a **code**; the frontend renders a message and a recommended
action. A raw exception message never reaches a user — it can carry a path, a
command, or an upstream response body.

Defined in `app/core/enums.py`; catalogued with copy in
`app/core/error_codes.py`.

| Code | Meaning | Retryable |
|---|---|---|
| `authentication_required` | Session expired | No — sign in |
| `repository_access_lost` | GitHub App access withdrawn | Yes, after re-granting |
| `installation_suspended` | Installation suspended on GitHub | Yes, after unsuspending |
| `credential_resolution_failed` | Could not obtain credentials | Yes |
| `clone_failed` | Repository could not be cloned | Yes |
| `provider_unavailable` | AI provider unreachable | Yes |
| `provider_rate_limited` | Provider rate limit hit | Yes, after a wait |
| `context_limit_exceeded` | Repository context too large | Yes, with a bigger model |
| `tool_failed` | An agent tool call failed | Yes |
| `test_failed` | Tests did not pass | Yes |
| `cancelled` | Cancelled by the user | Yes |
| `worker_interrupted` | Worker stopped mid-run | Yes — output preserved |
| `push_failed` | Branch could not be pushed | Yes — changes kept |
| `pull_request_failed` | PR could not be created | Yes — changes kept |
| `internal_error` | Unclassified | Yes |

## Classification

`classify(exc)` maps exceptions to codes: `RepositoryAccessError` and
`GitAuthError` → `repository_access_lost`; `LLMUnavailableError` →
`provider_unavailable`; an `LLMProviderError` mentioning a rate limit →
`provider_rate_limited`; `GitError` → `clone_failed`; anything else →
`internal_error`.

## Rules

- Never send a stack trace to a client.
- Every message names an action the user can actually take.
- Retryable and non-retryable are distinguished so the UI offers the right
  control instead of inviting a retry that will fail identically.
- All access-related failures share one message, so a caller cannot
  distinguish "revoked" from "never granted" from "not yours".
