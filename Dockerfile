FROM python:3.12-slim

# kubectl - required by the Kubernetes topology connector (WP_TOPOLOGY=k8s).
# In a pod it uses the in-cluster ServiceAccount automatically (empty context).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && ARCH=$(dpkg --print-architecture) \
 && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/v1.30.5/bin/linux/${ARCH}/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY woodpecker_mcp ./woodpecker_mcp
RUN pip install --no-cache-dir .

# Graph DB persists here; mount a volume to keep it across restarts.
ENV WP_KUZU_PATH=/data/woodpecker.kuzu \
    WP_HTTP_HOST=0.0.0.0

RUN mkdir -p /data && useradd -u 10001 wp && chown -R wp /data
USER wp

EXPOSE 8000
ENTRYPOINT ["woodpecker-mcp"]
CMD ["serve", "--http", "--port", "8000"]
