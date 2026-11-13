# Claude Task Router

Launcher local que escolhe o modelo do Claude Code no início da tarefa e preserva a escolha nas continuações. Classificação determinística PT/EN, sem chamadas de IA, proxy ou dependências de runtime além da biblioteca padrão do Python.

## Instalar

Requisitos: Linux/macOS, Python 3.11+, Claude Code 2.1.251+ instalado e autenticado. Não é necessário configurar uma chave de API adicional: o Claude usa a autenticação existente.

```bash
git clone https://github.com/Buraddomoon/claude-task-router.git
cd claude-task-router
bash scripts/install.sh
~/.local/bin/ctr doctor
```

O instalador cria um venv isolado em `~/.local/share/claude-task-router/venv` e o comando `~/.local/bin/ctr`. Não altera configurações do Claude nem arquivos do shell. Adicione `~/.local/bin` ao PATH se necessário. `CTR_VENV_DIR` e `CTR_BIN_DIR` personalizam esses caminhos. O empacotamento pode baixar setuptools durante a instalação; o roteamento é inteiramente local.

Alternativa, em um ambiente Python já escolhido: `python3 -m pip install --no-deps .`. Para executar direto do checkout: `python3 -m claude_task_router`.

## Usar no projeto

```bash
cd /caminho/do/seu/projeto

# Nova tarefa: classifica o primeiro prompt e abre o Claude interativo
ctr new "Corrija o typo no README.md"

# Continuações no Claude usam a mesma sessão; após sair, retome assim:
ctr resume latest "Agora valide o resultado"

# Outra tarefa: nova classificação e nova sessão
ctr new "Implemente autenticação OAuth"

# Escolha manual inicial ou na retomada
ctr new "Investigue esse problema" --model opus
ctr resume latest --model sonnet

# Alterar a escolha de uma tarefa que está parada
ctr model latest opus

# Durante a sessão interativa, /model continua disponível
```

`latest` considera somente as tarefas deste diretório; `ctr resume UUID` também funciona de outro diretório e executa no projeto original. `ctr status` mostra os UUIDs completos; prefixos únicos de pelo menos oito caracteres são aceitos. Use UUID em terminais com várias tarefas abertas.

| Situação | Padrão |
| --- | --- |
| Intenção simples reconhecida e delimitada: typo, renomear, traduzir, formatar | `economy` → Haiku |
| Programação usual, correção comum ou pedido ambíguo | `balanced` → Sonnet |
| Arquitetura, causa raiz, concorrência, autenticação, pagamentos, migração de dados ou escopo amplo com implementação | `advanced` → Opus |

Regras são heurísticas, não uma medida objetiva de dificuldade. Uma menção a autenticação numa tarefa simples pode elevar o tier por precaução. Use `classify` para inspecionar a decisão e `--model`/`--tier` para ajustar. Um pedido curto e ambíguo fica em Sonnet; tamanho sozinho não determina o modelo.

## Inspecionar sem consumir IA

```bash
ctr classify "Investigue uma falha intermitente" --json
ctr new "Corrija o typo no README" --dry-run
ctr resume latest --dry-run
ctr status --all --json
ctr show latest
ctr doctor
```

`classify` e `new --dry-run` não criam tarefas nem executam o Claude. `show` apresenta metadados e eventos, incluindo se o modelo efetivo foi observado. `doctor` chama apenas `claude --help`/`--version`; não verifica acesso da conta aos modelos. Opções globais vêm antes do subcomando.

## Arquivos, pipes e modo print

```bash
ctr new --prompt-file tarefa.txt
cat tarefa.txt | ctr new --prompt-file - -- -p --output-format json
ctr resume latest "Continue a implementação" -- -p --max-budget-usd 0.50
ctr new "Explique este comando git status" -- -p --output-format stream-json --verbose
```

O launcher limita prompts a 96 KiB para respeitar limites de argumentos do sistema; para tarefas grandes, referencie arquivos. As regras examinam no máximo 65.536 caracteres por padrão. O prompt é passado literalmente, sem execução de shell. Texto que começa com `-` pode ser fornecido por arquivo.

