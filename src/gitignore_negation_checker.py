#!/usr/bin/env python3
"""Check negated patterns in .gitignore files actually work.

Run: python3 src/gitignore_negation_checker.py .gitignore
     python3 src/gitignore_negation_checker.py project/
     python3 src/gitignore_negation_checker.py --stdin < .gitignore

A "!keep.txt" written before "*.txt", or under an
ignored folder, silently does nothing — the file
stays ignored and the author believes it is
tracked, and the missing file shows up at deploy
time. This tool reads each .gitignore file and
reports each broken negation, with the file and
the line number. It exits 1 when any negation is
broken, so it can fail a CI run. A file whose
negations all work exits 0.

A negation is broken in two ways, and both are
checked:

1. Order: the negation comes before any pattern
   that ignores the path it re-includes. Git
   applies patterns in order, last match wins, so
   a "!keep.txt" written above "*.txt" has nothing
   to re-include yet and never takes effect.
2. Parent directory: the re-included path sits
   inside a directory that is itself ignored, and
   no earlier negation re-includes that directory.
   Git cannot re-include a file inside an ignored
   directory, so "!build/keep.txt" under "build/"
   never takes effect. Ignoring "build/*" instead
   of "build/" leaves the directory itself alone,
   and re-including the directory first with
   "!build/" also works — both pass this check.

A file given directly on the command line is
always checked, whatever its name. A folder is
walked for files named exactly ".gitignore",
recursively by default (--no-recursive stops at
the top level). .git folders are never walked,
and directory links are never followed.

Blank lines and comments are skipped. A line
starting with "\\#" or "\\!" is a literal pattern,
not a comment or a negation, as git defines it.
Patterns are matched with git's own rules: "*"
and "?" never cross a slash, "**" does, a
pattern with no slash matches a name at any
depth, a pattern with a slash is anchored to the
folder the .gitignore file sits in, and a
trailing slash marks a directory-only pattern.
Each .gitignore file is checked on its own, so a
pattern is always read relative to the folder its
file sits in.

It never rewrites a file, never touches the
network, and reads only the files and folders
you point it at. It checks .gitignore files
only — not .git/info/exclude or a global
gitignore — and it does not check whether a
negation's target is a wildcard that merely
overlaps an earlier pattern; it compares the
patterns as written.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

GITIGNORE_NAME = ".gitignore"


def _pattern_to_regex(pattern):
    """Translate one gitignore pattern to a regex string.

    Returns (regex, anchored, dir_only). The regex is
    matched against a whole path or a whole name, never
    a substring. "*" and "?" never cross a slash, "**"
    does: a leading "**/" matches zero or more folders,
    a middle "/**/" matches zero or more folders, and a
    trailing "/**" matches everything inside.
    """
    dir_only = pattern.endswith("/")
    body = pattern.rstrip("/")
    anchored = body.startswith("/") or "/" in body
    body = body.lstrip("/")
    out = []
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        three = body[i:i + 3]
        if body.startswith("**/", i):
            out.append("(.*/)?")
            i += 3
        elif body.startswith("/**/", i):
            out.append("/(.*/)?")
            i += 4
        elif body.startswith("/**", i) and i + 3 == len(body):
            out.append("/.*")
            i += 3
        elif two == "**":
            out.append(".*")
            i += 2
        elif body[i] == "*":
            out.append("[^/]*")
            i += 1
        elif body[i] == "?":
            out.append("[^/]")
            i += 1
        elif body[i] == "[":
            close = body.find("]", i + 1)
            if close == -1:
                out.append(re.escape("["))
                i += 1
            else:
                inner = body[i + 1:close]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                inner = inner.replace("\\", "\\\\")
                out.append("[" + inner + "]")
                i = close + 1
        elif body[i] == "\\" and i + 1 < len(body):
            out.append(re.escape(body[i + 1]))
            i += 2
        else:
            out.append(re.escape(body[i]))
            i += 1
    return "".join(out), anchored, dir_only


def pattern_ignores(pattern, path, is_dir=False):
    """True when a gitignore pattern ignores a path.

    The path is relative to the folder the .gitignore
    file sits in, with no leading slash. A pattern
    also ignores a path when it ignores one of the
    path's parent folders, because everything inside
    an ignored folder is ignored too.
    """
    if not pattern:
        return False
    regex, anchored, dir_only = _pattern_to_regex(pattern)
    compiled = re.compile(regex)
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        candidate = "/".join(parts[:i])
        is_last = i == len(parts)
        if dir_only and is_last and not is_dir:
            continue
        if anchored:
            if compiled.fullmatch(candidate):
                return True
        elif compiled.fullmatch(parts[i - 1]):
            return True
    return False


def _parse_line(raw):
    """Split one raw line into (is_pattern, is_negation, pattern).

    Blank lines and comments are not patterns. A line
    starting with "\\#" or "\\!" is a literal pattern,
    not a comment or a negation. Trailing spaces are
    stripped, as git strips them.
    """
    line = raw.rstrip()
    if not line.strip():
        return False, False, None
    if line.startswith("#"):
        return False, False, None
    if line.startswith("\\#") or line.startswith("\\!"):
        return True, False, line[1:]
    if line.startswith("!"):
        return True, True, line[1:]
    return True, False, line


def _literal_ancestors(pattern):
    """Leading literal folder components of a pattern.

    "build/keep.txt" gives ["build"], "a/b/c.txt"
    gives ["a", "a/b"], "**/keep.txt" gives [] because
    no literal folder leads it, and "a/*/c.txt" gives
    ["a"]. Only literal folders can be checked for
    being ignored; a wildcard folder is not one folder.
    """
    parts = pattern.lstrip("/").rstrip("/").split("/")
    ancestors = []
    current = []
    for part in parts[:-1]:
        if any(char in part for char in "*?[\\"):
            break
        current.append(part)
        ancestors.append("/".join(current))
    return ancestors


def check_text(text):
    """Check one .gitignore document's text.

    Returns a list of findings, each {"line": int,
    "pattern": str, "reason": str}, in document order.
    """
    findings = []
    earlier = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        is_pattern, is_negation, pattern = _parse_line(raw)
        if not is_pattern:
            continue
        if is_negation:
            target = pattern
            target_path = target.lstrip("/").rstrip("/")
            target_is_dir = target.endswith("/")
            has_earlier = any(
                (not neg) and pattern_ignores(p, target_path,
                                              target_is_dir)
                for (_line, neg, p) in earlier
            )
            if not has_earlier:
                findings.append({
                    "line": lineno,
                    "pattern": "!" + pattern,
                    "reason": "has no earlier pattern to re-include",
                })
            for ancestor in _literal_ancestors(target):
                blocked = False
                for (_line, neg, p) in earlier:
                    if pattern_ignores(p, ancestor, True):
                        blocked = not neg
                if blocked:
                    findings.append({
                        "line": lineno,
                        "pattern": "!" + pattern,
                        "reason": ('parent directory "%s" is ignored, '
                                   "so git cannot re-include this path"
                                   % ancestor),
                    })
                    break
        earlier.append((lineno, is_negation, pattern))
    return findings


def check_file(path):
    """Check one file. Returns (findings, error)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], "not valid UTF-8"
    except OSError as exc:
        return [], str(exc)
    try:
        return check_text(text), None
    except Exception as exc:  # a pattern the matcher rejects
        return [], "could not be parsed: %s" % exc


