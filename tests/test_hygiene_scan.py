"""Guard the hygiene scanner — every rule catches its case, and only its case.

Three things are proved here, because a scanner can fail in three ways and only
one of them is visible from its output:

  1. each rule catches the shape it is for (VECTORS);
  2. each rule is the one doing the catching — disabling it makes its own vector
     pass, so a rule cannot be quietly redundant or dead (the mutation half);
  3. the two scanners in this repository do not overlap — no line is reported by
     both `hygiene_scan` and `secret_scan`, in either direction.

Plus the properties that are about the tree rather than the text: a clean tree
passes, a symlink that leaves the repository fails, and a file that cannot be
decoded is a FAILURE rather than a skip.

The trees are built in a temporary directory and removed again: no fixtures on
disk, no network.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from test_secret_scan import SHOULD_FLAG as SECRET_SCAN_LINES
from test_secret_scan import secret_scan

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "hygiene_scan", _ROOT / "scripts" / "hygiene_scan.py"
)
assert _spec and _spec.loader
hygiene_scan = importlib.util.module_from_spec(_spec)
# Registered before execution: the module defines dataclasses, and resolving
# their annotations looks the defining module up by name in sys.modules.
sys.modules[_spec.name] = hygiene_scan
_spec.loader.exec_module(hygiene_scan)

RULES = hygiene_scan.RULES
scan = hygiene_scan.scan
scan_text = hygiene_scan.scan_text

# rule name -> lines that rule must catch.
VECTORS: dict[str, list[str]] = {
    "machine-path": [
        "cwd = /Users/someone/project",
        'workdir: "/home/builder/app"',
        "socket at /private/tmp/session-4/ipc",
        "cache /var/folders/9k/abcd1234/T/build",
        r"path = C:\Users\someone\src",
        "see file:///Users/someone/project/notes.md",
        "launch: file:///home/builder/app/index.html",
    ],
    "transcript-url": [
        "see https://claude.ai/code/session_01ABCDEFxyz for the discussion",
        "notes: claude.ai/code/session/0123456789",
    ],
    "attribution-trailer": [
        "Co-Authored-By: Someone <someone@example.com>",
        "  co-authored-by: Someone Else <else@example.com>",
        "Generated with [Some Tool](https://example.com)",
        "\U0001f916 Generated with a tool",
    ],
}

# Lines that must NOT be reported: ordinary content that resembles a rule.
CLEAN = [
    "the integration stores state under /data and reads /config",
    "docs live under /Users and are not paths",  # no path into it
    "run: python scripts/smoke.py --host 192.0.2.10",
    "See https://www.home-assistant.io/integrations/ for the list",
    "co-authored the specification with the working group",  # not a trailer line
    "The diagram is generated with the build script",  # not at line start
    "/home/ is not a path either",
    "mkdir -p /data/home/.storage",  # a home inside a data dir
    "cache lives in /srv/Users/shared/x",  # not a per-machine path
    'mkdir -p "${work}/home/state"',  # built from a variable
    'cd "$(mktemp -d)/Users/test/app"',  # likewise
]

ALL_VECTORS = [(name, line) for name, lines in VECTORS.items() for line in lines]


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _make_tree(root: Path, files: dict[str, bytes]) -> None:
    """A git repository containing exactly these files, all tracked."""
    _run_git(root, "init", "-q")
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    _run_git(root, "add", "-A")


def test_every_rule_has_a_vector() -> None:
    assert {rule.name for rule in RULES} == set(VECTORS)


@pytest.mark.parametrize(("name", "line"), ALL_VECTORS)
def test_rule_catches_its_vector(name: str, line: str) -> None:
    assert name in [hit for hit, _ in scan_text(line)]


@pytest.mark.parametrize("line", CLEAN)
def test_ordinary_content_is_not_reported(line: str) -> None:
    assert scan_text(line) == []


@pytest.mark.parametrize(("name", "line"), ALL_VECTORS)
def test_removing_a_rule_makes_its_vector_pass(name: str, line: str) -> None:
    """Disable one rule at a time: its own vectors must then go unreported.

    This is what keeps a rule from being decorative. A vector still caught with
    its rule removed was being caught by something else, and the rule could be
    deleted without any test noticing.
    """
    weakened = [rule for rule in RULES if rule.name != name]
    assert scan_text(line, weakened) == []


@pytest.mark.parametrize(("name", "line"), ALL_VECTORS)
def test_secret_scan_does_not_report_a_hygiene_line(name: str, line: str) -> None:
    assert secret_scan.scan_text(line) == []


@pytest.mark.parametrize("line", SECRET_SCAN_LINES)
def test_hygiene_does_not_report_a_secret_scan_line(line: str) -> None:
    assert scan_text(line) == []


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        {
            "README.md": b"# Fine\n\nPaths here are relative: ./src/app.py\n",
            "src/app.py": b"BASE = './data'\n",
            "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
        },
    )
    (tmp_path / "docs_link").symlink_to("src/app.py")
    _run_git(tmp_path, "add", "-A")
    assert scan(tmp_path) == []


def test_symlinks_leaving_the_repository_are_reported(tmp_path: Path) -> None:
    _make_tree(tmp_path, {"keep.txt": b"content\n", "sub/keep.txt": b"content\n"})
    (tmp_path / "absolute_link").symlink_to("/etc/hosts")
    (tmp_path / "sub" / "escaping_link").symlink_to("../../elsewhere")
    (tmp_path / "sub" / "inside_link").symlink_to("keep.txt")
    _run_git(tmp_path, "add", "-A")

    reported = {finding.path: finding.rule for finding in scan(tmp_path)}
    assert reported.get("absolute_link") == "symlink-absolute"
    assert reported.get("sub/escaping_link") == "symlink-outside-repo"
    assert "sub/inside_link" not in reported
    # The mutation half for a check that is not a regex: with the symlink rule
    # off, those same files must go unreported.
    assert [f for f in scan(tmp_path, symlinks=False) if "link" in f.path] == []


def test_an_undecodable_file_is_a_failure_not_a_skip(tmp_path: Path) -> None:
    # Text in a single-byte encoding: no NUL, so it is not taken for a binary,
    # and it is not valid UTF-8 either.
    _make_tree(tmp_path, {"notes.txt": "héllo wörld".encode("latin-1")})
    assert any(finding.rule == "unreadable" for finding in scan(tmp_path))


def test_a_missing_tracked_file_is_a_failure(tmp_path: Path) -> None:
    _make_tree(tmp_path, {"gone.txt": b"content\n"})
    (tmp_path / "gone.txt").unlink()  # tracked, but not there to read
    assert any(finding.rule == "unreadable" for finding in scan(tmp_path))


def test_the_scanner_skips_itself_by_path_not_by_name(tmp_path: Path) -> None:
    _make_tree(tmp_path, {"tools/hygiene_scan.py": b"p = '/Users/someone/x'\n"})
    assert scan(tmp_path), "a file merely NAMED hygiene_scan.py was skipped"
