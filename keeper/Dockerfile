FROM python:3.12-slim
# keeper-alloy keeps only server-* containers carrying this label: other jobs'
# "server" tasks (Cognee, Node apps) must not land in service=keeper-server.
LABEL org.opencontainers.image.title="keeper"
WORKDIR /srv/keeper
COPY server.py smoke.py translate.py matrix.py aa.py inventory.py keyqueue.json probe-seed.json ./
COPY availability.py store.py credentials.py discovery.py inference.py sweeps.py selection.py api_v2.py runtime.py legacy_view.py service_api.py service_wire.py zencli_bridge.py tracing.py ./
COPY usage.py usage_metrics.py dashboard.py dashboard.html dashboard.js dashboard.css ./
ARG BUILD_ID=development
ENV PORT=8080 BUILD_ID=${BUILD_ID} PYTHONDONTWRITEBYTECODE=1
RUN python3 -c "import server, runtime, service_api, service_wire, dashboard; assert all((dashboard.ROOT / f).exists() for f, _ in dashboard.ASSETS.values())"
EXPOSE 8080
CMD ["python3", "server.py"]
