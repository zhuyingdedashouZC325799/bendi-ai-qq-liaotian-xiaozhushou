param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$cfg=Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8|ConvertFrom-Json
$root=[IO.Path]::GetFullPath($cfg.install_dir).TrimEnd('\')
if(-not(Test-Path -LiteralPath (Join-Path $root '.localbot-package')) -or $root -eq [IO.Path]::GetPathRoot($root).TrimEnd('\')){throw 'Not a managed LocalBot installation'}
$answer=[Windows.Forms.MessageBox]::Show('Uninstall this Local QQ Assistant? Its services will stop. Model and voice directories are retained.','Uninstall','YesNo','Question')
if($answer -ne 'Yes'){exit 0}
$prefix=$root+'\'
Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne $PID -and $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or ($_.CommandLine -and $_.CommandLine.Contains('--user-data-dir='+$prefix)))}|ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
$protected=@($cfg.models_dir,$cfg.voices_dir,$cfg.cache_dir)|ForEach-Object {[IO.Path]::GetFullPath($_).TrimEnd('\')}
foreach($folder in @('backend','runtime','templates','tools','scripts','engines','bridge','thirdparty')){
 $target=[IO.Path]::GetFullPath((Join-Path $root $folder))
 if(-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Invalid uninstall target'}
 if(@($protected|Where-Object {$_ -eq $target -or $_.StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase)}).Count){continue}
 if(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target -Recurse -Force}
}
foreach($name in @('本地QQ助手.exe','dependencies.json','THIRD_PARTY.md')){
 $file=Join-Path $root $name;if(Test-Path -LiteralPath $file){Remove-Item -LiteralPath $file -Force}
}
# Userdata and localbot.json deliberately remain for an explicit reinstall.
$shortcut=Join-Path ([Environment]::GetFolderPath('Desktop')) '本地QQ助手.lnk'
if(Test-Path $shortcut){$link=(New-Object -ComObject WScript.Shell).CreateShortcut($shortcut);if($link.WorkingDirectory -eq $root){Remove-Item -LiteralPath $shortcut -Force}}
if($cfg.uninstall_key){Remove-Item -LiteralPath $cfg.uninstall_key -Force -ErrorAction SilentlyContinue}
[Windows.Forms.MessageBox]::Show('Program components removed. Personal configuration, account data and selected model directories were retained.','Uninstall')|Out-Null
