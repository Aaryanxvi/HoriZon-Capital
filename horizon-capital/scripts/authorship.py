#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Horizon Capital - proprietary source.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# ---------------------------------------------------------------------------
"""Authorship stamping, signing and verification for Horizon Capital.

Six layers of provenance, strongest last:

  1. header    - comment block at the top of every source file
  2. footer    - differently-worded mark at the bottom of every source file
  3. zerowidth - invisible U+200B/U+200C signature inside the header block
  4. dunders   - __author__ / __copyright__ in every Python package __init__
  5. metadata  - LICENSE, pyproject.toml, package.json author fields
  6. manifest  - AUTHORSHIP.json: sha256 of every file, Ed25519-signed

Layers 1-5 are evidence a reader finds by grepping. They are removable by
anyone with write access - that is unavoidable, text in a file can always be
deleted. Layer 6 is the layer that actually proves something: it is a signed
statement that on date D the holder of a private key possessed exactly this
tree. Stripping the marks changes the hashes, so a stripped copy fails
verification against the signature you keep.

Usage:
    py -3.14 scripts/authorship.py stamp     # apply layers 1-5 (idempotent)
    py -3.14 scripts/authorship.py sign      # write + sign AUTHORSHIP.json
    py -3.14 scripts/authorship.py verify    # check signature + hashes
    py -3.14 scripts/authorship.py audit     # report mark coverage
    py -3.14 scripts/authorship.py selfcheck # run assertions, touch nothing

The private signing key lives OUTSIDE the repo, in
~/.horizon-authorship/ed25519_private.pem - never commit it. The matching
public key is committed as AUTHORSHIP.pub so anyone can verify.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

AUTHOR_NAME = "Aaryan Baadkar"
AUTHOR_EMAIL = "aaryanbaadkar71@gmail.com"
AUTHOR_GITHUB = "github.com/Aaryanxvi"
COPYRIGHT_YEAR = "2026"
PROJECT = "Horizon Capital"

# Grep for this token to find every stamped file.
MARK = "HC-AUTH-AARYAN-BAADKAR"

# Defaults to the horizon-capital tree. Set HC_AUTHORSHIP_ROOT to stamp a
# different root - the outer "Horizon capital" repo is the one with the
# GitHub remote and it tracks one source file above this directory.
REPO = Path(os.environ.get("HC_AUTHORSHIP_ROOT")
            or Path(__file__).resolve().parent.parent).resolve()
MANIFEST = REPO / "AUTHORSHIP.json"
PUBKEY = REPO / "AUTHORSHIP.pub"
KEYDIR = Path.home() / ".horizon-authorship"
PRIVKEY = KEYDIR / "ed25519_private.pem"

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
    "dist", "build", ".next", "out", "site-packages", ".mypy_cache",
    ".ruff_cache", ".superpowers", "coverage", ".turbo", "release",
    # Git worktrees hold full second checkouts of this same tree. Stamping
    # them dirties an unrelated branch, and the per-file token is derived from
    # the path, so the marks would not even match the primary copy.
    ".worktrees", "worktrees", ".claude", ".pytest_cache",
}

# extension -> (line_prefix, block_open, block_close)
# block_* are None for languages stamped with line comments.
STYLES: dict[str, tuple[str, str | None, str | None]] = {
    ".py": ("#", None, None),
    ".ts": ("//", None, None),
    ".tsx": ("//", None, None),
    ".js": ("//", None, None),
    ".jsx": ("//", None, None),
    ".mjs": ("//", None, None),
    ".cjs": ("//", None, None),
    ".css": (" *", "/*", " */"),
    ".scss": ("//", None, None),
    ".html": ("    ", "<!--", "-->"),
    ".yml": ("#", None, None),
    ".yaml": ("#", None, None),
    ".sh": ("#", None, None),
    ".sql": ("--", None, None),
}

MAX_BYTES = 512 * 1024
SKIP_NAME_PARTS = (".min.", "-lock.", ".lock", ".d.ts")

# --------------------------------------------------------------------------
# layer 3: zero-width signature
# --------------------------------------------------------------------------
ZW_ZERO = "​"   # zero width space      -> bit 0
ZW_ONE = "‌"    # zero width non-joiner -> bit 1
ZW_FENCE = "⁠"  # word joiner           -> delimiter


def zw_encode(text: str) -> str:
    """Encode text as invisible characters. Renders as nothing, greps as bytes."""
    bits = "".join(f"{byte:08b}" for byte in text.encode("utf-8"))
    body = "".join(ZW_ONE if bit == "1" else ZW_ZERO for bit in bits)
    return ZW_FENCE + body + ZW_FENCE


def zw_decode(blob: str) -> str:
    """Recover text from the first zero-width run found in blob."""
    if blob.count(ZW_FENCE) < 2:
        raise ValueError("no zero-width signature found")
    start = blob.index(ZW_FENCE) + 1
    end = blob.index(ZW_FENCE, start)
    bits = "".join("1" if ch == ZW_ONE else "0" for ch in blob[start:end]
                   if ch in (ZW_ONE, ZW_ZERO))
    if len(bits) % 8:
        raise ValueError("truncated zero-width signature")
    data = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
    return data.decode("utf-8")


SIGNATURE_PLAINTEXT = f"{AUTHOR_NAME} <{AUTHOR_EMAIL}> {AUTHOR_GITHUB}"

# --------------------------------------------------------------------------
# layers 1 + 2: file marks
# --------------------------------------------------------------------------


def file_token(rel: str) -> str:
    """Per-file id, so no single find/replace of one literal clears the repo."""
    seed = f"{rel}|{AUTHOR_NAME}|{AUTHOR_EMAIL}".encode()
    return hashlib.sha256(seed).hexdigest()[:12].upper()


def header_lines(rel: str) -> list[str]:
    token = file_token(rel)
    return [
        "-" * 74,
        f"{PROJECT} - proprietary source. Do not remove this notice.",
        f"Author: {AUTHOR_NAME} <{AUTHOR_EMAIL}> ({AUTHOR_GITHUB})",
        f"Copyright (c) {COPYRIGHT_YEAR} {AUTHOR_NAME}. All rights reserved.",
        f"{MARK}-{token}",
        zw_encode(SIGNATURE_PLAINTEXT),
        "-" * 74,
    ]


def footer_lines(rel: str) -> list[str]:
    token = file_token(rel)
    return [
        f"Originally authored by {AUTHOR_NAME} ({AUTHOR_EMAIL}).",
        f"Provenance token {token} - verify with scripts/authorship.py verify",
    ]


def render(lines: list[str], ext: str, indent: str = "") -> str:
    prefix, open_tag, close_tag = STYLES[ext]
    if open_tag:
        body = "\n".join(f"{indent}{prefix} {ln}".rstrip() for ln in lines)
        return f"{indent}{open_tag}\n{body}\n{indent}{close_tag}\n"
    return "".join(f"{indent}{prefix} {ln}".rstrip() + "\n" for ln in lines)


def insert_at(text: str, ext: str) -> int:
    """Byte-safe insertion point: after shebang / encoding line / doctype.

    Comments are legal before a Python docstring and before a JS directive
    prologue ("use client"), so only shebangs and the HTML doctype constrain
    us. Inserting before <!DOCTYPE> would trigger quirks mode.
    """
    lines = text.splitlines(keepends=True)
    idx = 0
    if ext == ".html":
        for i, ln in enumerate(lines[:5]):
            if ln.lstrip().lower().startswith("<!doctype"):
                return sum(len(x) for x in lines[:i + 1])
        return 0
    if lines and lines[0].startswith("#!"):
        idx = 1
        # PEP 263 encoding declaration must stay within the first two lines.
        if len(lines) > 1 and "coding" in lines[1] and lines[1].lstrip().startswith("#"):
            idx = 2
    elif lines and "coding" in lines[0] and lines[0].lstrip().startswith("#"):
        idx = 1
    return sum(len(x) for x in lines[:idx])


def footer_anchor(text: str, ext: str) -> int:
    """Where the footer goes: end of file, or before </html>."""
    if ext == ".html":
        low = text.lower()
        pos = low.rfind("</html>")
        if pos != -1:
            return pos
    return len(text)


@dataclass
class StampResult:
    stamped: int = 0
    already: int = 0
    skipped: int = 0
    failed: list[str] = None

    def __post_init__(self) -> None:
        if self.failed is None:
            self.failed = []


def iter_sources(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix not in STYLES:
                continue
            if any(part in name for part in SKIP_NAME_PARTS):
                continue
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path


def read_raw(path: Path) -> str:
    """Read without newline translation, so CRLF files stay CRLF on write.

    104 of this repo's source files are CRLF. Round-tripping them through
    universal newlines would rewrite every line of every one of them.
    """
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_raw(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def detect_eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def relpath(path: Path, root: Path = REPO) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:  # outside the repo (selfcheck temp dirs)
        return path.name


def stamp_file(path: Path, dry: bool = False) -> str:
    """Return 'stamped' | 'already' | 'skipped'."""
    ext = path.suffix
    rel = relpath(path)
    try:
        text = read_raw(path)
    except (UnicodeDecodeError, OSError):
        return "skipped"
    if MARK in text:
        return "already"

    eol = detect_eol(text)
    indent = "  " if ext == ".html" else ""
    head = render(header_lines(rel), ext, indent).replace("\n", eol)
    foot = render(footer_lines(rel), ext, indent).replace("\n", eol)

    cut = insert_at(text, ext)
    out = text[:cut] + head + text[cut:]
    anchor = footer_anchor(out, ext)
    sep = "" if out[:anchor].endswith("\n") or not out[:anchor] else eol
    out = out[:anchor] + sep + foot + out[anchor:]

    if not dry:
        write_raw(path, out)
    return "stamped"


def unstamp_file(path: Path, dry: bool = False) -> str:
    """Byte-exact inverse of stamp_file. Blocks are deterministic per path, so
    we regenerate them and remove them literally - no regex guessing.

    One documented exception: a source file that had no trailing newline comes
    back with one, because stamping had to add a separator before the footer.
    """
    ext = path.suffix
    rel = relpath(path)
    try:
        text = read_raw(path)
    except (UnicodeDecodeError, OSError):
        return "skipped"
    if MARK not in text:
        return "already"

    eol = detect_eol(text)
    indent = "  " if ext == ".html" else ""
    head = render(header_lines(rel), ext, indent).replace("\n", eol)
    foot = render(footer_lines(rel), ext, indent).replace("\n", eol)
    out = text
    for block in (head, foot):
        if block in out:
            out = out.replace(block, "", 1)
    if MARK in out or foot in out:
        return "failed"
    if not dry:
        write_raw(path, out)
    return "unstamped"


def cmd_unstamp(args) -> int:
    counts = {"unstamped": 0, "already": 0, "skipped": 0, "failed": 0}
    failed = []
    for path in iter_sources(REPO):
        outcome = unstamp_file(path, dry=args.dry_run)
        counts[outcome] += 1
        if outcome == "failed":
            failed.append(relpath(path))
    print(f"removed marks from {counts['unstamped']} files "
          f"({counts['already']} had none, {counts['failed']} partial)")
    for rel in failed[:15]:
        print(f"  partial, edit by hand: {rel}", file=sys.stderr)
    if args.dry_run:
        print("(dry run - nothing written)")
    return 1 if counts["failed"] else 0


def cmd_stamp(args) -> int:
    res = StampResult()
    for path in iter_sources(REPO):
        try:
            outcome = stamp_file(path, dry=args.dry_run)
        except Exception as exc:  # keep going; report at the end
            res.failed.append(f"{path}: {exc}")
            continue
        setattr(res, outcome, getattr(res, outcome) + 1)

    dunders = stamp_dunders(dry=args.dry_run)
    meta = stamp_metadata(dry=args.dry_run)

    print(f"headers+footers: {res.stamped} stamped, {res.already} already marked, "
          f"{res.skipped} unreadable")
    print(f"__author__ dunders: {dunders} __init__.py files")
    print(f"metadata: {', '.join(meta) if meta else 'nothing to change'}")
    for line in res.failed:
        print(f"  FAILED {line}", file=sys.stderr)
    if args.dry_run:
        print("(dry run - nothing written)")
    return 1 if res.failed else 0


# --------------------------------------------------------------------------
# layer 4: python dunders
# --------------------------------------------------------------------------
DUNDER_BLOCK = (
    f'__author__ = "{AUTHOR_NAME}"\n'
    f'__email__ = "{AUTHOR_EMAIL}"\n'
    f'__copyright__ = "Copyright (c) {COPYRIGHT_YEAR} {AUTHOR_NAME}"\n'
)


def stamp_dunders(dry: bool = False) -> int:
    count = 0
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "__init__.py" not in filenames:
            continue
        path = Path(dirpath) / "__init__.py"
        try:
            text = read_raw(path)
        except (UnicodeDecodeError, OSError):
            continue
        if "__author__" in text:
            continue
        eol = detect_eol(text)
        sep = "" if text.endswith("\n") or not text else eol
        if not dry:
            write_raw(path, text + sep + eol + DUNDER_BLOCK.replace("\n", eol))
        count += 1
    return count


# --------------------------------------------------------------------------
# layer 5: package metadata
# --------------------------------------------------------------------------
LICENSE_TEXT = f"""Copyright (c) {COPYRIGHT_YEAR} {AUTHOR_NAME} <{AUTHOR_EMAIL}>

