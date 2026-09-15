"""Makes the three live calls B14 was allowed, in record mode, against the fixture store.

Run once, by hand, from the repository root:

    .venv/bin/python tests/fixtures/b14/record_live.py

Writes into tests/fixtures/b14/responses/. tests/test_analyst.py replays these with zero
network by pointing a replay mode Router at the same directory. Not itself a test: it makes
real calls and costs real money, which is why it is not collected by pytest.

One thing discovered running this against the real seat, worth recording here rather than
silently working around it in shared code: `contracts/AnalystAnswer.schema.json` carries a
top level `allOf` for its supported/citations/decline_reason cross check. The default
provider's native structured output path (`agent_sdk_seat`, the only live path available on
this machine, since ANTHROPIC_API_KEY is unset) serialises the contract schema as a forced
tool's `input_schema`, and the Anthropic API rejects a top level `oneOf`, `allOf` or `anyOf`
there with a 400. Confirmed directly against the CLI: the identical schema with `allOf`
stripped succeeds, the schema unchanged does not. Neither the schema (contracts/**, owned by
B1) nor the seat adapter (src/digest/providers/agent_sdk_seat.py, owned by another task) are
in B14's owns_paths, so rather than patch either, this script uses the router's OWN third,
already documented negotiation path instead: a provider that declines native_structured, so
Router.negotiate falls through to `schema_in_prompt`, which embeds the schema in the prompt
text and never touches a tool's input_schema at all. The router still validates the answer
against the real contract afterwards, exactly as it does for every other path.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from build_fixture_store import QUESTIONS, RUN_ID, build_store  # noqa: E402

from digest.agents.analyst.analyst import ask  # noqa: E402
from digest.audit import Audit  # noqa: E402
from digest.router import Router  # noqa: E402

RESPONSES_DIR = HERE / "responses"

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    """Drop a markdown code fence around the JSON, if the model added one.

    Only needed on the schema_in_prompt path: without native structured output the model is
    free to wrap its answer in a fence, and the router's own JSON parser does not unwrap one
    on purpose, so a first attempt with a fence fails validation and the router retries once
    with the validation error appended, asking again for a bare object. Stripping it here
    only saves that one avoidable retry; it changes nothing about what gets validated.
    """
    match = _FENCE_RE.match(text.strip())
    return match.group(1) if match else text


class PromptOnlySeatProvider:
    """The real `claude` CLI, minus `--json-schema`, so no forced tool call is involved.

    Declaring native_structured and strict_tools both false is what makes
    `Router.negotiate` choose `schema_in_prompt`: the router embeds the contract schema in
    the user text itself (`digest.router.schema_in_prompt_text`) before this provider ever
    sees it, and validates the answer against the real schema in code either way. This
    class exists only for this one off recording script; it is not shipped under src/.
    """

    name = "agent_sdk_seat"

    def __init__(self, cli_path: str | None = None, timeout: float = 300.0) -> None:
        self.cli_path = cli_path or shutil.which("claude") or "claude"
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"native_structured": False, "strict_tools": False,
                "thinking_style": "adaptive", "effort": True}

    def translate_model_id(self, canonical_model_id: str) -> str:
        return canonical_model_id

    def complete(self, model_id: str, system: str, user: str, schema: dict, params: dict) -> dict:
        argv = [self.cli_path, "-p", user, "--model", model_id, "--output-format", "json",
                "--system-prompt", system, "--tools", "", "--no-session-persistence",
                "--setting-sources", ""]
        dropped: list[str] = []
        if params.get("effort"):
            argv += ["--effort", params["effort"]]
        if params.get("temperature") is not None:
            dropped.append("temperature")
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
        payload = json.loads(proc.stdout or "{}")
        if proc.returncode != 0 or payload.get("is_error"):
            raise RuntimeError("claude CLI failed (exit %s): %s"
                               % (proc.returncode, payload.get("result") or proc.stderr[:400]))
        usage = payload.get("usage") or {}
        return {
            "text": _strip_fence(payload.get("result") or ""),
            "tokens_in": int(usage.get("input_tokens") or 0),
            "tokens_out": int(usage.get("output_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
            "stop_reason": str(payload.get("stop_reason") or "end_turn"),
            "dropped_params": dropped,
            "provider_reported_cost_usd": payload.get("total_cost_usd"),
        }


def main() -> int:
    store_path = HERE / "_live_store"
    store = build_store(store_path)
    router = Router(REPO / "config" / "models.yaml", mode="record", responses_dir=RESPONSES_DIR)
    router.set_provider(PromptOnlySeatProvider())

    for name, question in QUESTIONS.items():
        audit = Audit(RUN_ID, store_path)
        answer = ask(question, store, router, audit)
        print("== %s ==" % name)
        print("question:", question)
        print("supported:", answer["supported"])
        print("answer:", answer["answer"])
        print("citations:", answer["citations"])
        print("decline_reason:", answer["decline_reason"])
        print()

    print("wrote recordings to %s" % RESPONSES_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
