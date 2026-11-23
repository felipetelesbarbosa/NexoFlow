-- Executar pelo psql com o administrador do PostgreSQL exclusivo da homologação.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('nexoflow_hub_hml.central.leitor'));

DO $$
BEGIN
    IF current_database() <> 'nexoflow_hub_hml' OR
       to_regclass('hub.central_tarefas') IS NULL OR to_regclass('hub.central_eventos') IS NULL THEN
        RAISE EXCEPTION 'CENTRAL_DESTINO_OU_VISOES_INVALIDAS';
    END IF;
    IF EXISTS (
        SELECT FROM pg_roles r WHERE r.rolname = 'hub_central_leitor'
        AND (NOT r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
             OR r.rolreplication OR r.rolbypassrls
             OR EXISTS (SELECT FROM pg_auth_members m WHERE m.member = r.oid))
    ) THEN
        RAISE EXCEPTION 'CENTRAL_PAPEL_INCOMPATIVEL';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hub_central_leitor') THEN
        DECLARE
            senha text := btrim(pg_read_file('/run/secrets/central_password'), E'\n\r ');
        BEGIN
            IF length(senha) < 32 THEN
                RAISE EXCEPTION 'CENTRAL_CREDENCIAL_INSUFICIENTE';
            END IF;
            EXECUTE format('CREATE ROLE hub_central_leitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', senha);
        END;
    END IF;
END
$$;
GRANT CONNECT ON DATABASE nexoflow_hub_hml TO hub_central_leitor;
GRANT USAGE ON SCHEMA hub TO hub_central_leitor;
GRANT SELECT ON hub.central_tarefas, hub.central_eventos TO hub_central_leitor;
ALTER ROLE hub_central_leitor IN DATABASE nexoflow_hub_hml SET default_transaction_read_only TO on;

DO $$
BEGIN
    IF has_database_privilege('hub_central_leitor', current_database(), 'CREATE,TEMP')
       OR has_schema_privilege('hub_central_leitor', 'hub', 'CREATE')
       OR EXISTS (
           SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'hub' AND c.relkind IN ('r','p','v','m','f')
           AND (has_table_privilege('hub_central_leitor', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES')
                OR has_any_column_privilege('hub_central_leitor', c.oid, 'INSERT,UPDATE,REFERENCES')
                OR (c.relname NOT IN ('central_tarefas','central_eventos')
                    AND has_any_column_privilege('hub_central_leitor', c.oid, 'SELECT')))
       ) THEN
        RAISE EXCEPTION 'CENTRAL_PRIVILEGIO_EXCESSIVO';
    END IF;
END
$$;
COMMIT;
