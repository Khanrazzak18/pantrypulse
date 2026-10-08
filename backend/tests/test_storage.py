import pytest

from app.storage import LocalStorage, S3Storage


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path / "uploads")


def test_put_then_get_round_trips_bytes(store):
    store.put("donations/abc123.pdf", b"%PDF-1.7 hello", "application/pdf")
    assert store.get("donations/abc123.pdf") == b"%PDF-1.7 hello"
    assert store.exists("donations/abc123.pdf")


def test_directories_are_created_on_demand_not_at_construction(tmp_path):
    root = tmp_path / "not-yet"
    LocalStorage(root)
    assert not root.exists()
    LocalStorage(root).put("a/b/c.txt", b"x", "text/plain")
    assert (root / "a/b/c.txt").read_bytes() == b"x"


def test_overwrite_replaces_contents_and_leaves_no_temp_files(store, tmp_path):
    store.put("k.txt", b"one", "text/plain")
    store.put("k.txt", b"two", "text/plain")
    assert store.get("k.txt") == b"two"
    assert [p.name for p in (tmp_path / "uploads").rglob("*") if p.is_file()] == ["k.txt"]


def test_delete_removes_the_file_and_is_idempotent(store):
    store.put("k.txt", b"x", "text/plain")
    store.delete("k.txt")
    assert not store.exists("k.txt")
    store.delete("k.txt")  # already gone: no error


def test_getting_a_missing_key_raises_file_not_found(store):
    with pytest.raises(FileNotFoundError):
        store.get("nope.txt")


@pytest.mark.parametrize(
    "key",
    ["../escape.txt", "a/../../escape.txt", "/etc/passwd", "a\\b.txt", "", ".", "a/./b",
     "a//b", "bad\x00key", " leading-space", "a/b/..", "..hidden/../x"],
)  # fmt: skip
def test_unsafe_keys_are_rejected_for_every_operation(store, tmp_path, key):
    for operation in (
        lambda: store.put(key, b"x", "text/plain"),
        lambda: store.get(key),
        lambda: store.delete(key),
        lambda: store.exists(key),
    ):
        with pytest.raises(ValueError):
            operation()
    assert not (tmp_path / "escape.txt").exists()


def test_s3_backend_is_a_documented_stub():
    with pytest.raises(NotImplementedError, match="S3"):
        S3Storage("some-bucket").put("k", b"x", "text/plain")
