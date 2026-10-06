# Changelog — NexoFlow 1.0

## 1.0 — Release consolidada

### Estabilidade do Setup

- Setup validado em Windows com primeira instalação e atualização real;
- atualização com rollback automático para a instalação anterior em caso de falha;
- elevação UAC automática quando necessária;
- modo não interativo para smoke tests e automação;
- `NexoFlow Uninstall.exe` realmente opcional inclusive na validação de integridade do payload;
- cenário de antivírus/EDR removendo o Uninstall opcional coberto por smoke test;
- preservação de `secrets_config.py`, `credentials` e `logs` verificada em atualização;
- publicação da Release v1.0 bloqueada se testes, auditoria, build ou smoke test falharem.


### Pedidos e status na Weni

- `ultimo_pedido` é a fonte prioritária para ID, data, produtos, quantidades e valores;
- novo campo `pedido_status` é preenchido pelo NexoFlow Weni após consultar o mesmo `pedido_id` na FarmaLíder API;
- valores oficiais de `pedido_status`: **Em processamento**, **Em trânsito**, **Concluído**, **Cancelado** e **Pronto para rota**;
- cancelamento explícito sempre prevalece e grava **Cancelado**;
- status 0, 1, 2 e 4 contam como pedido feito; somente status 3 fica fora dos indicadores;
- `pedido_status` também é preservado na `Base_Contatos` para Google Sheets/Looker Studio;
- pedidos em **Em processamento**, **Em trânsito** ou **Pronto para rota** ficam numa fila persistente de rechecagem até chegarem a **Concluído** ou **Cancelado**, mesmo sem nova mensagem na Weni.

Data de consolidação: 05/10/2026.

Esta é a release pública consolidada do NexoFlow. O histórico de versões de desenvolvimento foi removido do pacote; a documentação passa a tratar esta base funcional exclusivamente como **NexoFlow 1.0**.

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

### Identidade da release

- versão pública e lógica: **NexoFlow 1.0**;
- metadados de instalação e comandos `nexo versao`/`nexo status`: **1.0**;
- recursos de versão dos executáveis Windows: **1.0.0.0** (representação de quatro componentes exigida pelo formato VERSIONINFO do Windows).
