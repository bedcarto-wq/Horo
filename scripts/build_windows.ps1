$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne "Windows_NT") { throw "Windows-сборка создаётся только на Windows" }
python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости" }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Тесты не прошли" }
python -m PyInstaller --noconfirm --clean --windowed --onedir --name Horo --paths . scripts/launch_editor.py
if ($LASTEXITCODE -ne 0) { throw "Ошибка PyInstaller" }
python scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw "Не удалось включить лицензионные тексты" }
Copy-Item README.md, THIRD_PARTY.md, CHANGELOG.md -Destination dist/Horo/
Copy-Item docs -Destination dist/Horo/docs -Recurse -Force
Copy-Item examples -Destination dist/Horo/examples -Recurse -Force
$Revision = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { $Revision = "local-source" }
Set-Content -Encoding utf8 dist/Horo/BUILD.txt "Horo 0.4.1`nCommit: $Revision`nPlatform: Windows`nPython: $(python --version)"
Compress-Archive -Path dist/Horo -DestinationPath dist/Horo-0.4.1-Windows-x64.zip -Force
Write-Host "Готово: dist/Horo-0.4.1-Windows-x64.zip. Распакуйте всю папку, не только EXE."
