# zencli Nomad validation image: static Go server + opencode CLI.
# No secrets baked: opencode auth arrives via Nomad -var template
# (opencode_auth_json), staged at start. Build (repo root context):
#   GOOS=linux GOARCH=amd64 go build -o zencli/zencli-linux ./zencli/
#   docker build -f zencli/Dockerfile -t registry.pkubelka.cz/zencli:main-1 .
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path
ENV HOME=/root \
    PATH="/root/.opencode/bin:/usr/local/bin:${PATH}"
WORKDIR /srv/zencli
COPY zencli/zencli-linux ./zencli
COPY zencli/entry.sh /usr/local/bin/zencli-entry.sh
ENTRYPOINT ["/usr/local/bin/zencli-entry.sh"]
