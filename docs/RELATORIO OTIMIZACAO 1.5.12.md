# NexoFlow 1.5.12 — Diagnóstico e otimização

**Situação:** implementação em validação, sem publicação nesta etapa. As verificações descritas usam dados sintéticos ou cópias locais dos logs; nenhuma atualização ou campanha foi executada em produção. A execução Windows e o pacote instalado precisam passar no workflow do mesmo commit antes da publicação.

## Causas confirmadas nos logs

### PET: maioridade gerada antes do bloqueio de escrita

O Noturno PET de 03/11/2026 carregou 27.220 contatos e recebeu 476 cadastros da API, com HTTP 200 na consulta geral. A falha ocorreu durante a preparação de novos contatos: `enrichment()` calculava maioridade para ambos os segmentos; `_set_field_if_changed()` bloqueava essa escrita no PET; depois `_apply_customer_enrichment()` tentava acessar a evidência que não havia sido criada, produzindo `KeyError: maior_de_18_anos`.

A correção separa a regra na origem. PET não calcula, exige, valida nem grava `maior_de_18_anos`; idade pode continuar informativa. A FarmaLíder mantém sua validação de idade/maioridade. Planos, guardas e evidências PET não reivindicam esse campo. Dados opcionais ausentes ou nulos não fabricam evidência.

A revisão encontrou também o endereço PET sendo conferido com o segmento padrão FARMA. A conferência agora recebe o segmento ativo; proprietário, endereço completo e correspondência única com o pedido continuam obrigatórios.

### FARMA: o contador “aplicados” incluía persistência local

A captura anexada terminou durante a aplicação; não comprova conclusão de todos os 47.850 planos. A auditoria de 03/11/2026 contém:

| Evento | Quantidade |
| --- | ---: |
| `APLICADO` | 20.005 |
| `CONSULTA_PENDENTE` | 820 |
| `CONFLITO_CONTATO` | 5 |

O cruzamento dos 20.005 eventos aplicados com os planos da mesma revisão mostrou:

| Trabalho registrado | Quantidade |
| --- | ---: |
| Compra com mais de 25 dias; sem campos, sem ação e fora do grupo | 19.655 |
| Contato já no grupo; sem campos nem ação | 277 |
| Inclusão no grupo | 73 |
| Planos aplicados com campos a atualizar | 0 |

Portanto, os milhares de “aplicados” não demonstram milhares de POSTs de campos. A revisão inteira propunha apenas um contato com alterações de campos e 144 inclusões. O estado anexado tinha aproximadamente 25,3 MB: cada nova compra salva localmente passava por GET Weni e regravação integral do JSON, com sincronização de disco. Isso aumenta o custo conforme o estado cresce. Também houve timeouts nas releituras Weni. O log anterior não separava tempo de disco e de rede, então não permite atribuir uma porcentagem exata a cada componente.

O intervalo observado de 19 mil a 27 mil contatos levou aproximadamente 55 minutos e 20 segundos. Esse é o tempo daquela máquina, rota e execução; não é um benchmark controlado nem previsão para a versão corrigida.

### Pendências e conflitos

Os **820 eventos de pendência já processados** estavam na etapa `consulta_da_revisao`, antes de novas consultas da aplicação: 819 tinham `CPF_NAO_CONFIRMADO_BASE_GERAL` e um tinha `PEDIDO_NAO_CONFIRMADO_BASE_GERAL`. Não eram 820 novos erros HTTP.

A **revisão completa** tinha 837 pendências: 836 CPFs ausentes do índice da base geral e um cadastro sem snapshot suficiente de pedido. Nenhum desses contatos estava no grupo Recompra naquele snapshot. Os 836 CPFs também não apareciam no diário observado anexado. Isso comprova falta de cobertura observada, sem provar inexistência de cliente ou compra no endpoint individual. A política FARMA continua sem fallback individual na Recompra; essas evidências permanecem explícitas e são reavaliadas.

O trecho de log citado mostrava três conflitos; o arquivo completo contém cinco. Todos apresentavam `changed_sections=[urns]`, `changed_fields=[]` e contato existente. Os valores anteriores e atuais não foram preservados nesse evento, portanto não é possível concluir se houve troca de telefone, canal, inclusão de URN ou diferença de representação. A guarda foi mantida.

