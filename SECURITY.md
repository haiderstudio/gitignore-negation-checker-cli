# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the .gitignore files you point it at, and it never rewrites a file and never changes anything. It writes nothing except the report on standard output (and usage errors on standard error). It never fetches a URL and never runs git: patterns are checked as text, not by running a command.

It only checks that negated patterns in .gitignore files actually work. It never ignores or un-ignores a file itself, and it never changes what git tracks.

If you find a case where the tool rewrites a file, runs git, or reports a pass for a .gitignore file with a broken negation, please open an issue describing the exact commands and input. Do not include any real secret in the report.
