FROM postgres:17
RUN apt-get update && apt-get install -y ca-certificates curl && \
    curl -L -o /usr/local/bin/wal-g \
      https://github.com/wal-g/wal-g/releases/download/v2.0.1/wal-g-pg-ubuntu-20.04-amd64 && \
    chmod +x /usr/local/bin/wal-g && \
    apt-get purge -y curl && rm -rf /var/lib/apt/lists/*
ENV WALG_DOWNLOAD_CONCURRENCY=4 \
    WALG_UPLOAD_CONCURRENCY=4 \
    WALG_COMPRESSION_METHOD=lz4