All rights reserved.

{PROJECT} and all source files in this repository were written by
{AUTHOR_NAME} ({AUTHOR_GITHUB}). No permission is granted to copy, modify,
distribute or use this software, in whole or in part, without the prior
written consent of the copyright holder.

Authorship of this work is recorded in three independent places:

  * per-file notices carrying the token {MARK}
  * the git commit history, authored as {AUTHOR_NAME} <{AUTHOR_EMAIL}>
  * AUTHORSHIP.json, an Ed25519-signed manifest of every file's sha256,
    verifiable against the committed public key AUTHORSHIP.pub

Removing the notices from the source files invalidates the manifest
signature and is itself evidence of tampering.
"""


def stamp_metadata(dry: bool = False) -> list[str]:
    changed: list[str] = []

    lic = REPO / "LICENSE"
    if not lic.exists():
        if not dry:
            lic.write_text(LICENSE_TEXT, encoding="utf-8")
        changed.append("LICENSE")

    mailmap = REPO / ".mailmap"
    entry = f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>\n"
    if not mailmap.exists() or AUTHOR_EMAIL not in mailmap.read_text(encoding="utf-8"):
        if not dry:
            with mailmap.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        changed.append(".mailmap")

    for pkg in REPO.rglob("package.json"):
        if any(part in SKIP_DIRS for part in pkg.parts):
            continue
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("author") == f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>":
            continue
        data["author"] = f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>"
        data.setdefault("contributors", [f"{AUTHOR_NAME} <{AUTHOR_EMAIL}>"])
        if not dry:
            pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        changed.append(pkg.relative_to(REPO).as_posix())

    return changed


# --------------------------------------------------------------------------
# layer 6: signed manifest
# --------------------------------------------------------------------------
def _crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return serialization, ed25519


def load_or_create_key():
    serialization, ed25519 = _crypto()
    if PRIVKEY.exists():
        key = serialization.load_pem_private_key(PRIVKEY.read_bytes(), password=None)
        return key, False
    KEYDIR.mkdir(parents=True, exist_ok=True)
    key = ed25519.Ed25519PrivateKey.generate()
    PRIVKEY.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        os.chmod(PRIVKEY, 0o600)
    except OSError:
        pass
    return key, True


def public_pem(key) -> bytes:
    serialization, _ = _crypto()
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_manifest() -> dict:
    files = {}
    for path in iter_sources(REPO):
        rel = path.relative_to(REPO).as_posix()
        text_ok = True
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            text, text_ok = "", False
        files[rel] = {
            "sha256": sha256_file(path),
            "marked": MARK in text if text_ok else None,
            "token": file_token(rel),
        }
    payload = {
        "project": PROJECT,
        "author": {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL,
                   "github": AUTHOR_GITHUB},
        "copyright": f"Copyright (c) {COPYRIGHT_YEAR} {AUTHOR_NAME}",
        "signature_plaintext": SIGNATURE_PLAINTEXT,
        "signed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_head": git_head(),
        "file_count": len(files),
        "files": files,
    }
    return payload


def canonical(payload: dict) -> bytes:
    """Byte-stable serialisation - signatures must not depend on dict order."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def cmd_sign(args) -> int:
    key, created = load_or_create_key()
    if created:
        print(f"generated new signing key at {PRIVKEY}")
        print("  BACK THIS FILE UP. Lose it and you cannot re-sign as the "
              "same identity.")
    payload = build_manifest()
    sig = key.sign(canonical(payload))
    doc = {"payload": payload, "signature_hex": sig.hex(),
           "algorithm": "Ed25519", "public_key_pem": public_pem(key).decode()}
    MANIFEST.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    PUBKEY.write_bytes(public_pem(key))
    marked = sum(1 for v in payload["files"].values() if v["marked"])
    print(f"signed {payload['file_count']} files "
          f"({marked} carrying the {MARK} token)")
    print(f"  manifest: {MANIFEST.relative_to(REPO)}")
    print(f"  public key: {PUBKEY.relative_to(REPO)}")
    print(f"  git HEAD: {payload['git_head']}")
    return 0


