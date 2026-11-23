LOCK TABLE hub.eventos_weni IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM hub.eventos_weni) THEN
        RAISE EXCEPTION 'ROLLBACK_EVENTOS_COM_DADOS_BLOQUEADO';
    END IF;
END $$;
DROP VIEW hub.central_eventos, hub.central_tarefas;
DROP INDEX hub.tarefas_central;
DROP TABLE hub.eventos_weni;
DELETE FROM hub.migracoes WHERE versao=3;
