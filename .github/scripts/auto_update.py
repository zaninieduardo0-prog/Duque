#!/usr/bin/env python3
import os
import re
import subprocess
import json
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]

# Helper to write if changed
def write_if_changed(path: Path, content: str):
	old = path.read_text(encoding='utf-8') if path.exists() else ''
	if old != content:
		path.write_text(content, encoding='utf-8')
		return True
	return False

# 1) Expand known apps in computer/apps.py
apps_path = repo_root / 'computer' / 'apps.py'
if apps_path.exists():
	text = apps_path.read_text(encoding='utf-8')
	additions = {
		'vscode': ['code'],
		'visual studio code': ['code'],
		'spotify': ['cmd.exe', '/c', 'start', '', 'spotify:'],
		'firefox': ['cmd.exe', '/c', 'start', '', 'firefox'],
		'brave': ['cmd.exe', '/c', 'start', '', 'brave'],
		'notepad++': ['cmd.exe', '/c', 'start', '', 'notepad++'],
		'terminal': ['cmd.exe', '/c', 'start', '', 'wt'],
	}
	for name, cmd in additions.items():
		pattern = re.compile(rf"\b'{re.escape(name)}'\b")
		if not pattern.search(text):
			# Try to insert before resolve_app function end of KNOWN_APPS
			text = text.replace('}\n\n\ndef resolve_app', ',\n    ' + repr(name) + ': ' + repr(cmd) + '\n}\n\n\ndef resolve_app')
	write_if_changed(apps_path, text)

# 2) Inject AUTO_TTS toggle in interface/index.html
iface_path = repo_root / 'interface' / 'index.html'
if iface_path.exists():
	html = iface_path.read_text(encoding='utf-8')
	if 'let AUTO_TTS' not in html:
		insert_after = "/* sequência de inicialização */"
		idx = html.find(insert_after)
		if idx != -1:
			injection = "\n  // Controle de TTS automático (pode ser trocado no HUD)\n  let AUTO_TTS = true;\n  function toggleAutoTTS(){ AUTO_TTS = !AUTO_TTS; return AUTO_TTS; }\n"
			html = html[:idx+len(insert_after)] + injection + html[idx+len(insert_after):]
			write_if_changed(iface_path, html)

# 3) Ensure DUQUE_MODEL default is set to a low-latency value in brain/model.py
model_path = repo_root / 'brain' / 'model.py'
if model_path.exists():
	mtxt = model_path.read_text(encoding='utf-8')
	if 'gpt-4o-mini' not in mtxt:
		mtxt = mtxt.replace('self.model = model or os.getenv("DUQUE_MODEL", "gpt-5")', 'self.model = model or os.getenv("DUQUE_MODEL", "gpt-4o-mini")')
		write_if_changed(model_path, mtxt)

# 4) Commit changes to a branch and open a PR
changed = subprocess.run(['git', 'status', '--porcelain'], cwd=repo_root, capture_output=True, text=True).stdout.strip()
if changed:
	branch = 'autonomy/updates'
	subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], cwd=repo_root)
	subprocess.run(['git', 'config', 'user.email', 'github-actions[bot]@users.noreply.github.com'], cwd=repo_root)
	subprocess.run(['git', 'checkout', '-b', branch], cwd=repo_root)
	subprocess.run(['git', 'add', '--all'], cwd=repo_root)
	subprocess.run(['git', 'commit', '-m', 'chore(autonomy): automated updates (apps, interface, model)'], cwd=repo_root)
	# push
	subprocess.run(['git', 'push', '--set-upstream', 'origin', branch], cwd=repo_root)
	# create PR via REST API
	token = os.environ.get('GITHUB_TOKEN')
	if token:
		import urllib.request
		data = json.dumps({
			'title': 'Automated autonomy updates',
			'head': branch,
			'base': 'main',
			'body': 'Aplicações automáticas: mapeamentos de apps, toggle TTS e ajustes de modelo.'
		}).encode()
		req = urllib.request.Request(f'https://api.github.com/repos/{os.environ.get("GITHUB_REPOSITORY")}/pulls', data=data, headers={
			'Authorization': f'token {token}',
			'Accept': 'application/vnd.github.v3+json'
		})
		try:
			with urllib.request.urlopen(req) as resp:
				print('PR criado:', resp.status)
		except Exception as exc:
			print('Falha ao criar PR:', exc)
else:
	print('Nenhuma mudança detectada; nada a commitar.')
