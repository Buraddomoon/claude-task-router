# Detecção contextual e homologação Linux — #39/#40

16/11/2026, Linux x86_64, Python 3.14.3, Claude Code 2.1.325, PTY real,
autenticação existente, ferramentas desabilitadas e diretório temporário.
Implementação contextual em 612006d, com refinamentos de controles/UI posteriores.

## Comportamento entregue

`--conversation-routing` agora reconhece objetivos independentes sem exigir
`Nova tarefa:`. Compara palavras do pedido com um contexto lexical limitado
da tarefa, somente em memória. O contexto vem do pedido inicial; numa retomada,
lê no máximo 1 MiB do começo da transcrição nativa validada e usa o primeiro
pedido humano da própria sessão. Não copia esse pedido para o banco ou para
uma nova conversa. Sem contexto disponível, abstém e mantém tarefa/modelo.

Uma mudança inferida fica bloqueada antes da inferência. A UI oferece criar
nova tarefa, continuar na mesma ou cancelar, usando um código efêmero. O
usuário limpa o rascunho com **Ctrl-C uma vez** e envia o comando exibido.
O código expira em três minutos; controles inválidos/expirados nunca chegam
ao modelo. Pedidos e escolhas pendentes não são persistidos pelo roteador.

Confirmar nova tarefa classifica o modelo uma vez e abre novo UUID na TUI do
mesmo terminal. Confirmar continuação reabre o mesmo UUID com o modelo salvo
e o pedido pendente, sem classificar. Cancelar deixa a sessão atual intacta.
Marcadores explícitos inequívocos continuam disponíveis; negação, citação e
instruções futuras/compostas incertas não causam troca automática.

Essas regras são heurísticas PT/EN e não compreensão perfeita de intenção.
Mensagens de outros agentes/agendamentos não foram homologadas; a escolha
efêmera protege as transições inferidas, mas não prova todas as origens de
eventos nativos. O modo permanece opt-in, com Claude Code 2.1.295+.

## Corpus e separação

O resultado inicial de 25% de recall continua preservado em
[conversation-boundary-results.json](../evaluation/conversation-boundary-results.json).
Os erros da V1 passaram a desenvolvimento. Antes de implementar o detector
contextual, foi congelada a [V2](../evaluation/conversation-boundaries-v2.json),
commit a92a48d, com 48 casos de desenvolvimento e 48 casos destinados à avaliação.
O teste de separação encontrou `v2-eval-26`, cuja frase também aparecia no
desenvolvimento com outro contexto. O corpus não foi alterado; esse caso foi
excluído da pontuação reservada, restando **47 casos**. O
[resultado anterior sem filtro](../evaluation/conversation-boundary-results-v2-unfiltered.json)
foi preservado e identificado como superado. A exclusão retirou um acerto,
não um erro. Na imagem congelada, cada classe tem 16 casos, oito PT e oito EN;
o conjunto pontuado tem 16 novas tarefas, 15 continuações e 16 ambiguidades.
Os pares traduzidos
não são objetivos independentes; os autores do código e do corpus são os
mesmos, e o conjunto é público. Não é uma avaliação cega independente.

O [resultado V2](../evaluation/conversation-boundary-results-v2.json) registra
16/16 novas tarefas, 15/15 continuações e 16/16 ambiguidades reconhecidas,
zero falsos positivos e zero falsos negativos na amostra. Precisão/recall de
fronteira são 100% (16 predições positivas), acima dos limiares fixados de
98%/90%. Isso não estima uma taxa populacional nem garante linguagem arbitrária.
O scorer usa o contexto sintético do corpus; a aplicação da escolha é testada
separadamente. Após pontuar, só foram corrigidas orientações de limpeza de
rascunho e proteções de controle/marcador composto, sem ajustar aos casos
reservados. A CI verifica a V2 em Linux/macOS.

## Evidência nativa e contadores

[native-context-evidence.json](../evaluation/native-context-evidence.json)
contém somente IDs/modelos/eventos, hashes de fontes, uso do cliente,
contadores e resultados. O [harness opt-in](../evaluation/native_conversation.py)
envolve a CLI real e conta chamadas locais ao classificador; não registra
prompts, transcrições, argumentos de processo ou credenciais.

