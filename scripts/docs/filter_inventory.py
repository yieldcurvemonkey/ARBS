#!/usr/bin/env python3
# ABOUTME: Filters inventory.json to exclude .claude, books, and papers directories
# ABOUTME: Prepares focused list of project documentation for agent analysis

import json
import sys

def filter_inventory(input_file: str, output_file: str):
    """Filter inventory to focus on project docs"""
    with open(input_file, 'r') as f:
        data = json.load(f)

    # Exclude patterns
    exclude_patterns = [
        '.claude/',
        'docs/books/',
        'docs/papers/',
        'docs/references/papers/'
    ]

    filtered_files = []
    for file_info in data['files']:
        path = file_info['path']

        # Skip if matches exclude pattern
        if any(pattern in path for pattern in exclude_patterns):
            continue

        filtered_files.append(file_info)

    # Update data
    data['files'] = filtered_files
    data['total_files'] = len(filtered_files)
    data['total_lines'] = sum(f['lines'] for f in filtered_files)
    data['total_words'] = sum(f['words'] for f in filtered_files)
    data['filter_note'] = 'Excluded .claude/, docs/books/, docs/papers/, docs/references/papers/'

    # Write output
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Filtered {len(data['files'])} project documentation files")
    print(f"Total lines: {data['total_lines']}")
    print(f"Total words: {data['total_words']}")

if __name__ == '__main__':
    filter_inventory(
        '/home/user/ARBS/docs/analysis/inventory.json',
        '/home/user/ARBS/docs/analysis/inventory_filtered.json'
    )
