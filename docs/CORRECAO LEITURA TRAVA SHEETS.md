# Recuperação da leitura da trava Google Sheets

## Evidência e causa

Em 10/11/2026, no Analytics PET, o Google respondeu HTTP 429 indicando a cota de leituras por minuto por usuário. A leitura dos valores de `BI_Conversao` recuperou-se na quarta tentativa. Em seguida, `RolloverManager.finish → save → require → SheetsLease._lookup` fez uma nova leitura direta de `developerMetadata`; outro 429 foi propagado sem retentativa. A sincronização terminou com código 1, antes de confirmar o manifesto final dessa tabela.

O texto do Terminal PET comprova essa sequência. O arquivo `nexoflow.log` anexado separadamente encerra com a execução FARMA anterior, cujo erro final é HTTP 500 na releitura integral de `Itens_Pedidos_FarmaLider`. São ocorrências diferentes. Não houve inspeção remota das planilhas nesta investigação.

Antes da falha PET, o log registra:

| Tabela | Inseridas | Atualizadas | Sem mudança |
| --- | ---: | ---: | ---: |
| Base_Contatos | 115 | 1.150 | 26.161 |
| Pedidos_FarmaLider | 229 | 544 | 1 |
| Itens_Pedidos_FarmaLider | 300 | 827 | 2 |
| BI_Resumo_Diario | 1 | 0 | 0 |
| BI_Canais | 4 | 0 | 0 |
| BI_Conversao | 4 | 0 | 0 |

São resultados das operações registradas, não totais financeiros ou prova de conclusão global. O nome físico legado `Pedidos_FarmaLider` também é usado no perfil PET; a seleção dos arquivos pertence ao perfil. A coleta paginada recente informou 340 recebimentos e nenhuma pendência, sem comprovar cobertura civil completa. As etapas seguintes de BI, Meta nativa e publicação histórica automática não foram alcançadas. Não afirmar atualização de todas as fontes.

## Correção limitada

`app/sheets_continuation.py` repete exclusivamente a leitura de metadados da trava em HTTP 429 ou 5xx, até seis chamadas. Em 429, aguarda pelo menos 65 segundos; respeita `Retry-After` numérico ou data HTTP quando válido. Em 5xx usa espera exponencial limitada a 30 segundos, respeitando eventual prazo maior do serviço. A espera aparece em minutos/horas na apresentação.

A consulta bem-sucedida continua validando horário do Google, proprietário e valor da trava. Falhas permanentes 400/401/403/404 e metadados inválidos permanecem bloqueantes. A correção não repete POST de tomada/renovação/liberação, não muda a política de respostas incertas e não remove conferências ou guardas. Exaustão mantém erro e impede novas escritas dependentes da trava.

Os dez módulos protegidos pela assinatura histórica permanecem byte a byte iguais à main anterior. Revisões, journals e checkpoints não foram editados. A otimização de leitura integral de partes grandes do caminho operacional FARMA não faz parte desta correção. O controle preventivo histórico existente não é apresentado como cobertura de todas as chamadas de todos os aplicativos; outras rotinas ainda podem consumir a mesma cota.

## Validação e limites

Antes da correção, quatro dos cinco novos testes unitários falharam: recuperação de 429, limite de tentativas, horário do servidor após 429 e proprietário estrangeiro após 500. O controle de erros permanentes já passava.

Depois da correção, os testes cobrem recuperação de 429/5xx, prazo do serviço, exaustão sem escrita, erros permanentes sem retry, ausência de mensagem privada nos avisos e preservação do horário/proprietário. A integração utiliza o `GoogleSheetsStore`, `RolloverManager` e `SheetsLease` reais sobre Sheets/Drive simulados: injeta 429 na renovação posterior à releitura dos valores, confirma `READY` no manifesto persistido e repete a mesma operação sem nova escrita de fatos. Executada para FARMA e PET. As regressões existentes preservam resposta perdida e troca de proprietário.

