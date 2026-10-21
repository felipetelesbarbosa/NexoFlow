# NexoFlow 1.0 — Cadastro FARMA

Os componentes Weni, Analytics, Recompra e Planilhas compartilham a listagem `GET /api/Delivery/clientes/FARMA`. O NexoFlow usa a mesma autenticação e seleção de URL/proxy das outras consultas.

A lista pode conter objetos com **`cliente`, `ultimoPedido` e `itens`**. O NexoFlow aceita também o formato anterior, com apenas cadastro. Snapshots completos ficam em memória por CPF e ID de pedido durante a execução, após conferir proprietário, emissão, itens, valores e segmento. Eles atendem às consultas locais de cliente e pedido sem repetir HTTP. A data `cadastro` não é data de compra nem indicação de alteração recente. A regra de reconsultar pedidos já observados somente até 20 dias permanece vigente no Analytics.

Quando faltam pedido, itens ou dados consistentes, a consulta individual de CPF/pedido permanece disponível. Ausência ou `ultimoPedido` nulo na listagem não prova ausência de compra. Um snapshot de um cliente nunca fornece itens ou pedido a outro cliente. Duplicatas com respostas divergentes não são resolvidas escolhendo a primeira ocorrência.

## Seleção e dados preservados

- CPF válido dispensa comparação de nome e telefone. Zeros à esquerda só são restaurados quando os verificadores forem válidos.
- CPF inválido preenchido e não zerado exige primeiro nome ou telefone local correspondente, dentro dos candidatos daquele CPF. Quando as duas fontes cadastrais estão disponíveis, ambas precisam confirmar a identidade do mesmo ID. Ausência, zero e formatos malformados continuam pendentes.
- Todos os candidatos são preservados. IDs repetidos com cadastros divergentes ou múltiplas identidades compatíveis não autorizam vínculo automático.
- Quando o cadastro FARMA comprova os IDs daquele CPF, um pedido de outro ID retornado pela consulta individual é bloqueado. Ausência na listagem não prova ausência de cliente ou de compra: a consulta individual permanece como fallback.
- A base PET não é carregada automaticamente. Cadastro FARMA não garante produto humano; o filtro de itens pet e o tratamento dos pedidos mistos continuam obrigatórios.

## Preenchimento de campos ausentes

Com cliente identificado, gênero, idade/maioridade e localização podem ser preenchidos. Valores existentes são preservados. Datas de nascimento inválidas, futuras ou fora da faixa operacional não geram idade. Valores de sexo não reconhecidos não geram gênero.

O endereço só é usado quando pertence ao mesmo ID de cliente e corresponde de forma única ao endereço do último pedido. São conferidos CEP, cidade/estado, logradouro, número, complemento e bairro quando disponível; acentos, pontuação e abreviações usuais de logradouro são normalizados. Coincidência apenas de CEP não é suficiente. O endereço correspondente pode ser secundário. Dados incompletos, divergentes ou ambíguos ficam sem preenchimento automático de localização.

Cidade, estado e bairro passam pela padronização atual. Campos já preenchidos são preservados. A origem e o endereço usado para conferência acompanham a revisão; o endereço histórico do pedido é mantido.

Weni e Planilhas propõem somente campos já disponíveis na Weni e registram a origem no snapshot revisado. O apply relê os campos relevantes antes de gravar; uma mudança posterior gera conflito, sem sobrescrita. Analytics preenche as colunas existentes do Sheets, sem criar novas fontes no Looker. Nenhuma dessas informações autoriza alterar CPF, URNs, nome do canal, consentimento ou grupos de marketing.

## Configuração

Configurações opcionais em `secrets_config.py`; instalações existentes usam estes padrões automaticamente:

```python
FARMALIDER_CUSTOMER_DIRECTORY_MODE = "auto"
FARMALIDER_CUSTOMER_DIRECTORY_MIN_CONTACTS = 500
```

- `auto`: carrega o cadastro em cargas a partir do limite; a varredura completa da Recompra também o utiliza.
- `on`: utiliza o cadastro inclusive em cargas pequenas.
- `off`: mantém a validação por consultas individuais, sem baixar a listagem.

A listagem é obtida uma vez por preparação. Falha de formato ou indisponibilidade mantém as consultas individuais; erros de autenticação/permissão continuam sendo apresentados. Os logs mostram totais do índice, consultas cadastrais locais e leituras HTTP reaproveitadas, sem dados pessoais.

O reaproveitamento de CPF e pedido existe somente dentro da execução, com armazenamento temporário limitado. Leituras que falharam podem ser tentadas novamente. Recompra e deduplicação descartam as leituras da simulação antes da aplicação e revalidam os dados necessários. A revisão humana, as recusas, o estado local e a proteção contra duplicidade de admissão permanecem obrigatórios.

O ganho varia conforme a cobertura dos snapshots completos e a repetição de CPFs/pedidos. Cada preparação obtém uma listagem nova. Recompra e deduplicação descartam o índice da simulação antes da aplicação. A listagem completa não é baixada em cada pequena sincronização do modo automático. Logs agregados distinguem cadastros locais, últimos pedidos locais e pedidos por ID locais, além de informar o resultado da conferência de endereços.