### Pedidos observados que não chegaram ao Sheets

A conciliação dos anexos identificou **sete pedidos de outubro**, já observados, mas ausentes da planilha, somando **R$ 1.741,02**:

| Condição encontrada | Pedidos | Valor |
| --- | ---: | ---: |
| Três CPFs com contatos Weni duplicados | 6 | R$ 1.550,03 |
| CPF físico do contato malformado | 1 | R$ 190,99 |
| **Total** | **7** | **R$ 1.741,02** |

O histórico deixava de entregar a compra quando não conseguia escolher um único contato Weni. A correção permite manter o pedido sem UUID Weni quando a identidade oficial, o proprietário e o pedido estão comprovados. Não resolve conflitos escolhendo arbitrariamente um contato e não atribui o pedido ao WhatsApp.

A correção foi exercitada sobre **cópia temporária** do SQLite real anexado: sete de sete recuperados; após confirmar a entrega local, a repetição retornou zero novos pedidos desse conjunto. Isso não significa que toda a diferença com o relatório mensal esteja conciliada: compras nunca capturadas continuam dependendo de uma fonte histórica por pedido.

## Alterações na operação

### Consulta geral e seleção incremental

O índice em memória por CPF/ID já existia e foi preservado. A base geral é carregada uma vez por fase, quando necessária; leituras locais não são HTTP. A aplicação mantém sua própria conferência da fonte, independente da simulação.

A Recompra usa o estado existente, separado por segmento, para guardar os snapshots relevantes, hashes, cursor e próximos prazos. Com índice compatível e coleta anterior confirmada, consulta na Weni os contatos alterados desde o cursor com **15 minutos de sobreposição**. Compara a base geral atual localmente e seleciona clientes novos/alterados, mudança de pedido/status, prazo da campanha e retentativas. A API FarmaLíder não recebeu um `updated_at` inventado; `modified_on` da Weni não é usado como cursor de vendas.

Primeira execução, cache sem segmento/estrutura compatível e `--full` leem e validam toda a base. A completa recompõe o índice de contatos ativos sem apagar o histórico de pedidos/admissões. O dry-run não confirma checkpoint. Falhas isoladas têm retentativa persistida, sem repetir operações confirmadas dos demais; interrupção crítica não confirma um cursor incompleto.

### Estado local e escrita Weni

Compras que precisam somente atualizar o estado privado deixam de gerar GET por contato e regravação integral a cada compra. O trabalho é acumulado e salvo em checkpoint atômico, com contador próprio `estado_local`.

Escritas reais continuam enviando somente diferenças. Uma resposta de atualização de campos precisa confirmar o UUID e os valores esperados; resposta incapaz de confirmar exige GET. O cache só é atualizado após confirmação. Admissões e retiradas de grupo preservam suas releituras, auditoria e intenção durável antes do POST. Não foi presumido suporte da Weni a batch de campos de vários contatos.

A concorrência limitada de validação existente foi preservada. A melhoria principal elimina trabalho e consultas redundantes; não introduz disparos paralelos ou mutações concorrentes sem controle do estado. Agentes usados na revisão do código não são processos de envio dentro do aplicativo.

### Regra temporal e proteção de campanha

A preparação continua admitindo referências futuras na janela 0–25 dias FARMA ou 0–30 dias PET, para a Weni executar o evento exclusivamente no D+25/D+30. A data é a emissão do último pedido e o evento usa `pedido_data`. Compra nova atualiza a referência aplicável; recusas, Opt-Out, cancelamento, pagamento inválido e compra posterior pendente mantêm seus bloqueios. Não há inclusão retroativa nem repetição de admissão confirmada ou incerta.

O PET reutiliza também um `ultimoPedido: null` explícito e válido da base geral. Isso não transforma campo omitido, ausência no índice ou resposta malformada em cliente sem pedido.

### Deduplicação por CPF e pedidos

