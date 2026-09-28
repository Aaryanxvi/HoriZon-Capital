"""Tripwire: fails if the authorship marks or the signed manifest are stripped.

This is the anti-removal mechanism. Anyone who deletes the notices to pass the
code off as their own has to also find and neuter this test, the manifest, the
public key and 371 individual file headers - and the git history still names
the author.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

INNER = Path(__file__).resolve().parents[2]
SCRIPT = INNER / "scripts" / "authorship.py"


def _find_root() -> Path:
    """The signed root is the nearest ancestor holding AUTHORSHIP.json.

    The tree has a nested layout: the git remote lives on the outer
    "Horizon capital" repo, which tracks this inner directory, so the manifest
    sits one level above INNER.
    """
    for candidate in (INNER, *INNER.parents):
        if (candidate / "AUTHORSHIP.json").exists():
            return candidate
    return INNER


REPO = _find_root()
MANIFEST = REPO / "AUTHORSHIP.json"

# iter_sources() and the per-file tokens are relative to the signed root, so
# the module must be imported with the same root the manifest was signed at.
os.environ["HC_AUTHORSHIP_ROOT"] = str(REPO)

AUTHOR_NAME = "Aaryan Baadkar"
AUTHOR_EMAIL = "aaryanbaadkar71@gmail.com"
MARK = "HC-AUTH-AARYAN-BAADKAR"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists(), reason="authorship tooling removed from this checkout"
)


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    import authorship

    return authorship


def test_selfcheck_passes():
    """The stamping logic's own assertions still hold."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "selfcheck"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "HC_AUTHORSHIP_ROOT": str(REPO)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_manifest_signature_valid():
    """Ed25519 signature over the manifest still verifies."""
    assert MANIFEST.exists(), "AUTHORSHIP.json is missing"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "verify"],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "HC_AUTHORSHIP_ROOT": str(REPO)},
    )
    assert "signature OK" in proc.stdout, proc.stdout + proc.stderr
    assert "MARK STRIPPED" not in proc.stdout, proc.stdout


def test_manifest_names_the_author():
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    author = doc["payload"]["author"]
    assert author["name"] == AUTHOR_NAME
    assert author["email"] == AUTHOR_EMAIL
    assert doc["algorithm"] == "Ed25519"


def test_every_source_file_is_marked():
    """Coverage must stay at 100%. A stripped file fails here by name."""
    authorship = _load()
    unmarked = [
        authorship.relpath(p)
        for p in authorship.iter_sources(REPO)
        if MARK not in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not unmarked, f"authorship mark missing from: {unmarked[:20]}"


def _tooling(authorship) -> set[str]:
    """These two carry MARK and the ZW_* code points as data, not as a stamp.

    Derived rather than hardcoded, because the paths are relative to whichever
    root the manifest was signed at.
    """
    return {authorship.relpath(SCRIPT), authorship.relpath(Path(__file__))}


def test_zero_width_signature_survives():
    """The invisible signature decodes back to the author in every file."""
    authorship = _load()
    tooling = _tooling(authorship)
    checked = 0
    for path in authorship.iter_sources(REPO):
        if authorship.relpath(path) in tooling:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if authorship.ZW_FENCE not in text:
            continue
        assert authorship.zw_decode(text) == authorship.SIGNATURE_PLAINTEXT, path
        checked += 1
    assert checked > 300, f"only {checked} files carry the zero-width signature"


def test_git_history_attributes_the_author():
    """Independent of any file contents: the commit history names the author."""
    proc = subprocess.run(
        ["git", "log", "--format=%an <%ae>"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        pytest.skip("not a git checkout")
    authors = set(proc.stdout.split("\n")) - {""}
    assert f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>" in authors or any(
        AUTHOR_EMAIL in a for a in authors
    ), f"author absent from git history: {authors}"
