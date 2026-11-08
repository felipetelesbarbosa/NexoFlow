# Histórico em produção: inicialização das fontes e publicação FARMA/PET

> Correção posterior: a versão 1.5.24 corrige a varredura repetida de itens na conferência. Para bases grandes, atualizar em Preserve e preparar nova revisão sobre o mesmo backup consistente; preservar o plano interrompido. Ver [correção 1.5.24](CORRECAO%20CONFERENCIA%201.5.24.md).

## Correção após a revisão operacional 1.5.23

O relatório privado do Work identificou duas causas reproduzíveis. `quantidade`
era classificada como MAX porque a expressão encontrava `idade` dentro da palavra.
A regra de idade agora exige nome/token delimitado. Quantidades e unidades são
SUM; idade continua MAX. Não interpretar MAX de ticket individual como ticket médio
global: calcular receita válida / compras válidas no mesmo universo. Não somar
clientes distintos entre meses; usar TOTAL/ANO ou o distinto do detalhe adequado.

A segunda causa era a inicialização: getSchema somente expunha campos estáticos,
sem comprovar o hub. A leitura de dados exige partes confirmadas, e o preparo
exige fontes confirmadas para novas tabelas. Confirmação de **vínculo de fonte**
não é homologação de **valores publicados**. São evidências de fases diferentes.

Agora getSchema valida, em modo somente leitura, manifesto, segmento e as três
origens com IDs distintos. Relê o manifesto para detectar mudança durante a
vinculação e retorna somente o schema controlado. Funciona antes de existirem
partes e durante WRITING; nenhuma linha comercial é lida nesse modo. getData
continua recusando ausência de partes, WRITING, partes inconsistentes e leituras
parciais. O pedido do usuário não pode habilitar schemaOnly em getData.

Não foi removida a guarda de fontes do publicador Python. O Windows 1.5.23 pode
continuar sendo utilizado para publicar depois de atualizar o conector privado e
validar suas ligações. Não copiar módulos para a instalação nem reempacotar a
1.5.23. Esta correção de conector é versionada na main, sem release Windows.

## Work: atualizar a implantação privada

1. Ler AGENTS.md e o roteiro PUBLICADOR HISTORICO SQLITE SHEETS.md. Registrar SHA
   do código utilizado e fazer backup privado do projeto Apps Script/implantação
   e das configurações das fontes atuais. Não publicar credenciais.
2. No projeto privado do conector, atualizar os arquivos de connectors/continuacoes
   (Code.js, Tables.js, Schemas.js e appsscript.json; Apps Script pode usar .gs).
   Preservar IDs do projeto, acessos privados e fontes existentes. O leitor comum
   de connectors/looker_abc/Tables.js continua idêntico; se o conector ABC também
   for atualizado, usar seu próprio Code/Schemas/manifesto, sem misturar projetos.
3. Criar nova versão da implantação utilizada pelas fontes reais. Atualizar apenas
   código no editor não comprova que uma implantação versionada foi atualizada.
4. Nas fontes existentes, atualizar campos/inspecionar agregação padrão; campos
   antigos ou gráficos podem conservar MAX. Historico_Itens.quantidade deve ser
   Número/Soma. Corrigir apenas a agregação comprovadamente incorreta, preservando
   identidades, demais campos e gráficos. Comprovar 2 + 3 = 5 em ensaio controlado;
   não inserir linhas fictícias nas planilhas comerciais.

## Executar em ordem: FARMA e, após seu fechamento, PET

A demanda atual autoriza o Work a levar todo o histórico coletado de ambos os
segmentos, com as guardas abaixo. O Codex não executou essa carga comercial.
Cada segmento exige sua própria sessão/processo, configuração, três arquivos,
SQLite, backup, plano, journal e conferências. Nunca reaproveitar uma revisão
FARMA em PET. Não trocar NEXOFLOW_PERFIL dentro de processo que carregou módulos.

### 1. Conferir o destino e vincular as cinco fontes

No Terminal já selecionado para o segmento correto:

```text
nexo armazenamento diagnosticar-origens
nexo armazenamento status
```

Os três destinos FARMA já foram aprovados no Windows. Reconfirmar antes de operar;
PET ainda exige sua própria evidência. Não reconfigurar origens válidas à força.

Vincular fontes comerciais pelo ID do Dashboard/hub **do segmento**, nunca pelo
hub de homologação. Tabelas: Historico_Pedidos, Historico_Itens, BI_LTV_Clientes,
BI_Cobertura_Historica e BI_Historico_Resumo. getSchema deve validar origem/schema.
Conferir os parâmetros salvos da fonte, o segmento e os campos/tipos. Antes da
carga, erro explícito de getData por falta de partes é esperado: não chamá-lo de
leitura vazia conciliada nem de venda zero. Se nem a fonte puder ser salva,
registrar a etapa/erro exatos e corrigir o bloqueio; não confirmar ligação fictícia.

Somente após comprovar a vinculação comercial e seus parâmetros:

```text
nexo armazenamento ativar-data-studio --abas Historico_Pedidos Historico_Itens BI_LTV_Clientes BI_Cobertura_Historica BI_Historico_Resumo --confirmar-fontes
nexo armazenamento status
```

Isso registra a ligação, não READY/fechamento financeiro. Preservar o relatório
publicado e suas fontes antigas até a conferência integral dos dados novos.

### 2. Backup consistente e auditoria do SQLite existente

