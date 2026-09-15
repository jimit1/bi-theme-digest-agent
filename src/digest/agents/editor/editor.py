"""The editor agent: two calls, four read only tools, one validated proposal.

The design choice worth stating once. The editor gets two model calls rather than a tool
loop. Call one carries the theme index, this week's verified claims and the account
enrichment, and returns nothing but the ids of the themes it wants opened. Code opens those
through `read_theme`, logging one read event each, and call two carries the full context and
returns an `EditorProposal`.

Two calls rather than a loop because the sequence then behaves identically over the CLI seat
path and the direct API path, which is the entire point of the provider seam, and because
the audit log stays honest about what was read without depending on a model choosing to
announce a tool call. An id that is not in the index is dropped with a reject event rather
than resolved.

After the schema validation the router already performed, `validate_proposal` runs the cross
checks the contract lists. Those are checks a schema cannot express: a claim id has the right
shape long before it is one of this run's claim ids. A failure raises `ContractViolation`,
the caller retries once with the violation text appended using the router's own pinned retry
wording, and a second failure raises `SchemaRejected`. Nothing is patched and nothing is
coerced; a proposal that fails twice is a proposal nobody writes to the store.
"""
from __future__ import annotations

import datetime
import hashlib
import pathlib
import re
from typing import Any, Iterable, NamedTuple

from digest.agents.editor.tools import EDITOR_AGENT, EDITOR_STAGE, TOOL_NAMES, EditorTools
from digest.contracts import validate
from digest.errors import ContractViolation, SchemaRejected
from digest.router import retry_user_text
from digest.store import source_ref_label

__all__ = [
    "run_editor",
    "validate_proposal",
    "load_prompt",
    "manifest",
    "quiet_or_stale_themes",
    "build_date_for_week",
    "run_id_for_week",
    "PromptFile",
    "EDITOR_PROMPT",
    "THEME_REQUEST_PROMPT",
    "TIER",
    "STALE_AFTER_DAYS",
]

TIER = "synthesis"
BUILD_RUN_SUFFIX = "T07:00Z"
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

# contracts/file_formats.md section 3: stale is more than fourteen days without new
# evidence. The theme frontmatter carries the authoritative last_verified; the index line
# carries last_updated_run, which is what code has before a theme is opened, so that is what
# this flag is computed from.
STALE_AFTER_DAYS = 14

PROMPT_DIR = pathlib.Path(__file__).resolve().parent

#: Logical prompt name to the filenames accepted for it, most canonical first.
#: `contracts/INTERFACES.md` and `.claude/agents/editor.md` both name
#: `theme_request.prompt.md`; `editor_request.prompt.md` is accepted as an alias so the
#: other name in circulation resolves rather than failing at import time.
PROMPT_FILES: dict[str, tuple[str, ...]] = {
    "theme_request": ("theme_request.prompt.md", "editor_request.prompt.md"),
    "proposal": ("editor.prompt.md",),
}

THEME_REQUEST_PROMPT = "theme_request"
EDITOR_PROMPT = "proposal"

_SEPARATOR = "---"


class PromptFile(NamedTuple):
    """One parsed prompt file: its declared metadata, its system text, its user template."""

    name: str
    path: pathlib.Path
    version: str
    tier: str
    schema: str
    system: str
    user_template: str
    sha256: str


# --------------------------------------------------------------------------- prompt files


def _parse_prompt(text: str, path: pathlib.Path) -> tuple[dict[str, str], str, str]:
    """Split a prompt file into (frontmatter, system, user template).

    The format, from `contracts/INTERFACES.md`: optional YAML style frontmatter between two
    `---` lines, then the system prompt, then a lone `---`, then the user template. Parsed
    with a line scan rather than a YAML load because the frontmatter here is four flat
    strings and a dependency on the loader's type coercion is how a version number becomes
    a float.
    """
    lines = text.split("\n")
    meta: dict[str, str] = {}
    start = 0
    if lines and lines[0].strip() == _SEPARATOR:
        for index in range(1, len(lines)):
            if lines[index].strip() == _SEPARATOR:
                start = index + 1
                break
            raw = lines[index]
            if ":" not in raw:
                continue
            key, _, value = raw.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
        else:
            raise ContractViolation(
                "EditorPrompt", ["%s: frontmatter was opened and never closed" % path.name])
    body = lines[start:]
    for index, raw in enumerate(body):
        if raw.strip() == _SEPARATOR:
            system = "\n".join(body[:index]).strip("\n")
            user = "\n".join(body[index + 1:]).strip("\n")
            return meta, system, user
    raise ContractViolation(
        "EditorPrompt",
        ["%s: no --- separator between the system prompt and the user template" % path.name])


