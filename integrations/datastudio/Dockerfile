FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
ARG NEXOFLOW_SOURCE_SHA=unversioned
LABEL org.opencontainers.image.revision=$NEXOFLOW_SOURCE_SHA
WORKDIR /opt/nexoflow
COPY --chmod=0444 VERSION /opt/nexoflow/VERSION
COPY integrations/datastudio/requirements.lock /tmp/requirements.lock
# CA opcional de build como secret; não persistir CA corporativa nem desativar TLS.
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \
    pip --disable-pip-version-check install --no-cache-dir -r /tmp/requirements.lock && \
    useradd --uid 10001 --no-create-home publisher
COPY --chown=10001:10001 app /opt/nexoflow/app
COPY --chown=10001:10001 integrations /opt/nexoflow/integrations
RUN chmod -R a+rX /opt/nexoflow/app /opt/nexoflow/integrations
ENV NEXOFLOW_SOURCE_SHA=$NEXOFLOW_SOURCE_SHA
ENV PYTHONPATH=/opt/nexoflow/app:/opt/nexoflow PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 CMD python -m integrations.datastudio.health
CMD ["uvicorn","integrations.datastudio.runtime:app_factory","--factory","--host","0.0.0.0","--port","8080","--no-access-log","--limit-concurrency","8","--timeout-keep-alive","5"]
