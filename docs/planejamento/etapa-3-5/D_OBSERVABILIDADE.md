# D. Observabilidade mínima e contrato técnico
07/11/2026. A coleta mínima descrita como instalada é real. Grafana, Prometheus e Loki permanecem propostas; nenhum endereço administrativo foi publicado.

## Seleção e medição
Selecionado agora: Python stdlib + systemd timer + SQLite de telemetria + saída Prometheus textfile. Reutiliza o monitor independente existente e os alertas Cloudflare fora da VPS. Não instala banco de séries, UI ou agente privilegiado adicional; não expõe socket Docker ao frontend.

Coletor /usr/local/sbin/nexoflow-telemetry: a cada cinco minutos; limite 128 MiB, CPUQuota 25%, Nice 10, timeout 110s, lock contra concorrência e umask 0077. Medição inicial: 14,55s de parede, aproximadamente 0,68s de CPU em uma leitura do serviço; MemoryPeak não foi fornecido pelo systemd e não foi inventado. O teto de 128 MiB é configurado, não uma medição de pico.

91 séries na amostra expandida, sem collection_error. Saída privada em /var/lib/nexoflow/telemetry: metrics.sqlite, latest.json, metrics.prom. Sem servidor HTTP. A API futura deve ler cópia saneada por papel próprio; não dar acesso root/Docker ao frontend.

## Cobertura instalada
- CPU (delta /proc/stat), load, RAM/swap e espaço livre.
- Saúde/restarts/log bytes/CPU de cada um dos sete serviços; memória relativa ao limite de cada contêiner.
- Contadores de bytes de rede física e de leitura/escrita/I/O do disco raiz. São contadores para derivar taxas, não taxa instantânea.
- Tamanho de bancos, conexões, tabelas/índices agregados, estimativas de linhas vivas/mortas e tabelas selecionadas.
- Tarefas por segmento/estado, tentativas, checkpoints, fila mais antiga, última conclusão e pendências históricas.
- Idade do backup original/Hub e crescimento dos três volumes nomeados.
- Monitor independente detecta telemetria ausente/atrasada por 15 min e disco preventivo em 70%; o alerta de 85% continua no mecanismo original.

Os contadores de tarefas/tentativas são gauges do banco, não contadores monotônicos de eventos. Não calcular taxa de erro dividindo contagens de escopos incompatíveis. Estados sem linha não representam série zero no export atual; o futuro consumidor deve aplicar domínio conhecido com distinção de ausência de coleta.

## Retenção e segurança
Detalhe por cinco minutos: 30 dias. Agregado diário min/max/soma/n: 365 dias. Média diária = soma/n; não é percentil. SQLite limitado a 65.536 páginas de 4 KiB (256 MiB); páginas livres são reutilizadas. O limite interrompe novas gravações em falha segura, e o alerta de atraso detecta isso. Não há limpeza de pedidos, LTV ou auditoria de negócio.

Whitelist de nomes de métricas, chaves e valores de labels, números finitos e máximo de 128 séries por coleta. Sem URL, query string, Authorization, DSN, CPF, nome de cliente, telefone, endereço ou payload em métricas. Campos desconhecidos são recusados. Logs de erro do coletor usam código fixo; não imprimem exceção com credencial. Arquivos privados e exportação pública inexistente.

Testes: expiração do detalhe preservando agregado, segredo sentinela/campo desconhecido recusado, label indevida, NaN e cardinalidade recusados; monitor sem alerta quando saudável, alerta em atraso e limite preventivo; coleta real sem erros.

## Comparação com a stack futura
| Opção | Orçamento inicial para ensaio, não medição | Disco/retensão propostos | Decisão |
| --- | --- | --- | --- |
| Coletor atual | teto 128 MiB, CPU medida baixa | SQLite até 256 MiB + arquivos pequenos | Instalado |
| Prometheus + exporters | 400–1.000 MiB combinados | 15 dias / teto 2 GiB no ensaio | Adiar até métricas API e carga representativas |
| Grafana | 256–512 MiB | Configuração/painéis privados | Adiar para Etapa 5 |
| Loki + agente | 384–1.024 MiB | 7 dias / orçamento 2 GiB | Adiar até sanitização de logs na origem |
| Stack combinada | cerca de 1–2,5 GiB, variável por cardinalidade/consultas | Totais limitados e monitorados | Capacidade plausível, ainda não certificada |

Faixas são hipóteses para limites de teste, não capacidade prometida do produto. Medir RSS, CPU, cardinalidade, WAL, ocupação e p95 sob carga antes de instalar. Prometheus armazena em média 1–2 bytes/amostra comprimida, mas WAL/head, índices e cardinalidade exigem folga; isso não estima a RAM de uma stack concreta.

## Contrato para o Codex: chamadas HTTP
Instrumentação de cada tentativa, sem alterar o contrato financeiro:
http_client_requests_total{fonte,segmento,ambiente,metodo,rota_modelo,status,classe_erro}.
http_client_duration_seconds: histograma por operação/segmento, com buckets fixos e limites de cardinalidade. Exemplo de buckets: 0.05,0.1,0.3,0.5,1,2,5,10,30,90. Registrar timeouts/cancelamentos separadamente, não como HTTP 200. Retentativa conta como tentativa; uma métrica distinta conta operações finais.

Enumerar classe_erro: rede, proxy, tls, timeout, autenticacao, permissao, limite_429, http_4xx, http_5xx, contrato, identidade, financeiro, armazenamento, desconhecido. Não inferir token inválido de todo 403 nem ausência de pedidos de 503. Não gravar corpo bruto nem URL autenticada, especialmente a API histórica com token em query.

Média = soma de durações/número de tentativas; p95 calculado do histograma, nunca média dos p95s. Sucesso técnico, tarefa concluída e pedido financeiramente válido são medidas distintas. 400/401/403/429/500 explícitos, com denominador e janela documentados.

## Contrato para tarefas e eventos
Métricas: jobs_started/completed/failed/retried, duration histogram, queue_depth, oldest_job_age, checkpoint_age, processed_orders e data_pending, por ambiente/segmento/tipo enumerado. IDs opacos de tarefa/correlação ficam em evento detalhado privado, nunca como labels de séries.

Evento permitido: schema_version, timestamp UTC, ambiente, segmento, componente, operação enumerada, tarefa_id opaco, correlação opaca, tentativa, duração_ms, estado, código_erro fixo e contagens. Nenhum texto livre de erro externo. Testar sentinelas de segredo/PII, separação FARMA/PET, exceções e redirects antes de ligar a fonte real.

Pontos ainda não instrumentados: requisições por integração, códigos/latência média/p95, causas proxy/TLS e custos comerciais. Não aparecem como dados medidos nesta etapa. São contratos a implementar pelo Codex; os conectores comerciais seguem recusando leitura e escrita.

Fontes: script instalado e testes; [Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/).

