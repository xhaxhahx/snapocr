param(
  [Parameter(Mandatory=$true)][string]$op,
  [int]$x = 0, [int]$y = 0,
  [int]$x2 = 0, [int]$y2 = 0,
  [string]$keys = ""
)
$src = @'
using System;
using System.Runtime.InteropServices;
public class MC {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte sc, uint f, UIntPtr e);
}
'@
Add-Type -TypeDefinition $src

switch ($op) {
  "click" {
    [MC]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 120
    [MC]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)  # left down
    [MC]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)  # left up
    Write-Host "click ($x,$y)"
  }
  "drag" {
    [MC]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 150
    [MC]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 120
    $steps = 25
    for ($i = 1; $i -le $steps; $i++) {
      $cx = $x + [int](($x2 - $x) * $i / $steps)
      $cy = $y + [int](($y2 - $y) * $i / $steps)
      [MC]::SetCursorPos($cx, $cy) | Out-Null
      Start-Sleep -Milliseconds 25
    }
    [MC]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Write-Host "drag ($x,$y) -> ($x2,$y2)"
  }
  "key" {
    # keys 形如 "Return" / "^{ESC}"——SendKeys 语法
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Write-Host "key: $keys"
  }
  default { Write-Host "unknown op: $op" }
}
