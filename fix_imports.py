import os
import re

# Mapping of file name to its new module path
module_map = {
    'config': 'placsp.config',
    'models': 'placsp.core.models',
    'codelists': 'placsp.core.codelists',
    'catalog': 'placsp.core.catalog',
    'weaviate_schema': 'placsp.storage.weaviate_schema',
    'upserter': 'placsp.storage.upserter',
    'graph_ops': 'placsp.storage.graph_ops',
    'graph_sink': 'placsp.storage.graph_sink',
    'pipeline': 'placsp.ingestion.pipeline',
    'fetcher': 'placsp.ingestion.fetcher',
    'pliego_pipeline': 'placsp.ingestion.pliego_pipeline',
    'atom_parser': 'placsp.parsers.atom_parser',
    'codice_extractor': 'placsp.parsers.codice_extractor',
    'renderer': 'placsp.parsers.renderer',
    'pliego_html_parser': 'placsp.parsers.pliego_html_parser',
    'embedder': 'placsp.ai.embedder',
    'extractor': 'placsp.ai.extractor',
    'pliego_extractor': 'placsp.ai.extractor' # old name map just in case
}

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Regex to find `from .X import Y` or `from . import X`
    # We want to replace `.X` with `placsp.module.X`
    
    def replacer(match):
        module = match.group(1)
        if module in module_map:
            return f"from {module_map[module]} import"
        print(f"Warning: Unknown module {module} in {filepath}")
        return match.group(0)

    # replace `from .models import X` -> `from placsp.core.models import X`
    new_content = re.sub(r'from\s+\.(\w+)\s+import', replacer, content)

    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Fixed {filepath}")

for root, _, files in os.walk('src/placsp'):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))

# Also fix the script process_pliego.py
script_path = 'scripts/process_pliego.py'
with open(script_path, 'r') as f:
    s_content = f.read()
# Re-map script imports:
# from placsp.pliego_html_parser -> placsp.parsers.pliego_html_parser
for old, new in module_map.items():
    s_content = re.sub(rf'from placsp\.{old} import', f'from {new} import', s_content)

with open(script_path, 'w') as f:
    f.write(s_content)
print(f"Fixed {script_path}")
