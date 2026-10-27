param([Parameter(Mandatory=$true)][string]$ConfigFile,[switch]$ConfigureOnly)
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$cfg=Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8|ConvertFrom-Json
$root=$cfg.install_dir
$cache=$cfg.cache_dir
$env:LOCALBOT_CONFIG=$ConfigFile
$env:ASTRBOT_ROOT=Join-Path $root 'userdata'
$env:PYTHONUTF8='1'
$env:UV_PYTHON_INSTALL_DIR=Join-Path $root 'runtime\python'
$env:UV_CACHE_DIR=Join-Path $cache 'uv'
$env:PIP_CACHE_DIR=Join-Path $cache 'pip'
$env:TEMP=Join-Path $cache 'temp';$env:TMP=$env:TEMP
$env:OLLAMA_MODELS=Join-Path $cfg.models_dir 'ollama'
$downloads=Join-Path $cache 'downloads'
$reportFolder=Join-Path $cache 'logs\error-reports'
foreach($folder in @($env:TEMP,$downloads,$reportFolder)){ $null=New-Item -ItemType Directory -Force -Path $folder }
$log=Join-Path $cache ('logs\install-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Start-Transcript -Path $log -Force|Out-Null
function Download([string]$Url,[string]$Path,[string]$Hash=''){
 if(Test-Path -LiteralPath $Path){if($Hash -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ieq $Hash){return}}
 if($Url -notlike 'https://*'){throw 'Only HTTPS dependency downloads are allowed'}
 $partial=$Path+'.partial'
 for($attempt=1;$attempt -le 3;$attempt++){
  try{
   Write-Host "Download $attempt/3 : $Url"
   Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing -TimeoutSec 1800
   if($Hash -and (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ine $Hash){throw 'Dependency SHA256 mismatch'}
   Move-Item -LiteralPath $partial -Destination $Path -Force;return
  }catch{if($attempt -eq 3){throw};Start-Sleep -Seconds 2}
 }
}
function Expand([string]$Archive,[string]$Destination){
 $null=New-Item -ItemType Directory -Force -Path $Destination
 Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}
function Native([string]$Exe,[string[]]$Arguments){
 & $Exe @Arguments
 if($LASTEXITCODE -ne 0){throw "Dependency command failed: $Exe (exit $LASTEXITCODE)"}
}
try{
 $manifest=Get-Content (Join-Path $root 'dependencies.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $uvArchive=Join-Path $downloads 'uv.zip';Download $manifest.uv.url $uvArchive $manifest.uv.sha256
 Expand $uvArchive (Join-Path $root 'tools\uv')
 $uv=(Get-ChildItem (Join-Path $root 'tools\uv') -Filter uv.exe -Recurse|Select-Object -First 1).FullName
 Native $uv @('python','install','3.13')
 $basePython=(& $uv python find --managed-python 3.13 |Select-Object -Last 1).Trim()
 $backendEnv=Join-Path $root 'runtime\backend'
 Native $uv @('venv','--python',$basePython,$backendEnv)
 $backendPython=Join-Path $backendEnv 'Scripts\python.exe'
 $backendPython|Set-Content (Join-Path $root 'runtime\python-path.txt') -Encoding UTF8
 $requirements=Join-Path $root 'requirements-lock.txt'
 if(-not(Test-Path $requirements)){$requirements=Join-Path $root 'backend\app\requirements.txt'}
 Native $uv @('pip','install','--python',$backendPython,'-r',$requirements,'beautifulsoup4','pywin32','psutil','aiohttp','pillow')
 Native $backendPython @((Join-Path $root 'scripts\configure.py'),$ConfigFile)
 if(-not $ConfigureOnly){
  $ollamaArchive=Join-Path $downloads 'ollama.zip';Download $manifest.ollama.url $ollamaArchive $manifest.ollama.sha256
  Expand $ollamaArchive (Join-Path $root 'tools\ollama')
  $dashboardArchive=Join-Path $downloads 'dashboard.zip';Download $manifest.dashboard.url $dashboardArchive $manifest.dashboard.sha256
  Expand $dashboardArchive (Join-Path $root 'userdata\data\dist')
  $ffArchive=Join-Path $downloads 'ffmpeg.zip'
  Download 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $ffArchive
  Expand $ffArchive (Join-Path $root 'tools\ffmpeg-download')
  $ffBin=(Get-ChildItem (Join-Path $root 'tools\ffmpeg-download') -Filter ffmpeg.exe -Recurse|Select-Object -First 1).Directory.FullName
  $null=New-Item -ItemType Directory -Force (Join-Path $root 'tools\ffmpeg\bin')
  Copy-Item -LiteralPath (Join-Path $ffBin 'ffmpeg.exe') -Destination (Join-Path $root 'tools\ffmpeg\bin\ffmpeg.exe') -Force
  Copy-Item -LiteralPath (Join-Path $ffBin 'ffprobe.exe') -Destination (Join-Path $root 'tools\ffmpeg\bin\ffprobe.exe') -Force
  $phpReleases=Invoke-RestMethod 'https://windows.php.net/downloads/releases/releases.json'
  $php=$phpReleases.'8.4'.'nts-vs17-x64'.zip
  if(-not $php){throw 'Official PHP release metadata has changed'}
  $phpArchive=Join-Path $downloads 'php.zip';Download ('https://windows.php.net/downloads/releases/'+$php.path) $phpArchive $php.sha256
  Expand $phpArchive (Join-Path $root 'tools\php')
  @('extension_dir="ext"','extension=curl','extension=openssl','extension=mbstring','allow_url_fopen=On','default_socket_timeout=25')|Set-Content (Join-Path $root 'tools\php\php.ini') -Encoding ASCII
  if(-not(Test-Path (Join-Path $env:WINDIR 'System32\vcruntime140.dll')) -or -not(Test-Path (Join-Path $env:WINDIR 'System32\msvcp140.dll'))){
   Add-Type -AssemblyName System.Windows.Forms
   if([Windows.Forms.MessageBox]::Show('Microsoft Visual C++ runtime is required. Download and open its official installer now?','Required runtime','YesNo','Question') -ne 'Yes'){throw 'The required Microsoft runtime was declined'}
   $redist=Join-Path $downloads 'vc_redist.x64.exe';Download 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $redist
   $signature=Get-AuthenticodeSignature -FilePath $redist
   if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft'){throw 'Microsoft runtime signature verification failed'}
   Start-Process -FilePath $redist -WindowStyle Normal -Wait
   if(-not(Test-Path (Join-Path $env:WINDIR 'System32\vcruntime140.dll'))){throw 'Microsoft runtime installation was not completed'}
  }
  Native (Join-Path $root 'tools\php\php.exe') @('-v')
  if($cfg.bridge_type -eq 'napcat'){
   $bridgeArchive=Join-Path $downloads 'napcat.zip';Download $manifest.napcat.url $bridgeArchive $manifest.napcat.sha256
   $officialFolder=Join-Path $root 'thirdparty\napcat-installer'
   Expand $bridgeArchive $officialFolder
   Write-Host ('Open the official NapCat installer. Recommended destination: '+(Join-Path $root 'bridge'))
   $officialInstaller=Join-Path $officialFolder 'NapCatInstaller.exe'
   if(-not(Test-Path $officialInstaller)){throw 'Official NapCat installer layout changed'}
   Start-Process -FilePath $officialInstaller -WorkingDirectory $officialFolder -WindowStyle Normal -Wait
   $bridgeRoot=Join-Path $root 'bridge'
   $bridgeCore=Get-ChildItem $bridgeRoot -Filter napcat.mjs -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1
   if(-not $bridgeCore){
    Add-Type -AssemblyName System.Windows.Forms
    $pick=New-Object System.Windows.Forms.FolderBrowserDialog
    $pick.Description='Select the directory where the official NapCat installer installed NapCat'
    if($pick.ShowDialog() -ne 'OK'){throw 'QQ bridge installation was not completed'}
    $bridgeRoot=$pick.SelectedPath
    $bridgeCore=Get-ChildItem $bridgeRoot -Filter napcat.mjs -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1
    if(-not $bridgeCore){throw 'NapCat core is missing from the selected directory'}
   }
   $cfg|Add-Member -NotePropertyName bridge_path -NotePropertyValue $bridgeRoot -Force
   $cfg|Add-Member -NotePropertyName bridge_core_dir -NotePropertyValue $bridgeCore.Directory.FullName -Force
   $cfg|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $ConfigFile -Encoding UTF8
  }elseif(-not(Test-Path -LiteralPath $cfg.bridge_path)){throw 'Please install SnowLuma independently and select its directory first'}
  if($cfg.enable_cover){
   $rvcEnv=Join-Path $root 'engines\rvc';Native $uv @('venv','--python',$basePython,$rvcEnv)
   $rvcPython=Join-Path $rvcEnv 'Scripts\python.exe'
   $torchIndex=if($cfg.gpu_mode -eq 'nvidia'){'https://download.pytorch.org/whl/cu130'}else{'https://download.pytorch.org/whl/cpu'}
   Native $uv @('pip','install','--python',$rvcPython,'torch==2.14.0','--index-url',$torchIndex)
   Native $uv @('pip','install','--python',$rvcPython,'rvc-next==0.2.11','soundfile','librosa','numpy','scipy','pillow','tqdm','resampy','omegaconf')
   $env:RVC_NEXT_DATA_DIR=Join-Path $cfg.models_dir 'rvc'
   Native $rvcPython @('-m','rvc_next','assets','download')
   $legacyArchive=Join-Path $downloads 'rvc-source.zip'
   Download 'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/archive/refs/heads/main.zip' $legacyArchive
   Expand $legacyArchive (Join-Path $root 'engines\legacy-download')
   $legacy=Get-ChildItem (Join-Path $root 'engines\legacy-download') -Directory|Select-Object -First 1
   Copy-Item -Path (Join-Path $legacy.FullName '*') -Destination (Join-Path $root 'engines\legacy-rvc') -Recurse -Force
   $weight=Join-Path $cfg.models_dir 'uvr5\HP2_all_vocals.pth'
   $null=New-Item -ItemType Directory -Force (Split-Path $weight)
   Download 'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/uvr5_weights/HP2_all_vocals.pth' $weight
  }
  # Download model blobs with a dedicated, temporary Ollama port. No existing
  # recipient service is stopped or adopted during installation.
  $temporaryListener=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
  $temporaryListener.Start();$modelPort=$temporaryListener.LocalEndpoint.Port;$temporaryListener.Stop()
  $env:OLLAMA_HOST='127.0.0.1:'+$modelPort;$env:OLLAMA_NUM_PARALLEL='1';$env:OLLAMA_MAX_LOADED_MODELS='1'
  $ollama=Join-Path $root 'tools\ollama\ollama.exe'
  $modelServer=Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $cache 'logs\model-install.log') -RedirectStandardError (Join-Path $cache 'logs\model-install.err.log')
  try{
   $ready=$false;for($i=0;$i -lt 60;$i++){
    if($modelServer.HasExited){throw 'The dedicated model service exited'}
    try{
     $owner=Get-NetTCPConnection -LocalPort $modelPort -State Listen -ErrorAction Stop|Select-Object -First 1
     if($owner.OwningProcess -ne $modelServer.Id){throw 'Temporary port was claimed by another process'}
     $null=Invoke-RestMethod ('http://127.0.0.1:'+$modelPort+'/api/version') -TimeoutSec 2;$ready=$true;break
    }catch{Start-Sleep -Seconds 1}
   }
   if(-not $ready){throw 'The model download service did not start'}
   Native $ollama @('pull','qwen3-vl:4b')
   if(-not(Test-Path (Join-Path $cfg.models_dir 'ollama\manifests\registry.ollama.ai\library\qwen3-vl\4b'))){throw 'Model files are missing from the selected model directory'}
  }finally{if($modelServer -and -not $modelServer.HasExited){Stop-Process -Id $modelServer.Id -Force}}
 }
 Native $backendPython @((Join-Path $root 'scripts\configure.py'),$ConfigFile)
 $shell=New-Object -ComObject WScript.Shell
 $link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '本地QQ助手.lnk'))
 $link.TargetPath=Join-Path $root '本地QQ助手.exe';$link.Arguments='--run';$link.WorkingDirectory=$root;$link.Save()
 $uninstallId=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($root)).Replace('/','_').Replace('+','-').TrimEnd('=')
 $uninstallKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalQQAssistant-'+$uninstallId
 $null=New-Item -Path $uninstallKey -Force
 New-ItemProperty -Path $uninstallKey -Name DisplayName -Value 'Local QQ Assistant' -PropertyType String -Force|Out-Null
 New-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value '1.0.0' -PropertyType String -Force|Out-Null
 New-ItemProperty -Path $uninstallKey -Name InstallLocation -Value $root -PropertyType String -Force|Out-Null
 $uninstallCommand='powershell.exe -NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $root 'scripts\uninstall.ps1')+'" -ConfigFile "'+$ConfigFile+'"'
 New-ItemProperty -Path $uninstallKey -Name UninstallString -Value $uninstallCommand -PropertyType String -Force|Out-Null
 $finalCfg=Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8|ConvertFrom-Json
 $finalCfg|Add-Member -NotePropertyName uninstall_key -NotePropertyValue $uninstallKey -Force
 $finalCfg|Add-Member -NotePropertyName installation_complete -NotePropertyValue $true -Force
 $finalCfg|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $ConfigFile -Encoding UTF8
 Write-Host 'INSTALL_SUCCESS: Installed. Login to your own QQ and QQ Music before use.'
}catch{
 $report=Join-Path $reportFolder ('installation-failed-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.txt')
 ($_|Out-String)|Set-Content -LiteralPath $report -Encoding UTF8
 Write-Host ('INSTALL_FAILED: '+$report);throw
}finally{Stop-Transcript|Out-Null}
