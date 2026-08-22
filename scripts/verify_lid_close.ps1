# scripts/verify_lid_close.ps1
# Verifies that lid close, power button, and sleep button are all set to
# "Do nothing" on the current power scheme. Run as Administrator.
#
# Background: Microsoft docs give the LIDACTION GUID as
# 5ca83367-6e02-4682-a5a4-5d69c1f1f4ec, but on Windows 11 (Acer Insyde
# BIOS at least) the actual current GUID is
# 5ca83367-6e45-459f-a27b-476b1d01c936. Querying the registry under
# HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerSettings\4f971e89-...
# reveals the real GUIDs.
param([switch]$Apply)
$ErrorActionPreference = 'Stop'

$SCHEME = [Guid]'8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'  # High performance
$SUB_BUTTONS = [Guid]'4f971e89-eebd-4455-a8de-9e59040e7347'
$LIDACTION = [Guid]'5ca83367-6e45-459f-a27b-476b1d01c936'
$POWERBUTTON = [Guid]'7648efa3-dd9c-4e3e-b566-50f929386280'
$SLEEPBUTTON = [Guid]'96996bc0-ad50-47ec-923b-6f41874dd9eb'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class PC {
    [DllImport("powrprof.dll", SetLastError = true)]
    public static extern uint PowerReadACValueIndex(
        IntPtr RootPowerKey,
        [MarshalAs(UnmanagedType.LPStruct)] Guid SchemeGuid,
        [MarshalAs(UnmanagedType.LPStruct)] Guid SubGroupGuid,
        [MarshalAs(UnmanagedType.LPStruct)] Guid PowerSettingGuid,
        out uint DwordValue);

    [DllImport("powrprof.dll", SetLastError = true)]
    public static extern uint PowerWriteACValueIndex(
        IntPtr RootPowerKey,
        [MarshalAs(UnmanagedType.LPStruct)] Guid SchemeGuid,
        [MarshalAs(UnmanagedType.LPStruct)] Guid SubGroupGuid,
        [MarshalAs(UnmanagedType.LPStruct)] Guid PowerSettingGuid,
        uint DwordValue);

    [DllImport("powrprof.dll", SetLastError = true)]
    public static extern uint PowerSetActiveScheme(IntPtr UserPowerKey, [MarshalAs(UnmanagedType.LPStruct)] Guid SchemeGuid);
}
"@

if ($Apply) {
    Write-Host "Applying: lid close, power button, sleep button = Do nothing (0)"
    [PC]::PowerWriteACValueIndex([IntPtr]::Zero, $SCHEME, $SUB_BUTTONS, $LIDACTION, 0) | Out-Null
    [PC]::PowerWriteACValueIndex([IntPtr]::Zero, $SCHEME, $SUB_BUTTONS, $POWERBUTTON, 0) | Out-Null
    [PC]::PowerWriteACValueIndex([IntPtr]::Zero, $SCHEME, $SUB_BUTTONS, $SLEEPBUTTON, 0) | Out-Null
    [PC]::PowerSetActiveScheme([IntPtr]::Zero, $SCHEME) | Out-Null
}

function Read-Setting($Name, $Guid) {
    $cv = [uint32]0
    $r = [PC]::PowerReadACValueIndex([IntPtr]::Zero, $SCHEME, $SUB_BUTTONS, $Guid, [ref]$cv)
    $val = switch ($cv) {
        0 { 'Do Nothing' }
        1 { 'Sleep' }
        2 { 'Hibernate' }
        3 { 'Shut down' }
        default { "unknown($cv)" }
    }
    $status = if ($r -eq 0 -and $cv -eq 0) { '✅' } else { '❌' }
    return "$status $Name AC: $val"
}

Write-Host ""
Write-Host "Power Button & Lid Configuration (AC):"
Write-Host "  $(Read-Setting 'Lid close'    $LIDACTION)"
Write-Host "  $(Read-Setting 'Power button' $POWERBUTTON)"
Write-Host "  $(Read-Setting 'Sleep button' $SLEEPBUTTON)"
Write-Host ""
