FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py index.html login.html prompt_sinki.txt chart.umd.min.js ./
COPY montador-dossie/ ./montador-dossie/
COPY biblioteca-tcu/ ./biblioteca-tcu/

RUN mkdir -p /app/uploads
ENV UPLOAD_DIR=/app/uploads

EXPOSE 8080

# --timeout é o tempo TOTAL que um worker pode passar numa requisição, não um
# tempo ocioso: análise de edital grande com Opus 5 passa dos 5 minutos que
# estavam aqui, e o worker era morto no meio da espera pela resposta da API
# (WORKER TIMEOUT em 30/07/2026, duas vezes seguidas, na proposta da Conasa).
# Continuam 2 workers de propósito: a instância é free (512 MB) e subir esse
# número gastaria memória que não sobra — o próprio gunicorn já suspeitou de
# falta de memória naquele log.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "900", "--graceful-timeout", "60", "app:app"]
