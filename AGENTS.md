# Agent Workflow

This repository uses `jj` (Jujutsu) for local version control in colocated mode.

## Version Control Rules

- Prefer `jj` for all local version control operations.
- Do not use `git add`, `git commit`, `git stash`, `git checkout`, or other local Git mutation commands unless the user explicitly asks for Git.
- Use `jj log` to inspect history and status.
- Use `jj describe -m "..."` to name the current change.
- Use `jj new` to start the next unit of work.
- Use `jj edit <change>` to return to an existing change.
- Use `jj split` to separate mixed work after the fact.
- Use `jj undo` for safe rollback of the last version-control operation.

## Remote Operations

- The remote is still GitHub.
- Use `jj git fetch` to update from remote.
- Prefer `codex/issue-<n>-<slug>` for agent-created bookmarks so parallel work stays attributable to an issue or task.
- Use `jj bookmark create <name> -r @` before pushing a new line of work.
- Use `jj git push` or `jj git push --bookmark <name>` to publish changes.
- The `main` bookmark is tracked from `origin`.

## Repo State

- This repo has both `.git/` and `.jj/` directories.
- Treat `.jj/` as the source of truth for local history manipulation.
