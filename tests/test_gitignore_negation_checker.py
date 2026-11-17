#!/usr/bin/env python3
"""Tests for gitignore_negation_checker — stdlib unittest only.

Every .gitignore document in this file is made up for
testing. No real secret appears anywhere in this file.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import gitignore_negation_checker as checker

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/gitignore_negation_checker.py"


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write(tmp, name, text, encoding="utf-8"):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding=encoding)
    return str(path)


def findings_of(text):
    return checker.check_text(text)


class TestPatternMatching(unittest.TestCase):
    def test_star_matches_name_at_any_depth(self):
        self.assertTrue(checker.pattern_ignores("*.log", "a.log"))
        self.assertTrue(checker.pattern_ignores("*.log", "x/a.log"))
        self.assertFalse(checker.pattern_ignores("*.log", "a.txt"))

    def test_star_does_not_cross_a_slash(self):
        self.assertFalse(
            checker.pattern_ignores("docs/*.txt", "docs/sub/a.txt"))
        self.assertTrue(
            checker.pattern_ignores("docs/*.txt", "docs/a.txt"))

    def test_bare_name_matches_a_folder_and_its_contents(self):
        self.assertTrue(checker.pattern_ignores("build", "build/x.txt"))
        self.assertTrue(checker.pattern_ignores("build", "a/build/x.txt"))
        self.assertFalse(checker.pattern_ignores("build", "builder.txt"))

    def test_anchored_pattern_matches_from_the_root_only(self):
        self.assertTrue(checker.pattern_ignores("/build", "build/x.txt"))
        self.assertFalse(
            checker.pattern_ignores("/build", "a/build/x.txt"))

    def test_double_star_leading_matches_zero_or_more_folders(self):
        self.assertTrue(
            checker.pattern_ignores("**/*.log", "debug.log"))
        self.assertTrue(
            checker.pattern_ignores("**/*.log", "a/debug.log"))
        self.assertTrue(
            checker.pattern_ignores("**/*.log", "a/b/debug.log"))
        self.assertFalse(
            checker.pattern_ignores("**/*.log", "a/debug.txt"))

    def test_double_star_middle_matches_zero_or_more_folders(self):
        self.assertTrue(checker.pattern_ignores("a/**/b", "a/b"))
        self.assertTrue(checker.pattern_ignores("a/**/b", "a/x/b"))
        self.assertTrue(checker.pattern_ignores("a/**/b", "a/x/y/b"))
        self.assertFalse(checker.pattern_ignores("a/**/b", "a/x/c"))

    def test_double_star_trailing_matches_everything_inside(self):
        self.assertTrue(checker.pattern_ignores("abc/**", "abc/x"))
        self.assertTrue(checker.pattern_ignores("abc/**", "abc/x/y.txt"))
        self.assertFalse(checker.pattern_ignores("abc/**", "abc"))

    def test_question_mark_matches_one_character_not_a_slash(self):
        self.assertTrue(checker.pattern_ignores("file?.txt", "file1.txt"))
        self.assertFalse(checker.pattern_ignores("file?.txt", "file12.txt"))
        self.assertFalse(checker.pattern_ignores("file?.txt", "file/.txt"))

    def test_character_class_matches(self):
        self.assertTrue(checker.pattern_ignores("*.[oa]", "a.o"))
        self.assertTrue(checker.pattern_ignores("*.[oa]", "a.a"))
        self.assertFalse(checker.pattern_ignores("*.[oa]", "a.c"))
        self.assertTrue(checker.pattern_ignores("[abc].o", "b.o"))
        self.assertTrue(checker.pattern_ignores("[!abc].o", "d.o"))
        self.assertFalse(checker.pattern_ignores("[!abc].o", "a.o"))

    def test_directory_only_pattern_does_not_match_a_file(self):
        self.assertFalse(
            checker.pattern_ignores("build/", "build", False))
        self.assertTrue(
            checker.pattern_ignores("build/", "build", True))
        self.assertTrue(
            checker.pattern_ignores("build/", "build/x.txt", False))

    def test_escaped_hash_is_a_pattern_not_a_comment(self):
        is_pattern, is_negation, pattern = checker._parse_line(
            "\\#not-a-comment")
        self.assertTrue(is_pattern)
        self.assertFalse(is_negation)
        self.assertEqual(pattern, "#not-a-comment")

    def test_empty_pattern_matches_nothing(self):
        self.assertFalse(checker.pattern_ignores("", "a.txt"))


class TestNegationDetection(unittest.TestCase):
    def test_negation_after_its_pattern_passes(self):
        self.assertEqual(findings_of("*.txt\n!keep.txt\n"), [])

    def test_negation_before_its_pattern_fails(self):
        bad = findings_of("!keep.txt\n*.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)
        self.assertEqual(bad[0]["pattern"], "!keep.txt")
        self.assertEqual(bad[0]["reason"],
                         "has no earlier pattern to re-include")

    def test_negation_with_no_pattern_at_all_fails(self):
        bad = findings_of("!keep.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 1)

    def test_negation_matching_nothing_fails_even_with_patterns(self):
        bad = findings_of("*.log\n!keep.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["reason"],
                         "has no earlier pattern to re-include")

    def test_file_inside_ignored_folder_fails(self):
        bad = findings_of("build/\n!build/keep.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)
        self.assertEqual(bad[0]["pattern"], "!build/keep.txt")
        self.assertIn('parent directory "build" is ignored',
                      bad[0]["reason"])

    def test_star_inside_folder_leaves_the_folder_alone(self):
        self.assertEqual(
            findings_of("build/*\n!build/keep.txt\n"), [])

    def test_reincluding_the_folder_first_passes(self):
        self.assertEqual(
            findings_of("build/\n!build/\n!build/keep.txt\n"), [])

    def test_nested_ignored_folder_fails(self):
        bad = findings_of("a/b/\n!a/b/c.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertIn('parent directory "a/b" is ignored',
                      bad[0]["reason"])

    def test_deepest_blocked_parent_is_named(self):
        bad = findings_of("a/\n!a/b/c.txt\n")
        self.assertEqual(len(bad), 1)
        self.assertIn('parent directory "a" is ignored',
                      bad[0]["reason"])

    def test_negation_of_a_folder_passes(self):
        self.assertEqual(findings_of("docs/\n!docs/\n"), [])

    def test_negation_inside_reincluded_folder_passes(self):
        self.assertEqual(
            findings_of("docs/\n!docs/\n!docs/guide.txt\n"), [])

    def test_double_star_negation_passes(self):
        self.assertEqual(
            findings_of("**/*.log\n!debug.log\n"), [])

    def test_anchored_negation_after_anchored_pattern_passes(self):
        self.assertEqual(
            findings_of("/cache/\n!/cache/\n!/cache/keep.txt\n"), [])

    def test_wildcard_negation_after_wildcard_pattern_passes(self):
        self.assertEqual(findings_of("*.[oa]\n![abc].o\n"), [])

    def test_comments_and_blank_lines_are_skipped(self):
        text = ("# A comment\n\n*.txt\n"
                "# Another comment\n!keep.txt\n")
        self.assertEqual(findings_of(text), [])

    def test_commented_negation_is_not_a_negation(self):
        self.assertEqual(findings_of("# !keep.txt\n*.txt\n"), [])

    def test_escaped_bang_is_not_a_negation(self):
        self.assertEqual(findings_of("\\!keep.txt\n"), [])

    def test_duplicate_negation_is_not_flagged(self):
        self.assertEqual(
            findings_of("*.txt\n!keep.txt\n!keep.txt\n"), [])

    def test_two_broken_negations_reported_in_order(self):
        text = ("!keep.txt\n*.txt\nbuild/\n!build/keep.txt\n")
        bad = findings_of(text)
        self.assertEqual([f["line"] for f in bad], [1, 4])
        self.assertEqual([f["pattern"] for f in bad],
                         ["!keep.txt", "!build/keep.txt"])

    def test_empty_document_passes(self):
        self.assertEqual(findings_of(""), [])

    def test_document_with_no_negations_passes(self):
        self.assertEqual(findings_of("*.log\nbuild/\n"), [])

    def test_trailing_spaces_are_stripped(self):
        self.assertEqual(findings_of("*.txt   \n!keep.txt\n"), [])

    def test_question_mark_negation_passes(self):
        self.assertEqual(findings_of("file?.txt\n!file1.txt\n"), [])


class TestCLI(unittest.TestCase):
    def test_clean_file_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 0)
            self.assertIn("no broken negations", out)
            self.assertEqual(err, "")

    def test_flagged_file_exit_1_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "!keep.txt\n*.txt\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn('"!keep.txt" line 1', out)
            self.assertIn("has no earlier pattern to re-include", out)
            self.assertIn(path, out)

    def test_folder_walk_finds_gitignore_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            write(tmp, "sub/.gitignore", "build/\n!build/keep.txt\n")
            write(tmp, "notes.txt", "!keep.txt\n")
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)
            self.assertIn("sub", out)
            self.assertNotIn("notes.txt", out)

    def test_folder_walk_skips_nested_with_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            write(tmp, "sub/.gitignore", "build/\n!build/keep.txt\n")
            code, out, err = run_cli([tmp, "--no-recursive"])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)

    def test_exclude_skips_a_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            write(tmp, "sub/.gitignore", "build/\n!build/keep.txt\n")
            code, out, err = run_cli([tmp, "--exclude", "sub"])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_git_folder_skipped_in_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            write(tmp, ".git/.gitignore", "build/\n!build/keep.txt\n")
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_direct_file_checked_whatever_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "exclude.txt", "build/\n!build/keep.txt\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("exclude.txt", out)

    def test_duplicate_paths_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            code, out, err = run_cli([path, path])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "!keep.txt\n*.txt\n")
            code, out, err = run_cli(["--json", path])
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["checked"], 1)
            self.assertEqual(data["findings"], 1)
            self.assertEqual(data["files"][0]["path"], path)
            self.assertEqual(
                data["files"][0]["findings"][0]["line"], 1)
            self.assertEqual(
                data["files"][0]["findings"][0]["pattern"], "!keep.txt")
            self.assertEqual(
                data["files"][0]["findings"][0]["reason"],
                "has no earlier pattern to re-include")
            self.assertIsNone(data["files"][0]["error"])

    def test_stdin_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), "--stdin"],
                input="*.txt\n!keep.txt\n", cwd=tmp,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no broken negations", result.stdout)

    def test_stdin_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), "--stdin"],
                input="!keep.txt\n*.txt\n", cwd=tmp,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('FAIL <stdin>: "!keep.txt" line 1',
                          result.stdout)

    def test_stdin_with_paths_is_usage_error(self):
        code, out, err = run_cli(["--stdin", ".gitignore"])
        self.assertEqual(code, 2)

    def test_no_paths_is_usage_error(self):
        code, out, err = run_cli([])
        self.assertEqual(code, 2)

    def test_missing_path_exit_2(self):
        code, out, err = run_cli(["/nonexistent/path/xyz"])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_empty_folder_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no .gitignore files found", err)

    def test_bad_flag_exit_2(self):
        code, out, err = run_cli(["--nope"])
        self.assertEqual(code, 2)

    def test_version(self):
        code, out, err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("gitignore_negation_checker 1.0.0", out)

    def test_non_utf8_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", b"\xff\xfe!keep.txt\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("not valid UTF-8", out)

    def test_input_files_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "!keep.txt\n*.txt\n")
            before = Path(path).read_text()
            run_cli([path])
            self.assertEqual(Path(path).read_text(), before)

    def test_cli_runs_from_another_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            result = subprocess.run(
                [sys.executable, str(SRC), ".gitignore"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no broken negations", result.stdout)

    def test_cli_runs_under_fake_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, ".gitignore", "*.txt\n!keep.txt\n")
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                code, out, err = run_cli([path])
            finally:
                if old_home is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = old_home
            self.assertEqual(code, 0)


class TestExamples(unittest.TestCase):
    def test_run_example_output_matches_sample(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        expected = (REPO / "examples/sample-output.md").read_text()
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        clean = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "examples/clean/.gitignore"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0)
        self.assertIn(clean.stdout.strip(), readme)
        flagged = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "examples/flagged/.gitignore"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(flagged.returncode, 1)
        self.assertIn(flagged.stdout.strip(), readme)
        folder = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "examples/"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(folder.returncode, 1)
        self.assertIn("Checked 3 file(s), 2 broken negation(s) "
                      "in 1 file(s).", folder.stdout)
        self.assertIn("Checked 3 file(s), 2 broken negation(s) "
                      "in 1 file(s).", readme)
        edge = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "examples/edge/.gitignore"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(edge.returncode, 0)
        self.assertIn(edge.stdout.strip(), readme)
        js = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "--json", "examples/flagged/.gitignore"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(js.returncode, 1)
        self.assertIn(js.stdout.strip(), readme)
        stdin_bad = subprocess.run(
            [sys.executable, "src/gitignore_negation_checker.py",
             "--stdin"],
            input="!keep.txt\n*.txt\n",
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(stdin_bad.returncode, 1)
        self.assertIn(stdin_bad.stdout.strip(), readme)


class TestHygiene(unittest.TestCase):
    def _repo_files(self, skip_tests=True, skip_examples=True):
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs
                       if d not in (".git", "__pycache__")
                       and not (skip_tests and d == "tests")
                       and not (skip_examples and d == "examples")]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                yield Path(root) / name

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for marker in ("/home/", "/Users/", "C:\\"):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_no_real_secrets_outside_tests_and_examples(self):
        # The source holds no key values at all; the tests
        # and examples hold fake values only, so they are
        # excluded from this scan.
        patterns = [
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
            re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
            re.compile(r"AIza[0-9A-Za-z_-]{35}"),
            re.compile(r"[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),
            re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
            re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ"),
        ]
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for pattern in patterns:
                if pattern.search(text):
                    hits.append("%s: %s" % (path.name, pattern.pattern))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src/gitignore_negation_checker.py",
                       REPO / "tests/test_gitignore_negation_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"gitignore_negation_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src/gitignore_negation_checker.py").read_text()
        for marker in ("urllib.request", "requests", "socket",
                       "http.client", "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn("tests/test_gitignore_negation_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_readme_names_the_neighbouring_repos(self):
        readme = (REPO / "README.md").read_text()
        self.assertIn("gitignore-checker-cli", readme)
        self.assertIn("gitignore-duplicate-checker-cli", readme)


if __name__ == "__main__":
    unittest.main()
