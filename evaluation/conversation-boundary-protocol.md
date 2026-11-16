# Protocolo de detecção na conversa — #40

Congelado em 16/11/2026, antes de implementar/calibrar o detector de #39.
Estado atual: **V2 contextual aprovada no corpus e no E2E Linux;
homologação nativa macOS pendente**.
A [ADR revisada](../docs/adr/0001-conversation-task-boundaries.md) selecionou
supervisão POSIX após prova nativa Linux. A implementação contextual #39
foi entregue; #40/#32 permanecem abertas porque o usuário confirmou que não
há Mac disponível para cumprir #30 e o E2E real macOS.

## Evolução V2

O primeiro resultado abaixo pertence ao detector por marcadores. Seus casos
reservados se tornaram conhecidos e foram usados apenas como desenvolvimento
na evolução. Antes da implementação contextual, o commit a92a48d congelou
[conversation-boundaries-v2.json](conversation-boundaries-v2.json), com 48
casos de desenvolvimento e 48 destinados à avaliação, balanceados por classe/idioma.
SHA-256: `42bb4112b4ddc745f750b03ed674a8ed65bbaa2c86df1496626ca4190b334228`.
Os critérios numéricos de precisão, recall e falso positivo não foram relaxados.

O teste de separação encontrou uma frase repetida entre splits, `v2-eval-26`,
com contextos diferentes. O scorer exclui essa linha sem mudar o corpus ou seus
rótulos, e registra seu ID. O [primeiro resultado sem filtro](conversation-boundary-results-v2-unfiltered.json)
permanece preservado como superado; a linha excluída era um acerto.

O [resultado V2](conversation-boundary-results-v2.json), em 47 casos estritamente
separados por texto, tem 16/16 novas tarefas, 15/15 continuações e 16/16 ambiguidades: zero falsos
positivos/negativos; precisão e recall 100% na amostra. A avaliação é pública,
autoria compartilhada com o código e possui pares traduzidos; não prova
generalização nem compreensão perfeita. Transições inferidas ainda exigem
escolha antes de executar. O [QA nativo Linux](../docs/contextual-conversation-qa.md)
verifica a aplicação dessa escolha, contadores, modelo inválido, sinal real,
retomada e cancelamento. A CI roda o scorer V2 nos dois sistemas com zero IA.

O scorer agora aceita `--corpus`; por padrão usa V2. O JSON da V1 e seu
resultado original permanecem imutáveis. Ajustes posteriores ao primeiro
score V2 foram de UI/controles, proteção de marcadores compostos e exclusão
explícita da frase repetida, sem recalibrar a detecção com os casos reservados.

## Protocolo e resultados históricos V1

SHA-256 do corpus congelado:
`df272d3b2c9ea8250f2205813254cfec2f8ec0fbedb80ccd9606ab50444cc219`.

## Corpus e separação

[conversation-boundaries.json](conversation-boundaries.json) contém 24 casos
de desenvolvimento e 24 de avaliação. Cada split tem oito `new`, oito
`continue`, oito `ambiguous`, metade PT e metade EN em cada classe.
`previous_task` é contexto sintético de teste, não autorização para armazenar
prompts reais no banco. `prompt` é a próxima mensagem dentro da conversa aberta.

Só desenvolvimento pode orientar regras/limiares. Os casos de avaliação são
reservados para executar uma versão congelada do detector; são públicos no
repositório, portanto não constituem avaliação cega independente. Pares PT/EN
são traduções dentro do mesmo split, sem inflar o número de objetivos distintos.
Não mover casos entre splits, ajustar rótulos para melhorar a pontuação ou
reutilizar o conjunto como treino após ver resultados. Se isso acontecer,
registrar contaminação e congelar um novo conjunto antes de calibrar novamente.
O classificador de tier existente não é um detector aprovado de fronteiras.

## Critérios fixados antes da calibração

Reportar matriz 3×3: esperado × observado (`new`, `continue`, `ambiguous`),
por idioma e no total, com todos os IDs de erros e latência p50/p95.
`ambiguous` significa abstenção e preservação da tarefa até decisão explícita.

- **Falso positivo de fronteira:** predição `new` quando o esperado é
  `continue` ou `ambiguous`. Limite: **zero** (0/16 na V1, 0/31 na V2 pontuada).
- **Falso negativo de fronteira:** caso `new` sem reconhecimento, incluindo
  abstenção. Recall mínimo **90%**; exige 8/8 na V1 ou pelo menos 15/16 na V2.
- Precisão de fronteira mínima **98%**, com denominador publicado; zero
  predições `new` não pode ser tratado como precisão perfeita nem aprovação.
- Continuações devem preservar identidade, histórico e modelo em **8/8**;
  ambiguidade deve preservar a tarefa e oferecer escolha em **8/8**.
