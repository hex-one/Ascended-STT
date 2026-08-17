# Computes the SHA256 hash of a built release package.
#
# Usage:
#   .\scripts\hash_release.ps1 dist\AscendedSTT-v0.1.0-win64.zip
#
# Run this on every new build before submitting to Microsoft or writing
# release notes -- a rebuild from unchanged source still produces a
# different hash (timestamps, compiler/library versions, etc. all bleed
# into the output), and Microsoft's false-positive review applies to one
# specific file hash, not "this project" in general. Record the hash in
# DEFENDER_SUBMISSION.md's log alongside the submission outcome.

param(
    [Parameter(Mandatory = $true)][string]$Path
)

if (-not (Test-Path $Path)) {
    Write-Error "File not found: $Path"
    exit 1
}

$hash = Get-FileHash -Path $Path -Algorithm SHA256
Write-Output "File:   $Path"
Write-Output "SHA256: $($hash.Hash)"
