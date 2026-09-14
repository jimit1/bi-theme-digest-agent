# The contract pack

Everything that crosses a boundary in this system is defined here: every JSON schema, every
MCP tool signature, every Python interface, every file format on disk, every id rule, every
error semantic, and the file ownership map. Fifteen people can build fifteen parts of this
prototype without talking to each other because they all read this directory.

The rule that makes it work: no agent ever returns prose to another agent. Every model call
returns a named, versioned schema from this directory, validated in code, rejected on
failure, retried once with the validation error appended, then rejected permanently and
logged. Never patched, never coerced.

## How to load a schema

```python
from digest.contracts import validate, load_schema, schema_version

validate(doc, "ReaderOutput")      # raises ContractViolation(schema_name, errors) on failure
load_schema("Claim")               # the parsed schema document, cached, do not mutate
schema_version("Theme")            # "1.0.0"
```

The loader finds this directory by walking up from `src/digest/contracts.py` until it sees
a `contracts/README.md`, or by honouring `DIGEST_CONTRACTS_DIR` when that is set. Validation
is jsonschema Draft 2020-12.

Every schema file is self contained. There is not one cross file `$ref` in the pack, only
`#/$defs/...` inside a single file, so any validator in any language can be handed one file
with no resolver configured. Some definitions are therefore repeated between files on
purpose. `tests/test_contracts.py` asserts this.

## The versioning rule

Every schema carries a top level `schema_version` with a `const`, and every document written
against it must carry the same string. It is a semver string and it starts at `1.0.0`.

- Additive change that older documents still satisfy: bump the minor.
- Anything that invalidates a document already written: bump the major.
- Never change a schema in place without bumping. The store keeps documents from earlier
  runs and a reader has to be able to tell which contract produced them.

## Three conventions that apply to every schema here

1. **Strict.** `additionalProperties: false` on every object, and `required` lists every
   declared property. There are exactly four free form objects in the pack and they declare
   no properties at all: `AuditEvent.detail`, `RejectedClaim.raw`, `RecordedResponse.result.data`,
   and a Gong party `context` entry. Nothing else is open.
2. **Optional means required and nullable.** A field that prose calls optional is modelled as
   required with a `null` member in its type, not as an absent key. So `no_claims_reason`,
   `decline_reason`, `proposal_id`, `filed_issue_url`, `model_id`, `prompt_hash`,
   `withheld_comment_count` and `records.cursor` are always present and are `null` when they
   do not apply. One shape, no presence checks, no ambiguity about what a missing key meant.
   The one adapter note: the real Gong API omits `cursor` on the last page, so an adapter
   must treat missing and `null` identically.
3. **Dates are pattern checked, not format checked.** jsonschema does not enforce `format` by
   default and the checkers it can use depend on what is installed. Every date and timestamp
   field here carries an explicit `pattern` instead, so validation gives the same answer on
   every machine.

## Index

### Schemas

