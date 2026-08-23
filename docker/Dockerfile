FROM python:3.11-slim

WORKDIR /app

# Install dependencies before copying source — leverages Docker layer cache
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
