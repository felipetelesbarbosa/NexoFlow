# Antivírus e confiança

As detecções do Kaspersky no `NexoFlow Noturno.exe` foram observadas pelo operador. A quarentena explica a remoção do EXE e o ícone ausente. Não há laudo que confirme falso positivo nem prova de que permissões NTFS sejam a causa.

## Medidas da distribuição

- Launchers nativos compilados do código-fonte, sem packer, ofuscação ou credenciais embutidas.
- Processos filhos visíveis, caminhos explícitos e manifesto Windows `asInvoker`; elevação restrita à instalação/desinstalação quando necessária.
- Recursos de versão e ícones próprios finalizados antes dos hashes/assinaturas.
- Testes de console, executáveis e instalação real no Windows, além de análise estática, dependências e segredos.
- Manifesto SHA-256 do payload e hashes dos ZIPs publicados no release.
- Suporte a assinatura Authenticode com certificado confiável, timestamp e conferência do editor. Sem certificado configurado, os arquivos continuam sem assinatura.
- Relatório do build com commit, hashes dos EXEs/scripts e estado das assinaturas. O Microsoft Defender examina a pasta quando está ativo no runner; indisponibilidade é registrada, sem afirmar aprovação.

O relatório `RELATORIO DE SEGURANCA.json` fica no ZIP do Setup. A verificação de integridade/testes não comprova ausência de malware. Um exame sem detecção em uma máquina não garante aceitação pelo Kaspersky, EDR corporativo ou SmartScreen.

## Se houver detecção

1. Preserve versão, nome completo da detecção, SHA-256 e relatório do antivírus. Não envie credenciais, logs de clientes ou planilhas para serviços públicos de análise.
2. Confira a origem do download e os hashes publicados. Uma versão recompilada muda de hash, mesmo mantendo o nome do programa; aprovação de uma versão anterior não se transfere automaticamente.
3. Solicite reanálise pelo canal oficial do fornecedor: [Kaspersky OpenTip](https://opentip.kaspersky.com/) ou suporte corporativo. Envie somente o EXE público identificado e seu hash, quando autorizado. O responsável pelo envio deve acompanhar o protocolo e o resultado; este repositório não afirma ter obtido aprovação.
4. Para bloqueio do Windows/Defender, use o [portal de envio de arquivos da Microsoft](https://www.microsoft.com/en-us/wdsi/filesubmission), seguindo as instruções para desenvolvedores e conservando o protocolo.
5. Em computador corporativo, peça à TI uma decisão por editor/arquivo verificado. Não desative o antivírus nem exclua pastas inteiras, Downloads ou Temp da proteção.

O NexoFlow não altera Defender, Kaspersky, SmartScreen, UAC ou ACLs para forçar confiança. Se o EXE do Noturno estiver indisponível, o Setup valida separadamente a entrada em script e configura o atalho com seu ícone; isso mantém a execução disponível, sem declarar que o EXE foi aprovado pelo antivírus.

Consulte [assinatura Windows](ASSINATURA%20WINDOWS.md). Certificado, análise dos fornecedores e políticas corporativas são etapas externas; não podem ser substituídas por uma mudança de nome, ícone ou permissão.
