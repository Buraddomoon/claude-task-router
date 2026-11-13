# Arquitetura e pesquisa

Consulta: 13/11/2026. Ambiente observado: Claude Code 2.1.323, Codex CLI 0.167.2. Documentação e disponibilidade podem mudar; `ctr doctor` verifica a interface instalada sem inferência.

## Decisão

Usar um launcher Python com biblioteca padrão. A unidade de roteamento é uma tarefa criada explicitamente com `ctr new`, associada a uma sessão UUID do Claude. O launcher classifica o primeiro prompt e passa `--model` antes de iniciar o Claude. `ctr resume` recupera a escolha salva e passa `--resume` com o UUID exato. Mensagens adicionais ficam na mesma sessão; não há classificação de continuações.

| Superfície | Capacidade verificada | Uso nesta solução |
| --- | --- | --- |
| Claude CLI | Modelo por argumento, sessão explícita, retomada e modo print | Execução com terminal e autenticação existentes |
| Hooks Claude | Eventos de início e mudança observam modelo; hooks de prompt não oferecem setter do modelo principal | Observação silenciosa, sem texto injetado |
| Claude Agent SDK | Host controla a sessão e oferece controle de modelo | Possível evolução, dispensável para este launcher |
| Codex CLI | `--model`, `exec`, `resume` | Referência de arquitetura; não é destino do roteador Claude |
| Codex app-server | Host controla threads e turnos via protocolo | Integração mais ampla que o problema requer |
| Skills | Instruções/workflows carregados pelo agente | Não são usadas para fingir troca do modelo principal |

Fontes primárias: [Claude CLI](https://code.claude.com/docs/en/cli-reference), [sessões](https://code.claude.com/docs/en/sessions), [hooks](https://code.claude.com/docs/en/hooks), [Agent SDK](https://platform.claude.com/docs/en/agent-sdk/python), [Codex CLI](https://learn.chatgpt.com/docs/developer-commands?surface=cli), [Codex app-server](https://learn.chatgpt.com/docs/app-server). Codex foi verificado também pelo manual oficial atualizado da skill openai-docs e pelo `--help` local. Não há uma skill de roteamento carregada em cada mensagem.

## Política local

Tarefas pequenas com intenção delimitada e reconhecida usam `economy` (haiku); programação usual ou ambiguidade usa `balanced` (sonnet); sinais de risco ou raciocínio complexo usam `advanced` (opus). Comprimento é um sinal secundário, nunca a única medida. Textos PT/EN são normalizados localmente. Citações e palavras-chave podem induzir falsos positivos; a explicação e o override são parte do contrato. Não há classificador remoto ou dependência de embeddings.

Aliases são configuráveis para cada provedor; não há preços nem versões comerciais codificados. SessionStart registra o ID ativo quando disponível. Quando esse campo opcional falta (observado em 2.1.323), guarda o caminho validado da transcrição; após o processo terminar, uma leitura de até 1 MiB do final procura o ID em uma resposta da própria sessão e posterior ao início da execução. Só o ID é persistido, fixando a versão para retomadas. Uma mudança já observada por hook tem prioridade sobre essa recuperação. A documentação [de modelos](https://code.claude.com/docs/en/model-config) distingue aliases móveis, IDs explícitos, seleção manual e modos híbridos. `default` e `opusplan` são recusados porque não representam um único modelo estável. Outros IDs são encaminhados sem presumir disponibilidade na conta.

## Persistência e controle

SQLite guarda UUID, diretório de trabalho, modelo atual, tier, motivos enumerados, snapshot de política, tamanho e hash do primeiro prompt, caminho da transcrição, timestamps e eventos. O texto do prompt e o conteúdo das transcrições ficam fora desse banco. O Claude mantém seu próprio histórico segundo as configurações existentes. Cada tarefa possui lock POSIX durante sua execução; hooks atualizam somente sessões já conhecidas e no diretório esperado. Transações são curtas e não ficam abertas enquanto o subprocesso executa.

`--model` explícito e `ctr model` têm prioridade. O hook PostModelSwitch registra a mudança efetiva feita por `/model`, clientes ou pelo próprio Claude. Hooks não escrevem nada em stdout: nenhum token de contexto de roteamento é acrescentado. Em versões sem PostModelSwitch, `ctr doctor` informa incompatibilidade; versão mínima suportada: 2.1.251.

## Limites deliberados

- Uma nova tarefa exige `ctr new`. `/clear`, `/resume` e forks feitos dentro do Claude não criam tarefas gerenciadas; sair e usar o launcher mantém a fronteira explícita.
- O roteador não troca modelo durante a execução. Fallbacks e substituições internas do Claude/provedor ainda podem acontecer, inclusive no modo plan com Haiku; o launcher não promete impedir essas políticas. Não configura fallback e não usa `opusplan`.
- Se hooks forem desativados por configurações administradas ou pelo usuário, o ID efetivo e `/model` não poderão ser sincronizados. Use ID explícito e `ctr model` nesses ambientes; o status mostra se houve observação.
- O roteador não mede faturamento nem garante economia percentual ou qualidade. Latência local e comportamento são testáveis; consumo total depende do trabalho e do Claude.
- Linux/macOS, Python 3.11+. Windows nativo, proxy de API, roteamento automático dentro de IDE e um backend Codex ficam fora deste incremento.
