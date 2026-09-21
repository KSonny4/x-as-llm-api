# Authenticated service sidecar. Existing main-1/main-2 receipts are historical;
# this hardened exact-key build needs fresh parent-owned live verification.
FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY zencli/go.mod zencli/go.sum ./
COPY zencli/*.go ./
RUN CGO_ENABLED=0 go build -trimpath -o /out/zencli .

FROM debian:bookworm-slim
ARG TARGETARCH
ARG BUILD_ID=development
# Pin the genuine CLI version whose native permission auto-rejection was tested.
ARG OPENCODE_VERSION=1.18.31
RUN test "$TARGETARCH" = amd64 \
    && apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-x64.tar.gz" \
       | tar -xz -C /usr/local/bin \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/opencode --version
COPY --from=build /out/zencli /usr/local/bin/zencli
RUN mkdir -p /usr/local/libexec/keeper-clock \
    && ln -s /usr/local/bin/zencli /usr/local/libexec/keeper-clock/sh
ENV BUILD_ID=${BUILD_ID} HOME=/tmp
USER 65532:65532
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/zencli"]
