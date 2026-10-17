import boto3
import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.storage import LocalStorage, S3Storage, make_storage
from tests.conftest import fake_aws

BUCKET = "pantrypulse-test-uploads"


@pytest.fixture
def local_store(tmp_path):
    return LocalStorage(tmp_path / "uploads")


@pytest.fixture
def s3_client():
    with fake_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path):
    """The same contract is checked against both backends."""
    if request.param == "local":
        yield LocalStorage(tmp_path / "uploads")
        return
    with fake_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield S3Storage(BUCKET, client=client)


def test_put_then_get_round_trips_bytes(store):
    store.put("donations/abc123.pdf", b"%PDF-1.7 hello", "application/pdf")
    assert store.get("donations/abc123.pdf") == b"%PDF-1.7 hello"
    assert store.exists("donations/abc123.pdf")


def test_directories_are_created_on_demand_not_at_construction(tmp_path):  # local only
    root = tmp_path / "not-yet"
    LocalStorage(root)
    assert not root.exists()
    LocalStorage(root).put("a/b/c.txt", b"x", "text/plain")
    assert (root / "a/b/c.txt").read_bytes() == b"x"


def test_overwrite_replaces_contents(store):
    store.put("k.txt", b"one", "text/plain")
    store.put("k.txt", b"two", "text/plain")
    assert store.get("k.txt") == b"two"


def test_overwrite_leaves_no_temp_files_locally(local_store, tmp_path):
    local_store.put("k.txt", b"one", "text/plain")
    local_store.put("k.txt", b"two", "text/plain")
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
def test_unsafe_keys_are_rejected_for_every_operation(store, key, tmp_path):
    for operation in (
        lambda: store.put(key, b"x", "text/plain"),
        lambda: store.get(key),
        lambda: store.delete(key),
        lambda: store.exists(key),
    ):
        with pytest.raises(ValueError):
            operation()
    assert not (tmp_path / "escape.txt").exists()


def test_an_empty_file_and_a_large_file_round_trip(store):
    store.put("empty.bin", b"", "application/octet-stream")
    assert store.get("empty.bin") == b""
    big = bytes(range(256)) * 25_000  # 6.4 MB
    store.put("big.bin", big, "application/octet-stream")
    assert store.get("big.bin") == big


# --- S3 only ----------------------------------------------------------------------------------


def test_s3_objects_are_encrypted_at_rest_and_keep_their_content_type(s3_client):
    S3Storage(BUCKET, client=s3_client).put("donations/a.pdf", b"%PDF", "application/pdf")
    head = s3_client.head_object(Bucket=BUCKET, Key="donations/a.pdf")
    assert head["ServerSideEncryption"] == "AES256"
    assert head["ContentType"] == "application/pdf"


def test_s3_unsafe_keys_are_refused_before_any_request_is_made():
    class Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"the S3 client was used ({name}) for an unsafe key")

    store = S3Storage(BUCKET, client=Exploding())
    for key in ("../x", "/etc/passwd", "a//b", ""):
        with pytest.raises(ValueError):
            store.put(key, b"x", "text/plain")


def test_s3_errors_other_than_missing_key_are_not_hidden(s3_client):
    store = S3Storage("a-bucket-that-does-not-exist", client=s3_client)
    with pytest.raises(ClientError) as raised:
        store.get("k.txt")
    assert raised.value.response["Error"]["Code"] == "NoSuchBucket"
    with pytest.raises(ClientError):
        store.put("k.txt", b"x", "text/plain")


def test_s3_exists_is_false_for_a_missing_key_and_not_fooled_by_a_prefix(s3_client):
    store = S3Storage(BUCKET, client=s3_client)
    store.put("donations/a.pdf", b"x", "application/pdf")
    assert not store.exists("donations")
    assert not store.exists("donations/a")
    assert store.exists("donations/a.pdf")


def test_s3_needs_a_bucket_name():
    with pytest.raises(ValueError, match="bucket"):
        S3Storage("")


# --- choosing the backend from settings ---------------------------------------------------------


def settings_with(settings: Settings, **update) -> Settings:
    return settings.model_copy(update=update)


def test_the_default_backend_is_the_local_folder(settings, tmp_path):
    chosen = make_storage(settings_with(settings, storage_dir=str(tmp_path)))
    assert isinstance(chosen, LocalStorage)


def test_s3_is_chosen_by_settings_and_uses_the_named_bucket(settings):
    with fake_aws():
        chosen = make_storage(settings_with(settings, storage_backend="s3", s3_bucket=BUCKET))
    assert isinstance(chosen, S3Storage) and chosen.bucket == BUCKET


def test_s3_without_a_bucket_stops_at_startup_with_a_clear_message(settings):
    with pytest.raises(ValueError, match="S3_BUCKET"):
        make_storage(settings_with(settings, storage_backend="s3", s3_bucket=""))


def test_an_unknown_backend_name_is_refused(settings):
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        make_storage(settings_with(settings, storage_backend="ftp"))


def test_the_no_aws_guard_still_refuses_a_client_outside_the_fake():
    with pytest.raises(AssertionError, match="boto3"):
        boto3.client("s3", region_name="us-east-1")
    with fake_aws():
        boto3.client("s3", region_name="us-east-1")  # allowed here: it is moto's in-memory fake
    with pytest.raises(AssertionError, match="boto3"):
        boto3.client("s3", region_name="us-east-1")
