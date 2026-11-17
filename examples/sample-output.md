== examples/clean/.gitignore ==
OK — 1 file(s) checked, no broken negations.

== examples/flagged/.gitignore ==
FAIL examples/flagged/.gitignore: "!keep.txt" line 2 has no earlier pattern to re-include
FAIL examples/flagged/.gitignore: "!build/keep.txt" line 6 parent directory "build" is ignored, so git cannot re-include this path
Checked 1 file(s), 2 broken negation(s) in 1 file(s).

== examples/edge/.gitignore ==
OK — 1 file(s) checked, no broken negations.

== examples/ : the whole folder ==
FAIL examples/flagged/.gitignore: "!keep.txt" line 2 has no earlier pattern to re-include
FAIL examples/flagged/.gitignore: "!build/keep.txt" line 6 parent directory "build" is ignored, so git cannot re-include this path
Checked 3 file(s), 2 broken negation(s) in 1 file(s).
