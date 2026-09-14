"""The contract pack has to be self checking, or it is just documentation.

Three things are asserted here. Every schema in contracts/ loads, is a legal Draft 2020-12
schema, is strict, and carries a schema_version const. Every example document validates
against the schema its filename names. Every deliberately malformed example is rejected.
The third one is the one that matters: a schema that accepts everything passes the first
two and catches nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest.contracts import (  # noqa: E402
    ContractViolation,
    contracts_dir,
    is_valid,
    iter_errors,
    list_schemas,
    load_schema,
    schema_path,
    schema_version,
    validate,
)

CONTRACTS = REPO / "contracts"
EXAMPLES = CONTRACTS / "examples"
INVALID = EXAMPLES / "invalid"

SCHEMA_NAMES = sorted(p.name[: -len(".schema.json")] for p in CONTRACTS.glob("*.schema.json"))
EXAMPLE_FILES = sorted(EXAMPLES.glob("*.example.json"))
INVALID_FILES = sorted(INVALID.glob("*.invalid.json"))

EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


def _walk_objects(node, trail):
    """Yield (trail, subschema) for every object typed subschema that declares properties.

    A subschema with additionalProperties true and no properties is free form on purpose
    (AuditEvent.detail, RejectedClaim.raw, RecordedResponse.result.data, a Gong party
    context entry) and is skipped here. Everything that declares a property must be strict.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield trail, node
        for key, value in node.items():
            if key in {"description", "title", "$id", "$schema", "const", "enum", "examples"}:
                continue
            if key == "properties" and isinstance(value, dict):
                for pname, pval in value.items():
                    yield from _walk_objects(pval, trail + [pname])
            elif isinstance(value, (dict, list)):
                yield from _walk_objects(value, trail)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item, trail)


def test_pack_is_where_the_loader_thinks_it_is():
    assert contracts_dir() == CONTRACTS
    assert (CONTRACTS / "README.md").is_file()
    assert (CONTRACTS / "INTERFACES.md").is_file()
    assert (CONTRACTS / "mcp_tools.md").is_file()
    assert (CONTRACTS / "errors.md").is_file()
    assert (CONTRACTS / "file_formats.md").is_file()
    assert (CONTRACTS / "ownership.yaml").is_file()
    assert (CONTRACTS / "store_ROUTER.md").is_file()


