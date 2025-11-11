# Notes to Claude: Task Tracking Design Pattern

## Design Philosophy

**Rule**: Tasks are persistent and survive VM shutdowns. We track them in the repository, not in temporary files.

## Pattern

1. **Create `tasks/` directory** - All active task tracking files live here
2. **Check in task files** - They are part of the repository
3. **Update as you go** - Mark progress, update status, commit changes
4. **Delete only when complete** - Tasks stay in the repo until 100% done
5. **Never use /tmp/** - Temporary files disappear on VM restart

## Why This Matters

Claude has memory issues between sessions. By keeping tasks in the repo:
- Work persists across VM restarts
- Future Claude sessions can pick up where we left off
- Peter can see progress at any time
- Git history shows the journey

## Active Task Files

- `pandas_to_polars_manifest.txt` - Complete list of 135 files to migrate
- `migration_progress.md` - Current status (which batches are done)

## Example Workflow

```bash
# Start task
echo "## Batch 1: STARTED" >> tasks/migration_progress.md
git add tasks/migration_progress.md
git commit -m "tasks: Start Batch 1 migration"

# Work on task...
# Make changes...

# Update progress
echo "## Batch 1: COMPLETED (9 files)" >> tasks/migration_progress.md
git add tasks/migration_progress.md
git commit -m "tasks: Complete Batch 1 migration"

# When ALL batches done
rm tasks/pandas_to_polars_manifest.txt
rm tasks/migration_progress.md
git commit -m "tasks: Remove completed migration tracking"
```

## Key Principle

**Tasks don't vanish when the VM shuts down. They vanish when we mark them done and commit that fact.**
