# .claude Directory Sync

This directory contains version-controlled Claude Code configuration (agents, skills, commands, documentation).

## Directory Structure

```
.claude/
├── agents/              # ✓ Version controlled
│   ├── task-decomposer.md
│   ├── parallel-executor.md
│   ├── integration-synthesizer.md
│   ├── code-reviewer.md
│   ├── scout.md
│   ├── ai-docs-fetcher.md
│   ├── mcp-builder.md
│   └── meta-reviewer.md
│
├── skills/              # ✓ Version controlled
│   ├── decomposing-into-orthogonal-tasks/
│   ├── executing-parallel-tasks/
│   ├── synthesizing-with-mcts/
│   └── ... (22 skills total)
│
├── commands/            # ✓ Version controlled
│   ├── decompose.md
│   ├── parallel.md
│   ├── integrate.md
│   └── ... (9 commands total)
│
├── *.md                 # ✓ Version controlled
│   ├── README.md        # Main documentation
│   ├── WORKFLOWS.md     # Integration patterns
│   ├── SYSTEM_MAP.md    # Visual reference
│   ├── AGENT_TESTS.md   # Test scenarios
│   └── SYNC_README.md   # This file
│
├── hooks/               # ⊘ NOT version controlled (repo-specific)
├── settings.json        # ⊘ NOT version controlled (machine-specific)
├── settings.local.json  # ⊘ NOT version controlled
├── history.jsonl        # ⊘ NOT version controlled (runtime state)
├── references/          # ⊘ NOT version controlled (user-specific docs)
└── ... (other runtime files excluded)
```

## Two Locations

1. **`~/.claude/`** - Active configuration used by Claude Code
2. **`~/nova-mcp/.claude/`** - Version controlled copy in this repo

## Keeping in Sync

Use the sync script: `./sync-claude.sh`

### Sync to Repo (before git commit)

```bash
# You've made changes in ~/.claude and want to commit them
./sync-claude.sh to-repo

# Then commit
git add .claude
git commit -m "feat: update agents/skills"
git push
```

### Sync from Repo (after git pull)

```bash
# You've pulled changes and want to apply them to ~/.claude
git pull
./sync-claude.sh from-repo
```

### Interactive Mode

```bash
# Shows differences and prompts for direction
./sync-claude.sh
```

## What Gets Synced

### ✓ Version Controlled (synced)
- `agents/` - All agent definitions
- `skills/` - All skill definitions
- `commands/` - All slash commands
- `*.md` docs - README, WORKFLOWS, SYSTEM_MAP, etc.

### ⊘ NOT Version Controlled (excluded)
- `history.jsonl` - Command history (machine-specific)
- `settings.local.json` - Local settings
- `.credentials.json` - API keys
- `debug/`, `file-history/`, `downloads/`, `projects/`
- `session-env/`, `shell-snapshots/`, `todos/`
- `hooks/` - Repo-specific hooks
- `references/` - User-fetched documentation (via /docs command)

## Workflow

### Making Changes to Agents/Skills

1. Edit files in `~/.claude/` (Claude Code's active directory)
2. Test your changes
3. Sync to repo: `./sync-claude.sh to-repo`
4. Commit: `git add .claude && git commit -m "your message"`
5. Push: `git push`

### Applying Changes from Git

1. Pull changes: `git pull`
2. Sync from repo: `./sync-claude.sh from-repo`
3. Changes now active in `~/.claude/`

### On a New Machine

```bash
# Clone the repo
git clone <repo-url>
cd nova-mcp

# Sync to your home directory
./sync-claude.sh from-repo

# Now ~/.claude has all your agents, skills, and commands
```

## Important Notes

- **Always sync to repo before committing** - Ensures git has latest changes
- **Always sync from repo after pulling** - Applies changes to active config
- **Don't manually copy files** - Use the sync script to avoid mistakes
- **Runtime state is local only** - history, credentials, etc. never synced

## Troubleshooting

### Sync script shows errors

```bash
# Check permissions
ls -la ~/.claude
ls -la ~/nova-mcp/.claude

# Make script executable
chmod +x ./sync-claude.sh
```

### Files out of sync

```bash
# Run interactive mode to see differences
./sync-claude.sh

# Choose the correct sync direction
```

### Merge conflicts in .claude/

```bash
# If you get merge conflicts after git pull:

# 1. Resolve conflicts in ~/nova-mcp/.claude/
git add .claude
git commit

# 2. Sync resolved version to active config
./sync-claude.sh from-repo
```

## See Also

- [`README.md`](README.md) - Main system documentation
- [`WORKFLOWS.md`](WORKFLOWS.md) - Integration patterns and workflows
- [`SYSTEM_MAP.md`](SYSTEM_MAP.md) - Visual architecture reference
- [`AGENT_TESTS.md`](AGENT_TESTS.md) - Test scenarios for agents
