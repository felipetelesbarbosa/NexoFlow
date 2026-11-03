# Deduplicação no NexoFlow Weni

A revisão de duplicados integra as cargas incrementais e completas do NexoFlow Weni. Use o executável ou os comandos habituais; não é necessário executar um script separado.

1. Execute o dry-run. O relatório da Weni inclui **DEDUPLICAÇÃO DE CONTATOS**, com os nomes e UUIDs a excluir e a manter, os pedidos comprovados e as pendências.
2. Revise o relatório e confirme a aplicação pela janela habitual.
3. A aplicação revalida a identidade nas APIs, interrompe os fluxos e exclui somente os duplicados comprovados. Limpa as fontes e confere o resultado. Falhas isoladas ficam pendentes; a atualização dos demais contatos continua.
4. Atualize os dados no Data Studio para consultar as fontes corrigidas.

Antes da aplicação, encerre outras cargas de Analytics, Planilhas e Recompra. A rotina bloqueia outra execução simultânea da própria Weni; não inicia nem encerra os outros programas.

## Critérios

- O mesmo CPF matematicamente válido, inclusive após reposição comprovada de zeros à esquerda, deve identificar um único cliente oficial na API. Nome igual, sobrenome, emoji ou CPF genérico não comprovam duplicidade.
- Os pedidos considerados incluem referências da Weni e do histórico registrado. Cada pedido precisa ter o mesmo proprietário comprovado na API; a conferência não altera produtos, status ou valores financeiros antigos.
- Se apenas um contato tem pedidos comprovados, esse contato é preservado e os contatos sem pedido podem ser consolidados nele após a auditoria.
- Contatos com o **mesmo conjunto de pedidos** podem ser deduplicados. Se os conjuntos são diferentes, inclusive por um pedido histórico adicional, ambos são preservados. O critério não é somente a semelhança de produtos ou do valor.
- Havendo contatos preservados com pedidos diferentes, os nomes recebem numeração estável, como `Nome completo 1`, `Nome completo 2`. A mudança tem revisão e nova conferência de identidade/referências; não altera CPF, consentimento ou pedido. Perfis com pedidos distintos não têm a referência sobrescrita para transformar todos no mesmo último pedido; um pedido oficial posterior retira a referência antiga da Recompra quando aplicável, preservando o cadastro.
- Sem pedidos em todos os contatos, permanece a exigência de CPF válido e telefone **nativo** único para identificar o contato correto. Telefone copiado para um campo personalizado não substitui essa comprovação.
- CPF inválido/genérico, proprietário divergente, histórico conflitante, identidade oficial ambígua e falha de API permanecem pendentes. A identificação de CPF com vários contatos Weni não deve ser confundida com vários candidatos da própria API.
- Recusas de LGPD e marketing são preservadas no contato correto, inclusive `opt_in_marketing` no PET. Não há transferência automática de Opt-In. Bloqueio ou parada sem proteção equivalente impede a exclusão.

Esses critérios para **apagar um contato** não alteram as regras para validar vendas: CPF válido continua dispensando comparação de nome, telefone e e-mail; CPF inválido mantém a validação por primeiro nome ou número local.

Nas cargas de 25%, a comparação considera a base global para identificar o contato correto, mas propõe excluir somente os duplicados pertencentes à parte selecionada. O contato correto pode estar em outra parte.

## Planilhas e retomada

Os pedidos e itens reais são vinculados ao contato correto, preservando seus IDs, produtos, status e valores. Registros dos contatos excluídos saem da Base, do histórico de alterações, dos tickets e eventos associados e das fontes BI. Apenas diagnósticos sem pedido, sem itens e sem qualquer valor financeiro podem ser descartados da tabela de pedidos.

A rotina descobre os arquivos de Operação, Histórico e dashboard pela configuração `NexoFlow_Arquivos`; também aceita instalações com um único arquivo. Não altera as fontes do Data Studio, os períodos dos indicadores nem os marcos incrementais do Analytics.

O snapshot complementar `*_duplicados.json` acompanha a revisão da Weni. A política da 1.5.12 exige um novo dry-run: uma revisão destrutiva anterior não autoriza exclusões ou renomeações sob a regra nova.

Os comprovantes e backups ficam em `logs/duplicados/`, fora dos pacotes e do Git. Preserve-os durante uma recuperação. Lotes incompletos já revisados são retomados antes de novos lotes, sem repetir uma exclusão de contato confirmada. Resultados incertos de exclusões de linhas não são reenviados automaticamente: a rotina confere o estado e, se não conseguir comprová-lo, mantém apenas o lote pendente para nova conferência, sem cancelar a carga Weni. Não apague comprovantes ou arquivos de lock com uma execução ativa.

Sem duplicados comprovados, a etapa não grava alterações nas planilhas. Pendências aparecem no resumo e voltam à revisão nas próximas cargas.

## Falhas e próxima incremental

Falhas isoladas de consulta, preparação ou gravação não cancelam a carga Weni. Os contatos concluídos permanecem aplicados e o resumo informa as pendências. A próxima incremental revalida os contatos que falharam; quando necessário, recupera suas mensagens anteriores para não perder evidência após o avanço do checkpoint global.

Uma falha na deduplicação preserva seus comprovantes e não bloqueia a atualização normal dos demais contatos. Lotes incompletos são conferidos novamente na próxima execução. Nenhuma exclusão é presumida como concluída somente por ter sido enviada; a conferência do resultado continua obrigatória.

A opção legada `--require-complete` permanece aceita no comando Weni, mas falhas isoladas concluem com aviso e pendências em vez de cancelar a carga. Isso não modifica o comportamento dos comandos separados de Analytics e Recompra. Configuração inválida ou snapshot principal corrompido continua impedindo a aplicação de alterações não revisadas.
