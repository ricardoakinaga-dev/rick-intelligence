# Retomada da construção — 09/10/2026

## Objetivo e estado recuperado

Concluir a remediação local pendente do programa RICK Intelligence e executar os
gates reais, preservando os bloqueios de produção. O ponto de partida é o commit
`96efd7c`, com árvore limpa. O backlog vigente é
[AUD07](../backlog-auditoria-2026-10-07.md); os ponteiros Q17 em `.agent/` são
históricos quanto à construção local de outubro e continuam descrevendo a prova
externa, sem autorizar promoção. Não há AGENTS.md no checkout atual. AUD07-02/04
já retiraram os três legados; sua história Git permanece disponível.

## Critérios e sequência

1. AUD07-44/45: scanner continua detectando segredos; fixture negativa continua
   rejeitando o campo `private_key`; apenas `apps/web` integra o inventário Node
   atual; manifesto registra a retirada; manifests/locks ausentes ainda falham.
   Aceitar somente o identificador adicional MIT-0, documentado pelo SPDX.
2. AUD07-16/21: eliminar colisões de módulos de teste e permitir coleta conjunta
   de API/pacotes/worker sem export manual, inclusive fora da raiz.
3. AUD07-20/22–26: inventariar skips e cobertura; corrigir documentação corrente,
   links e descrição das suites; preservar documentos históricos.
4. Executar os gates locais AUD07-27, revisar o diff em uma etapa separada e
   registrar comandos, exit codes e limites. Revisão própria não é independente.
5. AUD07-46, descoberta pela execução conjunta: captura de configuração aceita
   criação de subdiretório vizinho, mantendo rejeição de substituição de inode,
   symlinks, mudança de permissões/conteúdo e hardlink da folha. Reprodução
   determinística deve falhar antes e passar depois da correção; repetir a
   suíte completa do instalador.

## Decisões

- A solicitação de concluir a construção autoriza correções locais reversíveis.
  O scanner não receberá exceções: o teste rejeita o nome do campo, logo seu valor
  pode ser um marcador sintético sem cabeçalho PEM. A descrição documental usa
  esse mesmo marcador, sem reproduzir uma assinatura de chave.
- A retirada de componentes foi decidida em AUD07-02/04. Alinhar o inventário à
  árvore implementa essa decisão; não exclui um componente Node existente.
- MIT-0 é MIT No Attribution conforme https://spdx.org/licenses/MIT-0.html;
  apenas esse identificador é acrescentado à política existente.
- O número de links de um diretório não identifica substituição: criar/remover
  um subdiretório muda esse número. Identidade do diretório continua vinculada
  por device/inode/mode/UID/GID e pelo descritor aberto sem seguir symlinks.
  `st_nlink` da folha regular permanece obrigatório e conferido durante a leitura.
- Nenhum dado, serviço de produção, credencial, corpus ou deploy será alterado.
  Runtime, revisão independente e promoção mantêm seus próprios critérios.

## Progresso

- [x] Recuperação: histórico Git, árvore, backlog, CI e plano Q17 inspecionados.
- [x] Baseline: lockfiles FAIL (3 legados ausentes); licenses FAIL (3 legados e
  MIT-0); secret-scan FAIL (fixture e sua reprodução no backlog).
- [x] Corrigir e validar supply chain.
- [x] Corrigir descoberta/coleta conjunta.
- [x] Consolidar documentação, skips e cobertura.
- [x] Executar gates CI/API/web, corrigir falhas integradas e revisar o diff local.
- [x] AUD07-46: reprodução determinística e suíte VPS completa aprovadas.
- [x] Corrigir fixtures de recuperação e repetir toda a matriz: 7.719 PASS, 221 skips.
- [ ] Revisão independente e evidência remota do candidato (AUD07-27/43).

## Recuperação e próximo passo

Construção local encerrada nesta rodada; resultados, hashes e limites estão no
[relatório](../reports/retomada-2026-10-09.md). Conferir `git status`, o manifesto
de verificação e AUD07-27/43 antes de retomar. O controlador Q17 mantém o
ponteiro externo sem avanço de status. Não há efeito externo em andamento.
Próxima ação de aceite: revisão separada do candidato e execução dos gates
externos com as configurações próprias de cada laboratório. Nenhuma falha
histórica ou teste não executado conta como aprovação.
