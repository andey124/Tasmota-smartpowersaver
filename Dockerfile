FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY README.md ./README.md

EXPOSE 8080

CMD ["uvicorn", "desk_power_guardian.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8080"]
