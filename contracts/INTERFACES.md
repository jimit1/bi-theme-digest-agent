# Python interfaces

The package is `digest`, under `src/`. Every signature here is exact. Types are Python 3.12
annotations. Where a function raises, the exception is named and lives in `digest.errors`.
No signature here contradicts a schema; where a dict is returned, the schema that validates
it is named.

Shared type aliases used throughout:

```python
RunId      = str    # ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$
Week       = str    # ^\d{4}-W\d{2}$
ClaimId    = str    # ^[0-9a-f]{12}$
ThemeId    = str    # ^THEME-\d{4}$
AccountId  = str    # ^ACC-\d{4}$
Tier       = str    # "extraction" | "synthesis" | "narrative"
Stage      = str    # one of the fixed ten in file_formats.md section 14
```

---

## `digest.contracts`

```python
CONTRACTS_DIR_ENV = "DIGEST_CONTRACTS_DIR"

def contracts_dir() -> pathlib.Path
def schema_path(name: str) -> pathlib.Path
def load_schema(name: str) -> dict                 # cached, do not mutate
def schema_version(name: str) -> str               # "1.0.0"
def list_schemas() -> list[str]                    # sorted names
def validator_for(name: str) -> jsonschema.protocols.Validator
def iter_errors(obj, schema_name: str) -> list[str]   # sorted, "$.path: message"
def validate(obj, schema_name: str) -> None           # raises ContractViolation
def is_valid(obj, schema_name: str) -> bool
```

`name` may be given as `"Claim"`, `"Claim.schema"` or `"Claim.schema.json"`. Anything path
shaped raises `ContractViolation`. `iter_errors` is sorted and deduplicated so the same bad
document always produces the same error list, which matters because that list is appended
verbatim to the router's retry prompt and a changing prompt would change its replay key.

---

## `digest.errors`

See `errors.md`. Import from here, never define an exception anywhere else.

---

## `digest.router`

The model seam. One file to swap platform.

```python
class StructuredResult(TypedDict):
    data: dict          # validated against schema_name
    model_id: str
    tier: Tier
    tokens_in: int      # non cached input tokens
    tokens_out: int
    cache_read: int
    cache_write: int
    cost_usd: float
    prompt_hash: str    # ^[0-9a-f]{16}$
    provider: str
    raw_text: str
    replayed: bool

class Router:
    def __init__(self,
                 config_path: str | pathlib.Path,
                 mode: Literal["replay", "live", "record"] = "replay",
                 responses_dir: str | pathlib.Path | None = None) -> None: ...

    def complete(self, tier: Tier, system: str, user: str, schema_name: str, *,
                 run_id: RunId, agent: str, audit: "Audit") -> StructuredResult: ...

    def tiers(self) -> dict[Tier, dict]          # the parsed tiers block
    def model_for(self, tier: Tier) -> str       # the configured model id
    def price(self, model_id: str) -> dict       # {input, output, cache_read, cache_write}
    def cost(self, model_id: str, tokens_in: int, tokens_out: int,
             cache_read: int, cache_write: int) -> float
```

`config_path` points at a file validating against `ModelsConfig.schema.json`. `responses_dir`
defaults to `<store>/runs/<run_id>/responses` and the committed replay corpus is read from
there. Construction raises `ContractViolation` if the config does not validate, and
`ValueError` if `mode` is not one of the three.

### Cost

```
cost_usd = (tokens_in   * price.input
          + tokens_out  * price.output
          + cache_read  * price.cache_read
          + cache_write * price.cache_write) / 1_000_000
```

`tokens_in` is non cached input only, matching the API usage block, so the four terms never
double count. Prices are per million tokens and are absolute rates in `config/models.yaml`,
not multipliers, so a reviewer can read the bill without arithmetic.

### Replay, record and live

The recording key:

```python
key = sha256("\x1f".join([tier, system, user, schema_name]).encode("utf-8")).hexdigest()[:16]
```

One file per key at `<responses_dir>/<key>.json` holding a `RecordedResponse`: the full
`StructuredResult` plus the request that produced it.

| Mode | Behaviour |
|---|---|
| `replay` | Load `<key>.json`, validate it against `RecordedResponse`, validate `result.data` against `schema_name`, return it with `replayed: True`. A missing file raises `ReplayMiss(key, tier, agent, responses_dir)`, exit code 3. No fallback to live, ever: a silent fallback makes a committed demo cost money and stop being reproducible |
| `record` | Make the live call, validate, write `<key>.json`, return with `replayed: False` |
| `live` | Make the live call, validate, write nothing, return with `replayed: False` |

The retry attempt carries different user text, so it has its OWN key and its own file. Both
files are committed. `request.attempt` distinguishes them for a human reading the directory.

### Validate, reject, retry once, then fail

`complete` runs this and nothing else runs it:

