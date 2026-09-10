# A demonstration you can run in front of people.
#
#     .\Demo_ForManagement.ps1
#     .\Demo_ForManagement.ps1 -Screen P1111UM00 -Division VD -From 20260909 -To 20260909
#
# What it does, in this order:
#
#   1. Signs in to G-MES first, so the audience never watches a login.
#   2. Puts Chrome on the RIGHT half of the screen and the tool's own window
#      on the LEFT half, side by side.
#   3. Types the answers into the tool one character at a time, slowly enough
#      to read, exactly as a person would.
#   4. Presses Enter, and the work happens in Chrome on the right while the
#      steps are ticked off on the left.
#   5. Saves a screenshot of the finished screen.
#
# Why the typing is real keystrokes and not piped input: piped input is
# invisible. The point of this script is that the audience sees the values
# appear in the box.
#
# It changes nothing about how the tool works. It only drives the same
# GMES_Workflow.bat a person would double-click.

[CmdletBinding()]
param(
    [string]$Screen   = "P1112UM00",
    [string]$Division = "VD",
    [string]$From     = "20260909",
    [string]$To       = "20260909",
    [int]   $TypeDelayMs = 55,      # per character - readable, not sluggish
    [int]   $ReadPauseMs = 1400,    # pause on each prompt so it can be read
    [switch]$SkipSignIn             # the browser is already up and signed in
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DemoWin {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int t, bool repaint);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@

function Say($text) { Write-Host "  $text" -ForegroundColor Cyan }

# --------------------------------------------------------------------------
# 1. The browser, signed in before anyone is watching
# --------------------------------------------------------------------------
# Is the automation browser already up? Starting Chrome from cold takes the
# best part of a minute, and the first version of this did it with the output
# swallowed - so the screen stayed empty and the demo looked hung before it
# had drawn anything. Nothing here is ever silent now.
$cdpUp = $false
try {
    Invoke-WebRequest "http://127.0.0.1:9444/json/version" -TimeoutSec 3 -UseBasicParsing | Out-Null
    $cdpUp = $true
} catch { }

if (-not $cdpUp -and -not $SkipSignIn) {
    Say "The automation browser is not running. Starting it and signing in."
    Say "This takes up to a minute the first time - Chrome will appear shortly."
    & python gmes_login.py            # output on purpose: silence looks like a hang
    if ($LASTEXITCODE -ne 0) { throw "Could not sign in to G-MES. Demo stopped." }
} elseif (-not $cdpUp) {
    throw "The automation browser is not running, and -SkipSignIn was given. " +
          "Run 'python gmes_login.py' first."
} else {
    Say "Automation browser is already up and signed in."
}

# The automation browser is the Chrome running on the CDP profile copy - NOT
# whatever Chrome windows the presenter has open. Identified by its command
# line so the demo never grabs someone's real browser.
$chrome = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" |
          Where-Object { $_.CommandLine -like "*CDP Profile*" } |
          ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
          Where-Object { $_.MainWindowHandle -ne 0 } |
          Select-Object -First 1
if (-not $chrome) { throw "The automation browser is not on screen. Run: python gmes_login.py" }

# --------------------------------------------------------------------------
# 2. The tool, in its own window
# --------------------------------------------------------------------------
Say "Opening GMES_Workflow.bat in its own window..."
$tool = Start-Process -FilePath "cmd.exe" `
                      -ArgumentList '/c', 'title G-MES REPORT TOOL && GMES_Workflow.bat' `
                      -WorkingDirectory $PSScriptRoot -PassThru

for ($i = 0; $i -lt 100 -and $tool.MainWindowHandle -eq 0; $i++) {
    Start-Sleep -Milliseconds 100
    $tool.Refresh()
}
if ($tool.MainWindowHandle -eq 0) { throw "The tool window did not appear." }

# --------------------------------------------------------------------------
# 3. Side by side
# --------------------------------------------------------------------------
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$half = [int]($area.Width / 2)
[DemoWin]::ShowWindow($chrome.MainWindowHandle, 9) | Out-Null   # restore if minimised
[DemoWin]::MoveWindow($chrome.MainWindowHandle, $area.X + $half, $area.Y, $half, $area.Height, $true) | Out-Null
[DemoWin]::MoveWindow($tool.MainWindowHandle,   $area.X,         $area.Y, $half, $area.Height, $true) | Out-Null
Say "Tool on the left, G-MES on the right."
Start-Sleep -Milliseconds 900

# --------------------------------------------------------------------------
# 4. Typing, visibly
# --------------------------------------------------------------------------
# SendKeys treats + ^ % ~ ( ) { } [ ] as instructions. None of our answers
# contain them, but a screen code or a division typed by someone else might,
# so each one is wrapped rather than trusted.
function Escape-Key([char]$c) {
    if ('+^%~(){}[]'.IndexOf($c) -ge 0) { return "{$c}" }
    return [string]$c
}

function Type-Answer([string]$text) {
    # Focus first, then CONFIRM the tool really is the foreground window.
    # Windows can refuse a foreground change requested by a background
    # process, and SendKeys goes to whatever is focused - so without this
    # check a failed activation types the screen code into whatever the
    # presenter happens to have open.
    $ok = $false
    for ($try = 0; $try -lt 8 -and -not $ok; $try++) {
        [DemoWin]::SetForegroundWindow($tool.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 250
        $ok = ([DemoWin]::GetForegroundWindow() -eq $tool.MainWindowHandle)
    }
    if (-not $ok) {
        throw "Could not bring the tool window to the front, so nothing was typed. " +
              "Click the tool window once and run the demo again."
    }
    foreach ($c in $text.ToCharArray()) {
        [System.Windows.Forms.SendKeys]::SendWait((Escape-Key $c))
        Start-Sleep -Milliseconds $TypeDelayMs
    }
    Start-Sleep -Milliseconds 350
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Milliseconds $ReadPauseMs
}

# The tool prints its banner and confirms the existing session before asking
# anything. With the browser already up that is a few seconds. Typing a
# little early is harmless anyway - a Windows console buffers keystrokes and
# hands them over when the program next reads - so this wait is for
# APPEARANCE, not correctness.
Say "Waiting for the tool's first question..."
Start-Sleep -Seconds 8

Say "Typing the answers..."
Type-Answer $Screen           # 1. Which screen?
Type-Answer $Division         # 2. Division
Type-Answer $From             # 3. From date
Type-Answer $To               # 4. To date
Type-Answer ""                # 5. Extra filter - none
Type-Answer ""                # Press Enter to start

# --------------------------------------------------------------------------
# 5. Watch it work
# --------------------------------------------------------------------------
Say "Running. The steps tick off on the left; G-MES answers on the right."

# Finished = a new file in the output folder. Anything already there is
# ignored, so a file from an earlier run cannot end the wait early.
$startedAt = Get-Date
$deadline = $startedAt.AddMinutes(3)
$done = $false
while ((Get-Date) -lt $deadline -and -not $tool.HasExited -and -not $done) {
    Start-Sleep -Seconds 2
    $tool.Refresh()
    $new = Get-ChildItem "Data Hub Folder\GMES" -Filter *.csv -ErrorAction SilentlyContinue |
           Where-Object { $_.LastWriteTime -gt $startedAt }
    if ($new) { $done = $true }
}
if ($done) { Say "Files delivered." } else { Say "Finished waiting - check the tool window." }
Start-Sleep -Seconds 3

$shot = Join-Path $PSScriptRoot ("demo_side_by_side_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".png")
$bmp = New-Object System.Drawing.Bitmap($area.Width, $area.Height)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($area.X, $area.Y, 0, 0, $bmp.Size)
$bmp.Save($shot, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()

Say "Screenshot: $shot"
Say "The tool window is still open on 'Press Enter to close...' - leave it up."
Write-Host ""
