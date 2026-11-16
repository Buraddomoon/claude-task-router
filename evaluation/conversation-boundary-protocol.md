# Protocolo de detecção na conversa — #40

Congelado em 16/11/2026, antes de implementar/calibrar o detector de #39.
Estado: **detector avaliado; critérios não atingidos; E2E completo pendente**.
A [ADR revisada](../docs/adr/0001-conversation-task-boundaries.md) selecionou
supervisão POSIX após prova nativa Linux. O modo experimental já existe,
mas a detecção livre e a homologação macOS #30 continuam pendentes.

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
  `continue` ou `ambiguous`. Limite: **0/16** no conjunto reservado.
- **Falso negativo de fronteira:** caso `new` sem reconhecimento, incluindo
  abstenção. Recall mínimo **90%**; com oito casos, exige **8/8**.
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
| Fronteira explícita digitada na TUI | Supervisor validado PT/EN, Claude 2.1.325 | Host nativo indisponível |
| Corpus reservado contra detector experimental | Executado; recall 25%, reprovado | Detector local portátil; não executado nesse SO |
| Fluxo completo, override, erro, interrupção e retomada da nova feature | Override/retomada nativos; erros e transição interrompida ainda sem E2E completo | Não executado; depende também de #30 |

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

O resultado **não aprova #40**. O detector não foi ajustado aos casos reservados
após pontuá-los. Evoluções que calibrem com esses erros devem usar outro
conjunto reservado antes de alegar generalização. A
[prova nativa](../docs/native-supervisor-proof.md) é evidência separada do
controle para marcadores, sem custo/faturamento geral medido.

Artefatos seguintes devem registrar SHA-256 do corpus, commit do detector,
versões, contadores, erros e limitações. Estes resultados não encerram #40.
