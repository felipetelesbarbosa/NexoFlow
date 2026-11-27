# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/hub:/opt/nexoflow/app:/opt/nexoflow:/opt/shared HUB_AMBIENTE=homologacao HUB_ESCRITA_REAL=false
WORKDIR /opt/hub
COPY hub/requirements.lock ./requirements.lock
COPY requirements.txt ./windows-requirements.txt
# A CA é opcional para redes sem inspeção e montada somente durante o build.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip --disable-pip-version-check install --no-cache-dir -r requirements.lock -r windows-requirements.txt
COPY --chown=10001:10001 hub/nexoflow_hub ./nexoflow_hub
COPY --chown=10001:10001 hub/migrations ./migrations
COPY --chown=10001:10001 app /opt/nexoflow/app
COPY --chown=10001:10001 integrations/datastudio /opt/nexoflow/integrations/datastudio
COPY --chown=10001:10001 VERSION /opt/nexoflow/VERSION
COPY --chown=10001:10001 hub/synthetic_settings.py /opt/nexoflow/secrets_config.py
RUN install -d -o 10001 -g 10001 /var/lib/nexoflow-noturno-teste
USER 10001:10001
CMD ["python", "-m", "uvicorn", "nexoflow_hub.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
