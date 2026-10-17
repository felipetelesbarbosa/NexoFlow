# NexoFlow 1.0: Curva ABC por período

## Estado

Conector preparado e testado localmente, publicado e autorizado em projeto privado Google Apps Script. **A integração ao relatório e a validação com dados reais ainda estão pendentes.** As abas existentes e a rotina Python continuam intactas. Uma carga Python com `--inicio/--fim` recalcula um único período compartilhado; ela não responde às datas de cada leitor do Looker.

## Registro de validação e pendências (17/10/2026)

- 10 testes do cálculo JavaScript aprovados, além da verificação de sintaxe do adaptador.
- 29 testes existentes de `test_looker_bi.py` aprovados com configuração fictícia isolada, sem credenciais reais ou consultas de rede.
- Código e manifesto salvos em projeto privado Apps Script. Autorização Google concluída pelo titular; primeira fonte reutilizável criada e adicionada ao relatório.
- Pendente: validar a consulta com a base real, concluir a substituição das fontes somente na página Curva ABC, comparar períodos e exportar/validar o PDF. A primeira troca revelou filtro associado à fonte antiga; precisa ser recriado. A conexão do navegador parou de responder durante esse ajuste.
- Código publicado na `main` após autorização explícita, no commit `70b66899adc228227383a1632ffce44f9f54c124`. A publicação anterior foi bloqueada pela revisão automática; a pendência foi resolvida.

## Como funciona

O conector usa Google Apps Script, solicita `dateRangeRequired` e recebe `request.dateRange.startDate/endDate` em cada consulta. Lê somente `BI_Itens` e `BI_Clientes_Vendas`, filtra as vendas no intervalo inclusivo, agrupa por código de produto, ordena por receita e só então calcula participação, acumulado, classes e pares. A tabela `BI_Produtos_ABC` antiga não é modificada.

Preserva a regra de `app/looker_bi.py`: o produto que cruza 80% permanece na classe A; o que cruza 95%, na B. Empates de receita recebem a mesma classe, com desempate de apresentação pelo código. Portanto, os totais não precisam ser exatamente 80/15/5.

Não retorna CPF, cliente, contato ou número original de pedido. Não usa serviços de terceiros, chave de API, endpoint público, nem escrita nas planilhas. O OAuth solicita somente leitura do Google Sheets; a autorização de acesso é feita pelo usuário no Google. Nenhum compartilhamento do relatório ou da planilha precisa mudar.

## Instalação privada

1. No Google Apps Script da conta dona do relatório, crie um projeto com o nome **NexoFlow 1.0 - Curva ABC**.
2. Copie `AbcCore.js` e `Code.js` para arquivos de script com os mesmos nomes (o editor pode mostrá-los como `.gs`). Habilite a exibição de `appsscript.json` e copie o manifesto.
3. Salve. Em **Implantar > Testar implantações**, selecione o tipo conector do Looker/Data Studio. Use o ID de implantação fornecido pelo Google, sem tornar o projeto público.
4. Autorize a leitura no Google e crie três fontes privadas a partir da mesma implantação. Informe o ID da planilha BI e escolha `abc`, `resumo` e `juntos`, respectivamente. Mantenha o ID fora do repositório.
5. Somente após testar a resposta do conector, substitua **nesta página** as fontes da tabela detalhada e dos seis cards ABC por `abc`; o resumo por `resumo`; e compras conjuntas por `juntos`. Preserve estilos e fórmulas compatíveis. Não substitua fontes do relatório inteiro.
6. Use `periodo_fim` como dimensão de período e intervalo automático nos componentes. O conector já recebe o intervalo completo e devolve a data final selecionada em cada linha. Remova intervalos personalizados dos componentes. Preserve o filtro `abc_disponivel = 1` somente nos componentes de classificação, sem ocultar o resumo de disponibilidade.
7. A coluna `periodo_inicio`/`periodo_fim` deve compor o período exibido. Os campos `*_pct` continuam em escala 0 a 100, como na origem antiga; cards existentes que dividem por 100 podem ser preservados. Não formatar o número 80 como 8.000%.

## Critérios de validação antes de considerar concluído

- Comparar receita e produtos com a página Produtos para dois intervalos diferentes e para um único dia.
- Conferir que o líder pode mudar, os percentuais são recalculados e os cards somam a quantidade total de produtos classificados e 100% da receita quando disponíveis.
- Conferir Top 5 sobre todos os produtos e pares por pedidos distintos.
- Testar um intervalo vazio e ausência/divergência de itens. Classes e Top 5 ficam indisponíveis em dados inconsistentes; não inventar classes ou percentuais.
- Confirmar desempenho com a base real. A versão lê até 150 mil linhas por aba e falha explicitamente se o limite for excedido; não entrega amostra silenciosa. Consulta com pedido acima de 500 SKUs também falha explicitamente no cálculo de pares.
- Exportar a página e conferir se o período, classes, cards, tabela e pares são coerentes. Retornar ao período padrão após os testes.

## Testes locais

```sh
node --test tests/test_looker_abc_connector.cjs
PYTHONPATH=app python3 -m unittest discover -s tests -p test_looker_bi.py
```

A suíte do conector usa somente dados fictícios. Não envia dados nem modifica Google Sheets. O resultado local não substitui a validação de OAuth, execução Apps Script e funcionamento no Looker com dados reais.

## Referências

- https://developers.google.com/looker-studio/connector/date-range
- https://developers.google.com/looker-studio/connector/reference
- https://developers.google.com/looker-studio/connector/manifest

## Uso privado e privacidade

Este componente destina-se ao uso interno, sob as permissões da conta que o instalar. O operador é responsável por autorizar apenas fontes e leitores permitidos. A instalação não estabelece oferta comercial, contrato de suporte ou política para terceiros. Não publicar em galeria sem revisão específica de identidade, termos e política de privacidade. O código não grava registros de negócio em logs nem transmite dados para fora dos serviços Google usados pelo próprio relatório.
