# Errors and exit codes

Every exception the pipeline raises on purpose lives in one module, `src/digest/errors.py`.
One module so a reader sees the whole failure surface in one screen, and so no module has to
import another module just to catch its errors. `digest.errors` imports nothing else from the
package.

## The classes

All of them subclass `DigestError`, which subclasses `Exception` and carries a class level
`exit_code`.

| Class | Raised by | Constructor | Attributes | Exit |
|---|---|---|---|---|
| `DigestError` | nothing directly | `(message)` | | 1 |
| `ContractViolation` | `digest.contracts.validate`, anything validating a document it built | `(schema_name: str, errors: Sequence[str])` | `schema_name`, `errors` | 2 |
| `SchemaRejected` | `digest.router.Router.complete`, after the single retry | `(schema_name, errors, attempts=2, agent=None, tier=None)` | `schema_name`, `errors`, `attempts`, `agent`, `tier` | 2 |
| `CitationUnresolved` | `digest.verify` callers that treat it as fatal, and the independent audit | `(claim_id: str, source_id: str, detail: str = "")` | `claim_id`, `source_id`, `detail` | 2 |
| `WindowViolation` | a connector, on an MCP `window_violation` error | `(requested, allowed, tool=None)` | `requested`, `allowed`, `tool` | 2 |
| `ReplayMiss` | `Router` in replay mode | `(key: str, tier: str, agent: str, responses_dir=None)` | `key`, `tier`, `agent`, `responses_dir` | 3 |
| `GateRefused` | `digest.gate.approve` | `(message: str = "--yes required")` | | 4 |
| `StoreReadOnly` | `digest.store`, only when a caller requires the commit to have happened | `(path: str, reason: str = "DIGEST_STORE_READONLY=1")` | `path`, `reason` | 4 |
| `EvalFailure` | `digest.eval` | `(failed: Iterable[str])` | `failed` | 5 |

## Exit codes

```
0  ok
1  unexpected error, anything that is not a DigestError
2  contract violation: schema invalid, citation unresolved, window violation
3  replay miss
4  refused: the human gate said no, or a required write hit a read only store
5  eval failure
```

`digest.errors.exit_code_for(exc) -> int` is the only place the mapping lives.
`digest.__main__` catches `BaseException` at the top level, logs it, and calls it.

Why exit codes and not just messages: the two GitHub workflows and `make demo` branch on
them, and a human reading a red job should be able to tell a schema rejection from a missing
recording without opening the log.

## Three semantics worth stating explicitly

**Rejection is data, not an exception.** `digest.verify.verify_citations` returns
`(accepted, rejected)` and raises nothing for a bad claim. A run with rejections is a normal
run, and the rejections land in `evidence/rejected/<run_id>.jsonl` with their reason codes.
`CitationUnresolved` exists for the callers that do want it fatal, principally the
independent citation audit that deliberately does not use the pipeline's own verifier.

**`ReplayMiss` never falls back to live.** A silent fallback would make a committed demo cost
money and stop being reproducible, and would hide the fact that a prompt changed. Exit 3,
with the key and the directory in the message and `--mode record` named as the fix.

**`StoreReadOnly` is not what a missing credential produces.** `Store.commit` logs one audit
event with `action: "commit"`, `outcome: "withheld"` and returns `None` when the store has no
`.git` directory or `DIGEST_STORE_READONLY=1` is set. The demo has to be green with no
credential configured. `StoreReadOnly` is raised only when a caller explicitly requires the
commit to have happened.

## What lands in the audit log

| Situation | `action` | `outcome` |
|---|---|---|
| A model call returned | `call_model` | `ok` |
| A model call raised | `call_model` | `error` |
| Output validated | `validate` | `ok` |
| Output failed validation twice | `reject` | `rejected` |
| A citation did not resolve | `verify` | `rejected` |
| An MCP server refused a window | `reject` | `rejected`, `detail.code: "window_violation"` |
| Private comments excluded by the query | `withhold` | `withheld`, `detail.count: n` |
| A commit skipped for a read only store | `commit` | `withheld` |
| The gate refused without `--yes` | `approve` | `withheld` |
