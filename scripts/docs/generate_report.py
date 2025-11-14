#!/usr/bin/env python3
# ABOUTME: Generates human-readable analysis report from JSON data
# ABOUTME: Consolidates inventory, categorization, and consolidation plan into summary

import json
import sys

def load_all_data():
    """Load all analysis data"""
    with open('/home/user/ARBS/docs/analysis/inventory_filtered.json', 'r') as f:
        inventory = json.load(f)

    with open('/home/user/ARBS/docs/analysis/categorization.json', 'r') as f:
        categorization = json.load(f)

    with open('/home/user/ARBS/docs/analysis/consolidation-plan.json', 'r') as f:
        consolidation = json.load(f)

    return inventory, categorization, consolidation

def main():
    inventory, categorization, consolidation = load_all_data()

    print("# Documentation Cleanup Analysis Report")
    print(f"\nGenerated: {inventory['analyzed_at']}")
    print(f"\n## Executive Summary")
    print(f"\n- **Total markdown files analyzed**: 233 (entire repository)")
    print(f"- **Project documentation files**: {inventory['total_files']} (excluding .claude/, books/, papers/)")
    print(f"- **Total lines**: {inventory['total_lines']:,}")
    print(f"- **Total words**: {inventory['total_words']:,}")
    print(f"- **Redundant topic groups**: {consolidation['total_redundant_groups']}")

    print(f"\n## Category Breakdown\n")
    for category, count in sorted(categorization['category_counts'].items(), key=lambda x: -x[1]):
        files = categorization['categories'][category]
        total_lines = sum(
            f['lines'] for f in inventory['files'] if f['path'] in files
        )
        print(f"- **{category}**: {count} files ({total_lines:,} lines)")

    print(f"\n## Redundant Documentation Groups\n")
    print(f"Found {len(categorization['redundant_groups'])} topic groups with 3+ documents:\n")

    for topic, info in sorted(categorization['redundant_groups'].items(),
                             key=lambda x: -x[1]['total_lines']):
        print(f"### {topic.replace('_', ' ').title()}")
        print(f"- Files: {info['count']}")
        print(f"- Total lines: {info['total_lines']:,}")

        if topic in consolidation['groups']:
            target = consolidation['groups'][topic]['consolidation_target']
            print(f"- **Primary**: {target['primary']}")
            print(f"- **Keep**: {len(target['keep'])} files")
            print(f"- **Archive**: {len(target['archive'])} files")
            if target.get('review_required'):
                print(f"- **Review required**: {len(target['review_required'])} files")

        print()

    print(f"## Orphaned Documentation\n")
    print(f"Found {consolidation['orphans']['total']} orphaned files (no references, minimal activity):\n")

    for orphan in sorted(consolidation['orphans']['files'], key=lambda x: -x['lines'])[:15]:
        print(f"- `{orphan['path']}` ({orphan['lines']} lines) - {orphan['recommendation']}")

    if consolidation['orphans']['total'] > 15:
        print(f"- ... and {consolidation['orphans']['total'] - 15} more")

    print(f"\n## Completed Tasks to Archive\n")
    print(f"Found {consolidation['completed_tasks']['total']} completed task documents:\n")
    for doc in consolidation['completed_tasks']['files'][:10]:
        print(f"- `{doc}`")

    if consolidation['completed_tasks']['total'] > 10:
        print(f"- ... and {consolidation['completed_tasks']['total'] - 10} more")

    print(f"\n{consolidation['completed_tasks']['recommendation']}\n")

    print(f"\n## Recommended Actions\n")
    print(f"### Phase 1: Archive Completed Tasks")
    print(f"- Move {consolidation['completed_tasks']['total']} completed task docs to `docs/archive/`")
    print(f"- Create CHANGELOG.md from phase summaries")

    print(f"\n### Phase 2: Consolidate Redundant Groups")
    for topic in consolidation['groups']:
        target = consolidation['groups'][topic]['consolidation_target']
        archive_count = len(target['archive'])
        if archive_count > 0:
            print(f"- **{topic}**: Archive {archive_count} docs, keep primary `{target['primary']}`")

    print(f"\n### Phase 3: Agent Review")
    total_review = sum(
        len(consolidation['groups'][topic]['consolidation_target'].get('review_required', []))
        for topic in consolidation['groups']
    )
    print(f"- Deep review of {total_review} docs with references")
    print(f"- Deep review of {consolidation['orphans']['total']} orphaned docs")
    print(f"- Total: ~{total_review + consolidation['orphans']['total']} docs requiring agent analysis")

    print(f"\n### Phase 4: Create New Structure")
    print(f"- Implement `docs/INDEX.md` central index")
    print(f"- Create architecture/, user-guides/, api-reference/ directories")
    print(f"- Implement auto-generation tools for diagrams and API docs")

    print(f"\n## Next Steps\n")
    print(f"1. Review this report")
    print(f"2. Launch agent batches (sets of 10) for deep analysis of:")
    print(f"   - {total_review} docs requiring reference verification")
    print(f"   - {consolidation['orphans']['total']} orphaned docs")
    print(f"3. Execute consolidation plan")
    print(f"4. Implement auto-generation infrastructure")

if __name__ == '__main__':
    main()
