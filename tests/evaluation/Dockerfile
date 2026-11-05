FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm bubblewrap iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir apm-cli==0.35.0 \
    && npm install -g @openai/codex@0.166.0-alpha.6
RUN useradd --uid 10001 --create-home agent && mkdir /work /state /opt/evaluation \
    && chown agent:agent /work /state
COPY evaluation/relay.py evaluation/worker.py apm_support.py native_support.py /opt/evaluation/
ENV HOME=/home/agent CODEX_HOME=/home/agent/.codex XDG_CACHE_HOME=/home/agent/.cache \
    PYTHONDONTWRITEBYTECODE=1 EVALUATION_MODEL_TOKEN=proxy-managed
USER 10001:10001
WORKDIR /work
CMD ["sleep", "infinity"]