def load_prompt(name: str, directory: pathlib.Path | None = None) -> PromptFile:
    """Read and parse one prompt file by logical name. Raises ContractViolation if unusable.

    The file is hashed so the manifest can prove which prompt produced a run. A prompt change
    is a diff on a pull request and a different hash in the envelope, which is the only
    reason prompt text lives in the repository rather than in a string literal.
    """
    try:
        candidates = PROMPT_FILES[name]
    except KeyError:
        raise ValueError(
            "unknown prompt %r, expected one of: %s" % (name, ", ".join(sorted(PROMPT_FILES)))
        ) from None
    root = pathlib.Path(directory) if directory else PROMPT_DIR
    for filename in candidates:
        path = root / filename
        if path.is_file():
            break
    else:
        raise ContractViolation(
            "EditorPrompt",
            ["$: no prompt file for %r in %s (looked for %s)"
             % (name, root, ", ".join(candidates))],
        )
    text = path.read_text(encoding="utf-8")
    meta, system, user = _parse_prompt(text, path)
    missing = [key for key in ("version", "tier", "schema") if not meta.get(key)]
    if missing:
        raise ContractViolation(
            "EditorPrompt",
            ["%s: frontmatter is missing %s" % (path.name, ", ".join(missing))])
    if meta["tier"] != TIER:
        raise ContractViolation(
            "EditorPrompt",
            ["%s: tier is %r, the editor runs on %r" % (path.name, meta["tier"], TIER)])
    if not system or not user:
        raise ContractViolation(
            "EditorPrompt", ["%s: system prompt or user template is empty" % path.name])
    return PromptFile(
        name=name,
        path=path,
        version=meta["version"],
        tier=meta["tier"],
        schema=meta["schema"],
        system=system,
        user_template=user,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def render(template: str, values: dict[str, str]) -> str:
    """Fill `{{TOKEN}}` placeholders. Plain replacement, because the content carries braces.

    `str.format` would choke on the first JSON example or YAML block anyone pastes into a
    prompt, and escaping every brace in a prompt file is a trap nobody remembers.
    """
    out = template
    for key, value in values.items():
        out = out.replace("{{%s}}" % key, value)
    return out


def manifest() -> dict[str, Any]:
    """What this agent is made of: prompt versions, hashes, tools, tier. For the envelope."""
    prompts = {}
    for name in sorted(PROMPT_FILES):
        prompt = load_prompt(name)
        prompts[name] = {
            "file": prompt.path.name,
            "version": prompt.version,
            "tier": prompt.tier,
            "schema": prompt.schema,
            "sha256": prompt.sha256,
        }
    return {"agent": EDITOR_AGENT, "tier": TIER, "tools": list(TOOL_NAMES), "prompts": prompts}


# --------------------------------------------------------------------------- the calendar


def build_date_for_week(week: str) -> datetime.date:
    """The Monday after the week, which is the day the build for that week runs."""
    match = WEEK_RE.match(week or "")
    if not match:
        raise ContractViolation("Week", ["$: %r is not a week label" % week])
    year, number = int(match.group(1)), int(match.group(2))
    try:
        sunday = datetime.date.fromisocalendar(year, number, 7)
    except ValueError as exc:
        raise ContractViolation("Week", ["$: %r is not a real ISO week: %s" % (week, exc)]) from exc
    return sunday + datetime.timedelta(days=1)


def run_id_for_week(week: str) -> str:
    """The build run id for a week, per the pinned calendar: `<Monday after>T07:00Z`."""
    return "%s%s" % (build_date_for_week(week).isoformat(), BUILD_RUN_SUFFIX)


def quiet_or_stale_themes(index: Iterable[dict[str, Any]],
                          as_of: datetime.date) -> list[dict[str, Any]]:
    """Which index lines code considers quiet or stale, with the day count behind it.

    Code decides this, not the editor. The editor is told the answer and writes one line
    about what it means; a model asked to do date arithmetic on twenty themes will eventually
    get one wrong and nobody will notice.
    """
    out: list[dict[str, Any]] = []
    for line in index:
        run_id = str(line.get("last_updated_run") or "")
        try:
            last = datetime.date.fromisoformat(run_id[:10])
        except ValueError:
            continue
        days = (as_of - last).days
        stale = days > STALE_AFTER_DAYS
        quiet = str(line.get("status")) == "quiet"
        if not (stale or quiet):
            continue
        out.append({
            "theme_id": line.get("theme_id"),
            "title": line.get("title"),
            "status": line.get("status"),
            "days_since_last_update": days,
            "stale": stale,
            "quiet": quiet,
        })
    return out


# --------------------------------------------------------------------------- prompt blocks


def _number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else ("%.2f" % number)


def build_index_block(index: Iterable[dict[str, Any]]) -> str:
    """The index as the editor reads it: one line per theme, aliases included."""
    rows = []
    for line in index:
        aliases = "; ".join(line.get("aliases") or []) or "-"
        rows.append(
            "- %s | %s | area %s | status %s | score %s | accounts %s | evidence %s "
            "| last updated %s | aliases: %s"
            % (line.get("theme_id"), line.get("title"), line.get("product_area"),
               line.get("status"), line.get("score"), line.get("accounts_count"),
               line.get("evidence_count"), line.get("last_updated_run"), aliases))
    return "\n".join(rows) if rows else "The store has no themes yet. Every claim opens a new theme."


def build_claims_block(claims: Iterable[dict[str, Any]]) -> str:
    """Each claim with the fields the editor is allowed to reason from, and its citation."""
    blocks = []
    for claim in claims:
        blocks.append("\n".join([
            "- claim_id: %s" % claim.get("claim_id"),
            "  account: %s %s (%s)" % (claim.get("account_id"), claim.get("account_name"),
                                       claim.get("account_type")),
            "  type: %s | importance: %s | product_area: %s"
            % (claim.get("claim_type"), claim.get("importance"), claim.get("product_area")),
            "  topic: %s" % claim.get("topic"),
            "  paraphrase: %s" % claim.get("paraphrase"),
            "  verbatim: %s" % claim.get("verbatim"),
            "  cited at: %s (%s)" % (source_ref_label(claim), claim.get("source")),
        ]))
    return "\n".join(blocks) if blocks else "No verified claims this week."


def build_enrichment_block(enrichment: dict[str, dict[str, Any]]) -> str:
    """Account facts, computed by code from the CRM. Sorted so the prompt is reproducible."""
    rows = []
    for account_id in sorted(enrichment):
        record = enrichment[account_id]
        products = ", ".join(record.get("products") or []) or "-"
        rows.append(
            "- %s %s | %s | tier %s | ARR %s USD | open cases %s | products: %s"
            % (account_id, record.get("account_name"), record.get("account_type"),
               record.get("tier"), _number(record.get("arr_usd")),
               record.get("open_case_count"), products))
    return "\n".join(rows) if rows else "No enrichment for this run."


def build_theme_bodies_block(themes: Iterable[tuple[dict[str, Any], str]]) -> str:
    """The full text of each theme the editor asked for, frontmatter facts then body."""
    blocks = []
    for theme, body in themes:
        aliases = "; ".join(theme.get("aliases") or []) or "-"
        blocks.append(
            "### %s %s\narea %s | status %s | accounts %s | evidence claims %s "
            "| last verified %s | aliases: %s\n\n%s"
            % (theme.get("theme_id"), theme.get("title"), theme.get("product_area"),
               theme.get("status"), ", ".join(theme.get("accounts") or []) or "-",
               len(theme.get("evidence") or []), theme.get("last_verified"), aliases,
               body.strip()))
    return "\n\n".join(blocks) if blocks else "You asked for no themes to be opened."


def build_quiet_block(flagged: Iterable[dict[str, Any]]) -> str:
    """The quiet and stale list, already decided by code. One line each."""
    rows = []
    for item in flagged:
        rows.append(
            "- %s %s: status %s, %s days since its last update%s"
            % (item["theme_id"], item["title"], item["status"],
               item["days_since_last_update"], ", past the fourteen day horizon"
               if item["stale"] else ""))
    return "\n".join(rows) if rows else "No theme is quiet or stale this week."


# --------------------------------------------------------------------------- the two calls


def run_editor(week: str, claims: list[dict], enrichment: dict[str, dict],
               store: Any, router: Any, audit: Any) -> dict:
    """Run the editor for one week and return a validated EditorProposal.

    Two model calls on the synthesis tier, every read logged, every cross check run, one
    retry on a cross check failure and then a hard rejection.
    """
    run_id = run_id_for_week(week)
    as_of = build_date_for_week(week)
    tools = EditorTools(store, audit, week, claims=claims, enrichment=enrichment)

    index = tools.read_theme_index()
    run_claims = tools.list_run_claims()
    # Reading the enrichment through the tool is what puts it in the run log; the block below
    # is built from the same records. Once per account, in id order, so the log is stable.
    for account_id in sorted({claim.get("account_id") for claim in run_claims}):
        if account_id in enrichment:
            tools.read_account(account_id)

    flagged = quiet_or_stale_themes(index, as_of)
    common = {
        "WEEK": week,
        "RUN_ID": run_id,
        "THEME_INDEX": build_index_block(index),
        "CLAIMS": build_claims_block(run_claims),
        "ENRICHMENT": build_enrichment_block(enrichment),
        "QUIET_OR_STALE": build_quiet_block(flagged),
    }

    # -- call one: which themes does it need opened
    request_prompt = load_prompt(THEME_REQUEST_PROMPT)
    request = router.complete(
        TIER, request_prompt.system, render(request_prompt.user_template, common),
        request_prompt.schema, run_id=run_id, agent=EDITOR_AGENT, audit=audit,
        stage=EDITOR_STAGE)
    needs = list(request["data"].get("needs_themes") or [])

    known = {line["theme_id"] for line in index}
    opened: list[tuple[dict[str, Any], str]] = []
    for theme_id in needs:
        if theme_id not in known:
            audit.log(agent=EDITOR_AGENT, action="reject", stage=EDITOR_STAGE,
                      target=theme_id, outcome="rejected",
                      detail={"reason": "theme_id is not in themes/_INDEX.md",
                              "call": "EditorThemeRequest"})
            continue
        opened.append(tools.read_theme(theme_id))

    # -- call two: the proposal
    editor_prompt = load_prompt(EDITOR_PROMPT)
    values = dict(common)
    values["THEME_BODIES"] = build_theme_bodies_block(opened)
    user = render(editor_prompt.user_template, values)

    proposal = _propose(router, editor_prompt, user, run_id, audit, index, run_claims,
                        enrichment)

    audit.log(agent=EDITOR_AGENT, action="propose", stage="propose", target=week,
              detail={"decisions": len(proposal["decisions"]),
                      "new_themes": len(proposal["new_themes"]),
                      "sections": len(proposal["digest"]["sections"]),
                      "file_proposals": len(proposal["file_proposals"]),
                      "themes_opened": len(opened),
                      "themes_requested": len(needs)})
    return proposal


def _propose(router: Any, prompt: PromptFile, user: str, run_id: str, audit: Any,
             index: list[dict], claims: list[dict], enrichment: dict) -> dict:
    """Call two, cross check, retry once with the violation appended, then reject."""
    result = router.complete(TIER, prompt.system, user, prompt.schema, run_id=run_id,
                             agent=EDITOR_AGENT, audit=audit, stage=EDITOR_STAGE)
    proposal = result["data"]
    try:
        validate_proposal(proposal, index, claims, enrichment)
        return proposal
    except ContractViolation as first:
        audit.log(agent=EDITOR_AGENT, action="reject", stage=EDITOR_STAGE,
                  target=prompt.schema, outcome="rejected",
                  detail={"attempt": 1, "check": "cross_check", "errors": first.errors})
        retry = retry_user_text(user, prompt.schema, first.errors)

    result = router.complete(TIER, prompt.system, retry, prompt.schema, run_id=run_id,
                             agent=EDITOR_AGENT, audit=audit, stage=EDITOR_STAGE)
    proposal = result["data"]
    try:
        validate_proposal(proposal, index, claims, enrichment)
    except ContractViolation as second:
        audit.log(agent=EDITOR_AGENT, action="reject", stage=EDITOR_STAGE,
                  target=prompt.schema, outcome="rejected",
                  detail={"attempts": 2, "check": "cross_check", "errors": second.errors})
        raise SchemaRejected(prompt.schema, second.errors, attempts=2, agent=EDITOR_AGENT,
                             tier=TIER) from second
    return proposal


# --------------------------------------------------------------------------- cross checks


def _referenced(proposal: dict) -> list[tuple[str, str]]:
    """Every theme id or placeholder in the proposal, with the json path it sits at."""
    out: list[tuple[str, str]] = []
    for position, decision in enumerate(proposal.get("decisions") or []):
        out.append(("decisions[%d].theme_id" % position, decision.get("theme_id")))
    for position, item in enumerate(proposal.get("theme_rationales") or []):
        out.append(("theme_rationales[%d]" % position, item.get("theme_id_or_placeholder")))
    digest = proposal.get("digest") or {}
    for position, item in enumerate(digest.get("sections") or []):
        out.append(("digest.sections[%d]" % position, item.get("theme_id_or_placeholder")))
    for position, item in enumerate(digest.get("reconciliations") or []):
        out.append(("digest.reconciliations[%d]" % position, item.get("theme_id_or_placeholder")))
    for position, item in enumerate(proposal.get("file_proposals") or []):
        out.append(("file_proposals[%d]" % position, item.get("theme_id_or_placeholder")))
    return [(path, value) for path, value in out if isinstance(value, str)]


def validate_proposal(proposal: dict, index: Iterable[dict], claims: Iterable[dict],
                      enrichment: dict[str, dict]) -> None:
    """Every cross check the contract lists, plus the two the brief adds. Raises or returns.

    Schema validation runs first so this is safe to call on a proposal that did not come
    through the router. Everything after it is a check a schema cannot make: a claim id has
    the right shape long before it is one of THIS run's claim ids.

    Errors are collected rather than raised one at a time, because a model given all of its
    mistakes at once fixes them in one retry and a model given the first one fixes that one
    and returns the rest.
    """
    validate(proposal, "EditorProposal")

    claim_list = list(claims)
    claim_ids = {claim["claim_id"] for claim in claim_list}
    claim_account = {claim["claim_id"]: claim.get("account_id") for claim in claim_list}
    known_themes = {line["theme_id"] for line in index}
    errors: list[str] = []

    # 3 (definitions first, so the other checks can use them).
    defined: dict[str, int] = {}
    for position, theme in enumerate(proposal.get("new_themes") or []):
        placeholder = theme["placeholder"]
        defined[placeholder] = defined.get(placeholder, 0) + 1
        if defined[placeholder] > 1:
            errors.append("new_themes[%d].placeholder: %s is defined more than once"
                          % (position, placeholder))

    # 1 and 5, plus "every claim decided exactly once".
    seen: dict[str, int] = {}
    assigned: dict[str, str] = {}
    for position, decision in enumerate(proposal.get("decisions") or []):
        claim_id = decision["claim_id"]
        theme_id = decision["theme_id"]
        action = decision["action"]
        seen[claim_id] = seen.get(claim_id, 0) + 1
        assigned.setdefault(claim_id, theme_id)
        if claim_id not in claim_ids:
            errors.append("decisions[%d].claim_id: %s is not one of this run's verified "
                          "claims" % (position, claim_id))
        if seen[claim_id] > 1:
            errors.append("decisions[%d].claim_id: %s is decided more than once"
                          % (position, claim_id))
        if action == "open" and not theme_id.startswith("NEW-"):
            errors.append("decisions[%d]: action open must name a NEW-n placeholder, got %s"
                          % (position, theme_id))
        if action == "append" and not theme_id.startswith("THEME-"):
            errors.append("decisions[%d]: action append must name an existing THEME-nnnn, "
                          "got %s" % (position, theme_id))
        account_id = claim_account.get(claim_id)
        if claim_id in claim_ids and account_id not in enrichment:
            errors.append("decisions[%d].claim_id: %s belongs to account %s, which has no "
                          "enrichment this run" % (position, claim_id, account_id))
    for claim_id in sorted(claim_ids - set(seen)):
        errors.append("decisions: claim %s was never decided; every claim gets exactly one "
                      "decision" % claim_id)

    # 2 and 3 over every reference in the document.
    for path, value in _referenced(proposal):
        if value.startswith("NEW-"):
            if value not in defined:
                errors.append("%s: %s is not defined in new_themes" % (path, value))
        elif value not in known_themes:
            errors.append("%s: %s is not in themes/_INDEX.md" % (path, value))

    # 4, plus "every digest section cites at least one claim of its theme".
    digest = proposal.get("digest") or {}
    for position, section in enumerate(digest.get("sections") or []):
        target = section["theme_id_or_placeholder"]
        matched = 0
        for cited in section["evidence_claim_ids"]:
            if cited not in claim_ids:
                errors.append("digest.sections[%d].evidence_claim_ids: %s is not one of "
                              "this run's verified claims" % (position, cited))
                continue
            if assigned.get(cited) != target:
                errors.append("digest.sections[%d].evidence_claim_ids: %s was assigned to "
                              "%s, not to %s"
                              % (position, cited, assigned.get(cited, "no theme"), target))
                continue
            matched += 1
        if matched == 0:
            errors.append("digest.sections[%d]: cites no claim assigned to %s"
                          % (position, target))

    if errors:
        raise ContractViolation("EditorProposal", sorted(errors))