A política considera conjuntos de pedidos comprovados, incluindo referências históricas. Preserva o contato com pedido quando os demais não têm; conjuntos iguais podem ser consolidados; conjuntos diferentes são preservados com nomes numerados estáveis após revisão. A conferência de identidade, proprietário, recusas, revalidação e retomada continua obrigatória. Sem pedidos em todos os contatos, conserva-se a proteção anterior por telefone nativo único. A regra não autoriza apagar clientes com CPFs diferentes ou consentir marketing.

Contatos preservados com pedidos distintos não têm a referência sobrescrita para transformar todos em um único pedido. Um pedido oficial posterior pode retirar a referência antiga do grupo, sem apagar o cadastro ou o histórico. Revisões destrutivas anteriores à nova política precisam ser regeneradas.

## Benchmarks medidos

Todos os números abaixo usam fixtures sintéticas e APIs simuladas, com a lógica real de decisão. Não incluem a rede, o disco e a carga das APIs da máquina do cliente.

| Cenário | Antes | Depois | Resultado observável |
| --- | --- | --- | --- |
| 500 contatos com compra a salvar apenas localmente | 1,747 s; 500 GET Weni; 0 POST de campos | 0,021–0,025 s; 0 GET; 0 POST de campos | 500 compras persistidas; elimina releituras e regravações por contato nesse caminho. |
| PET: 200 snapshots completos sem pedido (`ultimoPedido: null`) | 1,1145 s; 201 tentativas HTTP | 0,0223 s; 1 tentativa HTTP | Reaproveita a mesma resposta geral em vez de consultar cada CPF. |
| FARMA: carga completa com 2.000 snapshots válidos | 2,9899 s; 1 tentativa HTTP; 2.000 planos válidos | 2,8904 s; 1 tentativa HTTP; 2.000 planos válidos | Cobertura integral mantida. A consulta geral já era eficiente; a variação de CPU não demonstra ganho expressivo. |

Não extrapolar esses tempos para 47.850 contatos ou afirmar uma duração final em produção. O ganho depende da proporção de estado local, mudanças reais, campos já corretos e latência das APIs.

## Arquivos principais

| Área | Arquivos |
| --- | --- |
| Enriquecimento cadastral | `app/farmalider_customers.py`, `app/contact_enrichment.py`, `app/weni_update.py` |
| Recompra e incremental | `app/recompra.py`, `app/recompra_incremental.py`, `app/run_recompra.py` |
| Confirmação e métricas HTTP Weni | `app/weni_client.py` |
| Histórico observado sem vínculo Weni único | `app/customer_observations.py` |
| Deduplicação, revisão e fontes Sheets | `app/contact_dedup_guard.py`, `app/weni_dedup.py`, `app/dedup_sheets.py` |
| Versão, documentação e pacote | `VERSION`, `pyproject.toml`, `CHANGELOG.md`, guias e metadados de instalação/build/workflow |

Não foram modificados tokens, credenciais ou endpoints. As estruturas das planilhas e os contratos dos dashboards foram preservados.

## Validação e limites

A regressão do `KeyError` foi reproduzida antes da correção. Testes PET/FARMA executam criação, enriquecimento e auditoria em processos de perfil isolado, com dados preenchidos, nulos, ausentes e campos opcionais indisponíveis. O conjunto relacionado de 72 testes passou localmente, incluindo a correção de endereço PET.

As regressões adicionais cobrem primeira carga, completa e incremental; novo cliente, compra/status alterados, cache sem segmento, prazos, recusas, pendências, interrupção/retomada, fonte incompleta, confirmação de campos, referência de pedidos distintos e entrega idempotente do histórico. O resultado consolidado da suíte e os checks de código precisam ser conferidos na entrega final.

**Ainda necessário antes de publicar:** sucesso do workflow do mesmo commit, testes Windows, launchers, ícones e pacote instalado. Estes resultados não são substituídos por testes Linux ou benchmarks simulados. A tag e os arquivos disponibilizados no release também precisam corresponder ao commit validado.

Preserve estado e auditoria ao atualizar. A primeira execução da versão pode precisar preencher o índice; esse custo inicial não representa o custo das incrementais seguintes.
