# Configuração, backup e remoção

```bash
ctr setup                       # cria config válida; preserva se já existir
ctr setup --check-models        # valida nomes com /model nativo antes de salvar
ctr setup --force --min-tier balanced
ctr doctor
```

Não altera autenticação nem configurações do Claude. Opções `--economy`,
`--balanced` e `--advanced` escolhem aliases/IDs. `--config arquivo` seleciona
um destino explícito. Uma alteração com `--force` guarda cópia privada da
configuração anterior; valores inválidos são recusados antes da escrita.
Arquivos novos são 0600. A validação por `/model` não promete autorização futura.

```bash
ctr backup ~/roteador-backup.sqlite3
ctr --state-dir ~/roteador-restaurado restore ~/roteador-backup.sqlite3
ctr --state-dir ~/roteador-restaurado status --all
```

O backup usa a API de snapshot do SQLite, não uma cópia de arquivo durante
uma escrita. Contém metadados privados e nunca deve ser publicado como
diagnóstico. Restore verifica integridade/schema e só cria um banco novo;
não sobrescreve o banco ativo. Migrações antigas continuam transacionais.
O histórico do Claude é separado e não está nesse backup. Use `recover --cwd`
se o diretório original tiver mudado, fornecendo contexto explicitamente.

## Atualizar e remover

O instalador continua preparando uma geração antes de ativá-la. Execute
`bash scripts/install.sh` no checkout atualizado; `--rollback` reativa a
geração anterior sem rebaixar schema. Cada tarefa da nova versão instalada
mantém um lock compartilhado de instalação: atualização/remoção são recusadas
enquanto ela estiver rodando, inclusive se usar outro diretório de estado.
Encerre sessões de versões antigas antes de atualizar: elas ainda não têm
esse mecanismo. Retomar uma tarefa depois da atualização continua usando
seu UUID e decisão, sem reclassificação.

```bash
ctr uninstall
# Alternativa a partir do checkout:
bash scripts/install.sh --uninstall
```

O comando remove somente symlinks e gerações com marcador do instalador.
Configuração, banco, backups e todos os arquivos/histórico do Claude são
preservados. Caminhos alheios ou marcadores inválidos fazem a operação falhar
antes da remoção. Conteúdo desconhecido em `.releases/` é preservado; o
arquivo inofensivo `.install.lock` permanece para sincronizar uma reinstalação.
`--venv-dir`/`--bin-dir` em `ctr uninstall` ou `CTR_VENV_DIR`/`CTR_BIN_DIR` no
script selecionam instalações personalizadas. `--state-dir` permite conferir
também locks de tarefas conhecidas; o lease protege tarefas da versão atual
em qualquer estado personalizado.

Instalações feitas diretamente por pip devem ser removidas com o pip daquele
ambiente. O roteador não remove um ambiente Python sem marcador gerenciado.
Para apagar metadados após desinstalar, escolha conscientemente o diretório
de estado dedicado e seus backups; não há purge automático de conversas.
