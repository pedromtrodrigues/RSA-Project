FROM python:3.9-slim

WORKDIR /app/boat

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY boat.py .
COPY in_cam.json .
COPY in_denm.json .

CMD ["python3", "-u", "boat.py"]

