FROM python:3.9-slim

WORKDIR /app/rsu

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

COPY rsu.py .
COPY in_cam.json .
COPY in_denm.json .


EXPOSE 8000
CMD ["python3", "-u", "rsu.py"]

