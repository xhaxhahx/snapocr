# measure_coldstart.ps1 —— 冷启动到"启动 SnapOCR"日志行的时间
param([int]$Runs = 3, [string]$Exe = "$env:LocalAppData\Programs\SnapOCR\SnapOCR.exe")
$log = "$env:APPDATA\SnapOCR\logs\snapocr.log"
foreach ($i in 1..$Runs) {
    Get-Process SnapOCR -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800
    $before = (Get-Item $log).Length
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Start-Process $Exe
    while ($sw.Elapsed.TotalSeconds -lt 40) {
        Start-Sleep -Milliseconds 40
        try {
            $fs = [IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
            $fs.Seek($before, 'Begin') | Out-Null
            $sr = New-Object IO.StreamReader($fs)
            $tail = $sr.ReadToEnd()
            $sr.Close()
            if ($tail -match "SnapOCR v1") { break }
        } catch {}
    }
    "{0}: {1:N0} ms" -f $i, $sw.ElapsedMilliseconds
}
Get-Process SnapOCR -ErrorAction SilentlyContinue | Stop-Process -Force
"MEASURE_DONE"
