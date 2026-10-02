FROM python:3.11-slim

WORKDIR /app

# Instala dependências do sistema necessárias (ajuste conforme necessidade)
RUN apt-get update && apt-get install -y git build-essential wget ca-certificates && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY setup.cfg /app/ 2>/dev/null || true
COPY . /app/

RUN pip install --upgrade pip setuptools wheel
# Instalar dependências listadas no pyproject
RUN pip install .

EXPOSE 5000

CMD ["python", "servidor.py"]