def _is_gitignore_file(path):
    return Path(path).name == GITIGNORE_NAME


def collect_files(paths, recursive=True, exclude=None):
    """Expand CLI paths into a sorted list of .gitignore files.

    A file given directly is always checked, whatever its
    name. A folder is walked for files named exactly
    ".gitignore". .git folders are never walked, and
    directory links are never followed.
    """
    exclude = exclude or []
    found = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(str(path))
        elif path.is_dir():
            for dirpath, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [
                    d for d in dirs
                    if d != ".git"
                    and not any(fnmatch.fnmatch(d, pat) for pat in exclude)
                ]
                for name in files:
                    candidate = Path(dirpath) / name
                    if not _is_gitignore_file(candidate):
                        continue
                    if any(
                        fnmatch.fnmatch(str(candidate), pat)
                        or fnmatch.fnmatch(name, pat)
                        for pat in exclude
                    ):
                        continue
                    found.append(str(candidate))
                if not recursive:
                    break
        else:
            raise FileNotFoundError("no such file or folder: %s" % raw)
    seen = set()
    unique = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return sorted(unique)


def format_finding(path, finding):
    """One human-readable line for one broken negation."""
    return ("FAIL %s: \"%s\" line %d %s"
            % (path, finding["pattern"], finding["line"],
               finding["reason"]))


def run(paths, recursive=True, exclude=None, as_json=False):
    """Check paths, print the report, return the exit code."""
    try:
        files = collect_files(paths, recursive=recursive, exclude=exclude)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not files:
        print("error: no .gitignore files found", file=sys.stderr)
        return 2
    results = []
    findings = 0
    files_with_findings = 0
    for path in files:
        bad, error = check_file(path)
        count = len(bad) + (1 if error else 0)
        if count:
            findings += count
            files_with_findings += 1
        results.append({"path": path, "findings": bad, "error": error})
    if as_json:
        print(json.dumps(
            {"files": results, "checked": len(files),
             "findings": findings},
            indent=2))
    else:
        for result in results:
            if result["error"]:
                print("FAIL %s: %s" % (result["path"], result["error"]))
            for finding in result["findings"]:
                print(format_finding(result["path"], finding))
        if findings:
            print("Checked %d file(s), %d broken negation(s) "
                  "in %d file(s)." % (len(files), findings,
                                      files_with_findings))
        else:
            print("OK — %d file(s) checked, no broken "
                  "negations." % len(files))
    return 1 if findings else 0


def run_stdin(as_json=False):
    """Check one .gitignore document read from standard input."""
    text = sys.stdin.read()
    bad = check_text(text)
    findings = len(bad)
    if as_json:
        print(json.dumps(
            {"files": [{"path": "<stdin>", "findings": bad,
                        "error": None}],
             "checked": 1, "findings": findings},
            indent=2))
    else:
        for finding in bad:
            print(format_finding("<stdin>", finding))
        if findings:
            print("Checked 1 file(s), %d broken negation(s) "
                  "in 1 file(s)." % findings)
        else:
            print("OK — 1 file(s) checked, no broken negations.")
    return 1 if findings else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="gitignore_negation_checker",
        description="Check negated patterns in .gitignore files "
                    "actually work, fail CI when one does not.")
    parser.add_argument("paths", nargs="*",
                        help=".gitignore files or folders to walk")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        help="skip files or folders matching this pattern "
                             "(repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--stdin", action="store_true",
                        help="check one .gitignore document from standard "
                             "input")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no file or folder arguments")
        return run_stdin(as_json=args.json)
    if not args.paths:
        parser.error("give at least one .gitignore file or folder")
    return run(args.paths, recursive=not args.no_recursive,
               exclude=args.exclude, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
