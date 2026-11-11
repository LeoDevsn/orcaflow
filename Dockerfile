FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY orca_flow ./orca_flow
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 orcaflow && mkdir /data && chown orcaflow:orcaflow /data
USER orcaflow
VOLUME ["/data"]
EXPOSE 7460
ENV PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:7460/health', timeout=3)"
CMD ["python", "-m", "orca_flow", "--data-dir", "/data", "--server", "--host", "0.0.0.0", "--port", "7460"]
