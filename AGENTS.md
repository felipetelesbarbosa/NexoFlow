# NexoFlow 1.0

Ao atualizar este repositório, mantenha a identificação pública **NexoFlow 1.0**.

## Conferência antes da entrega

- Reproduza a falha relatada com dados sintéticos e registre uma regressão que falhe antes da correção, quando houver comportamento executável alterado.
- Valide a integração da rotina afetada: argumentos da CLI, simulação, revisão, aplicação, estado persistido, códigos de saída e continuidade das etapas. Simule APIs e recursos externos; execute a lógica real de decisão e validação.
- Cubra sucesso, falha isolada, falha crítica, alteração após a revisão e retomada sem duplicidade, conforme o risco da mudança. Launchers exigem testes Windows do console e do executável distribuído.
- Confira o diff e execute lint, tipos, testes pertinentes, consistência e os checks exigidos pelo workflow. Valide o pacote instalado quando houver impacto operacional; não use apenas a contagem de testes como evidência de correção.
- Antes de anunciar publicação, confirme o sucesso do workflow do mesmo commit, a tag e os arquivos efetivamente disponibilizados no release. Preserve versões e nomes estáveis.
- Informe o que foi validado e seus limites: teste local, compilação para Windows, execução no Windows e teste do pacote são evidências diferentes. Não prometa ausência de erros nem apresente hipótese como causa confirmada.

## Regras do projeto

- Use mensagens de commit curtas em português que descrevam a área ou a alteração, como `Automação`, `Documentação`, `Instalador` ou `Corrigir revisão da Recompra`. `NexoFlow 1.0` identifica a versão, não é uma mensagem obrigatória de commit. Separe alterações por área quando isso tornar a navegação do GitHub mais clara; não reescreva o histórico apenas para mudar os textos exibidos.
- A `main` é a única branch de trabalho do repositório. Atualize diretamente a `main`; não crie nem mantenha branches adicionais.
- Mantenha o título do release `NexoFlow 1.0`, a tag `v1.0` e os nomes estáveis dos pacotes. Só altere a versão quando o usuário pedir explicitamente.
- Ao publicar pacotes atualizados, republice o release para que a data corresponda à nova publicação.
- Preserve as credenciais e os diagnósticos privados fora do Git e dos pacotes públicos.
- Use os nomes de pagamento: 0 Cancelado, 1 Dinheiro, 2 Débito, 3 Crédito, 4 Ticket, 5 Pix por Link de Pagamento, 6 Pix no POS.
- Horários operacionais usam `America/Belem` (UTC-3).
- Status de pedido: EmAberto=-2, PendenteDePagamento=-1, EmProcessamento=0, ProntoParaRota=4, EmTransito=1, Concluido=2, Cancelado=3. Estados abertos permanecem em rechecagem. Todos os estados documentados não cancelados (-2, -1, 0, 4, 1, 2) contam como venda validada; status 3 ou pagamento 0 exclui a venda. Weni, Analytics e Recompra usam a mesma regra. No Analytics, reconsultar status dos pedidos já registrados somente quando a data do pedido estiver entre hoje e 20 dias atrás (inclusive), em America/Belem. Preservar pedidos mais antigos sem reconsulta automática, mantendo a consulta por CPF para descobrir novas compras e a validação inicial de pedidos ainda não registrados.

- Pedidos cuja resposta oficial, com identidade, proprietário e data verificados, não contém itens são tratados como cancelados e ignorados em vendas, produtos do dashboard e Recompra, sem bloquear a carga. Falhas de consulta e respostas malformadas continuam sendo erros.

- Textos apresentados ao usuário devem usar português brasileiro (pt-BR), com acentos e cedilha. Preserve identificadores técnicos. BAT/CMD em UTF-8 sem BOM com `chcp 65001`; PowerShell em UTF-8 com BOM; HTML com `lang="pt-BR"`; metadados dos executáveis em pt-BR.

- Consultar primeiro CPFs válidos; depois inválidos preenchidos não zerados. Valores ausentes, inteiramente zerados ou malformados são pendências cadastrais e não autorizam consulta por CPF. Repor zeros à esquerda até 11 dígitos somente se os dígitos verificadores forem válidos. Não alterar dígitos existentes nem confundir presença na API com validade matemática.

- CPF inválido exige primeiro nome correspondente (normalizando acentos, maiúsculas e símbolos) ou número local do telefone correspondente, ignorando +55 e DDD, do mesmo cliente da Weni. Bloqueie ausência, divergência e ambiguidade; cache compartilhado de CPF não compartilha identidade/pedidos.

- Recompra mantém a política de bloqueio por recusa/Opt-Out, inclusive quando marketing_opt_in está afirmativo; campo vazio não é tratado como consentimento registrado. Novas inclusões e trocas de referência exigem evento D+25 ainda futuro, reconferido antes do POST. A passagem do horário, sozinha, não remove contatos já admitidos com a mesma referência.

- Lançamento com `codProduto=0` e descrição vazia representa frete somente quando a soma desses lançamentos coincide com o frete oficial do cabeçalho. Validar vínculo e valores; não incluir em produtos, quantidades, Recompra ou valor dos produtos e não somar o frete duas vezes.

- `clientes/FARMA` pode retornar `cliente`, `ultimoPedido` e `itens`. Guardar snapshots completos e verificados em memória por CPF/ID durante a execução. Pedido/cliente/itens precisam pertencer à mesma identidade; respostas ausentes, incompletas ou ambíguas usam consulta individual, sem concluir ausência de compra. Cadastro só preenche campos vazios e mantém evidência na revisão. Endereço exige correspondência única com o último pedido (CEP, cidade/UF, logradouro, número e complemento), inclusive quando o endereço correspondente não é o principal. Leituras de preparação não podem autorizar uma aplicação posterior: Recompra e deduplicação reiniciam as leituras antes do apply. O arquivo PET usado como referência de formato não alimenta a operação FARMA.

## Perfis de segmento

- Atalhos tradicionais usam FARMA; atalhos Pets propagam `NEXOFLOW_PERFIL=PET` antes dos imports. Nunca trocar perfil em um processo que já carregou configurações ou clientes.
- Preservar os mesmos contratos de auditoria, rota direta/proxy, retentativas e aplicação nos dois perfis. Credenciais Weni, três destinos Sheets, logs, importações, revisões e estado devem permanecer separados. Revisões e manifestos copiados entre segmentos devem ser recusados.
- FARMA mantém filtro de produtos humanos e D+25. PET exige vínculo oficial PET, preserva seus itens e usa D+30, pedido_data, compra_recente e opt_in_marketing Sim/Não, sem exigência de maioridade. Pagamento da Recompra exige código documentado de 1 a 6; falhas de consulta permanecem pendentes em ambos os perfis.
