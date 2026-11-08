from plugins.platforms.a2a.outbound import Store
from pathlib import Path
import json, sys
s=Store(Path(sys.argv[1])); r=s.load(sys.argv[2])
def shape(x, depth=0):
    if depth>3: return type(x).__name__
    if isinstance(x,dict): return {k:shape(v,depth+1) for k,v in x.items()}
    if isinstance(x,list): return [shape(v,depth+1) for v in x[:2]]
    return type(x).__name__
print(json.dumps([shape(e) for e in r['events']],ensure_ascii=False))
