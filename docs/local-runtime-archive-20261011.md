# Arquivo da instalação local de 04/10/2026

Preservação solicitada pelo usuário em 11/10/2026 antes da migração de armazenamento. A árvore principal estava sincronizada com `c6fb3f0`; a pasta ignorada `.runtime/production-local-20261004` continha variantes locais adicionais.

Esta branch arquiva byte a byte 3 scripts locais, o modelo Compose e 32 variantes históricas de código/dependências. Os arquivos de credenciais, bancos, logs e capturas continuam somente no armazenamento local. O manifesto adjacente registra os 225 arquivos do snapshot: 184 iguais ao main consultado, 9 conteúdos já publicados historicamente e 32 variantes locais. A árvore `.runtime/.../source` versionada contém somente as variantes novas; o snapshot completo está preservado no SSD.

O wrapper `local_composition.py` contém uma composição explícita para testes locais, incluindo substituições de prontidão e de entrega de e-mail. As variantes dos guards diferem do main atual. Este arquivo histórico não promove essas substituições à produção. Sintaxe Python, JSON e shell foi validada; a pilha não foi reiniciada nem certificada novamente.
