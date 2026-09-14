<#
Downloads the remaining volumes of "Enzyklopädie Philosophie und Wissenschaftstheorie"
(Springer, ed. Mittelstraß) using an authenticated SpringerLink session cookie.

SETUP (do this once per session — cookies expire after a while):
  1. In your normal browser, go to https://link.springer.com and log in via
     Uni Bonn -> Shibboleth / institutional login, until Springer shows you as
     entitled (e.g. open the A-B volume page, "Download book PDF" should be
     available directly, no purchase prompt).
  2. Open DevTools (F12) -> Network tab, reload the page, click the top
     "link.springer.com/book/..." request, and copy the full value of the
     "cookie:" request header.
  3. Save that value into scripts\.springer-cookie.txt (plain text, one line,
     no quotes). Do NOT paste the cookie into chat/Claude — it's equivalent
     to your login session.

USAGE:
  powershell -File scripts\download-volumes.ps1
  (add -DryRun to just print what would happen)

NOTE (2026-09-04): Springer now fronts /content/pdf/*.pdf with a Fastly
"Client Challenge" bot check that a raw Invoke-WebRequest can't pass even
with a fully valid cookie (it just gets an HTML challenge page back, not a
PDF, and the script stops). All 8 volumes ended up being downloaded instead
by opening each book page in an actual logged-in browser and clicking
"Download book PDF" by hand. Keeping this script around in case Springer
loosens the check again, but don't be surprised if it still fails that way.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root       = Split-Path -Parent $PSScriptRoot
$outDir     = Join-Path $root "pdf-data"
$cookieFile = Join-Path $PSScriptRoot ".springer-cookie.txt"

if (-not (Test-Path $cookieFile)) {
    Write-Error "Missing $cookieFile — see the header of this script for how to create it."
    exit 1
}
$cookie = (Get-Content $cookieFile -Raw).Trim()

# Volume 1 (A-B) already downloaded manually; kept here for reference/completeness checks.
$volumes = @(
    @{ Num = 1; Range = "A-B";     Doi = "978-3-662-67543-4" },
    @{ Num = 2; Range = "C-F";     Doi = "978-3-662-67762-9" },
    @{ Num = 3; Range = "G-Inn";   Doi = "978-3-662-67764-3" },
    @{ Num = 4; Range = "Ins-Loc"; Doi = "978-3-662-67766-7" },
    @{ Num = 5; Range = "Log-N";   Doi = "978-3-662-67768-1" },
    @{ Num = 6; Range = "O-Ra";    Doi = "978-3-662-67770-4" },
    @{ Num = 7; Range = "Re-Te";   Doi = "978-3-662-67772-8" },
    @{ Num = 8; Range = "Th-Z";    Doi = "978-3-662-67774-2" }
)

$headers = @{
    "Cookie"     = $cookie
    "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    "Accept"     = "application/pdf,*/*"
    "Referer"    = "https://link.springer.com/"
}

foreach ($v in $volumes) {
    $outFile = Join-Path $outDir "$($v.Doi).pdf"
    $label   = "Bd. $($v.Num) ($($v.Range))"

    if (Test-Path $outFile) {
        Write-Host "[skip] $label — already present: $outFile"
        continue
    }

    $url = "https://link.springer.com/content/pdf/$($v.Doi).pdf"

    if ($DryRun) {
        Write-Host "[dry-run] would GET $url -> $outFile"
        continue
    }

    Write-Host "[download] $label -> $outFile"
    $tmpFile = "$outFile.part"
    try {
        Invoke-WebRequest -Uri $url -Headers $headers -OutFile $tmpFile -MaximumRedirection 5
    } catch {
        Write-Warning "Request failed for $label`: $_"
        Remove-Item -ErrorAction SilentlyContinue $tmpFile
        continue
    }

    # Verify we actually got a PDF and not an HTML login/paywall page.
    $bytes = [System.IO.File]::ReadAllBytes($tmpFile)
    $magic = [System.Text.Encoding]::ASCII.GetString($bytes[0..3])
    if ($magic -ne "%PDF") {
        Write-Warning "$label did not return a PDF (got '$magic...') — cookie likely expired or no entitlement. Stopping."
        Remove-Item -ErrorAction SilentlyContinue $tmpFile
        break
    }

    Move-Item $tmpFile $outFile
    Write-Host "[ok] $label — $((Get-Item $outFile).Length / 1MB) MB"

    # Be a polite, human-paced client: random 15-30s pause between volumes.
    if ($v -ne $volumes[-1]) {
        $pause = Get-Random -Minimum 15 -Maximum 31
        Write-Host "  waiting $pause s..."
        Start-Sleep -Seconds $pause
    }
}

Write-Host "Done."
