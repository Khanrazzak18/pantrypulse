"""The pre-commit hook really blocks secrets: tried in a throwaway git repository."""

import shutil
import subprocess

import pytest

from tests.conftest import BACKEND_DIR

ROOT = BACKEND_DIR.parent
GITLEAKS = ROOT / ".tools" / "bin" / "gitleaks"
# Looks like an AWS access key id and secret (random characters, not a real credential).
# Built from fragments so this file itself is not flagged by the scanner it tests.
FAKE_KEY_ID = "AK" + "IA" + "Q3EGRWXYZ7HNK5B2"
FAKE_AWS = (
    f'aws_access_key_id = "{FAKE_KEY_ID}"\naws_secret_access_key = "'
    + "w7Nq2Vx9Kd4L"
    + "m8Pz3Rt6Yb1Hc5Fg0Ja/Se+Ui2Oq"
    + '"\n'
)

pytestmark = pytest.mark.skipif(
    not GITLEAKS.exists(), reason="run `make security-tools` to install gitleaks"
)


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "Test")
    (tmp_path / ".githooks").mkdir()
    shutil.copy(ROOT / ".githooks" / "pre-commit", tmp_path / ".githooks" / "pre-commit")
    shutil.copy(ROOT / ".gitleaks.toml", tmp_path / ".gitleaks.toml")
    (tmp_path / ".tools" / "bin").mkdir(parents=True)
    (tmp_path / ".tools" / "bin" / "gitleaks").symlink_to(GITLEAKS)
    git("config", "core.hooksPath", ".githooks")
    return tmp_path, git


def commit(tmp_path, git, name, content):
    (tmp_path / name).write_text(content)
    git("add", "-f", name)
    return git("commit", "-q", "-m", "test")


def test_a_clean_commit_goes_through(repo):
    tmp_path, git = repo
    assert commit(tmp_path, git, "notes.txt", "nothing secret here\n").returncode == 0


def test_an_aws_key_in_a_file_blocks_the_commit(repo):
    tmp_path, git = repo
    result = commit(tmp_path, git, "config.py", FAKE_AWS)
    assert result.returncode != 0
    assert "leak" in (result.stdout + result.stderr).lower()
    assert FAKE_KEY_ID not in result.stdout + result.stderr  # redacted in the message


def test_a_private_key_blocks_the_commit(repo):
    tmp_path, git = repo
    key = (
        "-----BEGIN RSA "
        + "PRIVATE KEY-----\n"
        + "MIIEowIBAAKCAQEA"
        + "x7Qk9" * 60
        + "\n-----END RSA "
        + "PRIVATE KEY-----\n"
    )
    assert commit(tmp_path, git, "id_rsa", key).returncode != 0


@pytest.mark.parametrize("name", [".env", ".env.local", "backend/.env", ".env.production"])
def test_environment_files_are_blocked_even_with_harmless_content(repo, name):
    tmp_path, git = repo
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    result = commit(tmp_path, git, name, "PORT=3000\n")
    assert result.returncode != 0
    assert "must not be committed" in result.stdout + result.stderr


def test_the_example_environment_file_is_allowed(repo):
    tmp_path, git = repo
    assert commit(tmp_path, git, ".env.example", "JWT_SECRET=\nPORT=3000\n").returncode == 0


def test_the_real_repository_has_the_hook_and_it_is_executable():
    hook = ROOT / ".githooks" / "pre-commit"
    assert hook.exists() and hook.stat().st_mode & 0o111
    assert "gitleaks" in hook.read_text()
