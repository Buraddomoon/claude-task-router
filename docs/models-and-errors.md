# Modelos e diagnóstico

```bash
ctr doctor                  # interface e autenticação, sem chamada de IA
ctr models                  # /model nativo; não é lista completa de autorização
ctr models --check haiku     # validação nativa do nome/restrição, sem turno de IA
ctr models --probe haiku     # teste real curto, consome IA explicitamente
```

O roteador usa somente comandos públicos do Claude Code original. Não lê
arquivos de credenciais, não copia tokens e não implementa login próprio.
`doctor` mostra apenas login ativo, método e provedor, sem email/organização.
Se o login estiver ausente, use `claude auth login` no fluxo da Anthropic.

`--check` usa `/model nome` em modo print sem persistência e verifica
zero turnos/custo reportados. O teste real do Claude 2.1.323 mostrou que um
modelo inválido pode retornar código 0 e `is_error=false`, com texto “not found”.
O roteador não confunde esse resultado com disponibilidade. Só respostas
locais reconhecidas são classificadas como aceitas ou recusadas.

Aceito pela CLI não é garantia de autorização do backend nem disponibilidade
futura. `/model` mostra aliases e aceita IDs completos; o roteador não
inventa um catálogo global nem consulta endpoints privados da assinatura.
`--probe` envia apenas um pedido curto de OK, sem ferramentas, em modo restrito,
com um turno e limite estimado de US$ 0,03. Confere o ID observado, não altera
tarefas, não salva conversa e não é disparado automaticamente a cada mensagem.
O limite do Claude é estimado e pode ser ultrapassado no turno corrente.

## Falhas

O erro e a saída nativa continuam visíveis. A tarefa/UUID e escolha são
preservados, sem retry automático de inferência ou mudança silenciosa de
modelo. `resume UUID` tenta a sessão original; `recover UUID --prompt-file`
cria outra sessão com contexto explícito se o histórico não existir.

```bash
ctr new "Uma tarefa curta" --timeout 60 -- -p --max-budget-usd 0.10
```

`--timeout` é opt-in, positivo e exclusivo do modo print. Ao expirar, termina
o grupo do cliente, aguarda até cinco segundos e usa SIGKILL se necessário.
O código 124 e os metadados ficam salvos; o lock só é liberado após a saída.
Em modo print, sinais são encaminhados ao grupo. Sessões interativas mantêm
o terminal herdado e não recebem encerramento por tempo inesperado.
