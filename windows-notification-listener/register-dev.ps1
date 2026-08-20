param(
  [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root "TrafficManager.NotificationListener\TrafficManager.NotificationListener.csproj"
$layout = Join-Path $root "layout"
$assets = Join-Path $layout "Assets"

Write-Host "Building helper..."
dotnet build $project -c $Configuration
if ($LASTEXITCODE -ne 0) {
  throw "dotnet build failed"
}

$outDir = Join-Path $root "TrafficManager.NotificationListener\bin\$Configuration\net8.0-windows10.0.19041.0"
if (-not (Test-Path (Join-Path $outDir "TrafficManager.NotificationListener.exe"))) {
  $found = Get-ChildItem -Path (Join-Path $root "TrafficManager.NotificationListener\bin") -Recurse -Filter "TrafficManager.NotificationListener.exe" | Select-Object -First 1
  if (-not $found) {
    throw "Built executable not found"
  }
  $outDir = $found.DirectoryName
}

if (Test-Path $layout) {
  Remove-Item $layout -Recurse -Force
}
New-Item -ItemType Directory -Path $assets | Out-Null
Copy-Item -Path (Join-Path $outDir "*") -Destination $layout -Recurse -Force
Copy-Item -Path (Join-Path $root "Package.appxmanifest") -Destination (Join-Path $layout "AppxManifest.xml") -Force

Add-Type -AssemblyName System.Drawing
function Save-Logo([string]$path, [int]$size) {
  $bmp = New-Object System.Drawing.Bitmap $size, $size
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::FromArgb(88, 101, 242))
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose()
  $bmp.Dispose()
}

Save-Logo (Join-Path $assets "StoreLogo.png") 50
Save-Logo (Join-Path $assets "Square44x44Logo.png") 44
Save-Logo (Join-Path $assets "Square150x150Logo.png") 150

Write-Host "Registering package identity (Developer Mode required)..."
Add-AppxPackage -Register (Join-Path $layout "AppxManifest.xml")
Write-Host "Registered. Start 'Traffic Manager Notification Listener' from the Start menu."
