"""A fingerprint of the golden answer key (every expected.json), so it cannot change unnoticed.

The key was corrected once after the first eval run (see docs/eval/intake-eval.md). It is frozen
now: `make eval` refuses to run if the key differs from the digest committed in KEY.sha256, so a
later score cannot be helped by editing the answers.
"""

import hashlib
from pathlib import Path

from eval.make_golden_set import GOLDEN_DIR

DIGEST_FILE = GOLDEN_DIR / "KEY.sha256"


def key_digest(root: Path = GOLDEN_DIR) -> str:
    h = hashlib.sha256()
    for path in sorted(root.glob("*/expected.json")):
        h.update(path.parent.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def frozen_digest() -> str:
    return DIGEST_FILE.read_text().split()[0]


def assert_frozen() -> None:
    if key_digest() != frozen_digest():
        raise SystemExit(
            "The golden answer key differs from the frozen copy (eval/golden/KEY.sha256). "
            "Scores would not be comparable. Restore the key, or freeze a new one on purpose."
        )
