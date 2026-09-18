# keeper-probe image: on-demand dual prober (L1 curl always, L2 opencode
# CLI only on L1 non-ok). No secrets baked: opencode auth arrives via a
# Nomad template file (OPENCODE_AUTH_FILE), copied into place at start.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip python3 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path
ENV HOME=/root \
    PATH="/root/.opencode/bin:${PATH}"
WORKDIR /srv/probe
COPY probe/worker.py probe/dispatch.py keeper/smoke.py ./
COPY probe/entry.sh /usr/local/bin/probe-entry.sh
ENTRYPOINT ["/usr/local/bin/probe-entry.sh"]
CMD ["python3", "/srv/probe/dispatch.py"]
