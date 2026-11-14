FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY services ./services
COPY assets/boostio_icone.png ./assets/boostio_icone.png

# Estado persistente (sessão do Telegram e data/ultima_enviada.json):
# o processo roda com /state como diretório atual, então os caminhos
# relativos do código caem no volume sem nenhuma alteração.
WORKDIR /state

CMD ["python", "/app/main.py"]