def cmd_verify(args) -> int:
    serialization, _ = _crypto()
    if not MANIFEST.exists():
        print("no AUTHORSHIP.json - run `sign` first", file=sys.stderr)
        return 2
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload = doc["payload"]

    pub_src = PUBKEY.read_bytes() if PUBKEY.exists() else doc["public_key_pem"].encode()
    pub = serialization.load_pem_public_key(pub_src)
    try:
        pub.verify(bytes.fromhex(doc["signature_hex"]), canonical(payload))
    except Exception:
        print("SIGNATURE INVALID - manifest was altered after signing",
              file=sys.stderr)
        return 1
    print(f"signature OK - signed {payload['signed_at']} by "
          f"{payload['author']['name']} <{payload['author']['email']}>")

    missing, changed, unmarked = [], [], []
    for rel, rec in sorted(payload["files"].items()):
        path = REPO / rel
        if not path.exists():
            missing.append(rel)
            continue
        if sha256_file(path) != rec["sha256"]:
            changed.append(rel)
        try:
            if rec["marked"] and MARK not in path.read_text(encoding="utf-8"):
                unmarked.append(rel)
        except (UnicodeDecodeError, OSError):
            pass

    for label, items in (("deleted", missing), ("modified", changed),
                         ("MARK STRIPPED", unmarked)):
        if items:
            print(f"{label}: {len(items)}")
            for rel in items[:args.list_limit]:
                print(f"  {rel}")
            if len(items) > args.list_limit:
                print(f"  ... and {len(items) - args.list_limit} more")
    if not (missing or changed or unmarked):
        print(f"all {payload['file_count']} files match the signed manifest")
    return 1 if unmarked else 0


