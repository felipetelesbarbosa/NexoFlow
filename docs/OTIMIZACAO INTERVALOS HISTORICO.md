# Intervalos contíguos no publicador histórico

Desenvolvimento autorizado em 10/11/2026, posterior à release 1.5.31. A distribuição [1.5.32 foi publicada em 10/11/2026](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.32) após validação; não substituir módulos avulsos na instalação. Nenhum dado comercial foi consultado ou escrito nesta tarefa.

## Problema e alteração

`BulkTransport.read_rows` já reunia cabeçalho e linhas em um batchGet, mas enviava um endereço por linha. Um lote denso de 200 linhas usava 201 intervalos e recebia 201 objetos valueRanges. Isso multiplica metadados/endereço e o trabalho de serialização, embora seja uma única chamada HTTP.

Agora o transporte ordena/deduplica as posições existentes para montar intervalos exclusivamente contíguos. Lacunas não são lidas. Depois restaura a ordem original solicitada, inclusive posições repetidas. Posições futuras continuam vazias sem ampliar a grade antes do backup/reserva.

| Medida sintética: Historico_Pedidos, linhas 2–201, 15 colunas | Antes | Depois |
| --- | ---: | ---: |
| Linhas de dados conferidas | 200 | 200 |
| Intervalos enviados (inclui cabeçalho) | 201 | 2 |
| Soma de caracteres dos endereços A1 | 5.613 | 52 |
| Chamadas values_batch_get | 1 | 1 |

A soma de endereços não é tamanho total da requisição, nem bytes de toda a resposta. Os valores das células continuam sendo transferidos. Não se promete redução proporcional do tempo, eliminação de 429 ou aumento de throughput em produção. Benefício depende da contiguidade; linhas isoladas continuam com intervalos separados. Quotas e ritmo preventivo permanecem intactos.

## Invariantes e falhas

- Trava, origem física, geometria e cabeçalho são conferidos novamente em cada leitura; nenhum cache de segurança foi adicionado.
- FORMULA continua sendo o modo de leitura; células com fórmulas/zeros são preservadas para a comparação existente.
- Omissão de linhas vazias finais no contrato Sheets é preenchida como vazio nas posições corretas; vazio intermediário não desloca linhas.
- Ausência de um valueRange, linhas excedentes ou colunas excedentes bloqueiam, em vez de aprovar um lote parcial.
- Não há mudança de schemas, chaves, centavos, status, consentimento, identidade, exclusões, backups, reserva, publicação, conferência financeira ou rollback.
- Os dez módulos de assinatura protegidos em AGENTS permanecem sem alteração. A otimização é exclusiva de app/history_sheets_bulk.py, usada pelo Terminal e pela automação histórica do Analytics; não altera o contrato de dados do Hub ou implanta serviços.

## Evidências e reprodução

Antes da correção, os novos testes de lote denso/esparso e resposta agrupada falharam com o código anterior. Depois, as regressões exercitam valores equivalentes ao transporte de referência, intervalos mínimos, ordem/duplicatas, linhas futuras, vazios finais/intermediários, fórmulas, zeros, edição externa, resposta incompleta e dimensões divergentes.

As integrações existentes exercitam o publicador real sobre Sheets/Drive simulados: frações, mesma revisão, resposta perdida, quota, conferência ao centavo, retomada, rollback e idempotência. O Analytics mantém os testes de isolamento FARMA/PET. Não foi executado endpoint comercial ou refeito histórico para medir desempenho.

```sh
python -m unittest tests.test_history_sheets_bulk tests.test_analytics_history_sync tests.test_history_sheets_transport tests.test_history_publication tests.test_history_reconciliation tests.test_history_conference
```

Ver a [Base Mestre](planejamento/DIRETRIZES_E_CONHECIMENTO_NEXOFLOW.md) e o [guia de Analytics](ANALYTICS%20HISTORICO%20AUTOMATICO.md). A suíte completa e os checks do projeto são executados antes do commit; o CI automático registra a validação Windows no SHA enviado.

## Distribuição e homologação posterior

A entrega 1.5.32 usa o workflow oficial com Windows, executáveis, Setup Preserve/Clean/rollback e conferência dos ZIPs. Os commits preparatórios usam [skip release]. A 1.5.31 e suas tags/pacotes permanecem intactos. A otimização só chega ao PC após atualizar pelo novo Setup em Preserve; não exige repetir a coleta histórica.

No ambiente autorizado, registrar tempo total, chamadas, espera preventiva, bytes quando disponíveis e lotes confirmados do mesmo recorte. Comparar valores e fechamento mensal/TOTAL ao centavo. Não apagar journals, iniciar carga anual adicional ou aumentar quotas para demonstrar ganho. Não há medição real no PC do usuário, Kaspersky, proxy ou Google Sheets nesta entrega.

## Resultado local da entrega

- 78 regressões dirigidas do publicador, Analytics, transporte, reconciliação e conferência: aprovadas.
- Suíte Python: 1.980 testes executados, 73 ignorados por ambiente, zero falhas.
- 33 testes Node dos conectores: aprovados.
- Ruff, Pyright (zero erros/avisos), consistência, HTML gerado, pip-audit e Gitleaks staged: aprovados.
- Nenhum dos dez módulos protegidos mudou. Windows, executáveis instalados e transporte Google real não foram executados localmente; conferir o CI do commit antes de distribuir.

## Publicação comprovada

Tag v1.5.32 no SHA `9d4be5d911a817a09773fc843f7674a6480e0b71`; publicada em 10/11/2026, 19:16:49 (America/Fortaleza). [Workflow](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/42908265073) e CodeQL aprovados. Downloads públicos conferidos: SHA-256, CRC, manifesto, 104 módulos comparados ao commit, executáveis x64/pt-BR/1.5.32.0 e contrato anterior preservado nos dois ZIPs. Setup Preserve/Clean/rollback e pacote instalado passaram no Windows CI, sem validar o PC/rede/Google comercial do usuário. Registro posterior é exclusivamente documental; não muda tag, código ou bytes dos pacotes publicados.
