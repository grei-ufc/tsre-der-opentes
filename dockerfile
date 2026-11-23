FROM python:3.12.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# O adaptador OpenDSS, o coletor, as ferramentas do caso e o caso IEEE 13.
COPY src/ ./src/
COPY data/ ./data/

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "-m", "simulators.opendss.api_opendss", "--remote", "0.0.0.0:5671"]