def test_there_are_schemas_and_the_loader_lists_all_of_them():
    assert len(SCHEMA_NAMES) >= 20
    assert list_schemas() == SCHEMA_NAMES


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_loads_and_is_a_legal_draft_2020_12_schema(name):
    doc = load_schema(name)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert doc["$id"].endswith("/%s.schema.json" % name)
    assert doc.get("title") and doc.get("description")
    jsonschema.Draft202012Validator.check_schema(doc)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_has_a_version_const(name):
    assert schema_version(name) == "1.0.0"
    assert load_schema(name)["properties"]["schema_version"]["const"] == "1.0.0"
    assert "schema_version" in load_schema(name)["required"]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_object_is_strict_and_fully_required(name):
    doc = load_schema(name)
    loose = []
    for trail, sub in _walk_objects(doc, []):
        where = "%s:%s" % (name, ".".join(trail) or "<root>")
        if sub.get("additionalProperties") is not False:
            loose.append("additionalProperties not false at " + where)
        declared = set(sub["properties"])
        required = set(sub.get("required", []))
        if declared != required:
            loose.append("required != properties at %s (missing %s)"
                         % (where, sorted(declared - required)))
    assert loose == [], loose


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_no_cross_file_reference(name):
    """Every schema file must stand alone, so any validator can load one file with no resolver."""
    raw = schema_path(name).read_text(encoding="utf-8")
    doc = json.loads(raw)

    def refs(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref":
                    yield v
                else:
                    yield from refs(v)
        elif isinstance(node, list):
            for item in node:
                yield from refs(item)

    bad = [r for r in refs(doc) if not r.startswith("#/$defs/")]
    assert bad == [], bad


def test_every_schema_has_an_example_and_a_malformed_example():
    have_example = {p.name[: -len(".example.json")] for p in EXAMPLE_FILES}
    have_invalid = {p.name[: -len(".invalid.json")] for p in INVALID_FILES}
    assert have_example == set(SCHEMA_NAMES), sorted(set(SCHEMA_NAMES) ^ have_example)
    assert have_invalid == set(SCHEMA_NAMES), sorted(set(SCHEMA_NAMES) ^ have_invalid)


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_validates(path):
    name = path.name[: -len(".example.json")]
    doc = json.loads(path.read_text(encoding="utf-8"))
    validate(doc, name)
    assert doc["schema_version"] == schema_version(name)


@pytest.mark.parametrize("path", INVALID_FILES, ids=lambda p: p.name)
def test_malformed_example_is_rejected(path):
    name = path.name[: -len(".invalid.json")]
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert not is_valid(doc, name)
    with pytest.raises(ContractViolation) as exc:
        validate(doc, name)
    assert exc.value.schema_name == name
    assert exc.value.errors


def test_errors_are_deterministic_and_path_prefixed():
    doc = json.loads((INVALID / "Claim.invalid.json").read_text(encoding="utf-8"))
    first = iter_errors(doc, "Claim")
    second = iter_errors(doc, "Claim")
    assert first == second == sorted(first)
    assert all(e.startswith("$") for e in first)


def test_unknown_schema_and_path_shaped_names_are_refused():
    for bad in ["NoSuchSchema", "../etc/passwd", "sub/Claim", ""]:
        with pytest.raises(ContractViolation):
            load_schema(bad)


def test_name_forms_are_interchangeable():
    assert load_schema("Claim") is load_schema("Claim.schema.json") is load_schema("Claim.schema")


def test_analyst_answer_conditional_rules_bite_both_ways():
    good = json.loads((EXAMPLES / "AnalystAnswer.example.json").read_text(encoding="utf-8"))
    validate(good, "AnalystAnswer")

    unsupported_with_citations = dict(good, supported=False, decline_reason="no evidence in the store")
    assert not is_valid(unsupported_with_citations, "AnalystAnswer")

    unsupported_clean = dict(good, supported=False, citations=[],
                             decline_reason="no evidence in the store")
    validate(unsupported_clean, "AnalystAnswer")

    supported_without_citations = dict(good, citations=[])
    assert not is_valid(supported_without_citations, "AnalystAnswer")

    supported_with_decline = dict(good, decline_reason="should not be here")
    assert not is_valid(supported_with_decline, "AnalystAnswer")


def test_claim_source_ref_variants_are_mutually_exclusive():
    claim = json.loads((EXAMPLES / "Claim.example.json").read_text(encoding="utf-8"))
    validate(claim, "Claim")

    mixed = json.loads(json.dumps(claim))
    mixed["source_ref"]["case_id"] = "5008W00002aQpLrQAK"
    assert not is_valid(mixed, "Claim"), "a ref carrying both shapes must fail oneOf"

    partial = json.loads(json.dumps(claim))
    del partial["source_ref"]["affiliation"]
    assert not is_valid(partial, "Claim"), "the model may not omit a code filled ref field"


def test_reader_claim_is_the_model_facing_subset_only():
    reader = load_schema("ReaderOutput")
    claim = load_schema("Claim")
    model_fields = set(reader["$defs"]["ReaderClaim"]["properties"])
    assert model_fields == {
        "source", "source_ref", "verbatim", "paraphrase", "topic",
        "product_area", "claim_type", "importance", "importance_reason",
    }
    pipeline_fields = set(claim["properties"]) - model_fields
    assert pipeline_fields == {
        "schema_version", "claim_id", "run_id", "account_id", "account_name",
        "account_type", "speaker_side", "captured_at", "prompt_hash", "model_tier",
    }
    # The bounds the model is held to must match the bounds the stored claim is held to.
    for field in ["verbatim", "paraphrase", "topic", "importance_reason"]:
        assert (reader["$defs"]["ReaderClaim"]["properties"][field]["maxLength"]
                == claim["properties"][field]["maxLength"])


def test_no_model_id_outside_the_examples_directory():
    """A model id in a schema would put a model name back into application reach."""
    fam = "cla" + "ude-"
    needles = [fam + n for n in ("haiku", "opus", "fable", "sonnet")] + ["anthro" + "pic."]
    offenders = []
    for path in sorted(CONTRACTS.rglob("*")):
        if not path.is_file() or EXAMPLES in path.parents or path == EXAMPLES:
            continue
        if path.suffix not in {".json", ".md", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json" and any(n in text for n in needles):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], offenders


def test_no_en_or_em_dash_anywhere_in_what_this_task_owns():
    owned = [CONTRACTS, SRC / "digest" / "contracts.py", SRC / "digest" / "errors.py",
             Path(__file__)]
    offenders = []
    for root in owned:
        paths = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for ch, label in ((EN_DASH, "en dash"), (EM_DASH, "em dash")):
                if ch in text:
                    offenders.append("%s in %s" % (label, path))
    assert offenders == [], offenders
