#!/usr/bin/env python3
# ABOUTME: Validates consolidation plan against README.md references
# ABOUTME: Ensures docs referenced in README are not marked for archival

import json
import re

def load_consolidation_plan():
    """Load consolidation plan"""
    with open('/home/user/ARBS/docs/analysis/consolidation-plan.json', 'r') as f:
        return json.load(f)

def extract_readme_references():
    """Extract doc references from README.md"""
    with open('/home/user/ARBS/README.md', 'r') as f:
        content = f.read()

    # Find all .md references
    md_pattern = r'`([A-Z_]+\.md)`'
    refs = re.findall(md_pattern, content)

    # Also find relative paths
    path_pattern = r'\((docs/[^)]+\.md)\)'
    path_refs = re.findall(path_pattern, content)

    return set(refs), set(path_refs)

def validate_plan():
    """Validate consolidation plan against README references"""
    plan = load_consolidation_plan()
    md_refs, path_refs = extract_readme_references()

    print("# Consolidation Plan Validation\n")
    print(f"## README.md References")
    print(f"- Root-level docs: {len(md_refs)}")
    print(f"- Path docs: {len(path_refs)}")
    print()

    errors = []

    # Check each redundant group
    for topic, group_data in plan['groups'].items():
        target = group_data['consolidation_target']

        # Check archive list
        for doc in target['archive']:
            filename = doc.split('/')[-1]

            # Check if in README references
            if filename in md_refs or doc in path_refs:
                errors.append({
                    'doc': doc,
                    'issue': f'Marked for ARCHIVE but referenced in README.md',
                    'topic': topic
                })

        # Check consolidate_into_primary list
        for doc in target['consolidate_into_primary']:
            filename = doc.split('/')[-1]

            if filename in md_refs or doc in path_refs:
                errors.append({
                    'doc': doc,
                    'issue': f'Marked for CONSOLIDATE but referenced in README.md',
                    'topic': topic
                })

    # Report errors
    if errors:
        print(f"## ❌ Validation Errors: {len(errors)}\n")
        for err in errors:
            print(f"### {err['doc']}")
            print(f"- **Topic**: {err['topic']}")
            print(f"- **Issue**: {err['issue']}")
            print()

        print("## Recommended Fixes\n")
        for err in errors:
            print(f"- Move `{err['doc']}` from ARCHIVE/CONSOLIDATE to KEEP in `{err['topic']}` group")

    else:
        print("## ✅ No validation errors found\n")

    # List all README-referenced docs
    print(f"## All README.md Referenced Docs\n")
    print("Root-level:")
    for ref in sorted(md_refs):
        print(f"- {ref}")

    print("\nDocs/ paths:")
    for ref in sorted(path_refs):
        print(f"- {ref}")

if __name__ == '__main__':
    validate_plan()
