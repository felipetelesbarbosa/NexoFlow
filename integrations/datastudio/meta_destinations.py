"""Fontes adicionais do leitor de homologação. Compartilham a população e a revisão."""

DIM = "data conta_id moeda fuso politica_atribuicao".split()
METRICS = {
    "anuncios": "Anúncios distintos com entrega no período",
    "investimento_original": "Investimento original da conta na moeda do fato",
    "investimento_comprovado": "Investimento com destino exclusivo FARMA em todo o grupo",
    "pedidos_confirmados": "Pedidos únicos atribuídos pela rotina nativa",
    "receita_confirmada": "Receita dos pedidos atribuídos em BRL",
    "eventos_ctwa": "Eventos CTWA deduplicados no projeto",
    "wa_1": "Eventos com vigência comprovada do primeiro número",
    "wa_2": "Eventos com vigência comprovada do segundo número",
    "pendentes": "Eventos sem receptor comprovado",
    "conversas_meta": "Conversas iniciadas segundo a Meta",
    "conversas_meta_informadas": "Subtotal das conversas Meta nos fatos que informam a métrica",
    "fatos_sem_metrica_meta": "Fatos diários de anúncios sem valor para conversas Meta",
    "conversas_weni": "Conversas Weni distintas no grupo com identidade e cobertura completas",
    "dias_parciais": "Fatos diários com cobertura parcial ou desconhecida",
    "cpa": "Custo exclusivo dividido pelos pedidos do intervalo",
    "roas": "Receita em BRL dividida pelo investimento exclusivo em BRL",
}
PERIOD = ("Anuncios_Veiculados_FARMA", "Resumo_Anuncios_Veiculados_FARMA")
DETAIL = "Destinos_CTWA_Diarios"
CATALOG = "Catalogo_Destinos_Meta"


def specs():
    for name in PERIOD:
        fields = [
            *DIM,
            *([] if name == PERIOD[1] else ["anuncio_id", "campanha_nome"]),
            *METRICS,
        ]
        yield name, fields, "data"
    yield (
        DETAIL,
        [
            *DIM,
            "anuncio_id",
            "destino",
            "situacao",
            "configurado",
            "cobertura",
            "eventos_ctwa",
        ],
        "data",
    )
    yield CATALOG, ["campo", "definicao", "origem", "grao", "agregacao", "nulos"], None


