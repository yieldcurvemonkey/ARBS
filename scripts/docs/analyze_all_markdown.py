#!/usr/bin/env python3
# ABOUTME: Analyzes all markdown files in the repository and generates inventory metadata
# ABOUTME: Extracts git history, references, and categorizes documentation files

import json
import os
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set

REPO_ROOT = Path("/home/user/ARBS")
EXCLUDE_PATTERNS = [".git", "venv", "__pycache__", ".pytest_cache"]


def run_git_command(cmd: List[str], cwd: Path = REPO_ROOT) -> str:
    """Run a git command and return output"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        return ""


def find_markdown_files() -> List[Path]:
    """Find all markdown files excluding specific patterns"""
    md_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Remove excluded directories from traversal
        dirs[:] = [d for d in dirs if d not in EXCLUDE_PATTERNS]

        for file in files:
            if file.endswith('.md'):
                md_files.append(Path(root) / file)

    return sorted(md_files)


def get_file_metadata(file_path: Path) -> Dict:
    """Extract git metadata for a file"""
    rel_path = file_path.relative_to(REPO_ROOT)

    # First commit date
    first_commit = run_git_command([
        'git', 'log', '--follow', '--diff-filter=A', '--format=%aI', '--', str(rel_path)
    ])

    # Last modified date
    last_modified = run_git_command([
        'git', 'log', '-1', '--follow', '--format=%aI', '--', str(rel_path)
    ])

    # Commit count
    commit_count_output = run_git_command([
        'git', 'log', '--follow', '--oneline', '--', str(rel_path)
    ])
    commit_count = len(commit_count_output.split('\n')) if commit_count_output else 0

    # Line and word count
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = len(content.split('\n'))
            words = len(content.split())
    except Exception:
        lines = 0
        words = 0
        content = ""

    return {
        'first_commit': first_commit.split('T')[0] if first_commit else None,
        'last_modified': last_modified.split('T')[0] if last_modified else None,
        'commit_count': commit_count,
        'lines': lines,
        'words': words,
        'content': content
    }


def find_references_to_file(file_path: Path, all_files: List[Path]) -> Dict[str, List[str]]:
    """Find what references this file"""
    rel_path = file_path.relative_to(REPO_ROOT)
    filename = file_path.name

    referenced_by_code = []
    referenced_by_docs = []

    # Search Python files
    py_files = list(REPO_ROOT.rglob("*.py"))
    for py_file in py_files:
        if any(excl in str(py_file) for excl in EXCLUDE_PATTERNS):
            continue

        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if filename in content or str(rel_path) in content:
                    # Find line number
                    for i, line in enumerate(content.split('\n'), 1):
                        if filename in line or str(rel_path) in line:
                            referenced_by_code.append(f"{py_file.relative_to(REPO_ROOT)}:{i}")
                            break
        except Exception:
            pass

    # Search other markdown files
    for md_file in all_files:
        if md_file == file_path:
            continue

        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if filename in content or str(rel_path) in content:
                    for i, line in enumerate(content.split('\n'), 1):
                        if filename in line or str(rel_path) in line:
                            referenced_by_docs.append(f"{md_file.relative_to(REPO_ROOT)}:{i}")
                            break
        except Exception:
            pass

    return {
        'referenced_by_code': list(set(referenced_by_code)),
        'referenced_by_docs': list(set(referenced_by_docs))
    }


def extract_references_from_file(file_path: Path, content: str) -> List[str]:
    """Extract markdown links and file references from content"""
    references = []

    # Match markdown links [text](path)
    md_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    for match in re.finditer(md_link_pattern, content):
        link = match.group(2)
        # Filter out URLs and anchors
        if not link.startswith(('http://', 'https://', '#')):
            references.append(link)

    # Match direct .md file references
    md_ref_pattern = r'[\w/-]+\.md'
    for match in re.finditer(md_ref_pattern, content):
        ref = match.group(0)
        if ref != file_path.name:
            references.append(ref)

    return list(set(references))


def categorize_file(file_path: Path, metadata: Dict) -> tuple[str, str, str]:
    """Categorize a file and provide recommendation"""
    rel_path = str(file_path.relative_to(REPO_ROOT))
    filename = file_path.name.upper()

    # Essential files
    if filename in ['README.MD', 'CLAUDE.MD', 'CONTRIBUTING.MD', 'LICENSE.MD']:
        return 'essential', 'KEEP', 'Core project documentation'

    # Design documents
    if '/design/' in rel_path or 'DESIGN' in filename:
        return 'design', 'KEEP', 'Design documentation'

    # Reference material
    if '/books/' in rel_path or '/papers/' in rel_path or '/references/' in rel_path:
        return 'reference', 'KEEP', 'Reference material'

    # Completed tasks
    if any(x in filename for x in ['COMPLETE', 'SUMMARY', 'PHASE', 'SESSION']):
        return 'completed_task', 'ARCHIVE', 'Completed task documentation'

    # Migration docs
    if 'MIGRATION' in filename:
        return 'completed_task', 'ARCHIVE', 'Migration documentation'

    # Plans that might be complete
    if 'PLAN' in filename and metadata['last_modified']:
        try:
            last_mod = datetime.fromisoformat(metadata['last_modified'])
            age_days = (datetime.now() - last_mod).days
            if age_days > 30:
                return 'outdated', 'REVIEW', 'Plan document, not recently updated'
        except Exception:
            pass

    # Check if orphaned (no references and no recent updates)
    if (not metadata.get('referenced_by_code') and
        not metadata.get('referenced_by_docs') and
        metadata['commit_count'] <= 2):
        return 'orphan', 'REVIEW', 'No references found, minimal activity'

    # Active documentation
    if metadata['last_modified']:
        try:
            last_mod = datetime.fromisoformat(metadata['last_modified'])
            age_days = (datetime.now() - last_mod).days
            if age_days <= 30:
                return 'active_docs', 'KEEP', 'Recently updated'
        except Exception:
            pass

    # Default to active docs
    return 'active_docs', 'KEEP', 'Active documentation'


def analyze_all_files():
    """Main analysis function"""
    import sys
    print(f"# Finding markdown files in {REPO_ROOT}...", file=sys.stderr)
    md_files = find_markdown_files()
    print(f"# Found {len(md_files)} markdown files", file=sys.stderr)

    inventory = {
        'analyzed_at': datetime.now().isoformat(),
        'total_files': len(md_files),
        'total_lines': 0,
        'total_words': 0,
        'files': []
    }

    for i, file_path in enumerate(md_files, 1):
        print(f"# Analyzing {i}/{len(md_files)}: {file_path.relative_to(REPO_ROOT)}", file=sys.stderr)

        # Get git metadata
        metadata = get_file_metadata(file_path)
        content = metadata.pop('content')

        # Find references
        refs = find_references_to_file(file_path, md_files)
        metadata.update(refs)

        # Extract what this file references
        references = extract_references_from_file(file_path, content)
        metadata['references'] = references

        # Categorize
        category, recommendation, notes = categorize_file(file_path, metadata)
        metadata['category'] = category
        metadata['recommendation'] = recommendation
        metadata['notes'] = notes

        # Add path
        metadata['path'] = str(file_path.relative_to(REPO_ROOT))

        # Update totals
        inventory['total_lines'] += metadata['lines']
        inventory['total_words'] += metadata['words']

        inventory['files'].append(metadata)

    # Output JSON
    print(json.dumps(inventory, indent=2))


if __name__ == '__main__':
    import sys
    analyze_all_files()
