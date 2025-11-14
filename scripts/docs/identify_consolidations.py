#!/usr/bin/env python3
# ABOUTME: Identifies consolidation opportunities from categorized documentation
# ABOUTME: Proposes specific merge plans for redundant documentation groups

import json
import sys
from typing import List, Dict

def load_data():
    """Load inventory and categorization data"""
    with open('/home/user/ARBS/docs/analysis/inventory_filtered.json', 'r') as f:
        inventory = json.load(f)

    with open('/home/user/ARBS/docs/analysis/categorization.json', 'r') as f:
        categorization = json.load(f)

    return inventory, categorization

def create_consolidation_plan(topic: str, files: List[str], inventory: dict) -> Dict:
    """Create a consolidation plan for a redundant group"""

    # Get file details from inventory
    file_details = {}
    for file_info in inventory['files']:
        if file_info['path'] in files:
            file_details[file_info['path']] = file_info

    # Determine which files to keep vs consolidate
    plan = {
        'topic': topic,
        'total_files': len(files),
        'total_lines': sum(file_details[f]['lines'] for f in files if f in file_details),
        'files': []
    }

    # Categorize each file
    for filepath in files:
        if filepath not in file_details:
            continue

        details = file_details[filepath]
        filename = filepath.split('/')[-1]

        # Determine action
        action = 'CONSOLIDATE'
        target = None
        reason = ''

        # Keep files with specific patterns
        if 'UNIFIED_API' in filename or 'USER_GUIDE' in filename:
            action = 'KEEP'
            target = None
            reason = 'Primary API/guide documentation'

        # Archive completed items
        elif any(x in filename for x in ['COMPLETE', 'SUMMARY', 'PROGRESS', 'PLAN.md']):
            if 'COMPLETE' in filename or 'SUMMARY' in filename:
                action = 'ARCHIVE'
                reason = 'Completed task documentation'
            elif 'PROGRESS' in filename:
                action = 'ARCHIVE'
                reason = 'Progress tracking document'
            elif 'PLAN' in filename and details['category'] == 'completed_task':
                action = 'ARCHIVE'
                reason = 'Completed plan document'

        # Keep essential design docs
        elif '/design/' in filepath:
            action = 'KEEP'
            reason = 'Design documentation'

        # Keep reference materials
        elif '/references/' in filepath:
            action = 'KEEP'
            reason = 'Reference material'

        # Consolidate duplicates
        else:
            if details.get('referenced_by_code') or details.get('referenced_by_docs'):
                action = 'REVIEW'
                reason = 'Has references - needs agent review'
            else:
                action = 'CONSOLIDATE'
                reason = 'No references - candidate for consolidation'

        plan['files'].append({
            'path': filepath,
            'lines': details['lines'],
            'last_modified': details['last_modified'],
            'has_code_refs': bool(details.get('referenced_by_code')),
            'has_doc_refs': bool(details.get('referenced_by_docs')),
            'action': action,
            'reason': reason
        })

    return plan

