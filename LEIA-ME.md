# RADAR GBP/JPY — painel online + alertas de compra/venda

Projeto em português. O painel mostra velas de 5m, 15m, **30m** e 1h. A estratégia procura oportunidades independentemente em **velas fechadas de 15m e 30m** e usa a tendência de 1h para confirmação. Os alertas chegam por **Telegram**, mesmo com o computador desligado.

**Estado inicial:** código pronto para publicar e configurar. Não vem alojado nem ligado a contas: para receber alertas reais precisas das tuas próprias contas e credenciais.

## 1. Criar gratuitamente as contas

- Fonte de cotações: https://twelvedata.com — criar conta e copiar a **API key**. O plano gratuito anuncia 800 créditos/dia e dados de Forex em tempo real. Os limites e as condições podem mudar.
- GitHub: https://github.com — cria um repositório, por exemplo `radar-gbpjpy`, preferencialmente **privado**. Um repositório público não deve conter segredos e expõe o histórico de alertas; repositórios privados consomem minutos gratuitos do GitHub Actions.
- Telegram: cria um bot com https://t.me/BotFather e guarda o **token** que ele fornece. Depois abre uma conversa com o teu bot e envia `/start`.
- Streamlit Community Cloud: https://share.streamlit.io — para ter um endereço web do painel.

## 2. Obter o CHAT_ID do Telegram

No navegador, **apenas no teu dispositivo e sem partilhar a ligação**, visita:

`https://api.telegram.org/botO_TEU_TOKEN/getUpdates`

Substitui `O_TEU_TOKEN` pelo token real; já deves ter enviado `/start` ao bot. Na resposta JSON procura algo parecido com `"chat": {"id": 123456789, ...}` e copia o número, que será `TELEGRAM_CHAT_ID`. Se não houver mensagens, envia `/start` novamente e repete. **Nunca publiques nem envies o token em mensagens**; se for comprometido, regenera-o no BotFather.

## 3. Colocar o projeto no GitHub

1. Extrai o ZIP para uma pasta do computador.
2. Cria no GitHub um repositório, por exemplo `radar-gbpjpy`, e carrega os ficheiros e pastas que estão **dentro** da pasta extraída, mantendo `.github/workflows/alertas.yml`, `.state/last_signals.json`, `.streamlit/config.toml` e todos os `.py`.
3. Confirma que o ficheiro `.github/workflows/alertas.yml` aparece dentro do repositório.
4. Em **Settings > Secrets and variables > Actions > New repository secret**, cria exatamente estes 3 *secrets*:
   - `TWELVE_DATA_API_KEY` → chave de Twelve Data
   - `TELEGRAM_BOT_TOKEN` → token do BotFather
   - `TELEGRAM_CHAT_ID` → chat ID que obtiveste
5. Em **Settings > Actions > General > Workflow permissions**, seleciona **Read and write permissions** e grava. Isto permite ao programa guardar os identificadores dos sinais já enviados e não repetir alertas (em certos repositórios/organizações a opção poderá estar bloqueada).
6. Abre **Actions > GBPJPY — alertas Telegram > Run workflow**. Marca `test_telegram` para receber uma mensagem de teste. Depois executa sem essa opção para analisar o mercado.

Cada aviso identifica claramente **15m** ou **30m**. Os avisos usam uma rotina agendada **aproximadamente de 20 em 20 minutos durante a semana** e no início de domingo à noite. A rotina recupera as últimas velas de 15 e 30 minutos para não perder sinais recentes quando a execução atrasar. **Atrasos ou falhas do agendamento GitHub Actions são possíveis**. Não é uma infraestrutura de trading de baixa latência.

**Limites GitHub:** a execução em repositórios públicos com runners padrão geralmente é gratuita; repositórios privados têm uma quota de minutos (por exemplo, GitHub Free: 2 000 minutos/mês). O agendamento de 20 minutos reduz o consumo comparativamente a um de 15 em 15 minutos, mas não há garantia de ficar dentro da quota, nem de funcionar sempre. A atividade em repositórios públicos pode ser automaticamente suspensa após 60 dias sem atividade. Consulta os limites atuais do teu plano.

