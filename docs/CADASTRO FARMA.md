# NexoFlow 1.0 — Cadastro FARMA

Os componentes Weni, Analytics, Recompra e Planilhas compartilham a listagem `GET /api/Delivery/clientes/FARMA`. O NexoFlow usa a mesma autenticação e seleção de URL/proxy das outras consultas.

A lista contém **cadastro**, sem último pedido ou itens. A descoberta da última compra continua pelo endpoint de CPF, e o pedido por código continua sendo conferido. A data `cadastro` não é data de compra nem indicação de alteração recente. A regra de reconsultar pedidos já observados somente até 20 dias permanece vigente no Analytics.

## Seleção e dados preservados

- CPF válido dispensa comparação de nome e telefone. Zeros à esquerda só são restaurados quando os verificadores forem válidos.
- CPF inválido preenchido e não zerado exige primeiro nome ou telefone local correspondente, dentro dos candidatos daquele CPF. Quando as duas fontes cadastrais estão disponíveis, ambas precisam confirmar a identidade do mesmo ID. Ausência, zero e formatos malformados continuam pendentes.
- Todos os candidatos são preservados. IDs repetidos com cadastros divergentes ou múltiplas identidades compatíveis não autorizam vínculo automático.
- Quando o cadastro FARMA comprova os IDs daquele CPF, um pedido de outro ID retornado pela consulta individual é bloqueado. Ausência na listagem não prova ausência de cliente ou de compra: a consulta individual permanece como fallback.
- A base PET não é carregada automaticamente. Cadastro FARMA não garante produto humano; o filtro de itens pet e o tratamento dos pedidos mistos continuam obrigatórios.

## Preenchimento de campos ausentes

Com cliente identificado, gênero, idade/maioridade e localização podem ser preenchidos. Valores existentes são preservados. Datas de nascimento inválidas, futuras ou fora da faixa operacional não geram idade. Valores de sexo não reconhecidos não geram gênero.

O endereço só é usado quando existe um único endereço principal, pertence ao mesmo ID de cliente e não conflita com a localização já informada. Cidade, estado e bairro passam pela padronização atual. O endereço cadastral não substitui o endereço histórico dos pedidos.

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

O ganho varia conforme a repetição de CPFs/pedidos e a necessidade de conferir apenas cadastro. Para descobrir novas compras, as consultas individuais continuam necessárias. A listagem completa não é baixada em cada pequena sincronização do modo automático.
