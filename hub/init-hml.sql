-- Exclusivo do PostgreSQL TEMPORÁRIO da homologação. Não aplicar na VPS.
SELECT format('CREATE ROLE hub_hml LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', btrim(pg_read_file('/run/secrets/runtime_password'), E'\n\r ')) \gexec
CREATE DATABASE nexoflow_hub_hml OWNER hub_hml;
REVOKE ALL ON DATABASE nexoflow_hub_hml FROM PUBLIC;
GRANT CONNECT ON DATABASE nexoflow_hub_hml TO hub_hml;
