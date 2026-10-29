# Cidades, estados e bairros

O NexoFlow padroniza a grafia dos municípios conforme o IBGE e mantém os
estados por extenso, como **Pará**. Os bairros de Belém e Ananindeua usam as
referências abaixo, com acentos e correções de grafia revisadas.

No campo cidade desta base, **Pa** significa **Belém**, conforme confirmação
operacional. Variações de maiúsculas, espaços nas extremidades e caracteres
invisíveis em **Manaus** recebem a grafia oficial **Manaus**.

Conjuntos e subdivisões permanecem identificados: Cidade Nova 6 e Cidade
Nova VI, por exemplo, passam a **Cidade Nova VI**. Qualificadores de distrito
redundantes recebem o nome do bairro, como **Tapanã**.

A padronização é aplicada nas revisões da Weni, na gravação do Sheets e nas
tabelas do Data Studio. A revisão verifica cidade, estado, bairro e CEP antes de
aplicar alterações na Weni. Casos sem referência confiável permanecem para
conferência do endereço.

Uma referência de CEP conferida pode corrigir cidade, estado e bairro. O CEP
informado é preservado. A consulta deve corresponder ao mesmo CEP do contato;
respostas sem município válido permanecem para revisão.

Referências consultadas em 13/10/2026:

- [Municípios e unidades federativas — IBGE](https://servicodados.ibge.gov.br/api/docs/localidades)
- [Bairros de Belém](https://pt.wikipedia.org/wiki/Lista_de_bairros_de_Bel%C3%A9m_(Par%C3%A1))
- [Bairros de Ananindeua](https://pt.wikipedia.org/wiki/Lista_de_bairros_de_Ananindeua)
- [Polos e bairros — Prefeitura de Ananindeua](https://www.ananindeua.pa.gov.br/midias/legislacao/2366_decreto_n_2.984_de_24_de_junho_de_2025.pdf)
- [Bairro Levilândia — Prefeitura de Ananindeua](https://ananindeua.pa.gov.br/sehab/noticia/9343/prefeitura-de-ananindeua-entrega-certidoes-de-registro-de-imoveis-a-familias-do-bairro-levilandia)
- [Consulta pública de CEP — ViaCEP](https://viacep.com.br/)
