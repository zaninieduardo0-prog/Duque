"""Verifica se backends locais (gpt4all ou llama_cpp) estão disponíveis.
Uso: python scripts/check_local_model.py
Retorna 0 se encontrar algum backend funcional; imprime erros caso contrário.
"""
import os
import sys

backend = os.getenv("DUQUE_LOCAL_BACKEND", "gpt4all")
model_path = os.getenv("DUQUE_LOCAL_MODEL_PATH")

print(f"Verificando backend local: {backend}")

if backend == "gpt4all":
	try:
		from gpt4all import GPT4All
		print("gpt4all importado com sucesso")
		try:
			g = GPT4All(model=model_path) if model_path else GPT4All()
			print("Instância GPT4All criada com sucesso")
			sys.exit(0)
		except Exception as e:
			print(f"Falha ao inicializar GPT4All: {e}")
			sys.exit(2)
	except Exception as e:
		print(f"gpt4all não instalado: {e}")
		sys.exit(1)

elif backend == "llama":
	try:
		from llama_cpp import Llama
		print("llama_cpp importado com sucesso")
		if not model_path:
			print("DUQUE_LOCAL_MODEL_PATH não definido; é obrigatório para llama")
			sys.exit(2)
		try:
			l = Llama(model_path=model_path)
			print("Instância Llama criada com sucesso")
			sys.exit(0)
		except Exception as e:
			print(f"Falha ao inicializar Llama: {e}")
			sys.exit(2)
	except Exception as e:
		print(f"llama_cpp não instalado: {e}")
		sys.exit(1)

else:
	print(f"Backend desconhecido: {backend}")
	sys.exit(3)
