# Artefatos históricos necessários em clones

O [manifesto v1](v1/manifest.json) ancora por SHA-256 os 51 arquivos originais
PROD12/AUD15 citados pelos ledgers e gates ativos. O [archive](v1/inputs.tar.xz)
contém exatamente seus bytes locais anteriores ao reparo de portabilidade.
O restorer confere inventário, tipos, tamanhos, hashes, destinos limitados a quatro
raízes históricas de `.runtime` e conflitos antes de escrever. Não sobrescreve
arquivos existentes diferentes nem modifica ledgers, gates, quality bar ou aceites.

Sem esse conjunto, `make validate` passava apenas na máquina que tinha os logs.
As versões anteriores do bundle de control-inputs continuam intactas. Este anexo
preserva resultados históricos, incluindo falhas; não importa aprovação para o
candidato atual. Segredos ativos não foram adicionados ao pacote: inspeção
limitada dos 51 arquivos para blocos de chave privada, tokens GitHub, chaves AWS
e JWT não encontrou esses padrões; comparação em memória com 11 valores de
credenciais ativas do laboratório não encontrou correspondências. Essa inspeção
não equivale a uma auditoria exaustiva de segredos.
