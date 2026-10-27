import json, sys, pathlib, glob
sid = sys.argv[1]
files = glob.glob(str(pathlib.Path.home()/'.claude/projects/*'/f'{sid}.jsonl'))
seen = {}; tools = 0
for f in files:
    for line in open(f, encoding='utf-8'):
        try: d = json.loads(line)
        except ValueError: continue
        m = d.get('message') or {}
        if d.get('type') == 'assistant' and m.get('usage'):
            seen[m.get('id') or len(seen)] = m['usage']
            tools += sum(1 for c in m.get('content') or [] if isinstance(c, dict) and c.get('type') == 'tool_use')
tot = {k: sum(u.get(k, 0) or 0 for u in seen.values()) for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens','output_tokens')}
tot['calls'] = len(seen); tot['tool_uses'] = tools; tot['files'] = len(files)
print(json.dumps(tot))
