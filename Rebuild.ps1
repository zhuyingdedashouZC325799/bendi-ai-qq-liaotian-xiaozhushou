$ErrorActionPreference='Stop'
$zip=Join-Path $PSScriptRoot 'payload.zip'
Compress-Archive -Path (Join-Path $PSScriptRoot 'payload\*') -DestinationPath $zip -Force
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Core.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ("/resource:"+$zip+",Payload") ("/out:"+(Join-Path $PSScriptRoot 'LocalQQAssistantSetup.exe')) (Join-Path $PSScriptRoot 'Installer.cs')
if($LASTEXITCODE -ne 0){throw 'Build failed'}
