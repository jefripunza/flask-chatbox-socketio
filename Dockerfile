FROM python:3.11.3-slim-buster AS backend-builder
LABEL maintainer="Jefri Herdi Triyanto jefriherditriyanto@gmail.com"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 💯 Last Configuration
RUN sed -i 's/localhost/host.docker.internal/g' .env

# Expose port (change it if needed)
EXPOSE 5000

# Run the application
CMD ["flask", "run", "--host=0.0.0.0"]