| Cenário | Observação |
| --- | --- |
| Mudança PT sem marcador | A, `f101870e-6804-454a-813d-58287f67f436`, Haiku: pedido retido; antes da escolha, uma tarefa e zero classificações. Confirmação cria B, `b12d2625-d2e2-4f04-8cd0-c3227f7aab05`, Sonnet, uma classificação |
| Picker e escolha “mesma tarefa” | Picker `s` escolhe Haiku em B. Novo objetivo EN retido; escolher continuação reabre B/Haiku com o pedido, uma única vez. Contador total continua 1; B tem duas execuções |
| Modelo inexistente | Outro estado: Haiku inicial; nova tarefa confirmada recebe modelo inválido configurado para o teste. Cliente informa `model_not_found`, sem resposta útil, retry ou fallback do roteador; anterior intacta. Uma classificação; saída manual da TUI retorna 0 nativo |
| Interrupção durante transição | Harness injeta SIGINT real no launcher imediatamente após ele enviar SIGTERM ao cliente antigo. Retorna 143; nenhuma classificação nem tarefa sucessora |
| Retomar após interrupção | Mesmo UUID `ba548736-6282-45ef-a6e4-c0c9482135b1`, ID Haiku salvo e histórico. Novo pedido EN sem marcador é reconhecido a partir do contexto relido; cancelamento preserva sessão. Zero classificações e zero respostas novas |

Todos os estados tiveram `integrity_check=ok` e locks liberados após a saída.
Nenhum controle `ctr:` virou mensagem de usuário na transcrição. As mensagens
de bloqueio ficam como eventos nativos `system/informational`, conforme o
contrato público de UserPromptSubmit, sem `additionalContext` do roteador.
Não se usou `stopReason` nem `continue:false` para injetar instruções.

Foram cinco respostas únicas de modelo nos três cenários, uma interrompida,
mais um erro nativo de modelo indisponível; abaixo do teto de 12 turnos do
protocolo. O modelo Sonnet produziu texto simulando ferramentas apesar de elas
estarem desabilitadas; foi interrompido para limitar o ensaio. Não houve tool
call real. Isso não é evidência de qualidade da resposta. Mensagens de thinking
e texto com o mesmo ID são contadas uma só vez. Tokens são os informados pelo
cliente, não uma auditoria de fatura; custo em dólares não foi medido.

O harness registrou uma chamada local no cenário normal, uma no cenário de
erro, zero na interrupção e zero na retomada. Não houve inferência para
classificação nem campos de contexto de roteamento adicionados. A latência
local individual está no ledger em nanossegundos; não representa a latência
completa de reiniciar a TUI ou o tempo de resposta do provedor.

## Reprodução e pendência externa

Em terminal nativo, usando diretórios temporários próprios já criados:

```bash
python3 evaluation/native_conversation.py --record /tmp/ctr-qa/normal.jsonl -- \
  --state-dir /tmp/ctr-qa/state new \
  'Traduza as etiquetas do menu. Responda somente INICIO.' \
  --cwd /tmp/ctr-qa/project --model haiku --conversation-routing -- --tools '' --no-chrome
```

Digite um objetivo independente sem marcador, confira o bloqueio e o contador,
pressione Ctrl-C uma vez e use a escolha exibida. Repita escolhendo a mesma
tarefa após um picker com `s`. Saia e confira IDs, modelos e contagem.
`--interrupt-handoff` antes do primeiro `--` injeta o sinal real durante uma
transição, deliberadamente para o ensaio; não é opção do produto.

O teste de erro usa configuração temporária cujo tier balanced aponta a um
modelo inexistente, com a tarefa inicial explicitamente em Haiku. Não altere
o padrão global pelo picker. Registros são arquivos novos 0600 e não são
enviados automaticamente a lugar algum.

**#39 atende à implementação e ao smoke nativo. #40 e #32 continuam abertas
exclusivamente pelo aceite nativo macOS/#30 ainda não executado.** O usuário
confirmou nesta sessão que não há Mac disponível. A CI macOS usa cliente
simulado e não satisfaz essa dependência; este relatório não declara o projeto
inteiro ou a homologação macOS concluídos.
