"""What a finding asks a person to do, and which resource family it belongs to."""

from __future__ import annotations

import re
from typing import Any

REMOVE = "remove"
STOP = "stop"
RIGHTSIZE = "rightsize"
RETENTION = "retention"
REVIEW = "review"

_VERBS = {
    "delete": REMOVE,
    "remove": REMOVE,
    "terminate": REMOVE,
    "release": REMOVE,
    "decommission": REMOVE,
    "stop": STOP,
    "shutdown": STOP,
    "resize": RIGHTSIZE,
    "downsize": RIGHTSIZE,
    "rightsize": RIGHTSIZE,
    "reduce": RIGHTSIZE,
    "shrink": RIGHTSIZE,
    "retention": RETENTION,
    "lifecycle": RETENTION,
    "expire": RETENTION,
    "review": REVIEW,
    "investigate": REVIEW,
    "verify": REVIEW,
    "confirm": REVIEW,
    "check": REVIEW,
}

_VERB_RE = re.compile(
    r"\b(delete|remove|terminate|release|decommission|stop|shut ?down|resize|"
    r"downsize|right-?size|reduce|shrink|retention|lifecycle|expire|review|"
    r"investigate|verify|confirm|check)\b"
)


def classify_action(finding: dict[str, Any]) -> str:
    """The first verb in the recommendation decides; rule findings are removals."""
    if str(finding.get("detected_by") or "").startswith("rule:"):
        return REMOVE
    match = _VERB_RE.search(str(finding.get("recommendation") or "").lower())
    if not match:
        return REVIEW
    verb = match.group(1).replace(" ", "").replace("-", "")
    return _VERBS.get(verb, REVIEW)


def family_of(resource_type: str) -> str:
    """Types that are cleaned up together share a family."""
    if "snapshot" in resource_type.lower():
        return "snapshot"
    return resource_type