- Classificação local de modelo: **zero** nas continuações e ambiguidades;
  **no máximo uma** por nova tarefa confirmada. Override manual dispensa
  classificação quando a escolha já estiver definida explicitamente.
- **Zero** inferências extras para classificação, **zero** instruções de
  roteamento adicionadas ao contexto e **zero** persistência de texto no banco.

Os limiares valem para esta amostra pequena e não estimam uma taxa populacional.
Aprovar o corpus não basta: o mecanismo nativo e a preservação de estado são
critérios independentes. Na falha de qualquer critério, publicar o resultado
e manter #40/#32 abertas.

## E2E após desbloqueio

Executar o mesmo roteiro em Linux e macOS **nativos**, com Claude autenticado,
versões de SO/Python/Claude e commit registrados, ferramentas desabilitadas,
estado temporário privado e prompts sintéticos curtos. Até 12 turnos de
resposta por SO; parar no limite e registrar o que faltou. A TUI não oferece
o mesmo teto de orçamento em dólares do modo print. Não usar CI/fake como
substituto nem copiar credenciais para outra máquina.

| Caso | Evidência necessária antes/depois |
| --- | --- |
| Mudança livre PT/EN na TUI já aberta | IDs de tarefa, sessão e execução; decisão local única; modelo da primeira resposta; tarefa anterior recuperável |
| Continuação PT/EN e marcadores citados/negados | Mesma identidade/modelo/contexto; contador de classificação inalterado |
| Ambiguidade e pedido composto | Nenhuma transição silenciosa; escolha explícita antes de alterar a tarefa |
| Override pelo picker apenas nesta sessão | Escolha manual persiste em continuações e na retomada; prioridade até a fronteira real |
| Sair e retomar | Mesmo UUID/decisão; zero reclassificações |
| Interromper antes e durante uma transição | Estado anterior recuperável, nenhuma tarefa parcialmente confirmada; lock mantido até saída do cliente |
| Erro de aplicação de modelo/sessão | Prompt não executado no destino errado; código/erro visível; zero retry automático |
| Execuções concorrentes e hook atrasado | Lock recusa duplicação; evento de execução antiga não altera decisão/observação atual |
| Recuperar explicitamente | Origem intacta, vínculo entre IDs, escolha preservada e contexto fornecido explicitamente |

Medir decisões locais, turnos e tokens do cliente antes/depois, latência de
detecção e de transição, contexto acrescentado e chamadas extras. Reportar
custo em dólares somente se houver medição disponível, distinguindo estimativa
do CLI de faturamento. Exportar apenas metadados permitidos, não transcrições.

## Matriz atual

| Capacidade | Linux | macOS |
| --- | --- | --- |
| Observação/bloqueio e comandos públicos manuais | Prova #38, Claude 2.1.325 | Não executado |
| Fronteira explícita ou inferida digitada na TUI | Supervisor/contexto validados PT/EN, Claude 2.1.325 | Host nativo indisponível |
| Corpus reservado | V1: 25% recall; V2 contextual: 100%, zero FP/FN | CI executa o detector local, sem Claude |
| Override, erro, interrupção e retomada da nova feature | Picker, escolha de continuação, erro de modelo, SIGINT durante transição, retomada/cancelamento nativos comprovados | Não executado; depende de #30 |

## Primeiro resultado, sem recalibração após avaliação

`python3 evaluation/conversation.py --output /tmp/conversation-results.json`
não inicia Claude nem usa IA. Retorna código 1 quando os limiares falham.
O [resultado versionado](conversation-boundary-results.json) registra hash do
corpus e do detector, matriz 3×3 por idioma, IDs dos erros e latências locais.
O status no JSON do corpus pertence à imagem original congelada; resultados
ficam separados para preservar seu hash.

| Split | Novas reconhecidas | Falsos positivos | Falsos negativos | Precisão de fronteira | Recall |
| --- | --- | --- | --- | --- | --- |
| Desenvolvimento | 4/8 | 0 | 4 | 4/4, 100% | 50% |
| Avaliação reservada | 2/8 | 0 | 6 | 2/2, 100% | 25% |

No reservado, 8/8 ambiguidades resultaram em abstenção. Duas continuações
foram reconhecidas explicitamente; seis também resultaram em abstenção,
preservando a tarefa com aviso. Nenhuma continuação/ambiguidade gerou fronteira.
Esses números avaliam o detector, não demonstram todo o ciclo nativo.

O resultado V1 **não aprova #40**. Naquela rodada, o detector não foi ajustado
aos casos reservados após pontuá-los. Evoluções que calibrem com esses erros devem usar outro
conjunto reservado antes de alegar generalização. A
[prova nativa](../docs/native-supervisor-proof.md) é evidência separada do
controle para marcadores, sem custo/faturamento geral medido.

Artefatos seguintes devem registrar SHA-256 do corpus, commit do detector,
versões, contadores, erros e limitações. Estes resultados não encerram #40.
