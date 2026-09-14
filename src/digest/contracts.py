"""Load and enforce the contract pack in contracts/.

Every document that crosses a boundary in this system is validated here, by name, against
a file on disk. There is no inline schema anywhere in the package. That is the whole point:
a schema change is a diff on a pull request, and the run log records which version was used.

Usage:

    from digest.contracts import validate, load_schema, schema_version
    validate(doc, "ReaderOutput")          # raises ContractViolation on failure
    schema_version("ReaderOutput")         # "1.0.0"

Locating the pack: DIGEST_CONTRACTS_DIR wins if it is set. Otherwise this module walks up
from its own file until it finds a directory containing contracts/README.md. The marker is
the README rather than the directory name, so a stray directory called contracts elsewhere
on the path cannot be picked up by accident.

Validation is jsonschema Draft 2020-12. Every schema file is self contained: there are no
cross file $ref entries anywhere in the pack, so one file can be handed to any validator,
in any language, with no resolver configured.
"""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

import jsonschema

from digest.errors import ContractViolation

__all__ = [
    "ContractViolation",
    "CONTRACTS_DIR_ENV",
    "contracts_dir",
    "schema_path",
    "load_schema",
    "schema_version",
    "list_schemas",
    "validator_for",
    "validate",
    "iter_errors",
    "is_valid",
]

CONTRACTS_DIR_ENV = "DIGEST_CONTRACTS_DIR"
_MARKER = "README.md"
_SUFFIX = ".schema.json"


def _find_upwards() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts"
        if (candidate / _MARKER).is_file():
            return candidate
    raise ContractViolation(
        "contracts",
        ["could not locate a contracts directory above %s; set %s" % (here, CONTRACTS_DIR_ENV)],
    )


@functools.lru_cache(maxsize=1)
def _cached_dir(env_value: str | None) -> Path:
    if env_value:
        d = Path(env_value).expanduser().resolve()
        if not (d / _MARKER).is_file():
            raise ContractViolation(
                "contracts", ["%s=%s does not contain %s" % (CONTRACTS_DIR_ENV, d, _MARKER)]
            )
        return d
    return _find_upwards()


def contracts_dir() -> Path:
    """Absolute path of the contract pack. Honours DIGEST_CONTRACTS_DIR."""
    return _cached_dir(os.environ.get(CONTRACTS_DIR_ENV))


def _normalise(name: str) -> str:
    """Accept "Claim", "Claim.schema.json" or "Claim.schema". Reject anything path shaped."""
    stem = name.strip()
    if stem.endswith(_SUFFIX):
        stem = stem[: -len(_SUFFIX)]
    elif stem.endswith(".schema"):
        stem = stem[: -len(".schema")]
    if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        raise ContractViolation("contracts", ["%r is not a schema name" % name])
    return stem


def schema_path(name: str) -> Path:
    """Absolute path of one schema file. Does not check that it exists."""
    return contracts_dir() / (_normalise(name) + _SUFFIX)


@functools.lru_cache(maxsize=None)
def _load(stem: str, root: str) -> dict[str, Any]:
    path = Path(root) / (stem + _SUFFIX)
    if not path.is_file():
        raise ContractViolation("contracts", ["no schema named %s at %s" % (stem, path)])
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - a corrupt pack is a build failure
        raise ContractViolation(stem, ["schema file is not valid JSON: %s" % exc]) from exc


def load_schema(name: str) -> dict[str, Any]:
    """Return the parsed schema document. Cached; do not mutate the result."""
    return _load(_normalise(name), str(contracts_dir()))


def schema_version(name: str) -> str:
    """The semver string every document written against this schema must carry."""
    doc = load_schema(name)
    props = doc.get("properties", {})
    sv = props.get("schema_version", {})
    version = sv.get("const")
    if not isinstance(version, str):
        raise ContractViolation(
            _normalise(name), ["schema has no top level schema_version const"]
        )
    return version


def list_schemas() -> list[str]:
    """Every schema name in the pack, sorted."""
    return sorted(p.name[: -len(_SUFFIX)] for p in contracts_dir().glob("*" + _SUFFIX))


@functools.lru_cache(maxsize=None)
def _validator(stem: str, root: str) -> jsonschema.protocols.Validator:
    schema = _load(stem, root)
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    cls.check_schema(schema)
    return cls(schema)


def validator_for(name: str) -> jsonschema.protocols.Validator:
    """A cached, schema checked validator for one contract."""
    return _validator(_normalise(name), str(contracts_dir()))


def _format(error: jsonschema.ValidationError) -> str:
    path = "$" + "".join(
        "[%d]" % part if isinstance(part, int) else "." + str(part) for part in error.absolute_path
    )
    return "%s: %s" % (path, error.message)


def iter_errors(obj: Any, schema_name: str) -> list[str]:
    """Every validation error as a formatted string, sorted so the list is deterministic.

    Deterministic matters: this list is appended verbatim to the retry prompt, and a
    prompt that changes between runs would change its replay key.
    """
    errors = [_format(e) for e in validator_for(schema_name).iter_errors(obj)]
    return sorted(set(errors))


def validate(obj: Any, schema_name: str) -> None:
    """Validate obj against a named contract. Raises ContractViolation, returns None."""
    errors = iter_errors(obj, schema_name)
    if errors:
        raise ContractViolation(_normalise(schema_name), errors)


def is_valid(obj: Any, schema_name: str) -> bool:
    """True when obj validates. Use validate when you want the reasons."""
    return not iter_errors(obj, schema_name)
