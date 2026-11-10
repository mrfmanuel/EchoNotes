Before we start the project, check that this Windows machine has all the prerequisites. Do NOT install or change anything yet and do NOT create any project files — only inspect and report. Reply in English.

Run these checks (use Git Bash-compatible commands; if a command is not found, also try the Windows equivalent, e.g. `where <tool>` or `py --version`):

1. `git --version` and `git config user.name` / `git config user.email` (must be set for commits).
2. `gh --version` and `gh auth status` — report the logged-in account, the protocol (https/ssh), and the token scopes. Tell me whether the `repo`, `workflow` and `project` scopes are present.
3. Docker: `docker --version`, `docker compose version`, and `docker info` (to confirm Docker Desktop is RUNNING, not just installed). Also run `docker run --rm hello-world` as a smoke test.
4. Node: `node --version` (need >= 20) and `npm --version`.
5. Python: `python --version` and/or `py --version` (need >= 3.12).
6. uv: `uv --version`.
7. Optional but useful: `make --version` (likely missing on Windows — just report it), `curl --version`.

Then print a table: Tool | Required | Found version | Status (OK / MISSING / TOO OLD / NOT RUNNING) | Fix.

For anything that is not OK, give me the exact fix command for Windows (prefer `winget install ...`), but do NOT run installers yourself.

Interactive steps you cannot do for me — tell me exactly what to type:
- If `gh` is not logged in: tell me to run `! gh auth login` (GitHub.com → HTTPS → login with a web browser).
- If the `project` or `workflow` scope is missing: tell me to run `! gh auth refresh -h github.com -s project,workflow` and complete the browser step, then re-run `gh auth status` to confirm.

Finally, confirm whether the GitHub repo name `mrfmanuel/echonotes` is still free (`gh repo view mrfmanuel/echonotes` should fail with "not found"), and end with a one-line verdict: "READY for P1" or "NOT READY — fix: ...".
