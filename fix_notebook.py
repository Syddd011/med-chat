import json
import os

path = r'c:\projectt\med-chat\research\trials.ipynb'
with open(path, 'r', encoding='utf-8') as f:
    notebook = json.load(f)

changed = False
for cell in notebook.get('cells', []):
    if cell.get('cell_type') == 'code':
        source = cell.get('source', [])
        new_source = []
        skip_next = False
        for i in range(len(source)):
            if skip_next:
                skip_next = False
                continue
            line = source[i]
            
            # Simple heuristic to fix the split lines
            if 'Directo' in line and i + 1 < len(source) and 'ryLoader' in source[i+1]:
                # Merge them
                new_line = line.replace('Directo\n', 'DirectoryLoader\n').replace('Directo', 'DirectoryLoader')
                new_source.append(new_line)
                skip_next = True
                changed = True
            else:
                new_source.append(line)
        cell['source'] = new_source

if changed:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)
    print("Fixed the notebook!")
else:
    print("No changes made.")