Após `--`, há uma lista explícita de flags permitidas do Claude (`ctr --help`). Flags que controlam sessão, modelo, hooks ou persistência são rejeitadas; use os comandos do roteador para isso. Ferramentas e permissões do Claude continuam sob as configurações existentes e os argumentos explícitos do usuário. Saída do roteador vai para stderr; stdout e o código de saída do Claude são preservados.

## Configuração

Crie `~/.config/claude-task-router/config.json` usando [examples/config.json](examples/config.json), ou passe o arquivo explicitamente:

```bash
ctr --config /caminho/config.json new "Minha tarefa"
ctr --state-dir /caminho/estado --claude-bin /caminho/claude new "Minha tarefa"
```

`XDG_CONFIG_HOME` e `XDG_STATE_HOME` são respeitados. O roteador não carrega configurações de projetos automaticamente. `min_tier: "balanced"` elimina escolhas Haiku. Cada tier aceita um alias ou ID/deployment do provedor; você pode apontar `advanced` para outro modelo, como Fable, quando disponível na sua conta. `default`, `best` e `opusplan` são recusados para evitar escolhas móveis ou híbridas implícitas.

Na primeira execução, o ID efetivo é capturado por hook ou por leitura local limitada do final da transcrição. As retomadas usam esse ID, mesmo se aliases ou configuração mudarem. Se não for possível observar o modelo, o status mantém a escolha solicitada e o launcher avisa em stderr; um ID explícito evita depender de aliases. Uma mudança de `/model` é registrada por PostModelSwitch e passa a valer nas retomadas. `ctr model` registra a intenção; o Claude valida disponibilidade e autorização ao executar.

## Fronteira da tarefa e limites

- Uma nova tarefa gerenciada começa em `ctr new`. Para mudar de assunto com nova classificação, saia do Claude e use esse comando novamente.
- `/clear`, `/resume` e forks dentro do Claude seguem a semântica nativa e não criam tarefas no roteador. Para continuar uma tarefa gerenciada, use `ctr resume` após sair.
- O launcher não reclassifica mensagens, não faz escalonamento no meio da tarefa e não configura fallback. O Claude/provedor ainda pode fazer substituições internas, inclusive em plan mode com Haiku. Para uma execução estritamente fixa, revise essas políticas nativas no seu ambiente.
- Se hooks estiverem desativados por configuração/política, a sincronização automática não funciona; use ID explícito e `ctr model`. A ausência de observação é visível em `ctr show` e em stderr.
- Se o Claude falhar antes de salvar a conversa, a retomada nativa pode não encontrá-la. O roteador preserva metadados e código de erro, sem tentar novamente com outro modelo. Corrija a causa e inicie uma nova tarefa quando necessário.
- O banco privado contém metadados, hash/tamanho do prompt e caminho da transcrição; não contém o texto do prompt nem o conteúdo das conversas. O Claude continua mantendo seu próprio histórico. Não há telemetria adicionada pelo roteador.
- Há suporte de execução para Claude Code CLI; a pesquisa sobre Codex orientou a arquitetura. Esta versão não troca o modelo do Codex, de uma IDE já aberta ou de outros agentes.

As capacidades verificadas, as alternativas de integração e as fontes oficiais estão em [docs/architecture.md](docs/architecture.md). O uso de launcher aplica o modelo pela interface CLI; uma skill não é usada como mecanismo de troca do modelo principal.

## Desenvolvimento e validação

```bash
python3 -m unittest discover -s tests -v
python3 benchmarks/run.py
```

Os testes usam uma CLI simulada e não consomem IA. O benchmark reporta latência local e verifica exemplos sintéticos da política; não mede qualidade de respostas nem economia real de faturamento. Evidências do smoke real: [docs/validation.md](docs/validation.md).

Etapas são acompanhadas por issues com subissues nativas e milestone `V0.1`, seguindo a estrutura do memory-os; [governança](docs/governance.md). A instalação é local; para atualizar, faça pull e execute novamente o instalador. Para desinstalar, remova o symlink `~/.local/bin/ctr` e o venv dedicado. Os metadados ficam em `~/.local/state/claude-task-router` para recuperação até você removê-los.
