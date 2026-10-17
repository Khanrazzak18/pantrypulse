import re
from typing import Protocol

# Slash-separated segments of letters, digits, `_`, `.` and `-`. A segment cannot start with a
# dot, which rules out `.`, `..` and hidden files; no backslashes, spaces, NULs or empty segments.
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*(/[A-Za-z0-9][A-Za-z0-9_.\-]*)*$")


def check_key(key: str) -> str:
    """The same rule for every backend, applied before anything touches a disk or the network."""
    if not isinstance(key, str) or not _KEY.match(key):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


class StorageBackend(Protocol):
    """Where uploaded files live. The app writes nothing to disk except through this."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...
