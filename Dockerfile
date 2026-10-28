FROM python:3.12-slim-bookworm AS wirelog
ARG WIRELOG_REV=63f75a25139795b79f0ca75783c9d771c8fc892f
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates pkg-config cmake && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir meson==1.9.1 ninja==1.13.0
RUN git init /opt/wirelog-src && cd /opt/wirelog-src && git remote add origin https://github.com/semantic-reasoning/wirelog.git && git fetch --depth 1 origin ${WIRELOG_REV} && git checkout FETCH_HEAD
RUN meson setup /opt/wirelog-src/build /opt/wirelog-src --prefix=/usr/local --libdir=lib -Dtests=false -Dwirelog_log_max_level=error -Db_lto=false && meson compile -C /opt/wirelog-src/build && meson install -C /opt/wirelog-src/build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
ARG WIRELOG_REV=63f75a25139795b79f0ca75783c9d771c8fc892f
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WIRELOG_LIBRARY=/usr/local/lib/libwirelog.so WIRELOG_REV=${WIRELOG_REV} LINKMERCE_ROOT=/source/linkmerce
COPY --from=wirelog /usr/local/lib/libwirelog.so* /usr/local/lib/
COPY --from=wirelog /usr/local/lib/libnanoarrow.so* /usr/local/lib/
COPY --from=wirelog /usr/local/lib/libxxhash.so* /usr/local/lib/
COPY --from=wirelog /opt/wirelog-src /opt/wirelog-src
RUN ldconfig && useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY ontology ontology
COPY tests tests
COPY scripts scripts
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
