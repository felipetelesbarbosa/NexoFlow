# NexoFlow 1.0 — Changelog

## NexoFlow 1.0

### Diagnóstico privado dos CPFs com HTTP 500

- arquivo JSONL privado por execução identifica CPFs com falhas 5xx persistentes e correlaciona as referências do log;
- registro inclui horário de Belém, último HTTP 5xx, tentativas, motivo de encerramento e campos sanitizados da resposta;
- captura também consultas interrompidas pelo circuito enquanto aguardam nova tentativa;
- consultas recuperadas e testes com CPF fictício não criam registros privados de falha;
- Windows usa a pasta privada do usuário em LocalAppData, separada da instalação;
- logs normais mantêm referências anônimas; CPF e corpo diagnóstico não são impressos;
- Git e build protegem os registros contra publicação; falha de disco não substitui o erro original da API.

### Diagnóstico de rede e proxy

- diagnóstico sanitizado da Weni distingue HTTP 407/403 no proxy, certificado TLS, DNS, timeout e conexão recusada, incluindo exceções aninhadas;
- causas explícitas não transitórias encerram o retry da Weni sem repetir a mesma falha;
- diagnóstico mostra a rota efetiva da Weni, respeitando exceções de proxy;
- logs do diagnóstico usam America/Belem (UTC-3) e persistência local;
- avisos de rede do Google Sheets incluem categoria segura, sem texto bruto da exceção;
- HTTP 400/404 no CPF fictício da FarmaLíder é apresentado como resposta de rede, com autenticação não confirmada;
- diagnóstico não desativa TLS nem altera automaticamente a rota escolhida.

### Auditoria dos campos de pedido

- listas separadas por vírgula usam aspas CSV quando o nome contém vírgula, aspas ou quebra de linha, preservando o nome completo e a correspondência com quantidade e valor;
- Weni e Analytics compartilham a mesma leitura das listas, incluindo nomes como `Produto 0,5 MG`;
- auditoria verifica também atualizações parciais das listas e informa as contagens sem expor produtos;
- pagamento 5 corresponde a **Pix por Link de Pagamento** e pagamento 6 a **PIX no POS**;
- pagamento 0 é tratado como cancelamento: Weni recebe `pedido_forma_pagamento=CANCELADO` e `pedido_status=3`, sem venda nem atualização de `ultima_compra`;
- códigos numéricos de pagamento sem de-para a partir de 7 são preservados como Int32 não negativo na Weni e apresentados no Google Sheets/BI como `Não identificado (código X)`, sem inventar o de-para;
- pagamentos sem de-para geram `INFO` uma vez por código em cada execução, com totais por código no resumo;
- resumo distingue contatos com pedido validado pela API, inclusive sem alterações, de contatos com alterações; preparação e auditoria acontecem antes das gravações;
- listas realmente desalinhadas, CSV malformado, elementos vazios e códigos inválidos continuam bloqueados antes de qualquer gravação.

### Recuperação e diagnóstico da FarmaLíder

- pausas globais de 5, 10 e 20 segundos após falhas 5xx, inclusive proteção após a última tentativa;
- recuperação com uma requisição por vez e retorno gradual para duas e quatro;
- intervalo adaptativo reduzido após respostas saudáveis, evitando manter toda a carga em ritmo lento;
- circuito por rota interrompe falhas persistentes em várias consultas sem respostas válidas;
- diagnóstico por referência HMAC, categoria segura da resposta, latência, limite e quantidade em voo;
- identificação de rastreamento do servidor registrada somente quando é um UUID válido;
- horários de log sempre em America/Belem (UTC-3);
- falhas individuais preservam dados de cliente anteriores, registram `ERRO_API` e evitam GET duplicado por CPF;
- execução parcial retorna código 3 e mantém o marco incremental para nova tentativa;
- empacotamento bloqueia arquivos privados rastreados antes da publicação.

### Setup

- Setup validado em Windows com primeira instalação e atualização real;
- atualização com rollback automático para a instalação anterior em caso de falha;
- elevação UAC automática quando necessária;
- modo não interativo para smoke tests e automação;
- `NexoFlow Uninstall.exe` realmente opcional inclusive na validação de integridade do payload;
- cenário de antivírus/EDR removendo o Uninstall opcional coberto por smoke test;
- preservação de `secrets_config.py`, `credentials` e `logs` verificada em atualização;
- publicação do NexoFlow 1.0 bloqueada se testes, auditoria, build ou smoke test falharem.


