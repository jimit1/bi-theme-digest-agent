# Decisions

This is the decision log for the BI theme digest agent. One paragraph each, in the order a reader of this repository tends to hit them. Where a choice was made I say why once and move on. Everything here is a decision I actually made during the build, including the ones I got wrong the first time and fixed.

## What this runs on

**1. Python on the Claude Agent SDK, driving the local `claude` CLI on a Claude seat, with no API key.** Momentive Software runs Claude Enterprise seats as the primary platform, so code that authenticates on a seat is code the team can run on Monday without a provisioning ticket. The Anthropic API path is implemented too, but it is not what the demo uses.

**2. The seat adapter shells out to the CLI with `--setting-sources ""` rather than `--bare`.** I planned on `--bare` because it is the cleanest possible invocation. It does not work on a seat: `--bare` skips keychain reads, and the seat credentials live in the keychain, so every call comes back "Not logged in". `--setting-sources ""` strips settings, memory and plugin discovery while leaving the keychain alone, which gets the same honest token count. `--bare` is still available behind a flag for a machine that has an API key.

**3. Every model call carries a minimal system prompt.** Without one, the CLI ships the Claude Code default system prompt, which is about 34K tokens the agent never asked for. Every cost number in this repository would have been inflated by it. The system prompt each agent uses is the one in its own prompt file and nothing else.

**4. The CLI will not accept a contract schema verbatim, so the adapter strips exactly two keys.** The CLI's validator has no copy of the Draft 2020-12 meta schema and refuses a document carrying `$schema` or `$id`. The adapter removes those two and nothing else. Every constraint, including `additionalProperties: false`, goes over intact, and the router validates the response against the real unmodified contract afterwards regardless of which path ran.

**5. Native structured output stays the default on the seat path, even though it costs a preamble.** Passing a schema adds a 27K to 42K token preamble that the CLI writes to a one hour cache on the first call and reads back at ten percent for the rest of the run. I kept it because every live call validated on the first attempt. Schema in the prompt is cheaper per call and would have cost me retries, which are not cheaper.

**6. The cost table reports two numbers and says which is which.** The router prices tokens from the rate table in the contract. The CLI reports its own `total_cost_usd`, and it bills a one hour cache write at 2.0x input where the contract table says 1.25x. Rather than pick a favourite I print both, label them, and let the reader see the gap. The sample run is 5.47 USD by the pricing table and 6.69 USD by the CLI's own accounting.

**7. The provider call timeout is set by the caller, not by the tier map.** The first live build of week 37 died at the adapter's 300 second default in the middle of synthesis. Synthesis now asks for 1800 seconds because synthesis is the call that legitimately takes minutes. A timeout belongs to the thing making the call, not to a config file that has no idea how much work the call represents.

**8. Two repositories, code here and the context store next door.** `bi-theme-digest-agent` holds the code. `bi-theme-digest-store` holds the theme store, the evidence, the run logs and the recorded responses, and every pipeline run commits to it. Splitting them means the store's `git log` contains nothing but pipeline commits, so the audit trail reads on its own, and the agent's only write credential reaches the store and nothing else. They sit side by side under one build root, so `--store ../bi-theme-digest-store` is the default and works after two clones with no arguments.

**9. Replay is the default and live is the flag.** Every model response from the sample run is committed. `--replay` reproduces the entire three week run from those recordings, byte identical, in under twenty seconds, with no network and no credentials. `--live` makes real calls. Anyone can clone this and watch the whole pipeline execute without being provisioned first.

**10. The replay key is computed from the original user text, always.** The router appends a schema to the prompt only on the schema in prompt path. If the key were computed after that append, swapping a provider would invalidate every committed recording. It is computed before, so the replay corpus survives a provider change.

**11. A retry gets its own recording.** The retry prompt carries the validation error appended to the user text, so it is a different call and it gets a different key and its own file. The retry text is pinned verbatim in the interfaces document, because if that text ever drifts the committed recordings stop resolving. In record mode I write a file for every attempt including the failed one, so a rejection replays as a rejection instead of turning into a replay miss halfway through a run.

## Models and providers

**12. No model id appears in application code. Every call site asks for a tier.** `config/models.yaml` is the only runtime file that names a model, and a grep for a model id under `src/` is a build failure. Andrew's point about cheaper models arriving through gateways and routers is a real one, and a tier abstraction with a one file swap is the answer to it. `make swap-models` reruns the same week against a different tier map and prints cost, eval pass rate and theme assignment overlap against the reference run.

