# measure_onefile.ps1
param([int]$Runs = 3, [string]$Exe = "C:\snapocr_build\dist\SnapOCR-single.exe")
$log = "$env:APPDATA\SnapOCR\logs\snapocr.log"
foreach ($i in 1..$Runs) {
    Get-Process SnapOCR-single -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800
    $before = (Get-Item $log).Length
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Start-Process $Exe
    while ($sw.Elapsed.TotalSeconds -lt 120) {
        Start-Sleep -Milliseconds 60
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
Get-Process SnapOCR-single -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
$mei = Get-ChildItem $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue
"MEI_LEFT: $($mei.Count)"
"MEASURE_DONE"
