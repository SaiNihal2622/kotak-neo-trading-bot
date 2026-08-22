$ErrorActionPreference = 'Stop'
$water = 42066
$log = Get-Item 'logs\bot_stderr.log'
$content = Get-Content $log.FullName
$newCount = 0
$last3 = @()
$i = 0
foreach ($line in $content) {
  $i++
  if ($line -match 'Traceback|FATAL|Killed|Exception') {
    if ($i -gt $water) {
      $newCount++
      if ($last3.Count -lt 3) {
        $last3 += ("L{0}: {1}" -f $i, $line)
      }
    }
  }
}
Write-Output "new_since_watermark_${water} = $newCount"
foreach ($l in $last3) { Write-Output $l }
$lastLine = ($content | Select-Object -Last 1)
Write-Output "LAST_LOG_LINE: $lastLine"
Write-Output "total_lines: $i"
