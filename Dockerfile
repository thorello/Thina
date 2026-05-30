FROM node:20-alpine AS ui

WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY ui/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.py ./
COPY thina/ thina/
COPY services/ services/
COPY maps/ maps/
COPY --from=ui /ui/dist ./ui/dist

RUN mkdir -p data/audio data/run

ENV THINA_HOST=0.0.0.0
ENV THINA_PORT=8080

EXPOSE 8080

CMD ["python", "main.py"]
