FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8050
HEALTHCHECK CMD curl --fail http://localhost:8050/doencas-agravos/ || exit 1
CMD ["gunicorn", "app:server", "-b", "0.0.0.0:8050", "--workers", "1", "--timeout", "180"]
