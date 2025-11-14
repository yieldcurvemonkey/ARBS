#!/usr/bin/env python3
# ABOUTME: Generates agent task descriptions for deep documentation analysis
# ABOUTME: Creates parallel task batches for analyzing documentation relevance

import json
import sys
from pathlib import Path

def generate_agent_tasks(filtered_inventory_file: str, batch_size: int = 10):
    """Generate batches of files for agent analysis"""
    with open(filtered_inventory_file, 'r') as f:
        data = json.load(f)

    files = data['files']

    # Group by category for better batching
    categories = {}
    for file_info in files:
        cat = file_info['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(file_info)

    print("# Documentation Analysis Task Batches\n")
    print(f"Total files: {len(files)}")
    print(f"Categories: {list(categories.keys())}\n")

    # Print category summaries
    for cat, cat_files in categories.items():
        print(f"\n## Category: {cat} ({len(cat_files)} files)")
        print(f"- Lines: {sum(f['lines'] for f in cat_files)}")
        print(f"- Files:")
        for f in cat_files[:10]:  # Show first 10
            print(f"  - {f['path']} ({f['lines']} lines, {f['recommendation']})")
        if len(cat_files) > 10:
            print(f"  - ... and {len(cat_files) - 10} more")

    # Generate task list for agent analysis
    print("\n\n# Agent Analysis Tasks\n")

    # Prioritize by category
    priority_order = ['essential', 'active_docs', 'design', 'completed_task', 'outdated', 'orphan']

    task_num = 1
    for cat in priority_order:
        if cat not in categories:
            continue

        cat_files = categories[cat]

        # Batch files
        for i in range(0, len(cat_files), batch_size):
            batch = cat_files[i:i+batch_size]

            print(f"## Task {task_num}: Analyze {cat} documentation ({len(batch)} files)")
            print(f"\nFiles to analyze:")
            for f in batch:
                print(f"- {f['path']}")

            print(f"\nAgent Prompt:")
            print(f"```")
            print(f"Analyze these {cat} documentation files:")
            print(f"")
            for f in batch:
                print(f"- {f['path']}")
            print(f"")
            print(f"For each file:")
            print(f"1. Read the documentation")
            print(f"2. Identify any code references (file paths, classes, functions)")
            print(f"3. Read the referenced code")
            print(f"4. Verify documentation accuracy against current code")
            print(f"5. Assess relevance (essential/useful/outdated/redundant)")
            print(f"6. Recommend action (KEEP/UPDATE/CONSOLIDATE/ARCHIVE/DELETE)")
            print(f"")
            print(f"Output a JSON report with:")
            print(f"{{")
            print(f'  "file": "path/to/file.md",')
            print(f'  "code_references": ["file.py:123", "class.py:Class"],')
            print(f'  "code_exists": true/false,')
            print(f'  "accurate": true/false,')
            print(f'  "relevance": "essential/useful/outdated/redundant",')
            print(f'  "recommendation": "KEEP/UPDATE/CONSOLIDATE/ARCHIVE/DELETE",')
            print(f'  "notes": "Explanation of assessment"')
            print(f"}}")
            print(f"```")
            print(f"\n---\n")

            task_num += 1

if __name__ == '__main__':
    generate_agent_tasks('/home/user/ARBS/docs/analysis/inventory_filtered.json')
