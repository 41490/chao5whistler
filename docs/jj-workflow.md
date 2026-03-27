# JJ Workspace And Bookmark Workflow

This repository uses `jj` in colocated mode. The goal of this guide is to keep
`change`, `bookmark`, and `workspace` usage explicit so parked workspaces and
stale task branches do not accumulate again.

## Core Model

- Prefer a new `change` before opening a new `workspace`.
- Treat `bookmark` as the durable name for a task line that must be pushed,
  handed off, or resumed later.
- Treat `workspace` as a working-copy isolation tool, not as the default unit
  of planning.

## Default Rule

Use this default unless there is a concrete reason not to:

- `1 issue = 1 canonical bookmark = 1 active workspace`

Recommended naming:

- Bookmark: `codex/issue-<n>-<slug>`
- Workspace dir: `/opt/src/41490/chao5whistler-<issue-or-slug>`

Within that active workspace, continue work with:

- `jj new`
- `jj describe -m "..."`
- `jj edit <change>`

Do not open `-p2`, `-p3`, or extra parked workspaces unless work is actually
parallel.

## When To Open A Workspace

Open a separate workspace only when at least one of these is true:

- The default workspace already contains unrelated uncommitted work.
- The task is long-running or environment-heavy, such as soak, system service,
  ffmpeg toolchain, or live-stream verification.
- Multiple agents or people need to work in parallel.
- You need a clean experimental lane without contaminating the main working
  copy.

If none of the above is true, stay in the existing canonical workspace and use a
new `change` instead.

## When Parallel Work Is Allowed

If parallel work is necessary, require:

- `1 subtask = 1 workspace = 1 bookmark`

Recommended naming:

- `codex/issue-<n>-<slug>-p2`
- `codex/issue-<n>-<slug>-p3`

Each parallel lane must have:

- a clear owner
- a clear goal
- a clear planned deletion or merge point

Parallel `pN` lanes are short-lived tools. They should not become long-term
parked state.

## When To Create Or Push A Bookmark

Create a bookmark when the work:

- needs to be pushed to GitHub
- needs to be referenced from an issue
- needs to survive handoff across sessions
- needs a stable name while parallel work is active

Typical pattern:

```bash
jj bookmark create codex/issue-12-jj-workflow -r @
jj git push --bookmark codex/issue-12-jj-workflow
```

If the work is only a short local experiment and does not need durable
reference, a bookmark is optional.

## Merge And Convergence Timing

Create a separate `change` as soon as the work becomes:

- independently understandable
- independently reviewable
- independently revertible

Converge branches and workspaces as soon as one lane clearly becomes the
surviving line.

For parallel `pN` lanes, do not wait until days later. Converge on the same day
or before the parent issue is closed.

Allowed outcomes for each extra lane:

- merged into the surviving line
- explicitly abandoned
- explicitly kept, with the reason recorded in the issue

## Closure Checklist

When a task is merged into `main` or explicitly abandoned, do the cleanup in the
same round of work:

1. Check `jj workspace list`
2. Check `jj bookmark list`
3. If the task is finished:
   - `jj workspace forget <workspace>`
   - remove the corresponding directory
   - `jj bookmark delete <bookmark>`
   - `jj git push --deleted`
4. If the task is handing off to a new phase:
   - open a new issue/bookmark for the new phase
   - close the old bookmark/workspace instead of silently reusing the old name

## Hard Repo Rules

### Rule A

Every non-`default` workspace must satisfy one of:

- it has a corresponding task bookmark
- it is a clearly temporary experiment and the issue/comment records when it
  should be deleted

### Rule B

Any bookmark named `codex/issue-*` should be deleted when all three are true:

- the corresponding issue is closed
- the commit is already covered by `main`
- no active workspace still depends on that bookmark

## Recommended Day-To-Day Pattern

### Sequential work

- stay in one canonical workspace
- use `jj new` for each clean unit of work
- create or update a bookmark only when the line needs durable reference

### Parallel work

- open a separate workspace only when there is real concurrency or isolation
  need
- pair every parallel workspace with its own bookmark
- delete losing or finished lanes immediately after convergence

### Default workspace

- use it as the current integration line or light documentation line
- do not let it accumulate unrelated unfinished work from multiple issues
- once it is dirty with unrelated work, do not also use it as the commit/push
  lane for another issue