1. Resolve `tier` to a model id and `TierParams` from the config.
2. Call the provider. Write an `AuditEvent` with `action: "call_model"`, the stage the caller
   is in, the tier, the model id, the prompt hash, the token counts, the cost, and
   `outcome: "ok"` when the provider returned or `"error"` when it raised.
3. Parse the text as JSON and `validate(data, schema_name)`.
4. On success: write one `AuditEvent` with `action: "validate"`, `outcome: "ok"`, and return.
5. On failure: build the retry user text (below), call the provider again, write a second
   `call_model` event, and validate again.
6. On a second failure: write an `AuditEvent` with `action: "reject"`, `outcome: "rejected"`
   and `detail.errors` set to the validation error list, then raise
   `SchemaRejected(schema_name, errors, attempts=2, agent=agent, tier=tier)`.

So a final failure produces exactly three events: `call_model`, `call_model`, `reject`. A
first try success produces `call_model`, `validate`. A retry success produces `call_model`,
`call_model`, `validate`. Nothing is patched, nothing is coerced, nothing is "mostly fine".

The retry user text is pinned, because it is part of a replay key:

```
{original user text}

The previous response failed schema validation against {schema_name}.
Validation errors:
- {error 1}
- {error 2}
Return only a JSON object that satisfies the schema. Do not explain.
```

One blank line before `The previous response`, one error per line prefixed by `- `, errors in
the order `iter_errors` returned them.

---

## `digest.providers`

```python
class Capabilities(TypedDict):
    native_structured: bool
    strict_tools: bool
    thinking_style: Literal["adaptive", "budget", "always_on", "none"]
    effort: bool

class TierParams(TypedDict):
    max_tokens: int
    effort: str | None
    thinking_budget: int | None
    temperature: float | None

class ProviderResult(TypedDict):
    text: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_write: int
    stop_reason: str

class Provider(Protocol):
    name: str
    def __init__(self, **options) -> None: ...
    def capabilities(self) -> Capabilities: ...
    def translate_model_id(self, canonical_model_id: str) -> str: ...
    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult: ...

def get_provider(name: str, **options) -> Provider     # factory, raises ValueError on unknown
```

`schema` is the loaded schema document, not a name, so an adapter can hand it straight to a
native structured output request.

### Adapters

| Module | Name | State | Notes |
|---|---|---|---|
| `providers/agent_sdk_seat.py` | `agent_sdk_seat` | working, the default | Calls the `claude` CLI headless on a Claude seat, or `claude_agent_sdk`. No API key needed |
| `providers/anthropic_direct.py` | `anthropic_direct` | working, exercised with a stub transport in tests | `anthropic` 1.5.0. `ANTHROPIC_API_KEY` is unset in this environment, so the tests inject a transport |
| `providers/bedrock.py` | `bedrock` | stub | Constructor plus `translate_model_id`. `complete` raises `NotImplementedError("stub")` |
| `providers/vertex.py` | `vertex` | stub | Same |
| `providers/foundry.py` | `foundry` | stub | Same |
| `providers/openai_compatible.py` | `openai_compatible` | stub | Same |

`translate_model_id` is the part that actually differs between platforms and is the reason a
swap takes a day instead of an hour, so every stub implements it for real:

- Bedrock prefixes the family, for example `anthropic.` in front of the canonical id.
- Vertex separates the version with `@` rather than a hyphen.
- Foundry uses a deployment name from its own options, with the canonical id as the fallback.
- An OpenAI compatible gateway passes the id through unless an explicit map is configured.

### The `claude` CLI path, exactly

```
claude -p "<user>" --model <model_id> --output-format json \
       --json-schema '<schema json>' --system-prompt "<system>" \
       --tools "" --no-session-persistence --bare
```

