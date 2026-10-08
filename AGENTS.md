# NexoFlow 1.0

Ao atualizar este repositório, mantenha a identificação pública **NexoFlow 1.0**.

- Use exatamente `NexoFlow 1.0` como mensagem de commit, sem sufixo ou texto adicional.
- Atualize a `main`; não crie branches para atualizações rotineiras.
- Mantenha o título do release `NexoFlow 1.0`, a tag `v1.0` e os nomes estáveis dos pacotes. Só altere a versão quando o usuário pedir explicitamente.
- Ao publicar pacotes atualizados, republice o release para que a data corresponda à nova publicação.
- Preserve as credenciais e os diagnósticos privados fora do Git e dos pacotes públicos.
- Use os nomes de pagamento: 0 Cancelado, 1 Dinheiro, 2 Débito, 3 Crédito, 4 Ticket, 5 Pix por Link de Pagamento, 6 Pix no POS.
- Horários operacionais usam `America/Belem` (UTC-3).
- Status de pedido: EmAberto=-2, PendenteDePagamento=-1, EmProcessamento=0, ProntoParaRota=4, EmTransito=1, Concluido=2, Cancelado=3. Estados abertos permanecem em rechecagem; ProntoParaRota, EmTransito e Concluido contam como venda, sem cancelamento nem pagamento 0.

- Textos apresentados ao usuário devem usar português brasileiro (pt-BR), com acentos e cedilha. Preserve identificadores técnicos. BAT/CMD em UTF-8 sem BOM com `chcp 65001`; PowerShell em UTF-8 com BOM; HTML com `lang="pt-BR"`; metadados dos executáveis em pt-BR.
