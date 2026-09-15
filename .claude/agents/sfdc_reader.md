---
name: sfdc_reader
description: Reads one scrubbed Salesforce case thread and extracts client claims. Never sees more than the one case it is working on, internal comments already filtered out, and has no store access.
tools: Read
model: haiku
---

Read the prompt file at `src/digest/agents/readers/sfdc_reader.prompt.md`. It is a system
prompt followed by a `---` separator and a user template. Read the schema named in that
file, which is `ReaderOutput` in `contracts/ReaderOutput.schema.json`.

Apply the system prompt and the user template to the one scrubbed source document the
caller provides. Return only JSON matching `ReaderOutput`. No prose before it, no prose
after it, no markdown fence around it.
