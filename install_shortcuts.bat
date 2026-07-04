@echo off
REM Creates "WhispLocal" shortcuts on the Desktop and in the Start Menu
REM (silent launch, app icon, no console window).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$app = '%~dp0'.TrimEnd('\');" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'))) {" ^
  "  $lnk = $ws.CreateShortcut((Join-Path $dir 'WhispLocal.lnk'));" ^
  "  $lnk.TargetPath = 'wscript.exe';" ^
  "  $lnk.Arguments = '\"' + $app + '\WhispLocal.vbs\"';" ^
  "  $lnk.WorkingDirectory = $app;" ^
  "  $lnk.IconLocation = $app + '\icon.ico';" ^
  "  $lnk.Description = 'WhispLocal - offline voice dictation';" ^
  "  $lnk.Save();" ^
  "}"
echo Shortcuts created on Desktop and Start Menu.
pause
