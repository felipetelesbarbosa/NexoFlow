# Histórico 1.5.29: grade física, quota e primeiro lote

## Evidência e limites

O operador confirmou na 1.5.28 que a mesma revisão antiga foi reconciliada.
A aplicação de um lote recebeu HTTP 429 durante leituras do mapa e terminou
com HTTP 400. A conferência informou zero lotes confirmados e 4.301 restantes.
Isso não é um piloto aprovado, nem prova isoladamente que nenhum envio ficou
incerto. Não se acessou o Windows, journal ou destinos comerciais nesta correção;
nenhuma carga, consulta FarmaLíder ou escrita comercial foi feita.

No código publicado, `read_rows` envia intervalos a partir da linha 2 mesmo
quando a aba tem somente uma linha. Isso precede backup, intenção `sending` e
reserva de grade. A reprodução com limite físico no transporte simulado retorna
HTTP 400. As fixtures anteriores não recusavam esse intervalo. É um defeito
comprovado no código compatível com o relato; o texto genérico do erro comercial
não permite afirmar que foi a única causa daquele HTTP 400.

## Correções

- Releitura das dimensões atuais antes de consultar o lote. Posições fora da
  grade retornam ausência, sem GET inválido, resize ou escrita antecipada.
  Posições existentes são lidas em FORMULA e devolvidas na ordem pedida. Uma
  expansão externa preenchida não é considerada vazia pelo plano antigo.
- Cabeçalhos, colunas, manifesto, origens, pastas OAuth, edição de serviço e
  ACL privada continuam conferidos. Fórmulas e dados divergentes bloqueiam.
- O mapa continua consultado nas fronteiras da operação, após a conferência e
  antes de cada lote. Comparações internas usam o segmento já validado e não
  refazem a consulta por arquivo/intenção. Sem cache permanente de autorização.
  No cenário sintético de 12 pedidos, o piloto passa de dez para quatro
  revalidações de contexto (20 para oito requisições de mapa). Isso não garante
  ausência de quota em uma conta compartilhada.
- Quota de leitura espera 5, 10, 20, 40 e 65 segundos entre tentativas, mantendo
  o limite configurado e respeitando `Retry-After`. Não se repete cegamente
  escrita de fatos após resposta perdida.
- Erro HTTP informa etapa interna e categoria reconhecida, nunca corpo, URL,
  intervalo comercial ou valores do Google. Outras causas ficam não identificadas.
- `conferir` distingue zero lotes, piloto parcial, resposta incerta e publicação
  completa. A conferência parcial inclui `uncertain_batches`; não converte
  silenciosamente `sending` em `done`.

## Recuperação da revisão antiga

Reconciliação aceita os dez módulos oficiais 1.5.28 em LF ou CRLF, inclusive
os bytes do ZIP publicado. Preserva recibo anterior dentro do novo comprovante,
JSON original, snapshot, coordenadas, hashes, manifesto e journals.

Continuam obrigatórios: integridade, fontes/retransformação iguais, baseline
remoto igual, partes somente com cabeçalho e grade esperados, nenhuma incerteza
de manifesto, todos os lotes `pending`, nenhum backup e nenhum fato enviado.
Se houver `sending`, `done`, backup, conteúdo/estrutura estranha, compartilhamento
alterado ou assinatura desconhecida, interrompe sem forçar compatibilidade.
Não editar estados nem apagar backups para aceitar o plano.

## Testes

A configuração nova com gspread real passou a falhar antes da correção com
HTTP 400 na leitura de A2 da aba de uma linha. O novo orçamento de consultas
falha com os métodos publicados da 1.5.28 (dez chamadas contra quatro esperadas).

A recuperação simula revisão 1.5.25 com recibo 1.5.28, todas as partes criadas e
falha antes do primeiro lote. Confere reconciliação duas vezes, piloto, conferência,
retomada integral, rollback, reaplicação e idempotência. Exige JSON/source hash
preservados, nenhuma criação duplicada e diferença financeira zero. Controles
negativos cobrem mapa alterado antes do primeiro lote, expansão preenchida por
terceiro, colunas alteradas, resposta incerta, logs privados, quota e Retry-After.

Fixtures validam limites de `updateCells` antes de aplicar o lote, inclusive
`addSheet` seguido de `updateCells` no mesmo pedido atômico. Testes sintéticos
e Windows CI não substituem conferência das planilhas comerciais.

Na validação local Linux: 1.936 testes Python executados, 73 ignorados por
condições de ambiente e nenhuma falha; 57 regressões específicas do transporte,
publicador, reconciliação e CLI aprovadas. Os 33 testes Node passaram. Ruff,
Pyright, consistência, documentação gerada, pip-audit e varredura Gitleaks
passaram. Resultados Windows/pacotes continuam condicionados ao workflow.

## Roteiro Windows / Work

1. Fechar cargas. Guardar backup dos arquivos privados; não apagar plano,
   journal, recibos nem a cópia SQLite vinculada.
2. Instalar Setup oficial 1.5.29 em **Preserve**, conferindo o SHA-256.
   Não misturar módulos avulsos.
3. No Terminal FARMA, manter o caminho real da mesma revisão:

```powershell
nexo versao
$planoFarma = "C:\NexoFlow\logs\privado\revisao-farma-existente.json"
nexo historico --planilhas reconciliar --revisao $planoFarma
```

Prosseguir somente com reconciliação aprovada; ela não envia lotes de fatos.

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma --max-lotes 1
nexo historico --planilhas conferir --revisao $planoFarma `
  --resumo-mensal "C:\NexoFlow\logs\privado\farma-piloto-conferencia-1.5.29.json"
```

O piloto precisa confirmar **um lote**, sem diferenças nem resposta incerta.
Código 3 de pausa é esperado; zero lotes não é sucesso. Com 4.301 lotes iniciais
e nenhum outro envio, restarão 4.300 depois do primeiro lote.
Se houver erro, não repetir automaticamente: preservar saída, revisão e comprovantes.
Devolver mensagem sanitizada e relatório de conferência quando necessário;
não enviar journal/backups com dados pessoais. Não editar assinaturas ou estados.

Após o Work validar o piloto e as partes, retomar a mesma revisão:

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma
nexo historico --planilhas conferir --revisao $planoFarma `
  --resumo-mensal "C:\NexoFlow\logs\privado\farma-fechamento-1.5.29.json"
```

Rollback de lote confirmado, somente com justificativa operacional e sem edição
posterior de terceiros:

```powershell
nexo historico --planilhas rollback --revisao $planoFarma --lote 1
```

A publicação mantém WRITING até fechar todas as tabelas. As cinco fontes Data
Studio não devem apresentar carga parcial como total. Preservar ressalva
`LIMITES_DA_API_NAO_HOMOLOGADOS`, pendências, semântica financeira, segmentos e
exclusões já autorizadas. PET comercial e implantação Hub permanecem separados.

## Distribuição

Candidata 1.5.29, sem reutilizar tag/pacotes 1.5.28. SHA validado, resultados de
CI/CodeQL, hashes, data real e links oficiais são registrados nas notas da release
após as verificações. Enquanto os checks não terminarem, este documento não
declara o pacote aprovado.
