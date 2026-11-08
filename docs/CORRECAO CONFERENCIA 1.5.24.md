# Conferência de itens do histórico: correção 1.5.24

## Causa

Na conferência de um preparo comercial Windows, o SQLite 3.50.4 mostrou
`SEARCH incoming USING INDEX sqlite_autoindex_incoming_1 (t=?)`, mesmo com
`incoming_pedido` disponível. A consulta filtrava pedido e segmento, mas o
`ORDER BY k` permitia preferir o índice genérico `(t,k)`. Assim, cada pedido
podia examinar novamente todos os itens do segmento. CPU ativa não comprovava
avanço útil; o terminal somente informava a conclusão depois dessa etapa.

O tamanho do journal não é a causa demonstrada: ele armazena entradas, operações,
lotes e os dados necessários às conferências. Não apagar nem compactar esse
arquivo durante uma execução.

## Correção e regressão

`from_published` exige o índice por pedido/segmento que já cria antes da consulta.
Somente os itens correspondentes precisam ser ordenados. Os filtros de segmento
e vigência, valores em centavos, compradores distintos, estados e semântica
financeira continuam sendo conferidos integralmente.

A regressão usa pedidos e itens sintéticos e um orçamento de instruções SQLite,
sem limite de tempo dependente da máquina. A consulta anterior excede o orçamento;
a corrigida precisa concluir e manter contagem de pedidos, itens, unidades e
faturamento. Os testes de publicação cobrem preparo, piloto, retomada,
conciliação, edição externa e rollback; Windows e pacote exigem validação no CI.

## Retomada operacional

1. Se o comando de capacidade ainda estiver executando a consulta lenta,
   interromper com Ctrl+C e aguardar o encerramento. Preservar backup, plano,
   SQLite, WAL e journals. O comando de capacidade não publica fatos comerciais.
2. Instalar a distribuição 1.5.24 validada pelo Setup em **Preserve**. Não copiar
   módulos avulsos nem reaproveitar o número de uma release anterior.
3. Confirmar versão, perfil, origens e as cinco fontes comerciais. A atualização
   não exige renovar autorizações Google que continuam válidas nem reimplantar
   o conector quando o código implantado já é o corrigido para os schemas.
4. Conferir o hash do backup consistente já utilizado. Preparar uma revisão com
   nome inédito sobre esse mesmo backup. O plano interrompido permanece como
   evidência; não alterar assinaturas para fazê-lo passar com outro publicador.
5. Conferir capacidade, continuar com um lote de segurança e, após a conferência,
   retomar a mesma revisão nova até o fechamento. Exigir READY integral, zero
   lotes restantes e diferenças mensais/TOTAL e LTV iguais a zero.

Não recolher novamente a API para resolver a lentidão. Não publicar dados de
teste nos destinos comerciais. Só após fechar FARMA repetir em sessão PET
com configuração, fontes, backup e revisão próprios.
