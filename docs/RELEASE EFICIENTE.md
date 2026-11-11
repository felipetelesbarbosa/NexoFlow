# Releases com uma única geração de pacotes

A preparação da 1.5.33 executou desnecessariamente a preparação completa e outra compilação completa para publicar o mesmo SHA. A otimização do workflow é posterior àquela release; não altera o aplicativo instalado nem exige outra versão Windows.

## Fluxo preferido

1. Revisar o diff e executar os testes locais pertinentes uma vez. Alteração de Windows usa o versionamento vigente; correções de CI/documentação não criam uma nova versão do aplicativo.
2. No commit final de preparação autorizado, usar **`[skip release] [preparar pacotes]`**. Um único push executa qualidade, dependências, segredos, matriz Windows 3.11/3.14 com duas codificações, build, executáveis, Setup, Preserve/Clean/rollback e análise dos ZIPs. O marcador não autoriza publicação automática.
3. Acompanhar a execução com `gh run watch ID --exit-status --interval 60`. Usar os resultados e logs existentes; não repetir a suíte, a auditoria completa ou a análise do diff sem nova alteração/falha. O monitoramento determinístico evita consultas repetidas do modelo e mensagens sem mudança de estado.
4. Conferir o mesmo SHA na main, CodeQL, Meta nativo/MCP e a aprovação da geração. Não fazer um novo commit entre preparação e publicação.
5. Publicar os MESMOS artefatos, sem novo build:

```powershell
gh workflow run release-v1.yml --repo felipetelesbarbosa/NexoFlow --ref main `
  -f publish_release=true -f validated_run_id=ID_DA_EXECUCAO_APROVADA
```

6. Acompanhar o novo ID com `gh run watch`. Baixar os arquivos públicos, recalcular SHA-256, conferir CRC, versão e código e registrar a data real da publicação. Somente depois atualizar a documentação factual de publicação.

O caminho rápido pula os jobs pesados, mas exige evidências dos mesmos jobs na execução original. A tomada de decisão não depende de uma análise nova do modelo. Ele valida repositório oficial, workflow, branch main, SHA exato, estado final, todos os seis jobs exigidos, artefato único/não expirado com digest e a execução mais recente de CodeQL e Meta do mesmo SHA. Depois baixa o artefato daquele run, confere os hashes dos dois ZIPs, CRC, versão e assinatura dos dez módulos históricos. Usa os mesmos passos de publicação do fluxo completo, incluindo proteção da main/tag/release pública. Não substitui um ZIP aprovado por outro recompilado.

Se o artefato expirou ou o código mudou, é necessário gerar e validar novos pacotes. Falha/cancelamento, check ausente, outro SHA/branch/repositório, artefato duplicado e hashes divergentes bloqueiam a publicação. Não incrementar novamente uma versão ainda não publicada apenas por nova tentativa. Nunca reutilizar tag pública para código diferente.

## Compatibilidade e limites

- O modo completo manual continua disponível sem `validated_run_id`; preferir o caminho de reutilização após a preparação.
- Informar `validated_run_id` sem `publish_release=true` falha antes de baixar/publicar, sem iniciar os jobs pesados.
- O caminho rápido compartilha os mesmos passos de publicação por âncora YAML; não mantém um segundo publicador divergente.
- Nenhuma guarda operacional, teste obrigatório ou verificação de segurança foi removida: muda a reutilização de evidências do MESMO SHA, não o requisito de aprovação.
- ZIPs intermediários podem estar inacessíveis por restrição do ambiente. Isso não é motivo para recompilar automaticamente; distinguir bloqueio de transporte e falha do build. Não contornar o proxy ou alterar TLS.
- Testes do validador usam dados sintéticos e não publicam releases. A primeira publicação real pelo novo caminho deve registrar o tempo medido; não prometer redução percentual sem essa evidência.

A suíte completa permanece nas quatro combinações da matriz Windows (3.11/3.14 e duas codificações), que bloqueia o build por `needs`. A quinta execução completa no job de compilação foi removida por duplicação. Esse job conserva Python 3.13 para check-up e as validações próprias de executáveis, assinaturas, instalador e pacote instalado. Nenhum caso da suíte foi excluído.
