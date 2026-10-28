$src = @'
using System;
using System.Runtime.InteropServices;
public class B {
  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr w, string l, uint flags, uint timeout, out IntPtr result);
}
'@
Add-Type -TypeDefinition $src
# HWND_BROADCAST = 0xFFFF
$r = [IntPtr]::Zero
[B]::SendMessageTimeout([IntPtr]0xFFFF, 0x001A, [IntPtr]::Zero, "ImmersiveColorSet", 2, 2000, [ref]$r) | Out-Null
Write-Host "WM_SETTINGCHANGE(ImmersiveColorSet) broadcast sent"
