"""Módulo simples para TTS local usando pyttsx3 (cross-platform)."""
from __future__ import annotations

import os
import threading
import tempfile
import logging

log = logging.getLogger("duque.voz")

try:
	import pyttsx3
except Exception:
	pyttsx3 = None


class LocalTTS:
	def __init__(self):
		if pyttsx3 is None:
			raise RuntimeError("pyttsx3 não está instalado. Instale com 'pip install pyttsx3'")
		self.engine = pyttsx3.init()
		# Ajustes padrão (pode ser alterado por variáveis de ambiente)
		rate = int(os.getenv("DUQUE_TTS_RATE", "170"))
		self.engine.setProperty("rate", rate)
		pitch = os.getenv("DUQUE_TTS_PITCH")
		# pyttsx3 não possui propriedade pitch de forma consistente; ignorar se ausente
		self.lock = threading.Lock()

	def speak_to_file(self, text: str, path: str) -> dict[str, object]:
		try:
			with self.lock:
				# pyttsx3 salva em arquivo WAV via salvar para arquivo; comportamento depende do driver
				self.engine.save_to_file(text, path)
				self.engine.runAndWait()
			return {"success": True, "path": path}
		except Exception as exc:
			log.exception("Erro TTS local")
			return {"success": False, "error": str(exc)}

	def speak(self, text: str) -> dict[str, object]:
		try:
			with self.lock:
				self.engine.say(text)
				self.engine.runAndWait()
			return {"success": True}
		except Exception as exc:
			log.exception("Erro ao falar")
			return {"success": False, "error": str(exc)}
