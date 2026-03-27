# Claude Workflow Notes

This repository uses `jj` as the source of truth for local history operations.

- Prefer the repo-level rules in [AGENTS.md](AGENTS.md).
- For the concrete workspace/bookmark lifecycle, naming, and cleanup timing, see
  [docs/jj-workflow.md](docs/jj-workflow.md).

In practice:

- prefer opening a new `change` before opening a new `workspace`
- keep `1 issue = 1 canonical bookmark = 1 active workspace` by default
- delete task bookmarks and forget task workspaces once their work is merged
  into `main` or explicitly abandoned
