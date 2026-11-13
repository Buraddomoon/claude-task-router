# Convenções

- Python 3.11+ e biblioteca padrão; nenhuma chamada de IA para classificação.
- Classificar somente em `new`; `resume` reutiliza decisão persistida.
- Nunca persistir prompts, transcrições ou credenciais no banco do roteador.
- Executar `python3 -m unittest discover -s tests -v` antes de concluir alterações de comportamento.
- Criar issues com subissues nativas por etapa antes da implementação.
- Commits: `[Área] - Refs #N - objetivo` ou `[Área] - Closes #N - objetivo`.
- Padrão de issues inspirado no memory-os; ver docs/governance.md.
