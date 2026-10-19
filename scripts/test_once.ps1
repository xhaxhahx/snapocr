# test_once.ps1 - once-mode E2E: launch -> overlay -> send ESC -> process must exit
param([string]$Py = "C:\snapocr_build\.venv\Scripts\python.exe",
      [string]$Dir = "C:\snapocr_build")
Get-Process python, SnapOCR, SnapOCR-single -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Start-Process $Py -ArgumentList '-X', 'utf8', 'src\run.py', '--once', '--capture' `
    -WorkingDirectory $Dir -WindowStyle Hidden
Start-Sleep 4
$p = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Py }
if (-not $p) { Write-Host "FAIL_NO_PROCESS"; exit 1 }
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
Start-Sleep 3
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Py }
if ($alive) { Write-Host "FAIL_STILL_ALIVE"; $alive | Stop-Process -Force; exit 1 }
Write-Host "ONCE_MODE_PASS"
