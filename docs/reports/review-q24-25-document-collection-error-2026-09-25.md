# Revisão visual final — estado de erro de coleções em Documentos

**Data:** 25/09/2026. **Escopo:** tela `/app/documents` para usuário com permissão de upload, sem permissão de gestão, quando a consulta de coleções falha. Viewports inspecionados: mobile 375×812, tablet 768×1024 e desktop 1440×1000.

## Resultado da revisão

Uma revisão independente, somente leitura, examinou as três capturas finais e o código atualizado. Não encontrou achados P0–P3. O alerta e o retry permanecem legíveis; em mobile o retry fica abaixo da mensagem, em tablet e desktop cabe ao lado dela. O rótulo fica acima do seletor nos três tamanhos, o envio indisponível é perceptível e não há outra ação ativa de upload no estado de falha. O contraste calculado para o texto do alerta é 4,54:1.

As capturas finais estão em `evidence/implementation-q24-2026-09-24/verification-q24-25-web-collection-error-review-resolved-20260925/visual-renders/`:

- `upload-only-collection-error-mobile-viewport.png`
- `upload-only-collection-error-tablet-viewport.png`
- `upload-only-collection-error-desktop-viewport.png`

## Correções incorporadas

As revisões anteriores encontraram três problemas P3: o alerta mobile ficava alto porque o botão disputava espaço horizontal com a mensagem; o seletor desktop truncava “Coleções indisponíveis”; e, após ampliar o controle, o rótulo ficou alinhado ao lado dele, diferente de tablet/mobile. A implementação agora empilha a ação em telas estreitas, mantém 220 px para o seletor em desktop, alinha o rótulo acima do campo e preserva o estilo arredondado do controle. Um teste confirma a ordem do rótulo e do campo, o título de indisponibilidade, o estado desabilitado e o reflow mobile.

## Verificação

Na versão final, `make web-lint`, `make web-typecheck` e `make web-build` passaram. Os testes de produção de `tests/document-state.spec.ts` passaram 27/27 nos três viewports, incluindo falha/retry para uploader sem acesso de gestão, ausência de destino ativo, truncamento de nomes longos e retry binário.

A matriz E2E completa de 321 testes também passou numa versão funcional anterior às últimas correções visuais P3. Seus 18 resultados de performance são medições de laboratório com API sintética instantânea, CPU 4× e amostra única; não foram repetidos após o último ajuste de layout. O navegador desta verificação usa rotas API simuladas. Portanto, ela não cobre API real, chat, administração, acessibilidade assistiva completa ou a tarefa Q24-25 inteira.
