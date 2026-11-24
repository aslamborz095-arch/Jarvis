# Installation de JARVIS sur Windows
# Clic droit > Executer avec PowerShell  (ou : powershell -ExecutionPolicy Bypass -File install.ps1)
Start-Transcript -Path "$PSScriptRoot\install.log" | Out-Null
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
function Step($t) { Write-Host "`n>>> $t" -ForegroundColor Cyan }
function Has($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }

Step "1/7 Python"
function RealPython {
  foreach ($c in "py", "python") {
    try { $v = & $c --version 2>&1; if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3\.(1[0-3])") { return $c } } catch {}
  }
  $f = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python31*\python.exe", "$env:ProgramFiles\Python31*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($f) { return $f.FullName }
  return $null
}
$py = RealPython
if (-not $py) {
  Write-Host "Installation de Python 3.12..."
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  RefreshPath
  $py = RealPython
}
if (-not $py) { Write-Host "Python introuvable apres installation." -ForegroundColor Red; Read-Host "Entree pour fermer"; exit 1 }
Write-Host "Python : $py"

Step "2/7 Environnement Python + dependances"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -q

Step "3/7 Cerveau local (Ollama) - fonctionne sans internet"
if (-not (Has "ollama")) {
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
  RefreshPath
}
$model = "qwen2.5:7b"
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if ($ram -lt 12) { $model = "qwen2.5:3b"; Write-Host "RAM $ram Go : modele leger $model" }
ollama pull $model

Step "4/7 Modele de suivi des mains + reconnaissance vocale hors ligne"
$hand = "static\vendor\mediapipe\hand_landmarker.task"
if (-not (Test-Path $hand)) {
  Invoke-WebRequest "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" -OutFile $hand
}
& .\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small', compute_type='int8'); print('Whisper OK')"

Step "5/7 Configuration"
if (-not (Test-Path ".env")) {
  $token = -join ((48..57) + (65..90) | Get-Random -Count 8 | ForEach-Object { [char]$_ })
  $key = ""
  (Get-Content .env.example) `
    -replace "^ANTHROPIC_API_KEY=.*", "ANTHROPIC_API_KEY=$key" `
    -replace "^JARVIS_TOKEN=.*", "JARVIS_TOKEN=$token" `
    -replace "^OLLAMA_MODEL=.*", "OLLAMA_MODEL=$model" | Set-Content .env -Encoding UTF8
  Write-Host "CODE D'ACCES JARVIS : $token  (a garder)" -ForegroundColor Yellow
  "CODE D'ACCES JARVIS : $token" | Set-Content "$PSScriptRoot\CODE-ACCES.txt"
}

Step "6/7 Demarrage automatique a l'ouverture de session"
$vbs = Join-Path $PSScriptRoot "jarvis-hidden.vbs"
@"
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$PSScriptRoot"
sh.Run """$PSScriptRoot\.venv\Scripts\pythonw.exe"" server.py", 0, False
"@ | Set-Content $vbs -Encoding ASCII
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk")
$lnk.TargetPath = $vbs; $lnk.Save()

Step "7/7 Acces depuis le telephone (Tailscale, gratuit, chiffre)"
if (-not (Has "tailscale")) {
  winget install -e --id Tailscale.Tailscale --accept-package-agreements --accept-source-agreements
  RefreshPath
}
Write-Host "Connexion Tailscale : une page s'ouvre, connecte-toi (Google ou Microsoft)."
tailscale up --timeout 180s
tailscale serve --bg 8765
tailscale serve status

Start-Process wscript.exe $vbs
Start-Sleep 4
Start-Process "http://127.0.0.1:8765"
Write-Host "`nJARVIS est en ligne. Telephone : installe Tailscale, meme compte, ouvre l'adresse https://...ts.net ci-dessus." -ForegroundColor Green
Read-Host "`nTermine. Appuie sur Entree pour fermer"
