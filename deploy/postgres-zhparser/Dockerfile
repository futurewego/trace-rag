# PostgreSQL 16 + pgvector + zhparser (Chinese full-text segmentation)
# Powers trace-rag P2b hybrid retrieval: dense (pgvector cosine) + sparse
# (to_tsvector('zh', …) via zhparser) fused with RRF.
#
# Sources are VENDORED under vendor/ so the build needs no GitHub/registry access
# (build host cannot reach github.com; Docker Hub base is pulled via a mirror and
# retagged as pgvector/pgvector:pg16 beforehand):
#   - scws-1.2.3.tar.bz2  (release tarball WITH a pre-generated ./configure, so no
#                          autoreconf — avoids the newer-automake portability error)
#   - zhparser.tar.gz     (plain PGXS Makefile, no autotools)
#
# Build:  docker build -t trace-rag/pg-zhparser:pg16 deploy/postgres-zhparser
# Run:    docker run -d --name trace-rag-pg -p 5435:5432 \
#           -e POSTGRES_DB=ragdb -e POSTGRES_USER=raguser -e POSTGRES_PASSWORD=ragpass \
#           -v trace_rag_pg:/var/lib/postgresql/data trace-rag/pg-zhparser:pg16
FROM pgvector/pgvector:pg16

USER root

COPY vendor/scws-1.2.3.tar.bz2 vendor/zhparser.tar.gz /tmp/

RUN set -eux; \
    # China mirror for Debian apt (build host cannot reach deb.debian.org fast).
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates bzip2 build-essential postgresql-server-dev-16; \
    # --- SCWS 1.2.3 (release tarball ships ./configure, no autoreconf needed) ---
    cd /tmp; tar xjf scws-1.2.3.tar.bz2; cd scws-1.2.3; \
    ./configure --prefix=/usr/local; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    # --- zhparser (links against SCWS at /usr/local) ---
    cd /tmp; tar xzf zhparser.tar.gz; cd zhparser-master; \
    SCWS_HOME=/usr/local make -j"$(nproc)"; \
    make install; \
    # --- slim: drop the build toolchain, keep runtime .so + libscws ---
    apt-get purge -y --auto-remove bzip2 build-essential postgresql-server-dev-16; \
    rm -rf /tmp/scws* /tmp/zhparser* /var/lib/apt/lists/*

# First-init provisioning: extensions available in the app database.
# The 'zh' text-search configuration + the sparse GIN index are owned by the
# alembic migration (schema lives in code), not here.
COPY init-extensions.sql /docker-entrypoint-initdb.d/01-init.sql

USER postgres