**13. Three tiers, not four: extraction, synthesis, narrative.** The analyst agent asks for `narrative`. I had drafted a fourth analyst tier and dropped it, because a tier only earns its place if something would plausibly route it differently, and nothing would. Three is enough to show the seam.

**14. `config/models.yaml` carries no thinking configuration. The adapter derives it from the model family.** The thinking interface differs per family in ways that return a 400 rather than a warning: `claude-haiku-4-5` wants `{type: "enabled", budget_tokens: N}` and rejects `effort`, `claude-opus-5` has thinking on by default with `effort` from low to max, `claude-opus-4-6` needs `{type: "adaptive"}` stated explicitly, and `claude-fable-5-1` has thinking always on and returns a 400 for `budget_tokens`. A budget sitting in a config file would invite a 400 that the config file cannot explain. The derived budget is pinned in code so it is still reproducible.

**15. Providers sit behind one adapter interface with capability negotiation.** `Provider.complete(messages, schema, tier)` returns a structured result. The adapter declares what it supports and the router picks the strongest path available: native structured output first, then a strict tool call, then the schema in the prompt with validation and one retry in code. Same contract, three implementations, one call site. Two adapters work, Agent SDK on a seat and Anthropic direct, and the rest carry the constructor and the model id translation, which is the part that actually differs between them.

**16. The router steps down a path when a provider refuses a schema shape, and logs which path ran.** `AnalystAnswer` has a top level `allOf` for its supported-versus-declined cross check. The seat path serialises the contract schema as a forced tool's input schema, and the API rejects a top level `allOf` there with a 400. Rather than reshape the contract to suit one transport, the router falls through to schema in prompt for that one schema and validates in code, which is the fallback path existing for exactly this. The chosen path is in the audit log so nobody has to guess.

**17. Bedrock: I would run this on Claude Enterprise, or the Claude API directly, and I would not reach for Bedrock here.** Run on the platform when the constraint is speed of adoption and the platform's own identity and audit already satisfy the requirement, which is the case for Momentive Software because the agents inherit access through the platform's own APIs and the seat model means there is no key to provision, rotate or leak. Reach for Bedrock when the constraint is data residency in a specific AWS region, IAM native identity for agents that already run inside an AWS account, private networking with no public egress, or consolidated AWS billing against committed spend. This prototype assumes the first. The model router exists so that the second is a one file change rather than a rewrite: the thing that actually differs between the two is the model id translation, because Bedrock ids carry an `anthropic.` prefix and Vertex ids use an `@` version separator, and that detail is the difference between a swap taking an hour and taking a day.

**18. Sources sit behind a connector protocol too.** `SourceConnector` has `list_since(watermark)` and `fetch(id)`. Gong and Salesforce are two implementations. Zendesk, Intercom or a community forum is a new file and a config entry with no pipeline change. I am saying that rather than building it.

## Contracts and schemas

**19. No agent returns prose to another agent.** Every model call returns a named, versioned schema from `contracts/`, validated in code. A failure is retried once with the validation error appended, then rejected permanently and logged. Never patched, never coerced. This is the single decision that keeps a multi agent pipeline from becoming a parsing problem.

**20. Optional fields are required and nullable, never absent.** Every object keeps `required` equal to `properties`, so no consumer anywhere has to distinguish a missing key from a null one. The one adapter note that follows from it: the real Gong API omits `cursor` on the last page, so an adapter has to treat missing and null identically at the boundary.

**21. No cross file `$ref` anywhere in the contract pack.** Some definitions are duplicated between files on purpose, so any validator in any language can be handed one file with no resolver. A test asserts it.

**22. Dates and timestamps carry explicit pattern regexes rather than relying on JSON Schema `format`.** `format` is not enforced by default and depends on which optional checkers happen to be installed, which means validation gives different answers on different machines. A regex gives the same answer everywhere.

**23. `SourceDocument.scrubbed` is `const: true`, so a document is only ever persisted scrubbed.** The connector emits `scrubbed: true` with zero counts and the scrubber stage rewrites the turns and fills in the counts in place, before the document is written to the store and before any model sees it. Making it a constant rather than a boolean means there is no code path that can persist an unscrubbed document, because such a document would fail validation.

**24. A claim id hashes the full source reference as stored, not the narrower locator the model returned.** Hash what is stored, so a reviewer can recompute the id from the claim alone. The canonical JSON form and a working test vector are pinned in the contracts so two implementations cannot disagree.

## The pipeline and who decides what

**25. Hybrid orchestration. Code sequences the pipeline. One frontier agent, the editor, owns the judgment half.** The editor reads the existing themes, decides append versus open new, writes the digest and decides what gets proposed for filing. Everything else is code, because putting the reproducible parts of a pipeline at the mercy of a model's control flow buys nothing and costs determinism.

