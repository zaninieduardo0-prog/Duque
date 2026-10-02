#!/usr/bin/env python3
"""Script para push de uma branch local e criação de Pull Request no GitHub.
Uso: python scripts/gh_pr_create.py --branch BRANCH [--base main] [--title "..."] [--body "..."]
Requer: GH_TOKEN no ambiente com permissões repo.
Retorna JSON no stdout com resultado.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlparse


def run(cmd):
	proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
	return proc.returncode, proc.stdout, proc.stderr


def get_repo_owner_and_name():
	# lê remote origin
	code, out, err = run(["git", "config", "--get", "remote.origin.url"])
	if code != 0:
		return None
	url = out.strip()
	if url.endswith('.git'):
		url = url[:-4]
	# suportar git@github.com:owner/repo
	if url.startswith('git@'):
		# git@github.com:owner/repo
		parts = url.split(':', 1)
		if len(parts) == 2:
			path = parts[1]
		else:
			return None
	else:
		parsed = urlparse(url)
		path = parsed.path.lstrip('/')
	if '/' not in path:
		return None
	owner, repo = path.split('/', 1)
	return owner, repo


def push_branch(branch: str, remote: str = 'origin'):
	# git push -u origin branch
	# Preferir gh CLI se estiver disponível para criar PRs localmente
	code, out, err = run(["git", "push", "-u", remote, branch])
	return code == 0, out, err


def create_pr_github(owner: str, repo: str, head: str, base: str, title: str, body: str, token: str):
	import urllib.request

	url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
	data = json.dumps({"title": title, "head": head, "base": base, "body": body}).encode('utf-8')
	req = urllib.request.Request(url, data=data, headers={
		'Authorization': f'token {token}',
		'User-Agent': 'duque-assistant',
		'Accept': 'application/vnd.github.v3+json'
	})
	try:
		with urllib.request.urlopen(req) as resp:
			resp_data = resp.read().decode('utf-8')
			return True, json.loads(resp_data)
	except Exception as exc:
		return False, str(exc)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--branch', required=True)
	parser.add_argument('--base', default=os.getenv('DUQUE_DEFAULT_BASE', 'main'))
	parser.add_argument('--title', default='Proposta do Duque')
	parser.add_argument('--body', default='Proposta automática gerada pelo Duque')
	parser.add_argument('--remote', default='origin')
	args = parser.parse_args()

	branch = args.branch
	base = args.base
	title = args.title
	body = args.body

	owner_repo = get_repo_owner_and_name()
	if not owner_repo:
		print(json.dumps({"success": False, "error": "Não consegui determinar owner/repo a partir do remote origin"}))
		sys.exit(1)
	owner, repo = owner_repo

	ok, out, err = push_branch(branch, remote=args.remote)
	if not ok:
		print(json.dumps({"success": False, "error": "git push falhou", "stdout": out, "stderr": err}))
		sys.exit(1)

	token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
	# Se a CLI gh estiver disponível, use-a; caso contrário, use GH_TOKEN e GitHub API
	gh_check = run(["gh", "--version"])
	if gh_check[0] == 0:
		# usar gh cli
		code, out, err = run(["gh", "pr", "create", "--fill", "--head", branch, "--base", base, "--title", title, "--body", body])
		if code != 0:
			print(json.dumps({"success": False, "error": "gh pr create falhou", "stdout": out, "stderr": err}))
			sys.exit(1)
		# tentar recuperar PR info
		print(json.dumps({"success": True, "pr": {"note": "PR criado via gh CLI", "stdout": out}}))
		sys.exit(0)

	if not token:
		print(json.dumps({"success": False, "error": "GH_TOKEN não definido no ambiente e gh CLI não disponível"}))
		sys.exit(1)

	ok, resp = create_pr_github(owner, repo, branch, base, title, body, token)
	if not ok:
		print(json.dumps({"success": False, "error": resp}))
		sys.exit(1)

	print(json.dumps({"success": True, "pr": resp}))


if __name__ == '__main__':
	main()