## 4. Publicar o painel online

1. Acede a https://share.streamlit.io e inicia sessão.
2. Escolhe **Create app** → escolhe o repositório GitHub e o ficheiro de entrada `app.py`.
3. Em **Advanced settings > Secrets** coloca, substituindo a chave por uma real:

```toml
TWELVE_DATA_API_KEY = "A_TUA_CHAVE_TWELVE_DATA"
```

4. Publica. Receberás um URL no formato `https://<nome>.streamlit.app`, acessível por telemóvel e Windows 11.
5. O painel atualiza-se quando o visitas e periodicamente enquanto está aberto. **A Streamlit Community Cloud pode suspender o painel após 12 horas sem visitantes. Os alertas Telegram continuam independentes graças ao GitHub Actions.**

Um painel público permite a qualquer visitante usar a quota associada à tua API key através da aplicação. Recomenda-se configurar a visibilidade como privada se for para uso pessoal.

## Como interpretar o sinal

Um alerta COMPRA exige: tendência 1h positiva (EMA50 acima da EMA200 e a subir), EMA20 acima da EMA50 no período de 15m ou 30m, RSI entre 52 e 72 e um dos seguintes gatilhos: cruzamento MACD de subida, regresso acima da EMA20 com impulso positivo ou quebra de um máximo recente com impulso positivo. VENDA é a versão inversa, com RSI de 28 a 48.

O valor de entrada é o **fecho da vela**, não a cotação de execução. O stop sugerido é `máx(1,8 × ATR(14), 12 pips)` de distância. Os dois objetivos são `1,5R` e `2R`. Para GBP/JPY, 1 pip = 0,01 JPY. **São parâmetros heurísticos, não probabilidades e não foram validados com backtest de desempenho.** Os cálculos não integram spread, slippage, notícias nem tamanho total da carteira.

Não existe abertura/fecho automático de ordens. Um alerta pode ser recebido já depois de o mercado ter afastado o preço de referência. **Não entres só porque surgiu um alerta.**

## Executar localmente (opcional)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Define TWELVE_DATA_API_KEY como variável de ambiente ou num secrets.toml local
streamlit run app.py
```

Para o painel local, podes criar `.streamlit/secrets.toml` com:

```toml
TWELVE_DATA_API_KEY = "A_TUA_CHAVE"
```

Esse ficheiro está excluído do Git por `.gitignore`. Para testar o Telegram, podes definir as variáveis de ambiente `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` e executar `python alerts.py --test-telegram`.

## Segurança e limitações

- **Não colocar chaves em ficheiros do GitHub:** usa `Secrets` do GitHub e da Streamlit. Nunca partilhar o token do bot.
- Os dados da Twelve Data são preços do fornecedor, não necessariamente iguais aos da corretora; pode haver diferenças e atraso.
- As verificações agendadas pelo GitHub podem atrasar, falhar, ficar suspensas ou atingir limites; não prometem alertas instantâneos.
- A detecção de oportunidades é técnica e não garante resultados futuros. O mercado Forex pode mover-se violentamente em torno de notícias e de alterações na liquidez.
- Se o programa falhar antes de enviar uma mensagem, o GitHub mostrará erro no separador Actions. Não abras operações sem um plano de risco e stops apropriados.

## Ficheiros incluídos

- `app.py` — painel web adaptado a telemóvel, gráficos 5m/15m/30m/1h e histórico separado por período.
- `strategy.py` — cálculos de EMA, MACD, RSI, ATR, sinais, stop e objetivos.
- `datafeed.py` — ligação à Twelve Data.
- `alerts.py` — execução periódica de alertas de 15m e 30m por Telegram.
- `.github/workflows/alertas.yml` — agendamento online.
- `.state/last_signals.json` — proteção contra duplicação.
- `tests/test_strategy.py` — testes locais de consistência temporal.

**Notas:** Não é consultoria financeira. Testa primeiro em conta de demonstração e mantém controlo sobre as posições abertas.
