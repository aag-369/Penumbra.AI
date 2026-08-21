FROM python:3.11-slim AS base

# TenSEAL ships manylinux wheels, but a source build needs a toolchain and
# cmake. Kept in the image so a platform without a wheel still builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Public contexts are large; give the keystore its own volume so image layers
# stay small and keys survive a redeploy.
RUN mkdir -p /app/keystore
VOLUME ["/app/keystore"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