Always pass `--system-prompt`. Without it the call carries the default system prompt of about
34,000 tokens and every cost number in the write-up becomes a lie. The JSON result carries
`usage` (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`), `total_cost_usd`, `modelUsage`, and with `--json-schema` a
`structured_output` field. Map `input_tokens` to `tokens_in`, `cache_read_input_tokens` to
`cache_read`, `cache_creation_input_tokens` to `cache_write`.

### Capability negotiation order

The router picks the strongest path the adapter declares, in this order, and records which
one it used in the `call_model` audit event under `detail.path`:

1. `native_structured` : native structured output, the provider's own JSON schema format.
2. `strict_tools` : a single strict tool whose input schema is the contract, forced or
   instructed depending on the family.
3. Neither : the schema is embedded in the prompt and the result is validated in code.

All three give the same guarantee at the call site, because the router validates the result
against the contract in every case. Same contract, three implementations, one call site.

### Per model API handling, derived by the adapter from the model family

This is prose describing configuration. It is the only place model families are named
outside `config/*.yaml` and `contracts/examples/`, and none of it belongs in application
code. `config/models.yaml` carries no `thinking` key at all, on purpose: thinking handling is
a property of the model family, not of the tier, and putting it in config invites a 400 that
config cannot explain.

| Family | Thinking | Effort | Adapter must |
|---|---|---|---|
| opus 5 | On by default, adaptive | `low` to `max` | Omit `thinking`, or send `{"type": "adaptive"}`. Pass `effort`. Native structured output. `budget_tokens` returns 400. No assistant prefill |
| opus 4.6 | Must be enabled explicitly | `low` to `high` | Send `{"type": "adaptive"}` or get no thinking at all. No `xhigh` |
| haiku 4.5 | Older interface | rejected | Send `{"type": "enabled", "budget_tokens": N}` with `1024 <= N < max_tokens`. DROP `effort` from the request. 200K context, not 1M |
| fable 5.1 | Always on | supported | Omit `thinking` entirely. Forced `tool_choice` of `any` or `tool` returns 400, so use `auto` plus an instruction, or a strict tool. No assistant prefill. Handle `stop_reason: "refusal"`. Stream, because turns are long |

Derived values, pinned so two adapters compute the same number:

```python
thinking_budget = min(max(1024, max_tokens // 2), max_tokens - 1)   # budget style families only
```

`temperature` is omitted from the request whenever thinking is active, for every family.
When an adapter drops a parameter the model family does not accept, it records it in the
audit event under `detail.dropped_params`. Dropping silently is how a swap turns into an
afternoon of guessing.

### `config/models.yaml`

Validates against `ModelsConfig.schema.json`. Shape, with the tier names fixed:

```yaml
schema_version: "1.0.0"
provider: agent_sdk_seat
tiers:
  extraction: { model: <id>, effort: low,  max_tokens: 4000,  temperature: 0 }
  synthesis:  { model: <id>, effort: high, max_tokens: 16000, temperature: null }
  narrative:  { model: <id>, effort: high, max_tokens: 8000,  temperature: null }
pricing:
  <model id>: { input: 1.00, output: 5.00, cache_read: 0.10, cache_write: 1.25 }
```

`config/models.cheap.yaml` is the same shape with a different tier map, and is what
`make swap-models` runs to print the three line comparison of cost, eval pass rate and
theme assignment overlap against the reference run.

Which tier each agent asks for:

| Agent | Tier |
|---|---|
| `gong_reader`, `sfdc_reader` | `extraction` |
| `editor` (both calls) | `synthesis` |
| `analyst` | `narrative` |

---

## `digest.connectors`

```python
class SourceRef(TypedDict):
    source: Literal["gong", "salesforce"]
    source_id: str
    occurred_at: str        # ISO 8601 with timezone
    doc_type: Literal["call", "case"]
    title: str

class SourceConnector(Protocol):
    name: str               # "gong" | "salesforce"
    def list_since(self, watermark: datetime.date | None,
                   until: datetime.date) -> list[SourceRef]: ...
    def fetch(self, source_id: str) -> dict: ...     # validates as SourceDocument

class GongConnector:
    def __init__(self, mcp_client, accounts: "AccountDirectory") -> None: ...

class SalesforceConnector:
    def __init__(self, mcp_client, accounts: "AccountDirectory") -> None: ...

class AccountDirectory:
    """Resolves an email domain or a Salesforce AccountId to an ACC-nnnn id."""
    def by_domain(self, email_or_domain: str) -> tuple[AccountId, str] | None: ...
    def by_sfdc_id(self, sfdc_account_id: str) -> tuple[AccountId, str] | None: ...
```

`list_since(watermark, until)` returns everything with `occurred_at` strictly after the end
of `watermark` day and on or before the end of `until` day, sorted by `occurred_at` then
`source_id`. `watermark=None` means from the beginning. This is the incremental ingestion
answer: ingest reads `last_ingest_day` from `sources/_INDEX.md` and never re-reads a day it
already has.

`fetch` returns a dict that validates against `SourceDocument.schema.json`. It raises
`WindowViolation` when the MCP server refuses the window. It does NOT scrub: scrubbing is a
separate stage so the redaction count is its own number in the audit log.

### How each connector talks to MCP

Both use the `mcp` Python client over stdio, launching the server subprocess with the env in
`mcp_tools.md`. Every response is validated against its schema on receipt before a single
field is read.

**Gong `fetch(call_id)`**

1. `gong_get_calls_extensive([call_id])` : `metaData` and `parties`.
2. `gong_get_transcripts([call_id])` : `callTranscripts[0].transcript`.
3. One turn per monologue block. `text` is that block's `sentences[].text` joined by a single
   ASCII space. `ref.start_ms` is the first sentence `start`, `ref.end_ms` is the last
   sentence `end`. `sentences` on the turn carries the per sentence spans for the renderer.
4. `speaker_id` to party by `parties[].speakerId`. `affiliation` `External` maps to
   `speaker_side: "client"`; `Internal` and `Unknown` both map to `"momentive"`.
5. Account: take every `External` party's `emailAddress`, lowercase the part after the at
   sign, and match it against `accounts.json` `domain`. If more than one distinct account
   matches, take the one with the most matching parties; break a tie by the lowest
   `account_id`. No match means `account_id: null` and `account_name: null`.

**Salesforce `fetch(case_id)`**

1. `sfdc_get_case(case_id)` : the case and its published comments, plus
   `meta.withheld_comment_count` and `meta.soql`.
2. One turn per published comment, in `CreatedDate` order. `text` is `CommentBody`.
   `sentences` is an empty list.
3. `sfdc_get_users` on the distinct `CreatedById` values. `UserType == "Standard"` maps to
   `speaker_side: "momentive"`; any other value maps to `"client"`. An unresolved id maps to
   `"momentive"`.
4. Account: `Case.AccountId` through `AccountDirectory.by_sfdc_id`.
5. `title` is `Case.Subject`. It is metadata, not a turn, and no claim may cite it.

### `domain`, and where it lives

Gong does not tell you the Salesforce account, so the mock carries a `domain` per account.
It sits in `data/mock/accounts.json` OUTSIDE the Salesforce Account record, alongside it:

```json
{"account_id": "ACC-0001", "account_type": "customer",
 "domain": "greatlakesmuseums.example.org",
 "record": {"attributes": {"type": "Account", "url": "..."}, "Id": "...", "Name": "...",
            "Tier__c": "Enterprise", "ARR__c": 340000,
            "Renewal_Date__c": "2026-12-31", "Products__c": "membership;events;fundraising"}}
```

Outside the record because it is not a Salesforce field and pretending otherwise would break
the claim that the mock mirrors the API field for field. In production this mapping is a CRM
lookup and the connector interface does not change.

### Adding a source

A new source is a new file implementing `SourceConnector` plus a config entry. No pipeline
change. Zendesk, Intercom or a community forum would each be one file.

---

## `digest.pii.scrubber`

```python
PLACEHOLDERS = ("[EMAIL]", "[PHONE]", "[ADDRESS]", "[NAME]")

def load_names(path: str | pathlib.Path | None = None) -> list[str]
def scrub(text: str, names: list[str] | None = None) -> tuple[str, dict[str, int]]
def scrub_document(doc: dict, names: list[str] | None = None) -> tuple[dict, dict[str, int]]
```

`scrub` returns the cleaned text and counts keyed exactly `"EMAIL"`, `"PHONE"`, `"ADDRESS"`,
`"NAME"`. No total key; callers sum. `names` defaults to `data/mock/pii_names.json` via
`load_names`, whose file validates against `PiiNames.schema.json`.

Rules:

- Order of application is EMAIL, PHONE, ADDRESS, NAME. Emails first so a name inside an
  address is already gone by the time the name pass runs.
- Coverage: email addresses; United States phone formats including `(555) 555-0143`,
  `555-555-0143`, `555.555.0143`, `+1 555 555 0143` and a bare ten digit run; street
  addresses of the form number plus street words plus a suffix such as Street, St, Avenue,
  Ave, Road, Rd, Drive, Dr, Lane, Ln, Boulevard, Blvd, Way, Court, Ct, with an optional unit;
  and every person name in the supplied list.
- Name matching is case insensitive, on word boundaries, matching both the full name and the
  standalone surname. Over redaction is the safe direction here.
- **Idempotent.** Running `scrub` on already scrubbed text returns identical text and all
  zero counts. A placeholder must never be re matched.
- Counts are counts of substitutions, never values. No PII value ever reaches the audit log,
  the run manifest, or any file in the store.

**Scrubbing runs on `SourceDocument.turns[].text` before any model call.** Therefore a
Claim's `verbatim` is a substring of the SCRUBBED text, and the citation verifier checks
against the scrubbed source. That is stated here once and every other module refers to it.
A verbatim containing `[EMAIL]` is legal and resolves correctly; a verbatim containing a real
email address cannot exist, because the model never saw one.

---

## `digest.verify`

```python
def validate_reader_output(raw: dict) -> dict          # ReaderOutput; raises ContractViolation
def promote(reader_output: dict, doc: dict, *, run_id: RunId, prompt_hash: str,
            model_tier: Tier) -> list[dict]            # ReaderClaim[] -> Claim[]
def verify_citations(claims: list[dict], source_doc: dict) -> tuple[list[dict], list[dict]]
```

`promote` is the code-fills-the-rest step: it resolves each `ReaderClaim` locator to a turn
in `doc`, copies the code owned `source_ref` fields from that turn, sets `speaker_side` from
the turn, sets `account_id`, `account_name`, `account_type` from the document, computes
`claim_id`, stamps `run_id`, `captured_at`, `prompt_hash` and `model_tier`, and validates
each result against `Claim.schema.json`.

`verify_citations` returns `(accepted, rejected)` where `accepted` are Claims and `rejected`
are documents validating against `RejectedClaim.schema.json`. It raises nothing for a bad
claim; rejection is data, not an exception, because a run with rejections is a normal run.

### The checks, in this order

The order is pinned, because `reason_code` must be deterministic for the same input.

1. **`citation_unresolved`** : the `source_ref` does not identify a turn in `source_doc`.
   Gong: no turn with that `call_id`, `speaker_id`, `start_ms` and `end_ms`. Salesforce: no
   turn with that `comment_id`.
2. **`speaker_not_client`** : the resolved turn's `speaker_side` is not `client`. This is
   trap T4(c). A Momentive Software employee saying "a lot of our customers ask for this" is
   not a client claim.
3. **`citation_unresolved`** : `verbatim` is not an exact substring of the resolved turn's
   `text`. Exact means `verbatim in turn["text"]`, no normalisation, no whitespace
   collapsing, no case folding, no unicode folding. This assertion is the whole traceability
   claim, so it does not get to be approximate.
4. **`window_violation`** : the document's `occurred_at` is outside the run window.
5. **`duplicate`** : this `claim_id` already appeared in this run or already exists in the
   store.

For Gong, the resolved span is the turn's `text`, which is the monologue block's sentences
joined by a single ASCII space. That is exactly the string the reader was shown, so an honest
substring always holds and a hallucinated one never does.

`RejectedClaim.raw` is the post-scrub model output for that claim and nothing else. Never
source text.

---

## `digest.enrich`

```python
def enrich(account_ids: list[AccountId], sfdc_connector) -> dict[AccountId, dict]
```

Values validate against `Enrichment.schema.json`. Deterministic, no model. One
`sfdc_get_accounts` call for the whole list and one `sfdc_query_cases` sweep for open case
counts; `open_case_ids` are the cases whose `Status` is not `Closed`. `tier` is the lowercase
of `Tier__c`. `products` is `Products__c` split on `;`, empty string to empty list. A prospect
has `arr_usd` 0 and `renewal_date` null. An unknown account id raises `KeyError`.

---

## `digest.score`

```python
class ScoreInputs(TypedDict):
    distinct_customers: int
    distinct_prospects: int
    arr_sum: float
    open_cases: int
    recency_days: int
    claim_count: int
    high_importance_count: int

def score(theme: dict, enrichment_by_account: dict[AccountId, dict],
          claims_by_id: dict[ClaimId, dict], as_of: datetime.date) -> tuple[int, ScoreInputs]
```

### The formula, fixed

```
customers        = 30 * min(distinct_customers, 4) / 4
value            = 25 * min(arr_sum, 500000) / 500000
cases            = 20 * min(open_cases, 4) / 4
recency          = 15 * max(0, 14 - recency_days) / 14
severity         = 10 * min(high_importance_count, 3) / 3

total            = customers + value + cases + recency + severity
if distinct_customers == 0:
    total = total * 0.5                       # prospect penalty
score            = int(math.floor(total + 0.5))        # then clamp to 0..100
```

Rounding is `floor(total + 0.5)`, not Python's `round`, so half values always go up and two
implementations cannot disagree. Clamp to 0 through 100 after rounding.

### How each input is computed

| Input | Rule |
|---|---|
| `distinct_customers` | Distinct `account_id` on the theme whose `Enrichment.account_type` is `customer` |
| `distinct_prospects` | Distinct `account_id` whose `account_type` is `prospect` |
| `arr_sum` | Sum of `arr_usd` over the distinct CUSTOMER accounts. Prospects contribute zero, which is what puts trap T3 below customer backed themes |
| `open_cases` | Sum of `open_case_count` over the distinct customer accounts |
| `recency_days` | `(as_of - newest evidence claim date).days`, floored at 0. The claim date is the `occurred_at` date of its source document, carried on the claim's `captured_at` fallback only when the source date is unavailable |
| `claim_count` | `len(theme["evidence"])` |
| `high_importance_count` | Count of evidence claims with `importance == "high"` |

The editor supplies the narrative and never the number. Arithmetic a reviewer can recompute
is the point; the seven inputs are stored on the theme so they can.

---

## `digest.store`

```python
class ThemeIndexLine(TypedDict):
    theme_id: ThemeId
    title: str
    product_area: str
    status: Literal["open", "quiet", "filed"]
    score: int
    accounts_count: int
    evidence_count: int
    last_updated_run: RunId
    aliases: list[str]        # split from the "; " joined cell; [] when the cell is "-"
```

Parsed from and rendered to the markdown table row in `file_formats.md` section 4. The regex
there is the definition; this is the object it produces.

```python
class Store:
    def __init__(self, path: str | pathlib.Path) -> None: ...

    @classmethod
    def clone_or_open(cls, url_or_path: str, dest: str | pathlib.Path | None = None) -> "Store": ...

    # layer 0 and 1
    def read_router(self) -> str
    def read_theme_index(self) -> list[ThemeIndexLine]
    def write_theme_index(self, lines: list[ThemeIndexLine], run_id: RunId) -> None

    # layer 2
    def read_theme(self, theme_id: ThemeId) -> tuple[dict, str]      # (Theme frontmatter, body)
    def write_theme(self, theme: dict, body: str) -> pathlib.Path
    def allocate_theme_ids(self, placeholders: list[str]) -> dict[str, ThemeId]

    # evidence
    def append_claims(self, run_id: RunId, claims: list[dict]) -> int
    def append_rejected(self, run_id: RunId, rejected: list[dict]) -> int
    def read_claims(self, run_ids: list[RunId] | None = None,
                    week: Week | None = None) -> list[dict]

    # sources and the watermark
    def read_watermark(self) -> tuple[RunId | None, datetime.date | None]
    def write_watermark(self, last_ingest_run: RunId, last_ingest_day: datetime.date,
                        rows: list[dict]) -> None
    def write_source_document(self, doc: dict) -> pathlib.Path
    def read_source_document(self, source_id: str) -> dict

    # outputs
    def write_digest(self, week: Week, md: str, html: str) -> tuple[pathlib.Path, pathlib.Path]
    def write_proposal(self, theme_id: ThemeId, week: Week, run_id: RunId,
                       title: str, body: str, reason: str) -> pathlib.Path
    def read_proposals(self, week: Week) -> list[dict]
    def write_run_manifest(self, manifest: dict) -> pathlib.Path

    def commit(self, message: str, run_id: RunId) -> str | None
```

- `read_theme_index` parses `themes/_INDEX.md` with the regex in `file_formats.md` section 4
  and raises `ContractViolation("ThemeIndexLine", [...])` naming the line number on a line
  that does not match.
- `allocate_theme_ids` takes placeholders in any order, sorts them by their numeric suffix,
  and assigns ids continuing from the highest in the index. Same input, same ids, every time.
- `read_claims(week=...)` resolves the week to its five ingest run ids and reads those files.
- `write_theme` writes frontmatter validated against `Theme.schema.json` followed by the
  body. Frontmatter key order is the `StoreFrontmatter` five first, then the rest.
- `write_proposal` resolves nothing: the caller must have replaced any placeholder with a
  real theme id already.
- `commit` uses author `bi-theme-digest-agent <agent@example.invalid>` and message format
  `run <run_id>: <verb> <summary>`, for example `run 2026-09-14T07:00Z: build 2026-W37 digest,
  8 themes opened`. It returns the commit sha, or `None` after logging one audit event with
  `action: "commit"`, `outcome: "withheld"` and `detail.reason` when the store has no `.git`
  directory or `DIGEST_STORE_READONLY=1` is set. It never raises for those two cases; the
  demo has to be green with no credential configured.

Store layout is section 5 of the specification, plus `sources/<source_id>.json` for the
scrubbed source documents the renderer needs, and `runs/<run_id>/manifest.json`:

```
bi-theme-digest-store/
  ROUTER.md
  themes/_INDEX.md
  themes/THEME-0001.md ...
  evidence/claims/<run_id>.jsonl
  evidence/rejected/<run_id>.jsonl
  sources/_INDEX.md
  sources/<source_id>.json
  proposals/<week>/<theme_id>.md
  digests/<week>.md   digests/<week>.html
  runs/<run_id>/run.log.jsonl
  runs/<run_id>/manifest.json
  runs/<run_id>/responses/<key>.json
```

`contracts/store_ROUTER.md` is the scaffold text for `ROUTER.md`. Copy it verbatim.

---

## `digest.audit`

```python
class Audit:
    def __init__(self, run_id: RunId, store_path: str | pathlib.Path) -> None: ...

    def log(self, *, agent: str, action: str, stage: Stage, target: str,
            model_tier: Tier | None = None, model_id: str | None = None,
            prompt_hash: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
            cache_read: int = 0, cache_write: int = 0, cost_usd: float = 0.0,
            outcome: str = "ok", detail: dict | None = None) -> dict

    @contextlib.contextmanager
    def timed(self, agent: str, action: str, stage: Stage, target: str): ...

    def events(self) -> list[dict]
    def summary(self) -> dict          # the counts, rejected_by_reason, pii and usage blocks
```

`log` stamps `schema_version`, `ts` and `run_id`, validates the event against
`AuditEvent.schema.json`, appends one line to `runs/<run_id>/run.log.jsonl`, and returns it.
An event that does not validate raises `ContractViolation`; the log is not a place to be
lenient.

`timed` yields a mutable dict the body fills with any of the `log` keyword arguments. On exit
it merges `detail.duration_ms` and writes the event, setting `outcome` to `"error"` and
`detail.exception` to the class name if the body raised, then re raising.

`summary()` returns the `counts`, `rejected_by_reason`, `pii_redactions_by_kind` and `usage`
blocks of a `RunManifest`, derived from the events, so the manifest and the log can never
disagree.

**Reads are logged.** Every connector fetch, every store read, every theme the editor opens
produces an event with `action: "read"`. "What did it touch" has to be a query, not a guess.

---

## `digest.agents.readers`

```python
def read_source(doc: dict, router: Router, audit: Audit) -> dict      # ReaderOutput
def prompt_for(source: Literal["gong", "salesforce"]) -> tuple[str, str]   # (system, user template)
```

Prompt files, versioned in the repository so a prompt change is a diff on a pull request:

```
src/digest/agents/readers/gong_reader.prompt.md
src/digest/agents/readers/sfdc_reader.prompt.md
```

Each file is a system prompt followed by a `---` separator and a user template. The template
renders one `SourceDocument`: the account name and type, the participant list with each
side, then the turns, each turn preceded by its locator so the model can copy it into
`source_ref` rather than compute it. A reader sees one document and nothing else. It has no
store access and no tools.

`read_source` asks for tier `extraction` and schema `ReaderOutput`, logs a `read` event for
the document and lets the router log the model events, and returns the validated
`ReaderOutput`. A `SchemaRejected` from the router is caught by the caller in
`digest.pipeline`, which appends a `RejectedClaim` with `reason_code: "schema_invalid"`.

---

## `digest.agents.editor`

```python
def run_editor(week: Week, claims: list[dict], enrichment: dict[AccountId, dict],
               store: Store, router: Router, audit: Audit) -> dict      # EditorProposal
```

### The two call design, chosen

The editor gets two calls, not a tool loop.

- **Call 1.** The prompt carries `themes/_INDEX.md`, this run's verified claims and the
  account enrichment. Tier `synthesis`, schema `EditorThemeRequest`. The editor returns
  `{needs_themes: [theme_id]}`.
- **Call 2.** Code resolves each requested id with `read_theme`, logging one `read` event
  per theme, and puts the full theme bodies in the prompt. Tier `synthesis`, schema
  `EditorProposal`.

Chosen over a tool loop because it behaves identically over the CLI seat path and the direct
API path, which is the whole point of the provider seam, and because it keeps the audit log
honest about reads without depending on the model choosing to call a tool. An id that is not
in the index is dropped with a `reject` audit event rather than resolved.

### The four read only tools

Whether they are reached through a loop or called by code around the two calls, these are the
only four things the editor can cause to be read, and they are named so `grep` finds them:

```python
def read_theme_index() -> list[ThemeIndexLine]
def read_theme(theme_id: ThemeId) -> tuple[dict, str]
def list_run_claims() -> list[dict]
def read_account(account_id: AccountId) -> dict          # an Enrichment
```

**There is no write tool for it to call.** Not disabled, absent. Code validates the proposal
and code performs every write. An agent with a write tool would make the approval gate
advisory.

### The five cross checks code runs on the proposal

After schema validation, before any write. Each failure raises `ContractViolation`, exit 2:

1. Every `decisions[].claim_id` is one of this run's verified claim ids.
2. Every `THEME-nnnn` referenced anywhere in the proposal exists in `themes/_INDEX.md`.
3. Every `NEW-n` placeholder referenced anywhere is defined exactly once in `new_themes`.
4. Every `digest.sections[].evidence_claim_ids` entry is one of this run's verified claim
   ids, and that claim was assigned by `decisions` to that same theme or placeholder.
5. Every decision with `action: "open"` names a `NEW-n`, and every decision with
   `action: "append"` names an existing `THEME-nnnn`.

Prompt files: `src/digest/agents/editor/editor.prompt.md` and
`src/digest/agents/editor/theme_request.prompt.md`.

---

## `digest.agents.analyst`

```python
def ask(question: str, store: Store, router: Router, audit: Audit) -> dict   # AnalystAnswer

def search_store(query: str, store: Store, limit: int = 8) -> list[dict]
# [{theme_id, title, score, snippet, claim_ids}]
```

One read only retrieval tool, keyword match over `themes/_INDEX.md` and theme bodies. No
embeddings, no index build, no network. Scoring is case folded token overlap across the
title, the aliases and the body, ties broken by theme `score` descending then `theme_id`
ascending, so the same question returns the same themes every time. `snippet` is at most 300
characters around the best matching line.

**The analyst has no source access at all.** It reads the theme store and nothing else. If
the store does not support an answer it returns `supported: false`, zero citations and a
`decline_reason`, which the schema enforces in both directions. Tier `narrative`, schema
`AnalystAnswer`. Prompt file `src/digest/agents/analyst/analyst.prompt.md`.

---

## `digest.render`

```python
def render_markdown(week: Week, themes: list[dict], claims: list[dict],
                    manifest: dict, store: Store) -> str
def render_html(week: Week, themes: list[dict], claims: list[dict],
                manifest: dict, store: Store) -> str
def source_moment(claim: dict, store: Store) -> dict
```

`render_html` returns ONE file: inline CSS, inline JavaScript, no network requests of any
kind, no external font, no CDN. It opens from a file path on a laptop with no internet.

`source_moment(claim, store)` reads `sources/<source_id>.json` and returns what the HTML
expands a claim into:

```python
{
  "source": "gong",
  "label": "call 7782934451002 at 06:58",     # mm:ss, minutes keep counting past 59
  "speaker": "Dana Ruiz",
  "verbatim": "...",
  "before": "the sentence immediately before, or null",
  "after":  "the sentence immediately after, or null",
  "meta": {"call_id": "...", "start_ms": 418000, "end_ms": 437000}
}
```

| Source | Shown |
|---|---|
| Gong | `call_id`, speaker name, `mm:ss` derived from `start_ms`, the verbatim, and the two neighbouring sentences of context |
| Salesforce | `case_number`, `comment_id`, author name, the comment timestamp, and the verbatim |

Context comes from `SourceDocument.turns[].sentences` in the stored scrubbed source document.
`before` is the sentence immediately preceding the sentences containing the verbatim and
`after` the one immediately following, crossing a turn boundary when the verbatim sits at the
edge of a turn, and `null` when there is nothing there. Salesforce turns have no sentence
spans, so both are `null`.

`mm:ss` is `floor(start_ms / 60000)` and `floor((start_ms % 60000) / 1000)`, each zero padded
to two digits, with minutes continuing past 59 rather than rolling into hours.

Every claim in the digest carries a citation and every citation resolves. The count of
verified citations is printed at the end of every run.

---

## `digest.gate`

```python
def write_proposals(proposal: dict, store: Store) -> list[pathlib.Path]
def approve(theme_id: ThemeId, yes: bool, repo: str, dry_run: bool = False) -> str
```

`write_proposals` writes one file per `file_proposals[]` entry to
`proposals/<week>/<theme_id>.md` with `status: proposed`. Placeholders are already resolved
by the pipeline before this is called.

`approve` raises `GateRefused("--yes required")` when `yes` is false and `dry_run` is false.
With `dry_run=True` it prints the issue it would file and files nothing, and returns the
string `"dry-run"`. Otherwise it files:

```python
subprocess.run(
    ["gh", "issue", "create", "--repo", repo, "--title", title,
     "--body", body, "--label", "theme-digest"],
    check=True, capture_output=True, text=True,
)
```

Argument list form, never `shell=True`. The issue URL is the last line of stdout. On success
the proposal frontmatter moves to `status: filed` with `filed_issue_url` set, the theme's
`status` becomes `filed` and its `filed_issue_url` is set, and one audit event is written
with `action: "approve"` and `outcome: "ok"`. Code writes all of it; the agent proposed and
a human filed.

---

## `digest.__main__`

```
python -m digest ingest  --day 2026-09-08
python -m digest ingest  --since-watermark
python -m digest build   --week 2026-W37
python -m digest eval
python -m digest ask     "why does the renewal credit issue matter"
python -m digest approve --theme THEME-0003 --yes [--repo owner/name] [--dry-run]
python -m digest demo
```

Global flags, accepted before or after the verb:

| Flag | Default | Meaning |
|---|---|---|
| `--mode replay\|live\|record` | `replay` | Router mode. Replay is the default so the committed demo is free and reproducible |
| `--store PATH` | `../bi-theme-digest-store` | The context store repository |
| `--models PATH` | `config/models.yaml` | The tier map. The only file that names a model |
| `--responses-dir PATH` | `<store>/runs/<run_id>/responses` | Where recordings are read and written |
| `--mock-dir PATH` | `data/mock` | Passed to the MCP servers as `DIGEST_MOCK_DIR` |
| `--log-level LEVEL` | `INFO` | Standard logging level |

`demo` runs ingest for all fifteen ingestion days in date order, then build for
`2026-W37`, `2026-W38`, `2026-W39` in that order, then prints where the outputs landed. It is
what `make demo` calls and it is the only command the reader has to run.

Exit codes: `0` ok, `2` contract violation, `3` replay miss, `4` gate refused or store read
only, `5` eval failure, `1` anything unexpected. `digest.errors.exit_code_for(exc)` is the
one place that mapping lives.

---

## Fixed stage names

`connect`, `scrub`, `extract`, `verify`, `enrich`, `edit`, `score`, `render`, `store`,
`propose`.

Every `AuditEvent.stage` and every cost table row key is one of these ten. Nothing else is a
stage, and no module invents a new one.
