#!/usr/bin/env python3
"""Grant-scope guard for mana lanes.

Proves that only paths/keys explicitly granted by --allow-path/--allow-key pass,
and that out-of-scope paths fail non-zero.

Modes:
  --self-test                      deterministic built-in assertions
  --paths a,b,c                    predict-only path check (no git)
  --base <ref> [--allow-path ...]  review mode: git diff --name-only <ref>...HEAD

Scope semantics:
  * An --allow-path ending in "/" grants the whole subtree; otherwise it is an
    exact file path (or a shell-style glob when it contains * ? [).
  * Paths are normalized ("./" dropped, duplicate "/" collapsed) before compare.
  * Absolute paths, and anything that still escapes upward ("..", "../x"),
    can never be granted.
  * With no --allow-path, every path is denied (default deny).

--allow-key <prefix> (repeatable) is optional and only active in review mode.
A key is granted when it starts with any prefix. Prefixes are dotted, e.g.
"ui.m.txt.".

Limitation: the --allow-key check scans the *new* version of each changed
.toml file line by line. It does not diff-align keys, so a key that already
existed on the base branch is still reported. That is deliberate: no unified
diff parser here.
"""

import argparse
import fnmatch
import posixpath
import re
import subprocess
import sys

KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*=")

PATH_CASES = [
    ("exact file granted", "Cargo.toml", ["Cargo.toml"], True),
    ("subtree grants descendant", "src/musikalisches/foo.rs", ["src/musikalisches/"], True),
    ("subtree grants directory itself", "src/musikalisches", ["src/musikalisches/"], True),
    ("ungranted file denied", "res/secret.txt", ["Cargo.toml"], False),
    ("default deny with no grants", "Cargo.toml", [], False),
    ("normalization of ./ and //", "./ops//scripts/x.py", ["ops/scripts/x.py"], True),
    ("upward escape denied", "src/../../etc/passwd", ["src/"], False),
    ("dot-dot cannot be laundered", "../Cargo.toml", ["Cargo.toml"], False),
    ("absolute path denied", "/etc/passwd", ["/etc/passwd"], False),
    ("sibling prefix is not a subtree", "src/foo-bar", ["src/foo/"], False),
    ("glob matches", "ops/config/products.m.01.toml", ["ops/config/products.m.*.toml"], True),
    ("glob mismatch denied", "ops/config/other.toml", ["ops/config/products.m.*.toml"], False),
    ("inner escape re-checked", "src/foo/../../secret.txt", ["src/"], False),
]


def normalize(path):
    """Canonicalize a repo-relative path for comparison."""
    p = path.strip().replace("\\", "/")
    if not p:
        return ""
    return posixpath.normpath(p)


def is_ungrantable(norm):
    """Normalized absolute or upward-escaping paths can never be granted."""
    return norm.startswith("/") or norm == ".." or norm.startswith("../")


def _has_glob(pattern):
    return any(ch in pattern for ch in "*?[")


def path_allowed(path, allow_paths):
    norm = normalize(path)
    if not norm or not allow_paths:
        return False
    if is_ungrantable(norm):
        return False
    for raw in allow_paths:
        subtree = raw.endswith("/")
        pat = normalize(raw)
        if not pat or is_ungrantable(pat):
            continue
        if _has_glob(pat):
            if fnmatch.fnmatchcase(norm, pat):
                return True
            if subtree and fnmatch.fnmatchcase(norm, pat + "/*"):
                return True
            continue
        if subtree:
            if norm == pat or norm.startswith(pat + "/"):
                return True
        elif norm == pat:
            return True
    return False


def scan_toml_keys(text):
    """Return dotted keys of the new-version text, table-aware, best effort."""
    keys = []
    table = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            end = line.find("]")
            if end != -1:
                table = line[1:end].strip().strip("[]").strip()
            continue
        m = KEY_RE.match(line)
        if m:
            keys.append(f"{table}.{m.group(1)}" if table else m.group(1))
    return keys


def key_allowed(key, allow_keys):
    return any(key.startswith(prefix) for prefix in allow_keys)


def git_changed_files(base):
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"error: git diff failed: {proc.stderr.strip()}", file=sys.stderr)
        return None
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_show_head(path):
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path}"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def run_self_test():
    failures = 0

    def check(desc, actual, expected):
        nonlocal failures
        ok = actual == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {desc}")
        if not ok:
            print(f"       expected={expected!r} actual={actual!r}")
            failures += 1

    for desc, path, allows, expected in PATH_CASES:
        check(desc, path_allowed(path, allows), expected)

    check("toml table key", scan_toml_keys("[ui.m.txt]\nk = 1\n"), ["ui.m.txt.k"])
    check("toml top-level key", scan_toml_keys("a = 1\n"), ["a"])
    check(
        "toml comments/blank ignored",
        scan_toml_keys("# c\n\n[b]\n# x\nk = 2\n"),
        ["b.k"],
    )
    check("key prefix granted", key_allowed("ui.m.txt.k", ["ui.m.txt."]), True)
    check("key outside prefix denied", key_allowed("ui.m.other", ["ui.m.txt."]), False)
    check("empty prefix list denies", key_allowed("anything", []), False)

    print(f"self-test: {failures} failure(s)")
    return 1 if failures else 0


def run_paths_mode(args):
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    rejected = []
    for p in paths:
        ok = path_allowed(p, args.allow_path)
        print(f"{'ALLOW' if ok else 'DENY '} {p}")
        if not ok:
            rejected.append(p)
    if rejected:
        print("rejected paths:")
        for p in rejected:
            print(f"  {p}")
        return 1
    print(f"ok: {len(paths)} path(s) within grant")
    return 0


def run_review_mode(args):
    changed = git_changed_files(args.base)
    if changed is None:
        return 1

    rejected = []
    for p in changed:
        ok = path_allowed(p, args.allow_path)
        print(f"{'ALLOW' if ok else 'DENY '} {p}")
        if not ok:
            rejected.append(p)

    bad_keys = []
    if args.allow_key:
        for p in changed:
            if not p.endswith(".toml"):
                continue
            text = git_show_head(p)
            if text is None:
                continue
            for k in scan_toml_keys(text):
                if not key_allowed(k, args.allow_key):
                    bad_keys.append((p, k))

    if rejected:
        print("rejected files:")
        for p in rejected:
            print(f"  {p}")
    if bad_keys:
        print("rejected keys:")
        for p, k in bad_keys:
            print(f"  {k}  ({p})")
    if rejected or bad_keys:
        return 1
    print(f"ok: {len(changed)} file(s) within grant")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="mana grant-scope guard")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--paths")
    ap.add_argument("--base")
    ap.add_argument("--allow-path", action="append", default=[])
    ap.add_argument("--allow-key", action="append", default=[])
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()
    if args.paths is not None:
        return run_paths_mode(args)
    if args.base:
        return run_review_mode(args)
    ap.error("choose one of --self-test, --paths, --base")
    return 2


if __name__ == "__main__":
    sys.exit(main())
