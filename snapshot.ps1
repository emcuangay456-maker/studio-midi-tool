$desktop = [Environment]::GetFolderPath("Desktop")
$output = Join-Path $desktop ("snapshot_{0}.txt" -f (Get-Date -Format "HHmm"))

$lines = @()
$lines += "===== THOI GIAN: $(Get-Date) ====="
$lines += "===== PROJECT TREE ====="

Get-ChildItem -Path . -Recurse -File |
  Where-Object { $_.Extension -in ".py", ".js", ".json" } |
  ForEach-Object { $lines += (Resolve-Path -Relative $_.FullName) }

$lines += ""
$lines += "===== NOI DUNG FILES ====="
Get-ChildItem -Path . -Recurse -File |
  Where-Object { $_.Extension -in ".py", ".js" } |
  ForEach-Object {
    $lines += "--- $(Resolve-Path -Relative $_.FullName) ---"
    $lines += (Get-Content -Path $_.FullName -Raw)
    $lines += ""
  }

$lines += "===== GIT LOG (5 commit gan nhat) ====="
$gitLog = & "C:\Program Files\Git\cmd\git.exe" log --oneline -5 2>$null
if ($gitLog) { $lines += $gitLog }

Set-Content -Path $output -Value $lines -Encoding UTF8
Write-Host "Snapshot saved: $output"
$ErrorActionPreference = "SilentlyContinue"

$desktop = [Environment]::GetFolderPath("Desktop")
$output = Join-Path $desktop ("snapshot_{0}.txt" -f (Get-Date -Format "HHmm"))

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("===== THOI GIAN: $(Get-Date) =====")
$lines.Add("===== PROJECT TREE =====")

$projectFiles = Get-ChildItem -Path . -Recurse -File |
    Where-Object {
        ($_.Extension -in ".py", ".js", ".json") -and
        ($_.FullName -notmatch "\\node_modules\\") -and
        ($_.FullName -notmatch "\\__pycache__\\")
    }

foreach ($f in $projectFiles) {
    $rel = Resolve-Path -Relative $f.FullName
    $lines.Add($rel)
}

$lines.Add("")
$lines.Add("===== NOI DUNG FILES =====")

$contentFiles = Get-ChildItem -Path . -Recurse -File |
    Where-Object {
        ($_.Extension -in ".py", ".js") -and
        ($_.FullName -notmatch "\\node_modules\\")
    }

foreach ($f in $contentFiles) {
    $rel = Resolve-Path -Relative $f.FullName
    $lines.Add("--- $rel ---")
    try {
        $lines.Add((Get-Content -Path $f.FullName -Raw))
    } catch {
        $lines.Add("[Cannot read file]")
    }
    $lines.Add("")
}

$lines.Add("===== GIT LOG (5 commit gan nhat) =====")
$gitLog = git log --oneline -5 2>$null
if ($gitLog) {
    foreach ($l in $gitLog) { $lines.Add($l) }
}

Set-Content -Path $output -Value $lines -Encoding UTF8
Write-Host "Snapshot saved: $output"
