# ARBS — Claude Code Notes

## Worktrees — read this before writing any file

**Start new work in a NEW git worktree, not in the primary tree**, unless the user explicitly
says otherwise. The primary tree (`C:\Users\chris\clee\ARBS`) is frequently checked out on a
user feature branch with uncommitted work in progress; writing there disturbs it, and an
unstaged change you added is indistinguishable from one they made.

```bash
git -C C:/Users/chris/clee/ARBS worktree add ../ARBS-<short> -b <branch>
```

Use a **short sibling path** (`..\ARBS-l2`, `..\ARBS-tld`). Windows path limits bite on deep
node_modules and pytest temp dirs, and a long worktree name is what breaks first.

## Every git command must name its tree

**Always `git -C <worktree-path> ...`. Never rely on `cd` having stuck.**

This is not hypothetical. `cd /path && cmd &` backgrounds the whole list, and the *next*
command runs from the session's default directory — which is the primary tree. A
`git add`/`commit`/`push` chained after a `&` has landed on the wrong branch that way.

- The Bash tool's working directory resets between calls; a `cd` in one call does not bind
  the next.
- `git push origin <branch>` from *any* worktree pushes that ref — worktrees share the object
  store and refs — so a push "succeeding" is no evidence you were in the right tree.
- Before committing, confirm the branch: `git -C <path> status -sb | head -1`.
- After committing, confirm it landed: `git -C <path> log --oneline -1`.

If a git command produces output mentioning a branch you did not expect, stop and check
`git -C <primary> status --porcelain` and `git -C <primary> diff --cached --stat` before doing
anything else — the failure mode is staging or committing the user's in-flight work.

## Testing

- Fast gate (pre-commit): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Full suite (~1.5h; needs network + DATABASE_URL): `conda run -n stir python -m pytest tests`

Full suite ~1.5h; needs network + DATABASE_URL. Slow/network/db markers exclude the heavy tests.
