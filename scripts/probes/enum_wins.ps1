$src = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WE {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
  public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
'@
Add-Type -TypeDefinition $src
$target = [uint32]$args[0]
$cb = {
  param($h, $l)
  [uint32]$wpid = 0
  [WE]::GetWindowThreadProcessId($h, [ref]$wpid) | Out-Null
  if ($wpid -eq $target) {
    $sb = New-Object System.Text.StringBuilder 256
    [WE]::GetWindowText($h, $sb, 256) | Out-Null
    $r = New-Object WE+RECT
    [WE]::GetWindowRect($h, [ref]$r) | Out-Null
    Write-Host ("HWND={0} vis={1} title=[{2}] rect={3},{4},{5},{6}" -f $h, [WE]::IsWindowVisible($h), $sb.ToString(), $r.L, $r.T, $r.R, $r.B)
  }
  return $true
}
[WE]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
