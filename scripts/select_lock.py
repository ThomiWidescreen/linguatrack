"""Select source IDs into a new portable lock; preserves every source assertion."""
import argparse
import json
import os
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('input',type=Path)
p.add_argument('output',type=Path)
p.add_argument('sources',nargs='+')
a=p.parse_args()
if a.output.exists():
    p.error('Output lock already exists')
lock=json.loads(a.input.read_text())
items=[i.copy() for i in lock['inputs'] if i['source'] in a.sources]
if {i['source'] for i in items} != set(a.sources):
    p.error('Unknown source selection')
for i in items:
    i['path']=os.path.relpath((a.input.parent/i['path']).resolve(),a.output.parent.resolve())
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'version':1,'inputs':items},indent=2)+'\n')
