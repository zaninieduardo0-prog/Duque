@echo off
cd /d "%~dp0"
rem Carrega as variaveis atuais do Windows (DUQUE_*, chaves). O setx so vale para janelas novas;
rem assim o Duque nunca sobe com configuracao antiga.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$keep='OPENAI_API_KEY','ANTHROPIC_API_KEY','FISH_API_KEY','OLLAMA_HOST';$user=[Environment]::GetEnvironmentVariables('User');foreach($n in @($user.Keys)){ if($n -like 'DUQUE_*' -or $keep -contains $n){ [Environment]::SetEnvironmentVariable($n,$user[$n],'Process') } };foreach($n in @([Environment]::GetEnvironmentVariables('Process').Keys)){ if($n -like 'DUQUE_*' -and -not $user.ContainsKey($n)){ [Environment]::SetEnvironmentVariable($n,$null,'Process') } };Start-Process wscript.exe -ArgumentList ('\"{0}\"' -f (Join-Path (Get-Location) 'Duque.vbs'))"
