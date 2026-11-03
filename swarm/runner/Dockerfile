# Swarm runner: official Claude Code CLI (pinned), non-root, no extra privileges. Build args come from config/versions.lock.
ARG NODE_IMAGE=node:22-slim
FROM ${NODE_IMAGE}
ARG CLAUDE_CODE_VERSION
RUN test -n "$CLAUDE_CODE_VERSION" || (echo "CLAUDE_CODE_VERSION build-arg is required (config/versions.lock)" && false)
RUN apt-get update && apt-get install -y --no-install-recommends git python3 ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm cache clean --force
COPY hooks/swarm_hook.py /opt/swarm/swarm_hook.py
COPY settings.json /opt/swarm/settings.json
COPY entrypoint.sh /opt/swarm/entrypoint.sh
RUN useradd -m -u 10001 swarm && chmod 0555 /opt/swarm/entrypoint.sh && mkdir -p /swarm-out && chown 10001:10001 /swarm-out
USER 10001:10001
WORKDIR /work
ENV HOME=/home/swarm
ENTRYPOINT ["/opt/swarm/entrypoint.sh"]
