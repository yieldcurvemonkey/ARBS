# Development Guidelines

## Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality.

### Setup
```bash
pip install pre-commit
pre-commit install
```

### Usage
Hooks run automatically on `git commit`. To run manually:
```bash
pre-commit run --all-files
```

### Hooks Configured
- **black**: Code formatting (120 char line length)
- **isort**: Import sorting (black-compatible profile)
- **flake8**: Linting (120 char line length)
- **autoflake**: Remove unused imports and variables
- **trailing-whitespace**: Remove trailing whitespace
- **end-of-file-fixer**: Ensure files end with newline
- **check-yaml**: Validate YAML syntax
- **check-added-large-files**: Prevent committing large files (>1MB)
- **check-merge-conflict**: Detect merge conflict markers
- **mixed-line-ending**: Ensure consistent line endings

### Configuration Files
- `.pre-commit-config.yaml`: Pre-commit hook configuration
- `setup.cfg`: flake8 configuration
- `pyproject.toml`: black and isort configuration

### Skipping Hooks (Emergency Only)
If you absolutely must bypass hooks (not recommended):
```bash
git commit --no-verify
```

**Note**: Only use `--no-verify` in genuine emergencies. All code should pass quality checks.
