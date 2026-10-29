Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$out = "C:\Users\Vm\AppData\Local\Temp\snapocr_screen.png"
$b.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose()
Write-Host "saved: $out"
