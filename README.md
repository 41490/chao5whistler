# chao5whistler
> ghwhistler 加强版


## background
Youtube 有很多无限直播节目...


- 在挪威卑尔根线工作的女火车司机/工程师。 与您分享驾驶室的景色 https://www.youtube.com/@RailCowGirl
- Connecting people through music 🌎 https://www.youtube.com/@LofiGirl
- ...

## goal

用技术手段生成无限不循环音乐/节奏/图案...作为自己工作时的白噪音...


## logging
...TBD

## development

### jj workflow

This repo uses `jj` (Jujutsu) for local version control in colocated mode.

- inspect current state: `jj log` and `jj status`
- describe the current change: `jj describe -m "type(scope): summary"`
- start the next unit of work: `jj new`
- update from remote: `jj git fetch`
- publish a new line of work: `jj bookmark create codex/issue-<n>-<slug> -r @`
- push the bookmark: `jj git push --bookmark codex/issue-<n>-<slug>`

For local history manipulation, prefer `jj` over mutating Git commands.

## refer.
...TBD

## tracing

- 260319 DAMA init.

