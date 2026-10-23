import subprocess
ps = (
    'foreach ($t in (Get-ScheduledTask | Where-Object { $_.State -eq "Ready" -and ($_.TaskName -match "Heart|Wake|kotak|popup|nssm|supervisor") })) '
    '{ '
    '  $r = $t.Repetition; '
    '  $ri = "once"; '
    '  if ($r -and $r.Interval -ne [TimeSpan]::Zero) { $ri = $r.Interval.ToString() }; '
    '  Write-Output ("{0,-40} | int={1}" -f $t.TaskName, $ri) '
    '}'
)
r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', ps], capture_output=True, text=True, timeout=15)
print(r.stdout)
