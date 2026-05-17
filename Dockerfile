FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests

COPY ac_final.py .

CMD ["python", "ac_final.py"]
