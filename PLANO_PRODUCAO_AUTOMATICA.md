# Plano: produção automática de folhas de tatuagem

**Objetivo:** quando uma encomenda paga chega, o PC prepara sozinho, em poucos minutos, o PDF pronto a imprimir, o ficheiro de corte e uma pré-visualização, e envia um aviso. O operador só imprime, põe a folha na Cameo e manda cortar.

**Pressupostos:**
- Loja online com dados estruturados (site, Stripe e e-mail de encomenda enviado por Resend no domínio da loja).
- O job corre localmente, no PC de produção.
- Uma folha por encomenda; a arte é sempre espelhada.
- Todas as tatuagens são impressas a preto sólido: logótipos a cores têm de ser convertidos.

---

## 1. De onde vêm as encomendas

| Fonte | Prós | Contras |
|---|---|---|
| **API do site (recomendado)** | Todos os dados disponíveis (link do logótipo, tamanho, cópias); permite devolver o estado ("em produção"); o formato é controlado por nós. | É preciso um endpoint no site (por exemplo, encomendas pagas por produzir). |
| Stripe | Confirma o pagamento com certeza. | Só serve se o site gravar tamanho, cópias e link do logótipo nos metadados do pagamento. |
| E-mail | Já existe. | O Resend só envia e-mails, por isso teria de ler a caixa de correio por IMAP; depende do formato do e-mail; é a opção mais frágil. |

**Proposta:**
- O site é a fonte principal e o Stripe confirma que o pagamento está concluído.
- Como corre localmente, o job vai buscar as encomendas a cada poucos minutos em vez de as receber por webhook. Assim não é preciso expor o PC à internet.
- O e-mail fica como alternativa, caso o site não possa ter o endpoint.

---

## 2. Componentes

1. **Programa único `tattoo-job`**, que encadeia: conversão para preto sólido → Sheet Layout → Regmarks → Cut Contour.
   - Entrada: logótipo + tamanho + nº de cópias + id da encomenda.
   - Saída numa pasta `encomendas/<id>/`:
     - `print.pdf`: arte espelhada + marcas de registo, sem a camada de corte.
     - `cut.svg`: ficheiro para o Send to Silhouette.
     - `preview.png`: pré-visualização com os contornos de corte, ao lado do logótipo original para comparar a conversão a preto.
     - `relatorio.json`: cópias colocadas, tamanho, avisos e estado.
   - PDF/AI são convertidos para SVG com o Inkscape em linha de comandos (`inkscape --export-type=svg`); o PDF final também é exportado pelo Inkscape.
2. **Conversão para preto sólido** (antes da paginação) — **já implementada**
   - Extensão **Silhouette Solid Black**, também integrada na **Sheet Layout** (opção "Convert to solid black", ligada por omissão).
   - **Método:**
     - O logótipo (vetores e imagens) é composto tal como aparece: ordem de pintura, preenchimentos, contornos, opacidade.
     - Os gradientes entram com a cor média.
     - Cada ponto mais escuro que o limiar fica preto; os mais claros (branco, cores claras) ficam sem tinta.
     - O resultado é vetorizado num único path preto, a 20 px por mm do tamanho final.
     - Assim, as partes brancas por cima de partes escuras viram buracos, o que não acontece se só pintarmos os vetores de preto.
     - Tudo é feito em Python (numpy), sem chamar o Inkscape.
   - **Atalho exato:** se todas as cores já forem escuras, os vetores são apenas pintados de preto e mantém-se o vetor original.
   - **Limiar** configurável (por omissão 0,5): um limiar mais baixo mantém cores mais claras como preto.
   - **Limitações:** clip paths, máscaras e filtros não são considerados; texto tem de ser convertido em path.
   - **Uma peça por tatuagem:** um logótipo com partes separadas é tratado como uma só peça, tanto na paginação (as cópias não se metem entre as partes de outra cópia) como no corte (um contorno à volta de todas as partes).
3. **Leitor de encomendas**
   - Vai buscar as encomendas novas ao site/Stripe e descarrega o logótipo.
   - Guarda o estado numa base de dados local (SQLite), para que cada encomenda seja processada uma só vez, com novas tentativas em caso de falha.