Usar o mecanismo history_snapshot.snapshot documentado no roteiro, incluindo WAL;
encerrar outras cargas para um corte estável. Guardar hash/tamanho/instante e
comprovantes privados. Auditar a cópia em modo somente leitura. Não recolher
novamente a base para publicar. Sem acesso ao Windows, orientar o operador e
registrar explicitamente que os comandos foram executados por ele.

```text
nexo historico --auditar-banco CAMINHO_DA_COPIA_DO_SEGMENTO.sqlite --resumo-mensal CAMINHO_PRIVADO_DO_RESUMO.json
```

O Work informou conciliação aritmética agregada FARMA de 267.672 pedidos,
207.582 válidos, 60.077 cancelados, 13 pendências, 39.365 compradores e
3.383.966.990 centavos. Isso não é prova independente de cada pedido/cliente,
liquidação nem completude civil. Usar o corte efetivo e preservar pendências,
SEM_EMISSAO e LIMITES_DA_API_NAO_HOMOLOGADOS. Concentrações abril/2026 e junho/2025
exigem inspeção pontual privada; não ajustar valores para aproximar médias.
Não inventar totais PET; auditar seu próprio SQLite. Se ele não estiver disponível,
obter a evidência do operador antes de planejar, sem presumir acesso ao disco.

### 3. Capacidade global

```text
nexo historico --planilhas capacidade --banco CAMINHO_DA_COPIA_DO_SEGMENTO.sqlite --revisao CAMINHO_PRIVADO_INEDITO_DO_PLANO.json --resumo-mensal CAMINHO_PRIVADO_DO_ESPERADO.json
```

Revisar deltas, grades físicas, reservas, cabeçalhos, manifesto, partes antigas e
novas, OAuth/pasta/permissões. Histórico FARMA tinha 18.413.260 células; planejar
continuações oficiais, sem truncar ou apagar legado. Não usar estimativa agregada
como substituto dos deltas reais. Plano de outro código/destino ou resposta incerta
exigem reconciliação, nunca reinício cego.

### 4. Um lote de segurança e depois todo o restante

Antes da aplicação guardar backup privado das configurações, planos/journals e
fontes. Concluir o preparo e conferir destinos/segmento/capacidade primeiro.

```text
nexo historico --planilhas aplicar --revisao CAMINHO_REAL_DO_PLANO.json --max-lotes 1
nexo historico --planilhas conferir --revisao CAMINHO_REAL_DO_PLANO.json --resumo-mensal CAMINHO_PRIVADO_DO_PILOTO.json
```

Um lote tem até 200 linhas/1 MB, podendo ser menor. Conferir exatamente o subconjunto
confirmado, valores, posições e comprovantes. Não exigir que um lote feche todas
as tabelas nem inativar fatos fora da amostra. Pausa/código 3 não significa perda
de toda a carga. Se conferência estiver aprovada e não houver bloqueio, prosseguir
sem nova autorização por lote, na **mesma revisão**:

```text
nexo historico --planilhas aplicar --revisao CAMINHO_REAL_DO_PLANO.json
nexo historico --planilhas conferir --revisao CAMINHO_REAL_DO_PLANO.json --resumo-mensal CAMINHO_PRIVADO_DO_FECHAMENTO.json
```

Resposta perdida, edição externa, divergência, quota ou autenticação: interromper
as escritas dependentes e reconciliar. Não apagar journal, mudar de marca nem
recomeçar por outro plano para contornar guardas. Rollback específico, se necessário:

```text
nexo historico --planilhas rollback --revisao CAMINHO_REAL_DO_PLANO.json --lote NUMERO_CONFIRMADO_DO_LOTE
```

Rollback confere valores posteriores e recusa sobrescrever edição de terceiro;
não é restauração indiscriminada de planilha inteira.

### 5. Fechamento, painel e réplica PET

Exigir READY integral, zero lotes restantes e zero diferenças mensais/TOTAL no
mesmo universo, inclusive soma de compras válidas e LTV ao centavo. Repreparar com
novo nome e comprovar zero deltas idênticos. Não executar novamente uma escrita
idêntica apenas para demonstrar idempotência.

No painel, conferir leitura por manifesto de todas as partes, resumo anual,
período mensal/dia/vazio, cancelamentos e recortes. Somente após conferência trocar
as fontes necessárias do relatório preservando visual/filtros e cópia de recuperação.
Filtrar vigente=Sim e estado financeiro apropriado. Não somar itens à receita do
pedido, meses a TOTAL, compradores mensais entre si ou modelos de anúncios.
Ticket global é receita/compras, não MAX ou média simples dos tickets individuais.

Após fechar FARMA, repetir todo o procedimento para PET em nova sessão, com destinos,
fontes e snapshot PET próprios. Não publicar dados FARMA no projeto PET ou vice-versa.
Não alterar Weni, Recompra, anúncios, consentimentos ou VPS para publicar o histórico.

## Entrega operacional do Work

Relatar separadamente por segmento: versão/SHA/implantação, fontes comerciais,
corte/hash do snapshot, totais esperados/observados, plano de capacidade, partes,
lotes confirmados/restantes, cobertura/pendências, reconciliação financeira,
idempotência e fontes efetivamente utilizadas pelo painel. Distinguir simulações,
saídas do operador, leituras comerciais e ações realmente aplicadas. Qualquer
indisponibilidade deve ser explícita; não apresentar histórico parcial como completo.
