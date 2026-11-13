# Uso pessoal diário

O launcher continua exclusivo para Claude Code. Não exige conta adicional,
chave compartilhada, serviço em nuvem ou instruções de roteamento no contexto.
O usuário autentica diretamente no Claude Code original.

```bash
ctr run "Corrija o typo no README.md"    # tarefa nova, decisão local
ctr "Continue com os testes"             # retoma a tarefa recente deste projeto
ctr                                      # abre a última tarefa deste projeto
ctr run "Outra tarefa: implemente OAuth" --new
ctr run "Ajuste mais um detalhe" --continue
```

Uma frase entre aspas com espaços pode ser usada como atalho para `run`.
Palavras isoladas desconhecidas continuam sendo erros de comando, para que
um typo como `ctr sttaus` não dispare inferência. `new`, `resume UUID`,
`model` e `recover` continuam disponíveis e preservam sua gramática.

## Como a fronteira é decidida

`run` reconhece marcadores locais PT/EN como “continue”, “retome”, “na mesma
tarefa”, “now test it” e “agora valide o resultado”. Usa somente a última
tarefa do diretório canônico atual e exige recência de até 12 horas para
essas continuações automáticas. Uma execução anterior com erro pede escolha
explícita. Não há classificação de complexidade nem leitura de config nova
na continuação. `--new`/`--continue` sempre permitem decidir manualmente.

Sem marcador claro, um prompt inicia tarefa nova. Uma continuação sem tarefa
anterior, antiga ou com falha produz instrução para `resume`/`recover` em vez
de perder contexto silenciosamente. `ctr` sem prompt é uma escolha de abrir
a última tarefa e não aplica o limite de recência. O lock continua impedindo
duas execuções simultâneas da mesma tarefa.

Isso é detecção conservadora por regras, não leitura da intenção do usuário.
Não identifica mudanças arbitrárias de assunto dentro do terminal nativo do
Claude: as mensagens dessa sessão seguem sendo continuações. Para outro
assunto, saia e use `ctr run --new`. Não se intercepta o terminal nem se
injeta um classificador remoto para tentar adivinhar essas mudanças.

## Classificação

A política `local-rules-v4` não permite que um prefixo simples desative os
sinais de risco posteriores. “Corrija o typo para eliminar a vulnerabilidade
de autorização” recebe advanced; “formate o arquivo removendo os registros
antigos” não recebe economy. Citações, nomes de arquivo e identificadores
explícitos continuam diferenciados do trabalho solicitado. Regras continuam
heurísticas: `classify`, `--model`, `--tier` e `min_tier` ajudam a ajustar.

Restrições comuns de apresentação, como “retorne somente JSON” e “sem outras
alterações”, não contam sozinhas como trabalho adicional. Ações ou riscos
adicionais nesses trechos continuam sendo considerados.

O corpus anterior agora é uma regressão fixa, não um conjunto reservado novo
para esta política. O comando `python3 evaluation/run.py` continua aplicando
seus limites; o novo comportamento também tem regressões adversariais.
