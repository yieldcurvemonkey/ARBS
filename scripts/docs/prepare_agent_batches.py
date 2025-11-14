#!/usr/bin/env python3
# ABOUTME: Prepares agent batch definitions for deep documentation analysis
# ABOUTME: Organizes 37 docs into 4 batches of ~10 docs each

import json
from typing import List, Dict

def load_data():
    """Load consolidation plan and inventory"""
    with open('/home/user/ARBS/docs/analysis/consolidation-plan.json', 'r') as f:
        consolidation = json.load(f)

    with open('/home/user/ARBS/docs/analysis/inventory_filtered.json', 'r') as f:
        inventory = json.load(f)

    return consolidation, inventory

def extract_review_required_docs(consolidation: dict) -> List[str]:
    """Extract all docs marked for review"""
    review_docs = []

    for topic, group_data in consolidation['groups'].items():
        target = group_data['consolidation_target']
        if 'review_required' in target:
            review_docs.extend(target['review_required'])

    return list(set(review_docs))

def extract_orphaned_docs(consolidation: dict) -> List[Dict]:
    """Extract orphaned docs"""
    return consolidation['orphans']['files']

def organize_batches():
    """Organize docs into batches"""
    consolidation, inventory = load_data()

    # Get docs requiring review
    review_docs = extract_review_required_docs(consolidation)
    orphaned_docs = extract_orphaned_docs(consolidation)

    print(f"# Agent Batch Organization\n")
    print(f"Total docs for agent analysis: {len(review_docs) + len(orphaned_docs)}")
    print(f"- Docs with references (review): {len(review_docs)}")
    print(f"- Orphaned docs: {len(orphaned_docs)}\n")

    # Batch 1: Review docs (risk/covariance + grinold-kahn)
    batch1 = review_docs[:10]

    # Batch 2: Remaining review docs
    batch2 = review_docs[10:]

    # Batch 3: Large orphaned docs (>400 lines)
    large_orphans = [d for d in orphaned_docs if d['lines'] > 400]
    batch3 = [d['path'] for d in large_orphans[:10]]

    # Batch 4: Remaining orphaned docs
    remaining_orphans = [d for d in orphaned_docs if d['lines'] <= 400 or d not in large_orphans[:10]]
    batch4 = [d['path'] for d in remaining_orphans]

    batches = {
        'batch1_referenced_docs': {
            'description': 'Risk/Covariance + Grinold-Kahn docs with code references',
            'count': len(batch1),
            'docs': batch1
        },
        'batch2_referenced_docs': {
            'description': 'Remaining docs with references',
            'count': len(batch2),
            'docs': batch2
        },
        'batch3_large_orphans': {
            'description': 'Large orphaned docs (>400 lines)',
            'count': len(batch3),
            'docs': batch3
        },
        'batch4_small_orphans': {
            'description': 'Remaining orphaned docs',
            'count': len(batch4),
            'docs': batch4
        }
    }

    # Print batches
    for batch_name, batch_data in batches.items():
        print(f"## {batch_name}")
        print(f"**Description**: {batch_data['description']}")
        print(f"**Count**: {batch_data['count']} docs\n")
        print("**Files:**")
        for doc in batch_data['docs']:
            print(f"- {doc}")
        print()

    # Save to JSON
    with open('/home/user/ARBS/docs/analysis/agent_batches.json', 'w') as f:
        json.dump(batches, f, indent=2)

    print(f"\n✅ Batches saved to docs/analysis/agent_batches.json")

if __name__ == '__main__':
    organize_batches()
