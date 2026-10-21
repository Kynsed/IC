# Extração estruturada e auditoria

`updated_app.py` oferece a interface Flask, adquire o DOM de uma página com Selenium ou recebe uma imagem e solicita candidatos ao Gemini pela API REST `generateContent`. O contrato compartilhado em `../ic_contract.py` valida a resposta antes de publicá-la. A verificação factual pertence ao módulo `../analisys_tool/`: conformidade com o schema não demonstra que um valor está correto.

## Executar

Na pasta `extraction_tool`, com `flask`, `pandas`, `requests`, `beautifulsoup4` e `selenium` instalados no ambiente Python (além de Chrome para aquisição por URL):

```powershell
python .\updated_app.py
```

Acesse `http://127.0.0.1:5000/`. A execução direta carrega o `.env`, cria as pastas necessárias e inicia o servidor sem o recarregador de desenvolvimento. Importar o módulo não cria pastas nem lê o `.env` de imediato; a primeira chamada feita sem chave informada e sem `GEMINI_API_KEY` no ambiente lê o `.env` ao lado do script.

O botão **Usar dados de exemplo** substitui a aquisição da página por um HTML local de demonstração. **A chamada ao Gemini continua real**, usa a chave e pode ter custo. O botão **Testar Conexão com LLM** também faz uma chamada real, com prompt curto e até 2.048 tokens de saída. A suíte de testes abaixo usa respostas simuladas e bloqueia rede e navegador reais.

## Entrada e contrato

Informe campos separados por vírgula ou preencha **Schema JSON opcional**. O schema explícito tem precedência sobre os campos. O contrato exige um array de objetos; propriedades, tipos, campos obrigatórios e objetos/listas aninhados são validados recursivamente. Propriedades extras são proibidas. Trata-se de um subconjunto explícito de JSON Schema 2020-12, com keywords não suportadas rejeitadas pelo módulo compartilhado.