| File | What it is | Written by | Read by |
|---|---|---|---|
| `Claim.schema.json` | One client claim with the exact moment it came from | code, from a ReaderClaim | store, editor, verifier, renderer, analyst |
| `ReaderOutput.schema.json` | What a reader agent returns for ONE source document | `gong_reader`, `sfdc_reader` | `digest.verify` |
| `SourceDocument.schema.json` | One scrubbed source document, the only thing a reader sees | connectors and scrubber | readers, verifier, renderer |
| `Enrichment.schema.json` | Deterministic per account enrichment | `digest.enrich` | scorer, editor |
| `Theme.schema.json` | Frontmatter of `themes/<id>.md` | `digest.store` | editor, scorer, analyst, renderer |
| `EditorThemeRequest.schema.json` | Editor call 1: which themes to open in full | editor | `digest.agents.editor` |
| `EditorProposal.schema.json` | Editor call 2: every decision, the digest, what to file | editor | `digest.pipeline`, gate, renderer |
| `AnalystAnswer.schema.json` | A grounded answer, or a refusal with a reason | analyst | `digest.__main__` |
| `AuditEvent.schema.json` | One line of `runs/<run_id>/run.log.jsonl` | `digest.audit` | metrics, QA |
| `RejectedClaim.schema.json` | One line of `evidence/rejected/<run_id>.jsonl` | verifier, router | evals, metrics |
| `RunManifest.schema.json` | End of run counts, cost and stability | `digest.audit.summary` | metrics, docs |
| `GongCallsResponse.schema.json` | `gong_list_calls` response, mirrors `GET /v2/calls` | mock Gong server | `GongConnector` |
| `GongCallsExtensiveResponse.schema.json` | `gong_get_calls_extensive`, mirrors `POST /v2/calls/extensive` | mock Gong server | `GongConnector` |
| `GongTranscriptResponse.schema.json` | `gong_get_transcripts`, mirrors `POST /v2/calls/transcript` | mock Gong server | `GongConnector` |
| `SalesforceQueryResponse.schema.json` | `sfdc_query_cases`, `sfdc_get_accounts`, `sfdc_get_users` | mock Salesforce server | `SalesforceConnector`, `digest.enrich` |
| `SalesforceCaseResponse.schema.json` | `sfdc_get_case`, case plus published comments plus the withheld count | mock Salesforce server | `SalesforceConnector` |
| `GongCallFile.schema.json` | `data/mock/gong/calls/<call_id>.json` on disk | corpus generator, trap author | mock Gong server |
| `SalesforceCaseFile.schema.json` | `data/mock/salesforce/cases/<case_id>.json` on disk | corpus generator, trap author | mock Salesforce server |
| `MockAccountsFile.schema.json` | `data/mock/accounts.json` | corpus generator | both mock servers |
| `MockIndex.schema.json` | `data/mock/index.json`, the date window index | corpus generator | both mock servers |
| `PiiNames.schema.json` | `data/mock/pii_names.json` | corpus generator, trap author | scrubber, evals |
| `CorpusSeedSpec.schema.json` | `data/mock/seed_spec.yaml` | the build | corpus generator, trap author |
| `ModelsConfig.schema.json` | `config/models.yaml` and `config/models.cheap.yaml` | the build | `digest.router` |
| `RecordedResponse.schema.json` | `runs/<run_id>/responses/<key>.json` | router in record mode | router in replay mode |

### Documents

| File | What is in it |
|---|---|
| `INTERFACES.md` | Every Python interface: exact signatures, types, exceptions, and the score formula written out |
| `mcp_tools.md` | The two mock MCP servers: tool signatures, enforcement rules, launch commands, env |
| `file_formats.md` | Ids, the theme index line, the watermark block, proposal files, store frontmatter, the verify horizon, the mock corpus layout on disk |
| `errors.md` | Exception classes and the exit code map |
| `ownership.yaml` | Exclusive file ownership for B1 through B30. No path is owned twice |
| `store_ROUTER.md` | The scaffold text for `ROUTER.md` in the store repository |
| `examples/` | One valid instance per schema |
| `examples/invalid/` | One deliberately malformed instance per schema, so the schemas are proven to bite |

## Assumptions recorded here rather than buried in code

1. **Gong transcript units.** `sentences[].start` and `.end` are treated as milliseconds.
   That is stated as an assumption to confirm against Gong's own documentation. The rule
   regardless of the answer: `source_ref` stores the source system native unit and the
   digest renders human readable seconds. Converting at the storage layer is how citations
   stop resolving.
2. **Gong party affiliation.** `parties[].affiliation` with `Internal`, `External`,
   `Unknown` is the field trap T4(c) depends on. `Unknown` maps to `momentive`, not to
   `client`, so an unresolvable speaker can never produce a client claim.
3. **Salesforce comment author side.** `CaseComment.CreatedById` does not say whether the
   author is staff or a customer, so the pack adds a fourth Salesforce tool,
   `sfdc_get_users`, returning the standard `User.UserType` field. `Standard` means a
   Momentive Software employee; every other value is a portal or community user, that is a
   client. An unresolvable user maps to `momentive`.
4. **Account resolution.** Gong does not tell you the Salesforce account. The mock carries a
   `domain` per account, outside the Salesforce record, and the connector matches the email
   domain of an `External` party against it. In production that is a CRM lookup, and it is
   the one place the mock is not field for field the real API.
