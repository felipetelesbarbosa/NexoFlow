# NexoFlow 1.5.7 — Arquivos Google Sheets separados

| Arquivo | Abas |
|---|---|
| Dashboard: arquivo já configurado em `GOOGLE_SPREADSHEET_ID` | `BI_*` e `NexoFlow_Arquivos` |
| Operação: novo arquivo | Contatos, pedidos, itens, tickets, métricas, eventos, campanhas e Controle |
| Histórico: novo arquivo | `Historico_Alteracoes` |

O histórico de alterações é uma trilha de auditoria de contatos. As compras observadas continuam em `Pedidos_FarmaLider` e `Itens_Pedidos_FarmaLider` no arquivo de operação e alimentam todas as tabelas BI. A migração preserva esse histórico comercial; os KPIs não passam a considerar apenas compras novas.

A estrutura acima se repete para **FarmaLíder e Pets Líder**, totalizando seis arquivos quando os dois perfis são usados. A conta de serviço pode ser a mesma; os IDs e o mapa de destinos são próprios de cada marca. As abas mantêm o mesmo esquema nos dois segmentos, inclusive os nomes técnicos `Pedidos_FarmaLider` e `Itens_Pedidos_FarmaLider`.

## Migração

1. Atualize o NexoFlow e encerre todas as rotinas de Weni, Analytics, Planilhas e Recompra.
2. Crie dois arquivos vazios, Operação e Histórico. Compartilhe ambos como **Editor** com o `client_email` da sua conta de serviço Google.
3. Execute `comandos/dividir_planilhas.bat`, informe os links e confira o plano. Confirme apenas com as rotinas encerradas.
4. Aguarde a cópia nativa e a conferência de todas as células. Valores, fórmulas e posições de linhas são comparados em blocos limitados. Estruturas nativas são copiadas pelo Google e o cabeçalho e metadados são conferidos. Se a cópia integral falhar sem criar uma aba, abas simples podem ser transferidas em blocos nativos com valores tipados, formatos, notas, validações e dimensões. A retomada escreve intervalos fixos, sem acrescentar linhas duplicadas. Abas com estruturas vinculadas que não possam ser preservadas interrompem a migração para revisão.
5. A configuração é ativada na aba `NexoFlow_Arquivos` do arquivo original. O ID em `secrets_config.py` permanece igual. Todos os computadores que executam o NexoFlow devem usar a atualização com suporte a essa configuração.
6. Somente depois da ativação e de nova conferência as abas operacionais originais são retiradas. Dependências de fórmulas ou intervalos nomeados interrompem a limpeza para revisão.
7. Retome a sincronização incremental. O Data Studio mantém suas fontes `BI_*` no mesmo arquivo e nos mesmos IDs de abas; atualize os dados do relatório.

Não apague as abas manualmente. Se uma etapa falhar, preserve os arquivos e `logs/privado/migracao_planilhas.json` e repita a rotina com os mesmos destinos. Destinos com abas de mesmo nome não são sobrescritos. Uma resposta perdida durante a cópia pode ser retomada quando existe exatamente uma nova aba identificável.

## Acesso ao dashboard

A conta de serviço precisa de edição nos três arquivos. A conta Google proprietária das fontes do Data Studio precisa de leitura no arquivo Dashboard. Configure **credenciais do proprietário** nas fontes e compartilhe o relatório somente com as pessoas autorizadas. Os espectadores do relatório não precisam de acesso aos arquivos operacionais ou de histórico.

A migração não torna arquivos públicos nem altera os usuários que já têm acesso. Fontes do Data Studio que apontem diretamente para abas operacionais precisam ser substituídas pelas tabelas `BI_*` correspondentes antes da retirada dessas abas; a preservação automática cobre as fontes BI.

Cada arquivo continua sujeito ao limite de células do Google Sheets. A divisão libera capacidade, mas não cria armazenamento ilimitado. Arquivamento por período e troca do destino de histórico exigem uma migração própria; não remova arquivos anteriores para liberar espaço.

### Gravação e capacidade

Novos registros são escritos em intervalos explícitos, sempre a partir da coluna A, depois de reservar somente as linhas necessárias. O NexoFlow não usa a detecção automática de tabelas do `values.append`, que pode interpretar trechos separados por colunas vazias como tabelas diferentes e deslocar a escrita para a direita.

Retentativas repetem o mesmo intervalo sem duplicar registros. Se o cabeçalho ou a chave do destino mudar durante uma retentativa, a gravação é interrompida. Colunas vazias acrescentadas pela leitura retangular da API não são consideradas novos campos; valores preenchidos fora do cabeçalho bloqueiam a carga até a correção da tabela.

O limite de células considera todas as linhas e colunas alocadas em todas as abas de cada arquivo, incluindo células vazias. A separação entre Operação, Histórico e Dashboard permanece ativa.