O teste sintético não comprova recuperação no Google real nem elimina a possibilidade de novos 429. Sem coleta comercial, publicação de fatos, Weni, Recompra, Noturno, alteração de relatórios, VPS ou SQLite do operador nesta validação.

## Distribuição e retomada

A versão pública 1.5.32 permanece intacta. A entrega 1.5.33 foi publicada; instalar seu Setup em Preserve para atualizar `C:\NexoFlow`; não substituir módulos avulsos. Não atualizar durante uma carga em andamento. Não declarar correção instalada apenas por estar na main.

Após distribuição e instalação em Preserve, com nenhuma outra carga do mesmo segmento ativa, abrir o Terminal no perfil PET, conferir `nexo versao` e executar `nexo analytics`. Preservar continuações, índices, dados e checkpoints. O upsert relê as chaves existentes; não iniciar uma nova coleta histórica integral para reparar o BI. Se ocorrer novo erro, guardar a saída completa e o log do perfil `logs\PET\nexoflow.log`, sobretudo a primeira tentativa, as recuperações e o traceback final. Nunca mudar `WRITING` para `READY` manualmente.

### Conferência local em 11/11/2026 UTC

- 1.986 testes Python: sem falhas, 73 ignorados por condições de ambiente; inclui os seis novos testes e as regressões de Analytics/Noturno.
- 33 testes Node aprovados.
- Ruff, Pyright, consistência e documentação HTML aprovados.
- Os resultados locais são Linux com serviços simulados. Windows/Setup, CodeQL e instalação da correção dependem dos respectivos checks/distribuição; não confundir a aprovação da 1.5.32 com aprovação deste novo commit.

### Evidência FARMA complementar e distribuição 1.5.33

A execução FARMA de 10/11/2026 às 22:11 (America/Fortaleza) releu as duas partes de itens sem HTTP 500 nem novas inserções; falhou antes de BI_Vendas ao confirmar a renovação da trava por GET, com HTTP 429. O registro do erro em Controle também falhou nessa consulta. Isso não comprova ausência definitiva do HTTP 500. Teste adicional reproduz 429 após um POST bem-sucedido e confirma exatamente um POST, repetindo apenas o GET; outro teste confere Retry-After em formato de data HTTP. A correção funcional permanece a mesma.

A 1.5.33 foi publicada e seus pacotes foram verificados. Não houve consulta ou escrita comercial nesta preparação.

Validação local do conteúdo preparado para a 1.5.33: 1.988 testes Python sem falhas (73 ignorados), 33 testes Node aprovados, Ruff, Pyright, consistência, documentação e varredura de segredos aprovados. A documentação registra separadamente o teste de código e a publicação/instalação; Windows e pacotes serão conferidos pelo workflow oficial do SHA desta entrega.

## Publicação comprovada

Publicada em 10/11/2026, 23:28:34 (America/Fortaleza), tag `v1.5.33`, SHA `7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb`. [Workflow oficial aprovado](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/42943029299). CI do push, CodeQL e Meta aprovados no mesmo SHA. Windows 3.11/3.14 nas duas codificações, executáveis, Setup Preserve/Clean/rollback e pacote instalado aprovados.

Os dois downloads públicos passaram por CRC, SHA-256, comparação de 104 módulos com o commit (aceitando apenas CRLF), versões x64/pt-BR 1.5.33.0 e contrato histórico. As 484 entradas do manifesto foram conferidas. A release 1.5.32 e seus ativos foram comparados e preservados. Nenhum teste constitui conciliação comercial.

```text
aba283e796732aa6720b234f8a6268a780c18f5f497007d40f8226cc434249f0  NexoFlow-Setup-1.5.33.zip
a073fb20ff22a6fdcfe10b904db5d80771b854e1daed4e240e2fe247c2506ccd  NexoFlow-1.5.33.zip
```

O download do artefato intermediário foi bloqueado pelo proxy do ambiente de revisão; nenhuma configuração de rede foi contornada. A validação desse artefato ocorreu no CI. A conferência independente de bytes foi concluída nos downloads públicos após publicação.
