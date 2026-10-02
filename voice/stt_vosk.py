"""Interface mínima para STT local usando VOSK. Não baixa modelos automaticamente.
Instalação sugerida: pip install vosk soundfile
Baixar modelo VOSK e definir DUQUE_VOSK_MODEL_PATH.
"""
from __future__ import annotations

import os
import logging

log = logging.getLogger("duque.stt")

try:
	from vosk import Model, KaldiRecognizer
except Exception:
	Model = None
	KaldiRecognizer = None


def transcribe_wav(path: str) -> dict[str, object]:
	if Model is None or KaldiRecognizer is None:
		return {"success": False, "error": "vosk não instalado"}
	model_path = os.getenv("DUQUE_VOSK_MODEL_PATH")
	if not model_path:
		return {"success": False, "error": "DUQUE_VOSK_MODEL_PATH não configurado"}
	try:
		import wave

		wf = wave.open(path, "rb")
		if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
			return {"success": False, "error": "WAV deve ser mono 16-bit"}
		model = Model(model_path)
		rec = KaldiRecognizer(model, wf.getframerate())
		results = []
		while True:
			data = wf.readframes(4000)
			if len(data) == 0:
				break
			if rec.AcceptWaveform(data):
				results.append(rec.Result())
		results.append(rec.FinalResult())
		return {"success": True, "results": results}
	except Exception as exc:
		log.exception("Erro VOSK")
		return {"success": False, "error": str(exc)}