def propose_consolidation_targets(topic: str, plan: Dict) -> Dict:
    """Propose consolidation targets for a topic"""

    keep_files = [f for f in plan['files'] if f['action'] == 'KEEP']
    consolidate_files = [f for f in plan['files'] if f['action'] == 'CONSOLIDATE']
    archive_files = [f for f in plan['files'] if f['action'] == 'ARCHIVE']
    review_files = [f for f in plan['files'] if f['action'] == 'REVIEW']

    # Determine consolidation strategy based on topic
    consolidation_targets = {
        'grinold_kahn': {
            'primary': 'docs/GRINOLD_KAHN_FRAMEWORK.md',
            'description': 'Grinold-Kahn framework documentation',
            'keep': ['docs/GRINOLD_KAHN_FRAMEWORK.md',
                    'docs/GRINOLD_KAHN_DETAILED_SPECS.md',
                    'docs/GRINOLD_KAHN_IMPLEMENTATION_GAP_ANALYSIS.md'],
            'consolidate_into_primary': [],
            'keep_separate': ['docs/design/GRINOLD_KAHN_KNOWLEDGE_GRAPH.md',
                             'docs/references/Grinold-Kahn-Active-Portfolio-Management.md'],
            'archive': []
        },
        'backtest': {
            'primary': 'docs/BACKTEST_UNIFIED_API.md',
            'description': 'Unified backtest API documentation',
            'keep': ['docs/BACKTEST_UNIFIED_API.md'],
            'consolidate_into_primary': [],
            'keep_separate': ['docs/design/BACKTEST_UNIFICATION_PLAN.md'],
            'archive': ['BACKTEST_UNIFICATION_TASK.md',
                       'docs/BACKTESTING_FUTURES_SWAPS_PLAN.md',
                       'docs/GENERIC_BACKTEST_IMPLEMENTATION_PLAN.md',
                       'docs/GENERIC_BACKTEST_MIGRATION_PLAN.md',
                       'docs/GENERIC_BACKTEST_PROGRESS.md']
        },
        'strategy': {
            'primary': 'docs/USER_GUIDE_STRATEGY_CREATION.md',
            'description': 'Strategy creation user guide',
            'keep': ['docs/USER_GUIDE_STRATEGY_CREATION.md'],
            'consolidate_into_primary': [],
            'keep_separate': ['docs/STRATEGY_MODULARIZATION_DESIGN.md',
                             'docs/design/LONG_SHORT_STRATEGY_DESIGN.md'],
            'archive': ['docs/MODULARITY_IMPROVEMENTS_PLAN.md',
                       'docs/MODULARITY_REVIEW_AND_STRATEGY_TYPES.md',
                       'docs/STRATEGY_MODULARIZATION_SUMMARY.md',
                       'docs/STRATEGY_NOTEBOOKS_SUMMARY.md']
        },
        'risk_covariance': {
            'primary': 'docs/architecture/risk-covariance.md',
            'description': 'Risk and covariance estimation guide',
            'keep': ['docs/references/COVARIANCE_ESTIMATION_REFERENCE.md',
                    'docs/guides/extending_risk_models.md'],
            'consolidate_into_primary': ['docs/SECTOR_COVARIANCE_GUIDE.md',
                                        'docs/research/current_arbs_covariance_usage.md'],
            'keep_separate': ['docs/research/COVARIANCE_METHODS_FOR_FIXED_INCOME.md',
                             'docs/research/high_correlation_covariance.md',
                             'docs/research/practitioner_covariance_methods.md'],
            'archive': ['docs/research/SECTOR_COVARIANCE_PLAN.md']
        },
        'data_layer': {
            'primary': 'docs/DATA_LAYER_ARCHITECTURE.md',
            'description': 'Data layer architecture documentation',
            'keep': ['docs/DATA_LAYER_ARCHITECTURE.md'],
            'consolidate_into_primary': ['docs/CODEBASE_ASSESSMENT_DATA_LAYER.md'],
            'keep_separate': [],
            'archive': ['docs/ACTION_PLAN_DATA_LAYER.md',
                       'docs/ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md']
        },
        'alpha_signal': {
            'primary': 'docs/ALPHA_GENERATOR.md',
            'description': 'Alpha generation and signal documentation',
            'keep': ['docs/ALPHA_GENERATOR.md', 'docs/SIGNAL_COMBINATION_METHODS.md'],
            'consolidate_into_primary': [],
            'keep_separate': [],
            'archive': ['docs/ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md',
                       'docs/ALPHAVANTAGE_INTEGRATION_SPEC.md']
        },
        'portfolio': {
            'primary': 'docs/COMPOSABLE_PORTFOLIO_ARCHITECTURE.md',
            'description': 'Portfolio architecture documentation',
            'keep': ['docs/COMPOSABLE_PORTFOLIO_ARCHITECTURE.md'],
            'consolidate_into_primary': [],
            'keep_separate': ['docs/references/Grinold-Kahn-Active-Portfolio-Management.md',
                             'docs/resources/PORTFOLIO_MANAGEMENT_RESEARCH.md'],
            'archive': []
        }
    }

    target_plan = consolidation_targets.get(topic, {
        'primary': f'docs/architecture/{topic}.md',
        'description': f'{topic.replace("_", " ").title()} documentation',
        'keep': [f['path'] for f in keep_files],
        'consolidate_into_primary': [f['path'] for f in consolidate_files],
        'keep_separate': [],
        'archive': [f['path'] for f in archive_files]
    })

    target_plan['review_required'] = [f['path'] for f in review_files]

    return target_plan

def main():
    """Main consolidation identification"""
    inventory, categorization = load_data()

    redundant_groups = categorization['redundant_groups']

    consolidation_plan = {
        'total_redundant_groups': len(redundant_groups),
        'groups': {}
    }

    for topic, group_info in redundant_groups.items():
        # Create initial plan
        plan = create_consolidation_plan(topic, group_info['files'], inventory)

        # Propose consolidation targets
        targets = propose_consolidation_targets(topic, plan)

        consolidation_plan['groups'][topic] = {
            'files': plan['files'],
            'total_lines': plan['total_lines'],
            'consolidation_target': targets
        }

    # Add orphan recommendations
    orphans = categorization['categories']['orphan']
    orphan_details = []
    for file_info in inventory['files']:
        if file_info['path'] in orphans:
            orphan_details.append({
                'path': file_info['path'],
                'lines': file_info['lines'],
                'last_modified': file_info['last_modified'],
                'recommendation': 'REVIEW' if file_info['lines'] > 200 else 'DELETE'
            })

    consolidation_plan['orphans'] = {
        'total': len(orphans),
        'files': orphan_details
    }

    # Add completed task recommendations
    completed = categorization['categories']['completed_task']
    consolidation_plan['completed_tasks'] = {
        'total': len(completed),
        'files': completed,
        'recommendation': 'ARCHIVE to docs/archive/phase-summaries/ and docs/archive/migrations/'
    }

    print(json.dumps(consolidation_plan, indent=2))

if __name__ == '__main__':
    main()
