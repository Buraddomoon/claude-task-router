# Segurança e dados locais

Ferramenta de uso pessoal local, exclusiva para o Claude Code original. Não
adiciona proxy, servidor, coleta de credenciais ou telemetria. Não use uma
instalação compartilhada entre usuários do sistema operacional.

O estado deve ficar em um diretório dedicado do próprio usuário: 0700 para
diretório/locks e 0600 para banco/arquivos. Permissões antigas são corrigidas.
Symlinks no diretório final do estado/banco/lock, hardlinks e arquivos especiais
são recusados antes de modificar seu conteúdo. A conta do SO e os diretórios
ancestrais devem ser confiáveis; isso não é isolamento contra malware que já
execute com o mesmo usuário, nem criptografia em repouso. Use proteção do disco
e conta do sistema para esse requisito.

O banco guarda UUID, diretório de projeto, nomes de modelo, decisão/configuração,
hash e tamanho do prompt, caminho de transcrição e eventos. Não guarda prompt,
conteúdo de conversa ou chave de API. Caminhos e hashes ainda são metadados
potencialmente sensíveis. O Claude mantém histórico e políticas de dados próprios;
apagar o estado do roteador não apaga o histórico nativo nem dados do provedor.

`ctr diagnostics` exporta apenas versões/plataforma, schema e contagens. Não
exporta tarefas, UUIDs, diretórios, configuração, modelos personalizados,
transcrições, ambiente, email ou credenciais. `--output arquivo.json` cria um
arquivo novo 0600 e recusa sobrescrita. `show`/`status` são inspeções locais e
podem conter metadados privados; revise antes de compartilhar.

O launcher usa argv literal, sem shell para prompts. Hooks silenciosos usam
comando com quoting explícito e só observam execução/UUID/diretório conhecidos.
O prompt inicial é passado em argv ao Claude e pode aparecer na lista de
processos, conforme as permissões do sistema. `--prompt-file` muda a entrada
do roteador, mas não elimina essa exposição no processo filho. Não envie
segredos literais e não trate esse fluxo como canal confidencial em host
multiusuário; a interface interativa herdada não oferece essa garantia.
Não altere executáveis/configuração para código de origem desconhecida. As
permissões e ferramentas do Claude continuam nativas; `--restricted --tools ''`
reduz capacidades em testes sem exigir bypass de permissões.

Não há promessa de SLA ou programa de bug bounty. Para relatar uma falha,
prefira o canal privado disponível ao proprietário; não abra uma issue pública
com credenciais, prompts ou transcrições. Se não houver canal privado disponível,
avise o proprietário sem detalhes exploráveis até combinar um canal. Nenhuma
data de correção ou conformidade regulatória é alegada por este documento.
