# Recuperação da trava Sheets após resposta perdida

## Evidência de 11/11/2026 e causa comprovada no código

O Noturno FARMA encerrou cinco etapas com código zero e Analytics com código 1.
A publicação BI_Pedidos ficou parcial. O traceback mostra reset de conexão na
renovação da trava, seguido de HTTP 400 por conflito no ID reservado de metadado
quando o handler tentou registrar o erro em Controle. Isso não prova edição
humana, origem do reset ou qual POST remoto foi aplicado. Não é o aviso de
reagregação do Data Studio.

O defeito reproduzível é permitir outra renovação depois de uma mutação da trava
cuja confirmação falhou. A variável uncertain protegia gravações de fatos,
mas não todo o intervalo entre envio e confirmação da própria trava. O GET
já repetia HTTP 429/5xx, porém não falhas de transporte.

## Correção

- Marcar a trava como incerta antes de enviar sua mutação.
- Enviar o POST uma única vez; resposta perdida exige releitura exata do valor
  proposto. A releitura também verifica se o prazo confirmado ainda é válido.
- Repetir somente o GET em falhas de transporte, até seis tentativas, com
  esperas de 2, 4, 8, 16 e 30 segundos. Preservar política HTTP e relógio Google.
- Falha persistente, valor divergente ou confirmação expirada bloqueiam escritas
  subsequentes, inclusive Controle. Não apagar a trava incerta na liberação.
- Novo processo só pode obter a trava pelas guardas normais, respeitando sua
  expiração e outro proprietário. Nenhum READY ou manifesto é reparado manualmente.

Testes sintéticos reproduzem reset depois da aplicação, dois GETs falhos antes
da recuperação, confirmação indisponível após POST bem-sucedido/perdido,
conflito HTTP 400/valor antigo/outro proprietário, expiração durante confirmação,
handler real de escrita impedido de enviar fatos/Controle e retomada após expiração.
As regressões anteriores cobrem perfis, manifesto, continuações e idempotência.
O teste original falhou antes da correção. Os testes não comprovam recuperação
na planilha comercial, que permanece pendente de execução pelo operador.

## Retomada operacional

A mudança exige uma nova distribuição Windows validada. Código na main não muda
a instalação 1.5.33. Não substituir arquivos avulsos nem instalar durante carga.
Atualizar pelo Setup oficial em Preserve, preservando logs/journals e credenciais.
Após a publicação da versão corrigida e instalação, abrir o Terminal em FARMA,
confirmar a versão e executar somente Analytics:

```powershell
nexo versao
nexo analytics
```

Esse comando evita repetir Check-up/Weni/Recompra pelo Noturno. Não é retomada
por linha nem modo exclusivamente offline: Analytics executa suas próprias
consultas e validações. BI_Pedidos usa substituição da tabela e pode regravar sua
base inteira. Não usar `analytics planilhas` como atalho: é outro fluxo, de exports.
Não prometer duração nem continuação no último contador da execução interrompida.

Aguardando a correção, conservar as evidências e manter a carga pausada. Depois
exigir conclusão de BI_Pedidos, BI_Itens e resultado geral; falha de confirmação
impede declarar todas as fontes atualizadas. Work só retoma a comparação do
cartão quando o conector conseguir ler a publicação estável. O aviso de reagregação
continua sendo investigação separada. Não confirmar BI_Itens no Terminal antes
da validação e ligação efetiva da fonte no Google.

## Verificação local

Em 11/11/2026: suíte Python Linux com 2.001 testes, 73 ignorados, zero falhas;
78 testes Node aprovados; Ruff, Pyright (zero erros/avisos), consistência e
Gitleaks aprovados. Os dez módulos de assinatura permanecem idênticos à tag
v1.5.33. Sem alteração de versão, pacotes ou serviços comerciais nesta correção.
A aprovação Windows/CI/CodeQL do novo SHA e a distribuição corrigida são etapas
separadas; consultar as execuções no GitHub antes de anunciar disponibilidade.

## Retomada da preparação após indisponibilidade do GitHub

Em 11/11/2026, as tentativas de preparação, CodeQL e Meta/MCP da 1.5.34
registraram falha de inicialização, sem execução dos testes. O incidente oficial
[dvy0t3mvh1lg](https://stspg.io/jdjlq5zjyl48) afetou Actions, Pages e outros
produtos; foi resolvido às 18h21 (America/Fortaleza). A recuperação do serviço
não equivale à aprovação do código ou à publicação da versão.

A preparação será repetida em um novo commit documental, conservando a correção,
a numeração 1.5.34 e os releases anteriores. Execuções obsoletas podem ser
canceladas; não apagar commits, tags ou evidências para esconder falhas.
Publicar somente os pacotes aprovados e conferidos do mesmo SHA final.

## Distribuição concluída

Publicada em 11/11/2026, 19:12:49 (America/Fortaleza), SHA `a25ae828b6dc732ecfcafa60db145e8cf27c84f5`.
Preparação [43106347604](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43106347604)
e publicação com reutilização [43109707841](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43109707841)
aprovadas. CodeQL 43106347601 e Meta/MCP 43106366597 aprovados no mesmo SHA.
Não houve nova compilação na publicação. Os downloads públicos correspondem aos
artefatos originais. Conferidos 104 módulos Python e 485 arquivos do commit em
cada pacote, 492 entradas do manifesto Setup, executáveis x64 1.5.34.0, CRC e
contrato dos dez módulos históricos.

SHA-256 recalculados após baixar os dois ZIPs públicos:

```text
eb5164967fe6d55745212529390636df0a8d7ae9d4a14f8cae347699c1a4d036  NexoFlow-Setup-1.5.34.zip
4a8d6c2890fabdba4b7bfccbe50bd6b7f5723fa824bec4108276d87f3ffbdfbb  NexoFlow-1.5.34.zip
```

[Release e downloads oficiais](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.34).
Instalar em Preserve com cargas encerradas, conferir `nexo versao` e retomar
somente `nexo analytics` no perfil FARMA quando confirmado que não há outra carga
ativa. Não significa continuação da revisão BI_Pedidos anterior por linha.
A aplicação comercial, a conferência do manifesto após a carga e a validação dos
cartões v6 continuam pendentes. Nenhum destino comercial foi alterado nesta publicação.
