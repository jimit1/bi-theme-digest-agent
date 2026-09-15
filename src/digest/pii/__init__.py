"""PII scrubbing for source documents. See digest.pii.scrubber."""
from __future__ import annotations

from digest.pii.scrubber import (
    PLACEHOLDERS,
    load_names,
    scrub,
    scrub_document,
)

__all__ = ["PLACEHOLDERS", "load_names", "scrub", "scrub_document"]
