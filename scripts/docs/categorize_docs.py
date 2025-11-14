#!/usr/bin/env python3
# ABOUTME: Categorizes documentation files into groups for cleanup actions
# ABOUTME: Groups files by category and generates categorization report

import json
import sys
from collections import defaultdict
from datetime import datetime

def load_inventory(filepath: str) -> dict:
    """Load inventory JSON"""
    with open(filepath, 'r') as f:
        return json.load(f)

def refine_categorization(file_info: dict) -> str:
    """Refine the categorization based on additional analysis"""
    path = file_info['path']
    category = file_info['category']
    filename = path.split('/')[-1].upper()

    # Keep essential files as essential
    if category == 'essential':
        return 'essential'

    # Refine completed_task categorization
    if category == 'completed_task':
        # Phase summaries and session summaries should be archived
        if any(x in filename for x in ['PHASE', 'SESSION', 'SUMMARY', 'COMPLETE', 'MIGRATION']):
            return 'completed_task'

    # Refine design categorization
    if '/design/' in path or category == 'design':
        # Check if still active (referenced or recently updated)
        if file_info.get('referenced_by_code') or file_info.get('referenced_by_docs'):
            return 'design'
        # Check last modified
        if file_info['last_modified']:
            try:
                last_mod = datetime.fromisoformat(file_info['last_modified'])
                age_days = (datetime.now() - last_mod).days
                if age_days <= 60:  # Modified in last 2 months
                    return 'design'
                else:
                    return 'outdated'
            except Exception:
                pass

    # Refine active_docs categorization
    if category == 'active_docs':
        # Check for API/guide documentation patterns
        api_patterns = ['API', 'GUIDE', 'UNIFIED', 'GENERATOR', 'CALCULATOR', 'ESTIMATOR',
                       'ARCHITECTURE', 'FRAMEWORK', 'SPECS', 'ABSTRACTION']
        if any(pattern in filename for pattern in api_patterns):
            # Verify it has code references or recent updates
            has_refs = bool(file_info.get('referenced_by_code') or file_info.get('referenced_by_docs'))

            if file_info['last_modified']:
                try:
                    last_mod = datetime.fromisoformat(file_info['last_modified'])
                    age_days = (datetime.now() - last_mod).days
                    recently_updated = age_days <= 60
                except Exception:
                    recently_updated = False
            else:
                recently_updated = False

            if has_refs or recently_updated:
                return 'active_docs'
            else:
                return 'outdated'

        # Plans that are not completed
        if 'PLAN' in filename and 'COMPLETE' not in filename:
            # Check if implemented (look for corresponding code or completion doc)
            if file_info['last_modified']:
                try:
                    last_mod = datetime.fromisoformat(file_info['last_modified'])
                    age_days = (datetime.now() - last_mod).days
                    if age_days > 90:  # Plan is 3+ months old
                        return 'outdated'
                except Exception:
                    pass
            return 'active_docs'

    # Refine orphan categorization
    if category == 'orphan':
        # Some orphans might actually be useful standalone docs
        useful_orphans = ['CODEBASE_ANALYSIS', 'INSTALLATION', 'TODO', 'TRADER_REQUIREMENTS']
        if any(pattern in filename for pattern in useful_orphans):
            return 'active_docs'
        return 'orphan'

    # Reference materials
    if category == 'reference' or '/references/' in path:
        return 'reference'

    return category

def identify_redundant_docs(files: list) -> dict:
    """Identify potentially redundant documentation"""
    redundant_groups = {}

    # Group by topic keywords
    topic_groups = defaultdict(list)

    for file_info in files:
        path = file_info['path']
        filename = path.split('/')[-1].upper()

        # Extract topic keywords
        topics = []

        # Grinold-Kahn docs
        if 'GRINOLD' in filename or 'KAHN' in filename:
            topics.append('grinold_kahn')

        # Backtest docs
        if 'BACKTEST' in filename:
            topics.append('backtest')

        # Portfolio docs
        if 'PORTFOLIO' in filename:
            topics.append('portfolio')

        # Alpha/Signal docs
        if 'ALPHA' in filename or 'SIGNAL' in filename:
            topics.append('alpha_signal')

        # Risk/Covariance docs
        if 'RISK' in filename or 'COVARIANCE' in filename:
            topics.append('risk_covariance')

        # Data layer docs
        if 'DATA' in filename and 'LAYER' in filename:
            topics.append('data_layer')

        # Strategy/modularity docs
        if 'STRATEGY' in filename or 'MODULARITY' in filename:
            topics.append('strategy')

        # Add to groups
        for topic in topics:
            topic_groups[topic].append(file_info)

    # Identify groups with multiple docs that might be redundant
    for topic, group_files in topic_groups.items():
        if len(group_files) >= 3:  # 3+ docs on same topic
            redundant_groups[topic] = {
                'count': len(group_files),
                'files': [f['path'] for f in group_files],
                'total_lines': sum(f['lines'] for f in group_files)
            }

    return redundant_groups

def categorize_all():
    """Main categorization function"""
    inventory = load_inventory('/home/user/ARBS/docs/analysis/inventory_filtered.json')

    # Refine categorization
    categories = defaultdict(list)

    for file_info in inventory['files']:
        category = refine_categorization(file_info)
        file_info['refined_category'] = category
        categories[category].append(file_info['path'])

    # Identify redundant docs
    redundant_groups = identify_redundant_docs(inventory['files'])

    # Build output
    output = {
        'analyzed_at': datetime.now().isoformat(),
        'total_files': inventory['total_files'],
        'categories': dict(categories),
        'category_counts': {cat: len(files) for cat, files in categories.items()},
        'redundant_groups': redundant_groups
    }

    # Output JSON
    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    categorize_all()
