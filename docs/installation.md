# Instalação, atualização e rollback — #21

Requisitos: Linux/macOS, Python 3.11+ com venv/pip. Para executar tarefas reais,
Claude Code autenticado; a instalação e os testes não precisam da conta.
Em distribuições que separam venv, instale o pacote `python3-venv` apropriado.

```bash
bash scripts/install.sh
~/.local/bin/ctr --version
~/.local/bin/ctr doctor
```

`CTR_VENV_DIR` define o caminho estável do ambiente; `CTR_BIN_DIR` define o
diretório do comando. Ambos aceitam espaços e apóstrofos. O instalador cria
gerações em `<CTR_VENV_DIR>.releases/`, ativa uma por symlink e mantém
`<CTR_VENV_DIR>.previous` para rollback. Venvs antigos em diretório real
são reconhecidos pelo entrypoint do roteador e preservados como geração legada.
O symlink do comando continua apontando para `<CTR_VENV_DIR>/bin/ctr`.

Um comando alheio, diretório ou symlink quebrado em `CTR_BIN_DIR/ctr` é recusado.
Ambientes e backups alheios também são recusados. Instaladores concorrentes
não atualizam o mesmo ambiente simultaneamente. Uma falha ao preparar o novo
venv/pacote deixa a geração ativa funcionando. A ativação troca o symlink
atomicamente; a primeira migração de um venv legado exige renomear o diretório.
Disco cheio ou interrupção nesse intervalo pode exigir restaurar manualmente
o symlink para a geração legada em `.releases/`.

## Atualizar e voltar

Encerre sessões do roteador antes da atualização. Guarde uma cópia do estado
com o roteador parado (padrão `~/.local/state/claude-task-router`, respeitando
`XDG_STATE_HOME`/`--state-dir`). Essa cópia contém apenas metadados do roteador;
o histórico nativo do Claude é separado.

Faça fetch do repositório, selecione a tag desejada (por exemplo,
`git fetch origin --tags` e `git checkout v1.0.0`) e execute
`bash scripts/install.sh` novamente. Em main, pull também é possível.
O instalador não abre o banco. A CLI migra schemas antigos transacionalmente
ao ser executada, preservando tarefas, decisões, escolhas manuais e eventos.
Depois confira `ctr --version`, `ctr status --all` e retome um UUID conhecido.

Para retornar à geração anterior:

```bash
bash scripts/install.sh --rollback
```

Use os mesmos `CTR_VENV_DIR` e `CTR_BIN_DIR` empregados na instalação.
O rollback troca as gerações atual/anterior, permitindo desfazê-lo novamente.
Não rebaixa o schema do banco. Se a versão antiga não reconhecer o schema
novo, use o backup anterior em outro `--state-dir`; preserve o estado novo
para não perder tarefas criadas depois da atualização. Versões futuras de
schema são recusadas pela CLI, sem rebaixamento silencioso.

As gerações são mantidas para recuperação; não há limpeza automática que
possa apagar código em uso. Para desinstalar, remova o symlink do comando,
o symlink estável, `.previous`, `.releases/` e `.install.lock` desse ambiente.
O banco e as transcrições do Claude permanecem até serem removidos à parte.

## Evidência reproduzível

`python3 -m unittest discover -s tests -v` inclui:

- Instalação limpa em caminhos com espaços/apóstrofo; `new`, `model`,
  `resume` e hooks executados pelo artefato instalado fora da árvore fonte.
- Atualização preservando os bytes do banco antes de abrir a CLI; comparação
  de UUID, configuração, decisão, escolha manual, ID fixado e eventos depois.
- Falha real de build sem índice de pacotes, mantendo o ambiente ativo;
  rollback seguido de retomada do mesmo UUID e verificação da integridade.
- Migração do layout de venv legado e rollback com shebang funcional.
- Recusa de arquivos, diretórios, symlinks quebrados, ambientes e backups alheios.
- Migrações de bancos v1/v2/v3 e recusa de schema futuro (`test_migrations.py`).

`tests/installed_smoke.py` falha se importar código da árvore fonte e verifica
a proveniência do módulo. Usa somente CLI simulada; não faz inferência.
A CI constrói um wheel, instala-o e roda esse fluxo fora do checkout em
Linux/Python 3.11 e 3.14 e macOS Intel/Python 3.14. Os wheels ficam nos
artefatos de cada job. A homologação local inicial passou nos três testes de
instalação em 18,58 s; a evidência da matriz está nos checks do commit.
