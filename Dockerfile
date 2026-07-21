FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Baixar coordenadas dos municípios no build (evita download em runtime)
RUN mkdir -p /app/.cache && \
    curl -sL -o /app/.cache/municipios_coords.csv \
    "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

EXPOSE 8050
HEALTHCHECK CMD curl --fail http://localhost:8050/doencas-agravos/ || exit 1
CMD ["gunicorn", "app:server", "-b", "0.0.0.0:8050", "--workers", "1", "--timeout", "300"]