def cmd_audit(args) -> int:
    total = marked = 0
    unmarked = []
    for path in iter_sources(REPO):
        total += 1
        try:
            if MARK in path.read_text(encoding="utf-8"):
                marked += 1
            else:
                unmarked.append(path.relative_to(REPO).as_posix())
        except (UnicodeDecodeError, OSError):
            pass
    print(f"{marked}/{total} source files carry {MARK}")
    for rel in unmarked[:args.list_limit]:
        print(f"  unmarked: {rel}")
    if len(unmarked) > args.list_limit:
        print(f"  ... and {len(unmarked) - args.list_limit} more")
    inits = sum(1 for p in REPO.rglob("__init__.py")
                if not any(x in SKIP_DIRS for x in p.parts)
                and "__author__" in p.read_text(encoding="utf-8", errors="ignore"))
    print(f"{inits} __init__.py files carry __author__")
    return 0


# --------------------------------------------------------------------------
# selfcheck - the one runnable check for the non-trivial logic above
# --------------------------------------------------------------------------
def cmd_selfcheck(args) -> int:
    import tempfile

    # zero-width round trip, including non-ascii
    for probe in (SIGNATURE_PLAINTEXT, "Aaryan Baadkar", "unicode: é中"):
        assert zw_decode(zw_encode(probe)) == probe, probe
    # encoded form must be visually empty
    assert zw_encode("x").strip(ZW_FENCE + ZW_ZERO + ZW_ONE) == ""

    # per-file tokens differ per path, stable across runs
    assert file_token("a/b.py") != file_token("a/c.py")
    assert file_token("a/b.py") == file_token("a/b.py")

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        # shebang must stay on line 1
        py = d / "s.py"
        py.write_text('#!/usr/bin/env python3\n"""Doc."""\nX = 1\n', encoding="utf-8")
        cut = insert_at(py.read_text(encoding="utf-8"), ".py")
        out = py.read_text(encoding="utf-8")[:cut] + render(header_lines("s.py"), ".py")
        assert out.startswith("#!/usr/bin/env python3\n"), "shebang displaced"

        # PEP 263 encoding line must stay within first two lines
        enc = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nX = 1\n"
        assert insert_at(enc, ".py") == len(enc.splitlines(keepends=True)[0]) + \
            len(enc.splitlines(keepends=True)[1])

        # doctype must stay first in HTML
        html = "<!DOCTYPE html>\n<html>\n<body>hi</body>\n</html>\n"
        cut = insert_at(html, ".html")
        assert html[:cut].lower().startswith("<!doctype"), "doctype displaced"
        assert footer_anchor(html, ".html") == html.lower().rfind("</html>")

        # stamped python stays syntactically valid, and is idempotent
        real = d / "m.py"
        real.write_text('#!/usr/bin/env python3\n"""Doc."""\nVALUE = 41 + 1\n',
                        encoding="utf-8")
        globals_ns: dict = {}
        assert stamp_file(real) == "stamped"
        body = real.read_text(encoding="utf-8")
        compile(body, "m.py", "exec")
        exec(compile(body, "m.py", "exec"), globals_ns)
        assert globals_ns["VALUE"] == 42, "stamping changed behaviour"
        assert globals_ns["__doc__"] == "Doc.", "module docstring lost"
        assert MARK in body and zw_decode(body) == SIGNATURE_PLAINTEXT
        assert body.count(MARK) == 1 and "Originally authored by" in body
        assert stamp_file(real) == "already"
        assert real.read_text(encoding="utf-8") == body, "second pass rewrote file"

        # stamp -> unstamp must return the original bytes exactly
        for name, original in (
            ("r.py", '#!/usr/bin/env python3\n"""Doc."""\nX = 1\n'),
            ("r.tsx", '"use client";\nexport const A = 1;\n'),
            ("r.css", "body { color: red; }\n"),
            ("r.html", "<!DOCTYPE html>\n<html>\n<body>hi</body>\n</html>\n"),
        ):
            f = d / name
            f.write_text(original, encoding="utf-8", newline="")
            assert stamp_file(f) == "stamped", name
            assert MARK in f.read_text(encoding="utf-8"), name
            assert unstamp_file(f) == "unstamped", name
            assert f.read_text(encoding="utf-8") == original, f"round trip: {name}"

        # documented exception: a file with no trailing newline gains one
        f = d / "r_noeol.py"
        write_raw(f, "X = 1")
        stamp_file(f)
        unstamp_file(f)
        assert read_raw(f) == "X = 1\n"

        # CRLF files must stay pure CRLF - no LF smuggled in by the blocks
        f = d / "crlf.py"
        crlf_src = '#!/usr/bin/env python3\r\n"""Doc."""\r\nX = 1\r\n'
        write_raw(f, crlf_src)
        stamp_file(f)
        raw = f.read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n"), "lone LF in a CRLF file"
        compile(read_raw(f), "crlf.py", "exec")
        assert unstamp_file(f) == "unstamped"
        assert read_raw(f) == crlf_src, "CRLF round trip"

        # "use client" directive keeps working: comments precede the prologue
        tsx = d / "c.tsx"
        tsx.write_text('"use client";\nexport const A = 1;\n', encoding="utf-8")
        stamp_file(tsx)
        assert '"use client";' in tsx.read_text(encoding="utf-8")

        # signature binds the payload: flipping one byte must fail verification
        _, ed25519 = _crypto()
        k = ed25519.Ed25519PrivateKey.generate()
        p = {"a": 1, "b": [2, 3]}
        s = k.sign(canonical(p))
        k.public_key().verify(s, canonical(p))
        try:
            k.public_key().verify(s, canonical({"a": 2, "b": [2, 3]}))
        except Exception:
            pass
        else:
            raise AssertionError("tampered payload verified")
        # canonical form is order independent
        assert canonical({"a": 1, "b": 2}) == canonical({"b": 2, "a": 1})

    print("selfcheck OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stamp", help="apply layers 1-5")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_stamp)

    p = sub.add_parser("unstamp", help="exact reverse of stamp (layers 1-2)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_unstamp)

    p = sub.add_parser("sign", help="write + sign AUTHORSHIP.json")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("verify", help="check signature and hashes")
    p.add_argument("--list-limit", type=int, default=15)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("audit", help="report mark coverage")
    p.add_argument("--list-limit", type=int, default=15)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("selfcheck", help="assertions only, writes nothing")
    p.set_defaults(func=cmd_selfcheck)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# ---------------------------------------------------------------------------