No contrato gerado a partir de nomes, cada campo é obrigatório e permite `string`, `number`, `boolean` ou `null`. Use um schema explícito para tipos mais restritos, por exemplo:

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "nome": {"type": ["string", "null"], "x-entity-key": true},
      "idade": {"type": ["integer", "null"]}
    },
    "required": ["nome", "idade"],
    "additionalProperties": false
  }
}
```

`null` representa ausência de informação, não falha operacional. JSON inválido, chaves duplicadas, tipos incorretos, campos obrigatórios ausentes, recusa ou truncamento do modelo produzem tarefa `error`, sem linhas candidatas. Um array vazio válido produz tarefa `completed` com zero resultados. A resposta não é consertada por regex nem recebe coerções ou preenchimentos. Apenas uma cerca Markdown que envolva a resposta inteira pode ser removida pelo parser, mantendo a resposta bruta em arquivo separado.

Se a lista de campos incluir `descrição`, `descricao`, `description`, `detalhes` ou `details`, o schema gerado inclui `Resumo` (exceto quando já houver um campo de resumo). O prompt solicita até 30 palavras e vínculo exclusivo com a descrição; esta é uma instrução ao modelo, não uma garantia semântica ou um limite de palavras validado pelo schema. O schema explícito não recebe campos adicionais.

JSON é a saída de referência para integração: preserva tipos, `null`, listas e objetos. CSV é uma exportação de conveniência; objetos/listas são serializados como JSON dentro da célula, mas o formato tabular não preserva todos os tipos ou a distinção entre `null` e string vazia. A tabela da interface mostra `0` e `false` como valores, e somente ausência/`null` como “Não disponível”.

## Modelo e credenciais

O extrator usa somente a API Gemini. O seletor oferece `gemini-3.8-flash` (padrão), `gemini-3.7-flash` e `gemini-3.6-flash`. Outros identificadores, inclusive os antigos da OpenAI, são recusados com HTTP 400 antes de a tarefa começar. A existência e a disponibilidade desses modelos não são verificadas pela suíte offline. O manifesto registra o modelo solicitado e o `modelVersion` devolvido pelo provedor; use este último ao documentar uma execução.

**Nível de raciocínio.** `Padrão do modelo` (`default`) não envia `thinkingConfig`. `low`, `medium` e `high` valem para os três modelos; `minimal`, apenas para `gemini-3.6-flash`. Combinações inválidas retornam HTTP 400. O nível escolhido fica em `provider.parameters.thinking_level` no manifesto, inclusive em falhas anteriores à chamada.

**Credenciais.** A chave digitada na interface (ou o argumento `api_key`) tem precedência. Sem ela, vale `GEMINI_API_KEY` do ambiente e, na falta desta, a do `.env` ao lado do script; variáveis já definidas no ambiente prevalecem sobre o `.env`, que não deve ser versionado. A interface envia a chave no corpo do POST, e o servidor a repassa no header `x-goog-api-key`, nunca na URL. Credenciais não entram no manifesto, no prompt nem nos logs. O conteúdo da fonte e da resposta, naturalmente, integra os arquivos de auditoria.

**Imagens.** Os três modelos aceitam imagem PNG, JPEG, GIF ou WebP, enviada como `inline_data` em base64; outras extensões são recusadas com HTTP 400. Com imagem, ela é a fonte enviada ao modelo, mesmo quando uma URL também foi preenchida. Uploads recebem nomes UUID para evitar sobrescritas entre tarefas. O verificador textual não pode comprovar fatos diretamente em imagens; não é criado um texto fictício para representar uma imagem.

**Parâmetros fixos.** Timeout de 180 segundos, zero retentativas automáticas e limite de saída de 8.192 tokens. A `temperature` não é enviada: vale o padrão do modelo, como o Google recomenda para os modelos Gemini 3, e o manifesto registra `"temperature": "default"`. `finishReason` diferente de `STOP` é falha, mesmo quando existe texto JSON aparentemente válido; um bloqueio sem candidato registra o `blockReason`. Sem retentativa, um erro transitório, como HTTP 503 por alta demanda, encerra a tarefa com status `error` e ela precisa ser reenviada. Essas são configurações do experimento, não evidência de custo, latência ou qualidade. Nem os parâmetros fixos nem a preservação dos artefatos garantem reprodução idêntica em futuras chamadas de um serviço remoto.

## Artefatos por execução

Cada tarefa possui UUID. Em `results/`, são preservados:

| Arquivo | Conteúdo |
|---|---|
| `<id>.html` | Snapshot DOM retornado por Selenium, antes da limpeza; não são os bytes HTTP originais |
| `<id>_source.<ext>` | Cópia dos bytes da imagem, quando essa for a fonte |
| `<id>_text.txt` | Texto efetivamente enviado ao modelo, após limpeza de HTML; ausente para imagem |
| `<id>_prompt.txt` | Prompt de extração com schema e fonte textual ou indicação da imagem |
| `<id>_raw_response.txt` | Texto integral das partes de resposta do candidato, antes do parsing; partes de raciocínio (`thought`) ficam de fora |
| `<id>_data.json` | Candidatos conformes ao contrato, somente em sucesso |
| `<id>_data.csv` | Exportação tabular dos candidatos, somente em sucesso |
| `<id>_manifest.json` | Status, contrato, hashes SHA-256, modelo, parâmetros (incluindo nível de raciocínio e temperatura), motivo de término e erro |

O manifesto versão 1 relaciona caminhos relativos e hashes dos bytes de cada artefato e inclui o hash do schema em JSON canônico (UTF-8, chaves ordenadas, sem espaços entre separadores). O modelo solicitado e o identificador resolvido pelo provedor são registrados separadamente quando disponíveis. Informações de uso de tokens retornadas pelo provedor (`usageMetadata`) também são preservadas.

Falhas preservam os artefatos já obtidos, inclusive resposta truncada/inválida, e retiram os arquivos de candidatos. Se a aquisição falhar, não existe snapshot; se a API falhar antes de retornar texto, não existe resposta bruta. Falhas de permissão ou disco podem impedir o próprio manifesto, com erro registrado no log. Downloads de fonte, entrada, resposta e manifesto ficam disponíveis no status mesmo quando não há candidatos. O registro de tarefas é apenas em memória: após reiniciar o servidor, os arquivos continuam em disco, mas os IDs anteriores não reaparecem nos endpoints de status/download.

Em erros HTTP, o manifesto guarda o código e a mensagem devolvida pelo provedor, não o corpo completo da resposta. Requisições com imagens em base64 não são armazenadas. O texto bruto preservado é o conteúdo do candidato, não o envelope completo da resposta HTTP. O snapshot e os hashes permitem conferir quais dados foram usados, não provar a autenticidade do servidor remoto.

## Testes offline

```powershell
python -B -m unittest discover -s testes -v
node testes/test_interface.js
node testes/test_gemini_thinking.js
```

Os testes Python usam diretórios temporários e um Gemini simulado. Rede e navegador reais são bloqueados, e a chave vem de uma variável de ambiente fictícia, de modo que o `.env` real não é lido. `test_contrato_auditoria.py` cobre contrato, tipos aninhados, um único campo, parâmetros da requisição, erros de transporte/HTTP/exportação, truncamento e bloqueio, exclusão das partes de raciocínio, hashes, snapshots, imagens, uploads concorrentes, recusa de identificadores antigos e encerramento do driver. `test_gemini_thinking.py` cobre as 13 combinações de modelo e nível de raciocínio, nos endpoints e no manifesto.

Os testes JavaScript executam o código real da interface em um DOM mínimo: a exibição de zero, falso, nulos e objetos, e as opções de modelo e nível enviadas às rotas. Nenhum teste mede a qualidade de extração de modelos reais, a fidelidade visual do navegador ou o custo.

`TCC_Metricas_Avaliacao_Resumo.ipynb` e `URLs_Datasets_TCC.txt` permanecem como artefatos dos experimentos anteriores. Os novos testes não reexecutam esses experimentos nem validam suas conclusões.
