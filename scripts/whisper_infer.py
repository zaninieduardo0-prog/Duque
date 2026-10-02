#!/usr/bin/env python3
"""Placeholder para integrar Whisper local (ou similar).
Este script espera um caminho para um arquivo WAV e retorna transcrição JSON.
Requer instalação de modelos e bibliotecas (openai/whisper or whisper-ctr). Não baixa pesos.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('wav', help='arquivo wav a transcrever')
	args = parser.parse_args()

	# Tentativa simples: se 'whisper' estiver instalado no PATH (pipx script), use-o
	try:
		code = subprocess.run(['whisper', args.wav, '--model', 'small', '--language', 'pt'], capture_output=True, text=True)
		if code.returncode == 0:
			# Whisper tende a salvar arquivo .txt; tentamos ler
			txt = args.wav + '.txt'
			if os.path.exists(txt):
				with open(txt, 'r', encoding='utf-8') as fh:
					text = fh.read()
				print(json.dumps({'success': True, 'text': text}))
				return
		print(json.dumps({'success': False, 'error': 'whisper CLI falhou', 'stdout': code.stdout, 'stderr': code.stderr}))
	except FileNotFoundError:
		print(json.dumps({'success': False, 'error': 'whisper CLI não encontrado'}))

if __name__ == '__main__':
	main()
