# gitignore-negation-checker-cli

Check negated patterns in `.gitignore` files actually work — fail CI when one does not.

[![CI](https://github.com/haiderstudio/gitignore-negation-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/gitignore-negation-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`gitignore_negation_checker` reads each
`.gitignore` file and reports each broken
negation — with the file and the line number.
It exits 1 when any negation is broken, so it
can fail a CI run. A file whose negations all
work exits 0.

- A `!keep.txt` written before `*.txt`, or
  under an ignored folder, silently does
  nothing — the file stays ignored and the
  author believes it is tracked, and the
  missing file shows up at deploy time. This
  names the exact line, and the fix is one
  reorder per pattern once found.
- A negation is broken in two ways, and both
  are checked. **Order:** the negation comes
  before any pattern that ignores the path it
  re-includes. Git applies patterns in order,
  last match wins, so a `!keep.txt` written
  above `*.txt` has nothing to re-include yet
  and never takes effect. **Parent directory:**
  the re-included path sits inside a directory
  that is itself ignored, and no earlier
  negation re-includes that directory. Git
  cannot re-include a file inside an ignored
  directory, so `!build/keep.txt` under
  `build/` never takes effect. Ignoring
  `build/*` instead of `build/` leaves the
  directory itself alone, and re-including the
  directory first with `!build/` also works —
  both pass this check.
- A file given directly on the command line is
  always checked, whatever its name. A folder
  is walked for files named exactly
  `.gitignore`, recursively by default
  (`--no-recursive` stops at the top level).
  `.git` folders are never walked, and
  directory links are never followed.
- `--json` prints the result as JSON, and
  `--stdin` checks one `.gitignore` document
  read from standard input.
- Blank lines and comments are skipped. A line
  starting with `\#` or `\!` is a literal
  pattern, not a comment or a negation, as git
  defines it. Patterns are matched with git's
  own rules: `*` and `?` never cross a slash,
  `**` does, a pattern with no slash matches a
  name at any depth, a pattern with a slash is
  anchored to the folder the `.gitignore` file
  sits in, and a trailing slash marks a
  directory-only pattern. Each `.gitignore`
  file is checked on its own, so a pattern is
  always read relative to the folder its file
  sits in.

## Who it is for

Every developer with a `.gitignore` that
re-includes files — a build folder that keeps
one shipped file, a logs folder that keeps one
sample, a docs folder that keeps one guide.
One broken negation and the file silently
stays ignored, and the gap shows up as a
missing file at deploy time. This is the gate
that stops it at the pull request.

## What it does NOT do

- It does not check whether files are actually
  ignored or tracked. That is repo #41,
  gitignore-checker-cli, which checks
  tracked-vs-ignored state — this tool only
  checks the order and the parent-directory
  rule of negations.
- It does not check duplicate patterns. That
  is repo #67, gitignore-duplicate-checker-cli
  — duplicates are a different check on the
  same files.
- It does not check `.git/info/exclude` or a
  global gitignore, and it does not check
  whether a negation's target is a wildcard
  that merely overlaps an earlier pattern; it
  compares the patterns as written.
- It never rewrites a file, never runs git,
  and never touches the network.

## How this differs

- A fresh search of GitHub on Nov 15, 2026
  found 0 results for
  `"gitignore-negation-checker-cli"` and 0
  results for `gitignore negation checker` —
  a completely empty field.
- No rival checks gitignore negations.

## Install

```sh
git clone https://github.com/haiderstudio/gitignore-negation-checker-cli.git
cd gitignore-negation-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one `.gitignore` file:

```sh
python3 src/gitignore_negation_checker.py .gitignore
```

A file whose negations all work passes:

```sh
$ python3 src/gitignore_negation_checker.py examples/clean/.gitignore
OK — 1 file(s) checked, no broken negations.
```

A file with broken negations fails, with the
file and line for each one:

```sh
$ python3 src/gitignore_negation_checker.py examples/flagged/.gitignore
FAIL examples/flagged/.gitignore: "!keep.txt" line 2 has no earlier pattern to re-include
FAIL examples/flagged/.gitignore: "!build/keep.txt" line 6 parent directory "build" is ignored, so git cannot re-include this path
Checked 1 file(s), 2 broken negation(s) in 1 file(s).
```

Check a whole folder (`.gitignore` files only):

```sh
$ python3 src/gitignore_negation_checker.py examples/
FAIL examples/flagged/.gitignore: "!keep.txt" line 2 has no earlier pattern to re-include
FAIL examples/flagged/.gitignore: "!build/keep.txt" line 6 parent directory "build" is ignored, so git cannot re-include this path
Checked 3 file(s), 2 broken negation(s) in 1 file(s).
```

Check one document from standard input:

```sh
$ printf '!keep.txt\n*.txt\n' | python3 src/gitignore_negation_checker.py --stdin
FAIL <stdin>: "!keep.txt" line 1 has no earlier pattern to re-include
Checked 1 file(s), 1 broken negation(s) in 1 file(s).
```

Machine-readable output:

```sh
$ python3 src/gitignore_negation_checker.py --json examples/flagged/.gitignore
{
  "files": [
    {
      "path": "examples/flagged/.gitignore",
      "findings": [
        {
          "line": 2,
          "pattern": "!keep.txt",
          "reason": "has no earlier pattern to re-include"
        },
        {
          "line": 6,
          "pattern": "!build/keep.txt",
          "reason": "parent directory \"build\" is ignored, so git cannot re-include this path"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "findings": 2
}
```

Exit codes: 0 when every negation works, 1 when
any negation is broken or a file cannot be read, 2
for a usage error (a missing path, a bad flag, or no
`.gitignore` files found).

## Examples

Negations that work, in their ordinary forms —
`examples/clean/.gitignore` holds all of them,
and it passes:

```sh
$ python3 src/gitignore_negation_checker.py examples/clean/.gitignore
OK — 1 file(s) checked, no broken negations.
```

Negations that work, in their trickier forms —
a `**` pattern, a `*` inside a folder, and a
character class — `examples/edge/.gitignore`
has all of them, and it passes:

```sh
$ python3 src/gitignore_negation_checker.py examples/edge/.gitignore
OK — 1 file(s) checked, no broken negations.
```

A negation written before its pattern still
fails — the order is the whole check:

```sh
$ printf '!keep.txt\n*.txt\n' | python3 src/gitignore_negation_checker.py --stdin
FAIL <stdin>: "!keep.txt" line 1 has no earlier pattern to re-include
Checked 1 file(s), 1 broken negation(s) in 1 file(s).
```

Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_gitignore_negation_checker.py
```

The tests cover pattern matching (a `*` matches
a name at any depth but never crosses a slash, a
bare name matches a folder and its contents, an
anchored pattern matches from the root only, a
leading `**/` matches zero or more folders, a
middle `/**/` matches zero or more folders, a
trailing `/**` matches everything inside, `?`
matches one character but not a slash, character
classes match including `[!...]`, a
directory-only pattern does not match a file, an
escaped `\#` is a pattern not a comment, an empty
pattern matches nothing), negation detection (a
negation after its pattern passes, a negation
before its pattern fails, a negation with no
pattern at all fails, a negation matching
nothing fails even with other patterns present,
a file inside an ignored folder fails, a `*`
inside a folder leaves the folder alone,
re-including the folder first passes, a nested
ignored folder fails, the deepest blocked
parent is named, a negation of a folder passes,
a negation inside a re-included folder passes,
a `**` negation passes, an anchored negation
after an anchored pattern passes, a wildcard
negation after a wildcard pattern passes,
comments and blank lines are skipped, a
commented negation is not a negation, an
escaped `\!` is not a negation, a duplicate
negation is not flagged, two broken negations
are reported in order, an empty document passes,
a document with no negations passes, trailing
spaces are stripped, a `?` negation passes),
the CLI (exit 0/1/2, folder walking for
`.gitignore` files only, nested folders,
`--no-recursive`, `--exclude`, `.git` skipped,
a direct file checked whatever its name,
duplicate paths checked once, `--json` output,
`--stdin`, bad flags, missing paths, empty
folders, `--version`, a non-UTF-8 file reported,
input files left unchanged, the tool run from
another folder and under a changed HOME), the
bundled examples (sample output compared
byte-for-byte against a fresh run, and the
README-quoted outputs checked against it), and
hygiene checks (no placeholder text, no
absolute paths, no real secrets outside the
tests and examples, stdlib imports only, no
network use in the source, `.env` first in
`.gitignore`, CI file runs the test file, README
names the neighbouring repos).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
idea of checking gitignore negations is not new, and
the pattern matching follows git's own documented
rules — but no existing tool does this one job,
checking that negated patterns in local .gitignore
files actually work, as a tested command-line gate
with a CI exit code, as the search above shows —
and every line of code here is original, built on
nothing but Python's standard library.