### Pedidos e status na Weni

- a FarmaLíder API é a fonte de verdade dos pedidos; `pedido_id` e `ultimo_pedido` da Weni são localizadores para recuperação;
- novo campo `pedido_status` é preenchido pelo NexoFlow Weni após consultar o mesmo `pedido_id` na FarmaLíder API;
- valores atuais de `pedido_status`: **-1 Pendente pagamento**, **0 Em processamento**, **1 Em trânsito**, **2 Concluído** e **3 Cancelado**; **4 Pronto para rota** permanece aceito como legado, fora do enum atual;
- cancelamento explícito ou pagamento 0 prevalece e grava o status efetivo **3, Cancelado** na Weni/BI;
- `Pedidos_FarmaLider` preserva os códigos brutos de status e pagamento retornados pela API para auditoria;
- somente status efetivo 2, Concluído, validado pela API e sem cancelamento entra nos indicadores de venda e atualiza `ultima_compra`;
- `pedido_status` também é preservado na `Base_Contatos` para Google Sheets/Looker Studio;
- pedidos em **Pendente pagamento**, **Em processamento**, **Em trânsito** ou no estado legado **Pronto para rota** ficam numa fila persistente de rechecagem até chegarem a **Concluído** ou **Cancelado**, mesmo sem nova mensagem na Weni.

Data de consolidação: 05/10/2026.

Esta documentação descreve exclusivamente o **NexoFlow 1.0**.

### Analytics e BI

- sincronização Weni → FarmaLíder → Google Sheets com carga completa e incremental;
- preservação de todos os contatos retornados pela Weni na `Base_Contatos`;
- validação e enriquecimento de CPF/cliente pela API FarmaLíder;
- processamento de pedidos e itens confirmados;
- camada BI mantida pelo Analytics com `BI_Resumo_Diario`, `BI_Canais`, `BI_Conversao`, `BI_Vendas`, `BI_Ads` e `BI_Status`;
- batches adaptativos no Google Sheets, redução de leituras/escritas redundantes, retry/backoff e progresso operacional;
- cache seguro da FarmaLíder no incremental e revalidação integral na carga completa.

### NexoFlow Weni

- atualização auditada de campos de contato diretamente pela API Weni;
- identificação multicanal por WhatsApp, Instagram, Facebook/Messenger e outras URNs nativas;
- captura e validação de CPF, idade, maioridade e LGPD com contexto;
- sincronização de grupos Opt-In/Opt-Out LGPD;
- confirmação de pedido e última compra via FarmaLíder antes da escrita transacional;
- atribuição conservadora de Meta/Google Ads com first touch e last touch;
- carga completa com dry-run, revisão humana, snapshot congelado, SHA-256, releitura por contato, conflitos isolados e checkpoint seguro.

### Operação e distribuição

- `NexoFlow Analytics.exe`, `NexoFlow Weni.exe` e `NexoFlow Terminal.exe`;
- CLI `nexo` para status, diagnóstico, rotinas Weni, Analytics, APIs somente leitura e logs;
- Setup com validação SHA-256 do payload, Python 3.11+ x64, `.venv`, preservação de dados privados e atalhos Windows;
- desinstalação via `installer\uninstall.ps1` com wrapper `desinstalar_nexoflow.cmd`;
- `NexoFlow Uninstall.exe` incluído como launcher opcional, sem se tornar requisito do Setup ou do check-up; em ambientes onde antivírus/EDR o bloqueiem, a instalação e a desinstalação por script continuam funcionando normalmente;
- launchers nativos sem `system()`, sem packers/ofuscação e sem credenciais embutidas;
- check-up, testes automatizados e auditoria de consistência.

### Identidade do NexoFlow 1.0

- versão pública e lógica: **NexoFlow 1.0**;
- metadados de instalação e comandos `nexo versao`/`nexo status`: **1.0**;
- recursos de versão dos executáveis Windows: **1.0.0.0** (representação de quatro componentes exigida pelo formato VERSIONINFO do Windows).