**26. The editor is a two call design, not a tool using loop.** Call one returns an `EditorThemeRequest` naming the themes it needs. Code resolves those themes, logs a read event for each one, and passes them into call two, which returns the `EditorProposal`. I chose this because it behaves identically over the seat path and the direct API path, and because the audit trail then does not depend on the model choosing to call a tool. Reads are logged because code did them, not because the model was cooperative.

**27. Deterministic code, not a model, wherever a join, a regex or arithmetic will do.** Account enrichment, citation verification, prioritization scoring and PII scrubbing are all code. Cheaper, reproducible, and unhallucinatable. It is also the honest engineering answer, which is the one being graded.

**28. Prioritization scores are computed in code and the model writes only the narrative rationale.** Numbers a reviewer can recompute beat numbers a model asserted, and Andrew will check.

**29. Score rounding is `floor(total + 0.5)`, clamped to 0 through 100.** Python's `round` is banker's rounding, which means two correct implementations can disagree on a half value. Pinning the rule means they cannot.

**30. `speaker_side` is derived by code from the connector's participant side, never by the model.** The model can still quote a staff turn, and when it does the verifier rejects the claim with `speaker_not_client`. That is deliberate: the trap where an employee says the customer's line is caught at the verifier, where it is a join, rather than in a prompt, where it is a hope.

**31. I added a fourth Salesforce tool, `sfdc_get_users`, because side cannot be derived without it.** `CaseComment.CreatedById` alone cannot tell staff from a customer, and side is mandatory on every claim. `UserType = Standard` is a Momentive Software employee, anything else is a portal or community user and therefore a client, and an unresolved user maps to staff. Gong's `affiliation = Unknown` maps to staff for the same reason. An unidentifiable speaker must never be able to produce a client claim, so the unknown case always falls to the side that cannot manufacture evidence.

**32. Citations resolve to the transcript turn, not to the sentence.** A turn is one speaker's monologue. The reader copies the turn's locator exactly as shown and quotes a contiguous span inside it, and the verifier resolves the turn and asserts the quote is an exact substring of the sentences inside the cited window. I considered sentence level spans and dropped them, because a model computing millisecond boundaries is exactly the arithmetic that should not be delegated to a model. The digest renders the turn's start as mm:ss.

**33. The pipeline runs on simulated dates.** A claim's capture time is the ingest run's timestamp for the day it covers, and a theme's last verified date is the build run's date. Recency, quiet and stale are therefore computed against the corpus calendar and reproduce identically on any day the demo is run, instead of drifting every day nobody touches the repository.

**34. The verify horizon is 14 days from a theme's last verified date, stated once in the contracts.** One theme in the corpus receives nothing after week 37, so it is the one that goes quiet and then goes stale at the week 39 build. The flag has something real to fire on.

**35. The approval gate writes real GitHub issues, and only when a human runs `approve`.** The agent drafts a proposal and can never file one. Two steps, create and approve, in a system the team already trusts, demonstrable in thirty seconds. A missing credential does not break the demo: the store logs a withheld commit and returns cleanly.

**36. The weekly digest's run line aggregates the week's ingest runs, not just the build.** Sources, withheld comments, redactions, claims verified and rejected, and the cost of ingest plus build. A product manager reads the digest as the week's work, not as one build process. The build's own manifest keeps its own counts and the weekly aggregate sits beside it.

**37. The manifest's proposal count counts propose events, not files on disk.** The audit roll up increments once per audited propose action, so the weekly manifests read 13, 11 and 9 while the committed proposal directories hold 6, 5 and 4, one file per distinct theme. Both numbers are published. I am noting it rather than quietly reconciling it, because a reader who counts the files will otherwise think something is wrong.

## The mock corpus

**38. The mock corpus carries four deliberate traps.** Dedupe, classification, vocabulary reconciliation and least privilege each need something real to do, or they are claims in a README rather than behaviour in a system.

**39. The corpus is produced by a committed generation script, and the traps are hand written so they are exact.** The script means the team can regenerate and scale it. Hand writing the traps means the traps cannot drift, and the traps are the proof. Three weeks of corpus: week one is the cold start, week two appends and opens exactly one genuinely new theme, week three has a theme going quiet and the stale flag firing. Three digests is the minimum that shows the store behaving as memory rather than as a log.

**40. The mock connectors mirror the real Gong and Salesforce API shapes field for field.** The production swap is then a base URL and a credential with no translation layer. This is the detail I expect to be spot checked, so it is the detail I did properly.

