# Modelos de configuração

Exemplos para configurar os acessos do NexoFlow. Copie `secrets_config.example.py` para `secrets_config.py` na raiz da instalação e preencha com suas próprias credenciais.

Configure `PERFIS["FARMA"]` e `PERFIS["PET"]`: token da organização Weni, token autorizado da API e IDs de Dashboard, Operação e Histórico de cada marca. A mesma credencial Google pode ser compartilhada, com acesso aos seis arquivos. Os dois perfis usam produção. Veja [segmentos e fluxos](../docs/SEGMENTOS%20E%20FLUXOS.md).

O exemplo de webhook é opcional. Consulte o [guia de instalação](../docs/README%20INSTALACAO.md). Os modelos não incluem acessos reais.

A Recompra FARMA usa a base geral mesmo em cargas pequenas ou quando o modo automático normalmente dispensaria a listagem; dados insuficientes ficam pendentes. Isso não troca os tokens, destinos ou regras de consulta dos demais módulos. Guarde os arquivos preenchidos apenas na instalação local.
