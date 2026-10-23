with open('Logs/bot_stderr.log', 'rb') as f:
    f.seek(-300000, 2)
    text = f.read().decode('utf-8', errors='replace')
lines = text.split('\n')
for line in lines[-50:]:
    try:
        print(line[:200])
    except UnicodeEncodeError:
        print(line[:200].encode('ascii', 'replace').decode('ascii'))