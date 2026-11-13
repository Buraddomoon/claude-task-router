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

Aliases são configuráveis para cada provedor; não há preços nem versões comerciais codificados. SessionStart registra o ID ativo quando disponível. Quando esse campo opcional falta (observado em 2.1.323), guarda o caminho validado da transcrição; após o processo terminar, uma leitura de até 1 MiB do final procura o ID em uma resposta da própria sessão e posterior ao início da execução. Só metadados são persistidos: o ID observado é separado da escolha e só fixa a versão se for compatível com ela. Uma mudança já observada por hook tem prioridade sobre essa recuperação. A documentação [de modelos](https://code.claude.com/docs/en/model-config) distingue aliases móveis, IDs explícitos, seleção manual e modos híbridos. `default` e `opusplan` são recusados porque não representam um único modelo estável. Outros IDs são encaminhados sem presumir disponibilidade na conta.

## Persistência e controle

SQLite guarda UUID, diretório de trabalho, modelo solicitado, ID resolvido compatível, modelo efetivo, tier, motivos enumerados, snapshot de política, tamanho e hash do primeiro prompt, caminho da transcrição, timestamps e eventos. O texto do prompt e o conteúdo das transcrições ficam fora desse banco. O Claude mantém seu próprio histórico segundo as configurações existentes. Cada tarefa possui lock POSIX durante sua execução; hooks atualizam somente sessões já conhecidas e no diretório esperado. Transações são curtas e não ficam abertas enquanto o subprocesso executa.

`--model` explícito e `ctr model` têm prioridade. O hook PostModelSwitch registra a mudança efetiva; somente sources command/picker/sdk atualizam a intenção (requested_model quando presente, to_model como alternativa). Sources auto/resume nunca substituem a escolha. IDs resolvidos não são renovados por eventos auto. Divergências ficam em eventos model_diverged. Hooks não escrevem nada em stdout: nenhum token de contexto de roteamento é acrescentado. Em versões sem PostModelSwitch, `ctr doctor` informa incompatibilidade; versão mínima suportada: 2.1.251.

## Limites deliberados

- Uma nova tarefa exige `ctr new`. `/clear`, `/resume` e forks feitos dentro do Claude não criam tarefas gerenciadas; sair e usar o launcher mantém a fronteira explícita.
- O roteador não troca modelo durante a execução. Fallbacks e substituições internas do Claude/provedor ainda podem acontecer, inclusive no modo plan com Haiku; o launcher não promete impedir essas políticas. Não configura cadeias de fallback e não usa `opusplan`. Envia switchModelsOnFlag=false para o controle nativo de confirmação de fallback de conteúdo, sem limitar availableModels ou o override manual. Cadeias nativas por turno podem não disparar PostModelSwitch; effective_model representa uma observação, não prova o modelo de todas as respostas.
- Se hooks forem desativados por configurações administradas ou pelo usuário, o ID efetivo e `/model` não poderão ser sincronizados. Use ID explícito e `ctr model` nesses ambientes; o status mostra se houve observação.
- O roteador não mede faturamento nem garante economia percentual ou qualidade. Latência local e comportamento são testáveis; consumo total depende do trabalho e do Claude.
- Linux/macOS, Python 3.11+. Windows nativo, proxy de API, roteamento automático dentro de IDE e um backend Codex ficam fora deste incremento.

Observações são vinculadas a execution_id, criado antes de Popen e incluído nos comandos dos hooks. O início limpa observed_at, effective_model, hook_seen_at e caminho de transcrição da execução anterior, preservando model/resolved_model. Hooks só atualizam a execução corrente ainda aberta. Transcrições exigem evidência atual, intervalo temporal válido e comparação atômica de execução e choice_revision; nenhuma transação permanece aberta durante leitura de conteúdo ou execução do Claude.

`recover` cria um UUID novo e preserva escolha, ID compatível, tier, decisão e snapshot de configuração da tarefa original. Exige contexto explícito, não copia a conversa nem classifica novamente. A origem fica em recovered_from; a tarefa original não é reescrita. --cwd permite recuperar em outro diretório. Falhas preservam o código do Claude e mostram como retomar/recuperar, sem retry remoto.

As migrações de schema são serializadas com BEGIN IMMEDIATE antes de consultar user_version. DDL e versão ficam numa única transação, sem executescript/commit implícito. Bancos v1/v2 reconstroem a intenção pelos eventos manuais e só recuperam IDs compatíveis de eventos não automáticos; v3 mantém escolha e ID, invalidando observações sem identidade de execução. Falhas durante a migração revertem schema e dados; versões futuras são recusadas.