4. **Agendamento:** o Agendador de Tarefas do Windows corre o leitor a cada 5 minutos.
5. **Aviso ao operador** com a pré-visualização e o estado (pronta / rever / falhou), por e-mail via Resend, por notificação no ambiente de trabalho ou por Telegram.
6. **"Imprimir e cortar" com um clique:** um script por encomenda que imprime o `print.pdf` e, depois de a folha ser carregada na Cameo, envia o corte com as definições de marcas corretas.

---

## 3. Verificações automáticas

Antes de uma encomenda ser dada como "pronta":

| Verificação | Resultado |
|---|---|
| Formato e tamanho do ficheiro (só os formatos esperados, recusa ficheiros enormes) | falhou |
| Resolução no tamanho pedido < 150 ppp | falhou |
| Resolução no tamanho pedido entre 150 e 300 ppp | rever |
| Logótipo sem transparência e sem fundo branco | rever |
| Vetorização perdeu demasiado detalhe (área de tinta antes vs. depois) | rever |
| As cópias pedidas não cabem numa folha (indica o tamanho máximo) | rever |
| Conversão a preto apaga mais de 15% da tinta colorida (cores claras abaixo do limiar, por exemplo amarelo) — já implementado | rever |
| Conversão a preto junta zonas que só se distinguiam pela cor: mais de 30% das fronteiras de cor perdidas — já implementado | rever |
| Logótipo mais de 85% preto depois da conversão (fundo de cor que virou bloco) — já implementado | rever |
| SVG do cliente: remover scripts e referências externas antes de processar | — (sempre) |

Estados finais: **pronta**, **rever** (com o motivo) ou **falhou**.

---

## 4. Ambiente no PC de produção

- Python próprio para o job, com `inkex`, `numpy`, `lxml` e `Pillow` em versões fixas.
- Inkscape 1.4 na linha de comandos, para converter e exportar.
- Chaves (Stripe só de leitura, token do site, Resend) no Gestor de Credenciais do Windows ou num `.env` fora do repositório.
- Logs por encomenda e um log geral.

---

## 5. Fases

| Fase | Entrega | Critério para avançar |
|---|---|---|
| **0. Pré-requisitos** | Extensões testadas no Inkscape real; teste das marcas de registo na Cameo (marcas mais curtas, corte fora do retângulo das marcas) | Uma folha impressa e cortada à mão, com o corte alinhado |
| **1. Programa `tattoo-job`** | Corre sobre um ficheiro local e gera o PDF, o corte, a pré-visualização e o relatório | Testes com logótipos de exemplo: vetor preto, vetor a cores (com partes brancas sobrepostas), PNG transparente, JPG com fundo, cores claras, baixa resolução |
| **2. Leitor de encomendas** | Vai buscar encomendas ao site/Stripe, sem imprimir nem cortar | Corre uma semana em paralelo com o processo manual e acerta em tudo |
| **3. Avisos e verificações** | Pré-visualização + estado enviados ao operador | Os casos "rever" chegam com o motivo certo |
| **4. Imprimir e cortar com um clique** | Script por encomenda; impressão automática opcional | Uma encomenda real do início ao fim |
| **5. Robustez** | Alertas de erro, limpeza de pastas antigas, cópias de segurança | — |

**Testes:**
- Testes unitários existentes: `test/test_outline.py` e `test/test_layout.py`.
- Uma pasta de encomendas de exemplo com o resultado esperado de cada uma, para testes de regressão.
- Testes da cadeia completa sem a Cameo, usando o modo do Send to Silhouette que escreve os comandos num ficheiro em vez de os enviar à máquina.

---

## 6. O que fica fisicamente com o operador

Pôr o papel na impressora, imprimir e colocar a folha impressa na Cameo. A impressão pode ser automática, mas o corte só pode começar depois de a folha ser carregada.

---

## 7. Questões em aberto

1. Onde o site guarda o logótipo carregado pelo cliente (link público, armazenamento privado?) e se é possível expor uma API de encomendas por produzir.
2. Se o tamanho e o nº de cópias também ficam nos metadados do Stripe.
3. Tamanho do papel (só A4?) e modelo da impressora.
4. Canal preferido para os avisos.
5. Se o site deve receber de volta o estado da encomenda (em produção / enviada).
6. Se o cliente deve ver e aprovar a versão a preto antes da produção (por exemplo, pré-visualização no site no momento da encomenda), o que eliminaria a maioria dos casos "rever" da conversão.
