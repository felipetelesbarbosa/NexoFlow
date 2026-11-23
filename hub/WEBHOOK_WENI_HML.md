# Recepção de um evento de fluxo na homologação FARMA

O Hub recebe `POST /v1/webhooks/weni/farma`. O emissor usa uma chamada HTTP do fluxo depois de confirmar a transferência. A ocorrência identifica a passagem por esse ponto do fluxo. A contagem não mede o total de conversas do projeto no Insights.

Habilite a rota na API de homologação com `HUB_WENI_FARMA_TOKEN_FILE` apontando para um segredo privado próprio de pelo menos 32 caracteres. Na ausência dessa configuração a rota retorna 404. O header é `Authorization: Bearer <segredo de entrada>`. Use uma credencial dedicada do emissor. As credenciais de administração, do Windows e do usuário da Central têm outras finalidades.

## Corpo de teste

```json
{
  "evento_id": "74dee121-16eb-4014-8a73-6a3fbe4dddf7",
  "tipo": "atendimento_transferido",
  "ocorrido_em": "2026-11-23T08:15:00-03:00"
}
```

O identificador deve ser um UUID da **ocorrência**. Duas transferências no mesmo atendimento precisam de identificadores diferentes. Repetições da mesma transferência devem usar o UUID e o instante originais, inclusive se houver perda da resposta. Um UUID de contato ou um horário recalculado no reenvio não satisfaz esse contrato. Preencha apenas os três campos. O instante usa data, hora, segundos e offset ou `Z`.

A primeira solicitação válida devolve HTTP 200 com `estado=CONFIRMADO`, `recibo` e `recebido_em` após o commit em PostgreSQL. A repetição idêntica devolve o mesmo recibo. Um horário diferente para o mesmo ID devolve 409 e conserva o primeiro evento. Erros de validação retornam 422. Uma falha de persistência gera 503 e permite o reenvio da mesma ocorrência.

## Ensaio com n8n

1. Na homologação isolada, aplique a migração 003 e use o perfil de composição documentado para habilitar a recepção. Confirme que o n8n de teste alcança o alias interno `hub-api`.
2. Importe `hub/n8n/webhook-weni-farma-hml.json` no n8n de teste. Mantenha o workflow inativo. Associe aos dois nós HTTP a mesma credencial *Header Auth*, preenchida pelo canal privado.
3. Execute o gatilho manual. O primeiro nó envia o exemplo e o segundo repete a ocorrência. O último exige o mesmo recibo e o mesmo horário de recebimento nas duas respostas. Uma nova execução do exemplo inteiro reutiliza o mesmo ID.
4. Na Central, consulte os eventos FARMA. O exemplo adiciona uma única ocorrência mesmo após novas execuções. Um intervalo ou tela vazia deve ser conferido pela resposta da API.

A URL `http://hub-api:8000` pertence à rede do ensaio. Conectar uma instância externa da Weni exige homologar um ingresso HTTPS restrito, a autenticação e a geração do identificador pelo fluxo real. Este ensaio usa um emissor sintético e dispensa alterações em fluxos, contatos e grupos.
