# AUD24 — smoke Orca/AT-SPI (evidência parcial de acessibilidade)

**Data:** 24/10/2026. **Escopo:** transporte AT-SPI local; **não** é auditoria humana de leitor de tela, WCAG ou usabilidade clínica.
**Autoridade:** o usuário aceitou Orca/AT-SPI local como evidência parcial nesta sessão.

## Ambiente observado

| Item | Valor |
|---|---|
| Orca | 46.1 |
| AT-SPI | 2.52.0 |
| Navegador acessível | Google Chrome / Chromium 1.0 via AT-SPI |
| Display | X11 `:0.0` |
| Speech | desabilitado explicitamente no smoke (`--disable speech`) |
| Preferências | diretório local temporário, `GSETTINGS_BACKEND=memory` |

## O que foi provado

- `orca --replace --disable speech` inicializou o script default e permaneceu ativo.
- O AT-SPI registry/bus respondeu e o Orca anexou-se ao **Google Chrome** como aplicação acessível.
- O log do Orca registrou objetos com `role=static`, `states=enabled, sensitive, showing, visible`, interfaces `Action, Collection, Component, Document, Hypertext, Text` e eventos `object:property-change:accessible-name`.
- `orca -l` listou Google Chrome e aplicações XFCE; o teste confirma que o caminho AT-SPI → Chromium funciona neste host.

## Limites

- Não houve navegação sistemática da aplicação RICK, travessia de todos os fluxos, leitura por áudio, teste com usuário cego ou avaliação WCAG.
- O browser acessível usado no smoke foi uma instância existente do Chrome, não a matriz RICK completa.
- A evidência é **parcial**; AUD24-045 continua aberto para um revisor humano/AT real.

## Decisão humana de 24/10

O usuário autorizou **apenas o smoke teste funcional** e aceitou esse teto para AUD24-045, sem auditoria humana/leitor de tela completo. O smoke executado em 375/768/1440 (`copy-recovery` + `canonical-shell`, incluindo axe, foco e teclado) passou **33/33**.

**Residual aceito:** não há avaliação com usuário cego, leitor de tela em fluxo completo, áudio ou conformidade WCAG formal. O aceite é de escopo, não uma alegação de acessibilidade plena.