**41. One file per Gong call and one file per case, and the index lists the trap files even though a different author writes them.** The generator writes the index from the trap slots in the seed specification, which removed the only ordering dependency between the corpus generator and the trap author. Traps live in an identical directory shape and load through the same code path, so nothing special happens to them at read time.

**42. The generated transcripts were rewritten once for coherence.** The first cut placed monologues by a coin flip, which could put a closing line first and repeat the same filler sentence back to back. They now follow a fixed shape: greeting, agenda, the one planted point with a concrete detail and a question and an answer, then two or three genuinely unrelated exchanges, then a close. Realistic mock data is part of what gets spot checked, and a transcript that reads like it was shuffled undermines everything built on top of it.

**43. A generated case subject is the first clause of that account's own planted claim, never the theme title.** The first cut used the theme title as the subject of every case in a theme, which handed the editor the vocabulary reconciliation trap for free, in the data, before the model ever looked at it. That is a two line fix and I made it directly on the generator after its worker had finished, which is the one time in this build I edited product code outside the worker that owned it. I am recording it because the rule it breaks is one I set myself.

## The build itself

**44. The build is a parallel fanout of single purpose agents under one orchestrator.** Every worker owns an exclusive set of file paths, receives only the contract slice it needs, and returns a structured envelope with its assumptions in a named array rather than buried in code. Context rot is the failure mode of a large agent build, and the fix is narrow briefs and exclusive ownership, not a bigger context window. This document exists because those envelopes existed.

**45. The build roster ran on four tiers and `config/build_models.yaml` records what ran.** The orchestrator on `claude-fable-5-1`, the writer and reviewer tier on `claude-opus-5`, and the cheap tier on `claude-sonnet-5`. The plan named `claude-opus-4-6` for the cheap tier; the harness offers opus, sonnet and haiku, and sonnet is the honest cheap tier. Writing down what actually ran beats writing down what was planned.

**46. The Anthropic direct adapter is implemented and unit tested against a captured request body, not exercised live.** There is no API key on this machine. I would rather ship an adapter whose exact request body is asserted in a test than claim a live call I did not make.

**47. Both repositories are public and contain nothing proprietary.** The link can be forwarded without a permission step.

## Tuning: what the live runs showed

**48. The first live run was measured, not shipped.** It produced 83 claims and 20 themes against a plan of 9, the golden set came back 17 of 18, and rerunning week 37 agreed with itself at 0.79 Jaccard. Three separate causes, each fixed at the thing that owned it and the whole pipeline re-run end to end: filler conversation in the generated corpus carried sentences a reader could legitimately extract as asks; the readers were splitting one point into a problem claim and a fix claim and quoting restatements; and the editor was splitting facets of one problem into separate themes. The golden set caught the reader miss and the theme count caught the rest. This is the eval loop doing its job, so it is reported here rather than hidden.

**49. Live run two, on the tuned build: 55 claims from 53 sources, 12 themes.** Week 37 opened 11, week 38 opened exactly one, week 39 opened none with four quiet and four stale, the week 37 rerun agreed at 1.000, replay was byte identical. The golden set still caught one reader recall miss: the reader quoted a non claim remark and missed an explicit stated need. So the reader prompts went to 1.2.0 with a recall first rule and a stricter definition of praise, validated against a corpus wide planted point recall check before the final run.

**50. Live run three is the sample run this write up reports.** 55 claims from 53 sources, 11 themes by week 39. Week 37 opened ten, nine problems plus the one planted praise. Week 38 opened exactly one. Week 39 opened none, with three quiet and three stale. Golden set 18 of 18, zero rejected claims, replay of the whole three weeks byte identical from the committed recordings in under twenty seconds with no network, 5.47 USD by the pricing table and 6.69 USD by the CLI's own accounting.

**51. Week 37 opened one more problem theme than the plan expected, and I left it.** The plan expected eight problem themes plus at most one praise theme, and the editor opened nine plus one. The extra one is a real and separate reporting gap in the corpus, it is cited, and no golden set assertion objects to it. Tuning it away would have meant tuning the agent to match my plan rather than to match the evidence.

**52. The week 37 rerun agreed on every claim to theme assignment and ranked a different top three, and I report it as measured.** Claim co-assignment is a perfect 1.000 and both runs produced the same theme count, so the editor partitions the week's claims identically. The ranking moved because the scores are computed in code from theme inputs, so what changed is which claims the second opinion grouped under which label, not the arithmetic. That is the honest read on how stable this is, and it is a better thing to publish than a number I picked because it looked better.
