param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$env:PYTHONUTF8='1';$env:LOCALBOT_CONFIG=$ConfigFile
try{
 $root=Split-Path -Parent $ConfigFile
 $python=(Get-Content (Join-Path $root 'runtime\python-path.txt') -Raw -Encoding UTF8).Trim()
 if(-not(Test-Path -LiteralPath $python)){throw 'Python runtime missing. Run the installer to repair this installation.'}
 & $python -u (Join-Path $root 'scripts\runtime.py') $ConfigFile
}catch{Write-Host ($_|Out-String) -ForegroundColor Red;$null=Read-Host 'Press Enter to close'}
