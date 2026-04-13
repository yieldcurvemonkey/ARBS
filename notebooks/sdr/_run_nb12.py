"""Run NB12 FOMCAnalyzer notebook as script."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nest_asyncio; nest_asyncio.apply()
import matplotlib; matplotlib.use('Agg')

with open(os.path.join(os.path.dirname(__file__), '12_fomc_analyzer.ipynb'), encoding='utf-8') as f:
    nb = json.load(f)

lines = []
for c in nb['cells']:
    if c['cell_type'] == 'code':
        src = ''.join(c['source']).replace('display(', 'print(')
        lines.append(src)
        lines.append('')

script = '\n'.join(lines)
exec(compile(script, '12_fomc_analyzer.ipynb', 'exec'))