def install(conn):
    conn.execute("""CREATE OR REPLACE VIEW farma.ds_destino_meta_base_v1 WITH(security_barrier=true) AS
      SELECT b.*, (nullif(d.registro->>'payload_api_json','')::jsonb)->'nf_destino_v1' AS audit,
        nullif(btrim(d.registro->>'campanha_nome'),'') AS campanha_nome
      FROM farma.ds_bi_meta_resultados b LEFT JOIN farma.nf_atuais d ON
      d.tabela='Meta_Ads_Diario' AND d.registro->>'chave'=b.chave
      WHERE b.segmento='FARMA' AND b.classificacao='FARMA'""")
    conn.execute("""CREATE OR REPLACE VIEW farma.ds_destinos_ctwa_diarios WITH(security_barrier=true) AS
      SELECT b.data,b.conta_id,b.moeda,b.fuso,b.politica_atribuicao,b.anuncio_id,
        CASE WHEN e.key IN ('WA_1','WA_2') THEN e.key ELSE 'PENDENTE' END AS destino,
        e.key AS situacao,coalesce(b.audit->>'configurado','SEM_AUDITORIA') AS configurado,
        coalesce(b.audit->>'cobertura','DESCONHECIDA') AS cobertura,e.value::numeric AS eventos_ctwa
      FROM farma.ds_destino_meta_base_v1 b CROSS JOIN LATERAL jsonb_each_text(
        coalesce(nullif(b.audit->'eventos','{}'::jsonb),
          jsonb_build_object(CASE WHEN b.audit IS NULL THEN 'SEM_AUDITORIA' ELSE 'SEM_EVENTOS' END,b.eventos_ctwa))) e""")
    conn.execute("""CREATE OR REPLACE FUNCTION farma.ds_veiculacao_meta_v3(inicio date,fim date,resumo boolean)
    RETURNS TABLE(data date,conta_id text,moeda text,fuso text,politica_atribuicao text,anuncio_id text,
      anuncios bigint,investimento_original numeric, investimento_comprovado numeric,pedidos_confirmados numeric,
      receita_confirmada numeric,eventos_ctwa numeric,wa_1 numeric,wa_2 numeric,pendentes numeric,
      conversas_meta numeric,conversas_weni bigint,dias_parciais bigint,cpa numeric,roas numeric,
      conversas_meta_informadas numeric,fatos_sem_metrica_meta bigint,campanha_nome text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $fn$
    BEGIN
      IF inicio IS NULL OR fim IS NULL OR fim<inicio THEN RAISE EXCEPTION 'DS_PERIODO_INVALIDO'; END IF;
      IF EXISTS (SELECT 1 FROM farma.ds_destino_meta_base_v1 x WHERE x.data BETWEEN inicio AND fim
        GROUP BY x.conta_id,x.anuncio_id,x.data HAVING count(*)>1) THEN
        RAISE EXCEPTION 'DS_ANUNCIOS_GRAO_AMBIGUO'; END IF;
      IF EXISTS (SELECT 1 FROM farma.ds_destino_meta_base_v1 x WHERE x.data BETWEEN inicio AND fim
        AND x.audit IS NOT NULL AND x.eventos_ctwa IS DISTINCT FROM (SELECT coalesce(sum(value::numeric),0)
          FROM jsonb_each_text(x.audit->'eventos'))) THEN RAISE EXCEPTION 'DS_DESTINOS_CONTAGEM_DIVERGENTE'; END IF;
      RETURN QUERY WITH base AS MATERIALIZED (
        SELECT b.*,bool_or(b.impressoes>0 OR b.investimento_original>0)
          OVER(PARTITION BY b.conta_id,b.anuncio_id) AS veiculado
        FROM farma.ds_destino_meta_base_v1 b WHERE b.data BETWEEN inicio AND fim
      ), identidades AS (
        SELECT b.conta_id,b.moeda,b.fuso,b.politica_atribuicao,CASE WHEN resumo THEN NULL ELSE b.anuncio_id END ad,
        count(DISTINCT i.id) n FROM base b CROSS JOIN LATERAL jsonb_array_elements_text(
          CASE WHEN jsonb_typeof(b.audit->'conversas_distintas_privadas')='array'
               THEN b.audit->'conversas_distintas_privadas' ELSE '[]'::jsonb END) i(id)
        WHERE b.veiculado GROUP BY 1,2,3,4,5
      ), grupos AS (
        SELECT b.conta_id,b.moeda,b.fuso,b.politica_atribuicao,CASE WHEN resumo THEN NULL ELSE b.anuncio_id END ad,
        count(DISTINCT b.anuncio_id) n,
        CASE WHEN count(b.investimento_original)=count(*) THEN sum(b.investimento_original) END custo,
        CASE WHEN count(*) FILTER(WHERE b.audit->>'configurado'='FARMA' AND b.investimento_atribuivel IS NOT NULL)=count(*)
          THEN sum(b.investimento_atribuivel) END exclusivo,
        CASE WHEN count(b.pedidos_confirmados)=count(*) THEN sum(b.pedidos_confirmados) END pedidos,
        CASE WHEN count(*) FILTER(WHERE b.moeda_receita='BRL' AND b.receita_confirmada IS NOT NULL)=count(*)
          THEN sum(b.receita_confirmada) END receita,
        CASE WHEN count(b.eventos_ctwa)=count(*) THEN sum(b.eventos_ctwa) END ctwa,
        sum(coalesce((b.audit->'eventos'->>'WA_1')::numeric,0)) wa1,
        sum(coalesce((b.audit->'eventos'->>'WA_2')::numeric,0)) wa2,
        CASE WHEN count(b.conversas_iniciadas_meta)=count(*) THEN sum(b.conversas_iniciadas_meta) END conv,
        sum(b.conversas_iniciadas_meta) conv_informadas,
        count(*)-count(b.conversas_iniciadas_meta) sem_metrica,
        CASE WHEN NOT resumo THEN (array_agg(b.campanha_nome ORDER BY b.data DESC)
          FILTER(WHERE b.campanha_nome IS NOT NULL))[1] END campanha,
        bool_and(coalesce(jsonb_typeof(b.audit->'conversas_distintas_privadas')='array',false)) identidades_completas,
        count(*) FILTER(WHERE b.audit->>'cobertura' IS DISTINCT FROM 'COMPLETA') parciais
        FROM base b WHERE b.veiculado GROUP BY 1,2,3,4,5
      ) SELECT inicio,g.conta_id,g.moeda,g.fuso,g.politica_atribuicao,g.ad,g.n,g.custo,g.exclusivo,
        g.pedidos,g.receita,g.ctwa,g.wa1,g.wa2,g.ctwa-g.wa1-g.wa2,g.conv,CASE WHEN g.identidades_completas THEN coalesce(i.n,0) END,g.parciais,
        g.exclusivo/nullif(g.pedidos,0),CASE WHEN g.moeda='BRL' THEN g.receita/nullif(g.exclusivo,0) END,
        g.conv_informadas,g.sem_metrica,g.campanha
        FROM grupos g LEFT JOIN identidades i ON (i.conta_id,i.moeda,i.fuso,i.politica_atribuicao)=(g.conta_id,g.moeda,g.fuso,g.politica_atribuicao) AND i.ad IS NOT DISTINCT FROM g.ad ORDER BY g.conta_id,g.moeda,g.fuso,g.politica_atribuicao,g.ad;
    END $fn$""")
    # Preserve a assinatura e a cobertura exigida pelos leitores anteriores.
    conn.execute("""CREATE OR REPLACE FUNCTION farma.ds_veiculacao_meta_v1(inicio date,fim date,resumo boolean)
    RETURNS TABLE(data date,conta_id text,moeda text,fuso text,politica_atribuicao text,anuncio_id text,
      anuncios bigint,investimento_original numeric, investimento_comprovado numeric,pedidos_confirmados numeric,
      receita_confirmada numeric,eventos_ctwa numeric,wa_1 numeric,wa_2 numeric,pendentes numeric,
      conversas_meta numeric,conversas_weni bigint,dias_parciais bigint,cpa numeric,roas numeric)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $fn$
      SELECT v.data,v.conta_id,v.moeda,v.fuso,v.politica_atribuicao,v.anuncio_id,
        v.anuncios,v.investimento_original,v.investimento_comprovado,v.pedidos_confirmados,
        v.receita_confirmada,v.eventos_ctwa,v.wa_1,v.wa_2,v.pendentes,
        v.conversas_meta,v.conversas_weni,v.dias_parciais,v.cpa,v.roas
      FROM farma.ds_veiculacao_meta_v3(inicio,fim,resumo) v
      ORDER BY v.conta_id,v.moeda,v.fuso,v.politica_atribuicao,v.anuncio_id
    $fn$""")
    conn.execute(
        "REVOKE ALL ON FUNCTION farma.ds_veiculacao_meta_v1(date,date,boolean), "
        "farma.ds_veiculacao_meta_v3(date,date,boolean) FROM PUBLIC"
    )
    conn.execute(
        "GRANT EXECUTE ON FUNCTION farma.ds_veiculacao_meta_v1(date,date,boolean), "
        "farma.ds_veiculacao_meta_v3(date,date,boolean) TO nf_ds_farma_read"
    )
    conn.execute("GRANT SELECT ON farma.ds_destinos_ctwa_diarios TO nf_ds_farma_read")
    from psycopg import sql

    rows = []
    for key, definition in METRICS.items():
        origin = (
            "Meta Insights"
            if key
            in {
                "investimento_original",
                "conversas_meta",
                "conversas_meta_informadas",
                "fatos_sem_metrica_meta",
            }
            else "Flows v2 e cadastro empresarial"
            if key in {"eventos_ctwa", "wa_1", "wa_2", "pendentes"}
            else "NexoFlow, Meta e Weni"
        )
        rows.append(
            (
                key,
                definition,
                origin,
                "conta/moeda/fuso/política no período",
                "razão das somas"
                if key in {"roas", "cpa"}
                else "distintos"
                if key in {"anuncios", "conversas_weni"}
                else "soma",
                "indisponível se nenhum fato informar a métrica"
                if key == "conversas_meta_informadas"
                else "zero quando todos os fatos informam a métrica"
                if key == "fatos_sem_metrica_meta"
                else "indisponível quando faltar cobertura, identidade ou denominador aplicável",
            )
        )
    for field, description, origin in [
        (
            "data",
            "Data inclusiva na conta. A fonte por período devolve o início selecionado.",
            "Meta Insights",
        ),
        ("conta_id", "Identificador textual da conta compartilhada.", "Meta Graph"),
        (
            "anuncio_id",
            "Identificador textual do anúncio, independente do criativo.",
            "Meta Graph",
        ),
        (
            "campanha_nome",
            "Nome mais recente informado nos fatos do anúncio no período.",
            "Meta Insights",
        ),
        ("moeda", "Moeda do investimento original.", "Meta Graph"),
        (
            "fuso",
            "Fuso da conta. Eventos Weni em America/Belem são convertidos por instante.",
            "Meta Graph e Flows",
        ),
        (
            "politica_atribuicao",
            "Versão e janelas da consulta nativa.",
            "Meta Insights",
        ),
        (
            "destino",
            "WA_1, WA_2 ou PENDENTE. Um evento entra uma vez.",
            "Weni e histórico de vínculos",
        ),
        (
            "situacao",
            "Motivo do reconhecimento ou pendência do receptor.",
            "Validação nativa",
        ),
        (
            "configurado",
            "Exclusividade na vigência do anúncio/conjunto.",
            "Configuração oficial Meta",
        ),
        (
            "cobertura",
            "Completa ou parcial no instante da coleta.",
            "Coletores FARMA e PET",
        ),
    ]:
        rows.append(
            (
                field,
                description,
                origin,
                "dimensão",
                "sem agregação",
                "ausência preservada",
            )
        )
    values = sql.SQL(",").join(
        sql.SQL("({})").format(sql.SQL(",").join(map(sql.Literal, r))) for r in rows
    )
    conn.execute(
        sql.SQL(
            "CREATE OR REPLACE VIEW farma.ds_catalogo_destinos_meta AS SELECT * FROM (VALUES {}) "
            "AS d(campo,definicao,origem,grao,agregacao,nulos)"
        ).format(values)
    )
    conn.execute("GRANT SELECT ON farma.ds_catalogo_destinos_meta TO nf_ds_farma_read")
