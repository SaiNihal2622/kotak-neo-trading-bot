import json
d = json.load(open('data_cache/system_audit.json'))
print('overall:', d.get('overall'))
print('subsystems:')
for k, v in d.get('subsystems', {}).items():
    details = (v.get('details') or '')[:120]
    print(f'  {k}: {v.get("status")} - {details}')
