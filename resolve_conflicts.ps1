param (
    [string]$FilePath
)

$content = Get-Content $FilePath
$newContent = @()
$inConflict = $false
$keep = $false

foreach ($line in $content) {
    if ($line -match "^<<<<<<< HEAD") {
        $inConflict = $true
        $keep = $true
        continue
    }
    if ($line -match "^=======") {
        $keep = $false
        continue
    }
    if ($line -match "^>>>>>>>") {
        $inConflict = $false
        $keep = $false
        continue
    }
    
    if (-not $inConflict -or $keep) {
        $newContent += $line
    }
}

$newContent | Set-Content $FilePath
