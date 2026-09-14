"""Every exception the pipeline raises, and the exit code each one maps to.

One module so a reader can see the whole failure surface in one screen, and so no module
has to import another module just to catch its errors. Nothing here imports anything else
from the package.

Exit codes, fixed by contract:

    0  ok
    1  unexpected error (any exception that is not a DigestError)
    2  contract violation (schema invalid, citation unresolved, window violation)
    3  replay miss
    4  gate refused, or a write refused because the store is read only
    5  eval failure

Why an exit code and not just a message: the GitHub workflows and `make demo` branch on it,
and a human reading a red job should be able to tell a schema rejection from a missing
recording without opening the log.
"""
from __future__ import annotations

from typing import Iterable, Sequence

__all__ = [
    "DigestError",
    "ContractViolation",
    "SchemaRejected",
    "ReplayMiss",
    "WindowViolation",
    "CitationUnresolved",
    "GateRefused",
    "StoreReadOnly",
    "EvalFailure",
    "exit_code_for",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "EXIT_CONTRACT",
    "EXIT_REPLAY_MISS",
    "EXIT_REFUSED",
    "EXIT_EVAL",
]

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONTRACT = 2
EXIT_REPLAY_MISS = 3
EXIT_REFUSED = 4
EXIT_EVAL = 5


class DigestError(Exception):
    """Base class for every error the pipeline raises on purpose."""

    exit_code: int = EXIT_UNEXPECTED


class ContractViolation(DigestError):
    """A document failed validation against a named schema in contracts/.

    Raised by digest.contracts.validate and by anything that validates a document it
    built itself. `errors` is the sorted list of human readable validation errors, one
    string per error, formatted as "<json path>: <message>".
    """

    exit_code = EXIT_CONTRACT

    def __init__(self, schema_name: str, errors: Sequence[str]) -> None:
        self.schema_name = schema_name
        self.errors = list(errors)
        detail = "; ".join(self.errors) if self.errors else "no detail"
        super().__init__("%s failed validation: %s" % (schema_name, detail))


class SchemaRejected(DigestError):
    """A model returned output that failed validation twice.

    Raised by digest.router.Router.complete after the single retry. The output is never
    patched and never coerced. The router has already written a `reject` audit event and
    the caller is expected to append a RejectedClaim with reason_code schema_invalid.
    """

    exit_code = EXIT_CONTRACT

    def __init__(self, schema_name: str, errors: Sequence[str], attempts: int = 2,
                 agent: str | None = None, tier: str | None = None) -> None:
        self.schema_name = schema_name
        self.errors = list(errors)
        self.attempts = attempts
        self.agent = agent
        self.tier = tier
        super().__init__(
            "%s rejected after %d attempt(s) (agent=%s tier=%s): %s"
            % (schema_name, attempts, agent, tier, "; ".join(self.errors) or "no detail")
        )


class ReplayMiss(DigestError):
    """Replay mode was asked for a recording that does not exist.

    This is a hard failure on purpose. Silently falling through to a live call would make
    a committed demo cost money and stop being reproducible.
    """

    exit_code = EXIT_REPLAY_MISS

    def __init__(self, key: str, tier: str, agent: str, responses_dir: str | None = None) -> None:
        self.key = key
        self.tier = tier
        self.agent = agent
        self.responses_dir = responses_dir
        super().__init__(
            "no recorded response for key %s (tier=%s agent=%s dir=%s). "
            "Run with --mode record to create it." % (key, tier, agent, responses_dir)
        )


class WindowViolation(DigestError):
    """A connector asked an MCP server for data outside the configured date window.

    The server refuses the request rather than trimming the result, so the refusal is
    visible instead of looking like a thin day.
    """

    exit_code = EXIT_CONTRACT

    def __init__(self, requested: object, allowed: object, tool: str | None = None) -> None:
        self.requested = requested
        self.allowed = allowed
        self.tool = tool
        super().__init__(
            "window_violation in %s: requested %r, allowed %r" % (tool or "tool", requested, allowed)
        )


class CitationUnresolved(DigestError):
    """A claim's verbatim does not resolve to its cited span.

    digest.verify normally returns these as RejectedClaim records rather than raising.
    The exception exists for callers that treat an unresolvable citation as fatal, such
    as the independent citation audit.
    """

    exit_code = EXIT_CONTRACT

    def __init__(self, claim_id: str, source_id: str, detail: str = "") -> None:
        self.claim_id = claim_id
        self.source_id = source_id
        self.detail = detail
        super().__init__(
            "citation for claim %s does not resolve in source %s%s"
            % (claim_id, source_id, (": " + detail) if detail else "")
        )


class GateRefused(DigestError):
    """The human gate refused to act.

    Raised by digest.gate.approve when --yes was not supplied. The message is exactly
    "--yes required" for that case, because the acceptance test asserts on it.
    """

    exit_code = EXIT_REFUSED

    def __init__(self, message: str = "--yes required") -> None:
        super().__init__(message)


class StoreReadOnly(DigestError):
    """A write or commit was demanded while the store is read only.

    store.commit does NOT raise this: it logs a skip and returns None when the store has
    no git directory or DIGEST_STORE_READONLY is set to 1. This is raised only when a
    caller explicitly requires the commit to have happened.
    """

    exit_code = EXIT_REFUSED

    def __init__(self, path: str, reason: str = "DIGEST_STORE_READONLY=1") -> None:
        self.path = path
        self.reason = reason
        super().__init__("store at %s is read only (%s)" % (path, reason))


class EvalFailure(DigestError):
    """One or more golden set assertions failed."""

    exit_code = EXIT_EVAL

    def __init__(self, failed: Iterable[str]) -> None:
        self.failed = list(failed)
        super().__init__("%d eval assertion(s) failed: %s" % (len(self.failed), "; ".join(self.failed)))


def exit_code_for(exc: BaseException) -> int:
    """Map an exception to the process exit code. Anything unknown is 1."""
    if isinstance(exc, DigestError):
        return exc.exit_code
    return EXIT_UNEXPECTED
