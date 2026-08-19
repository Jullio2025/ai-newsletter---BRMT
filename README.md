# Newsletter IA — setup

Newsletter diária automática de novidades de IA, gerada com Claude e enviada pro Telegram.
Roda de graça no GitHub Actions, sem precisar de VPS.

## Passo a passo

### 1. Criar o bot do Telegram
1. Fala com [@BotFather](https://t.me/BotFather) no Telegram
2. Manda `/newbot`, escolhe um nome e um username (precisa terminar em "bot", ex: `meuainews_bot`)
3. Ele te devolve um **token**, tipo `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
4. Guarda esse token

### 2. Pegar seu chat_id
1. Manda qualquer mensagem pro bot que você acabou de criar (procura ele pelo username no Telegram e dá "Start")
2. No navegador, acessa (troca `<TOKEN>` pelo token do passo 1):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Procura por `"chat":{"id":123456789,...}` — esse número é o seu `chat_id`

> Se quiser mandar pra um **canal** em vez de privado: cria o canal, adiciona o bot como admin,
> e o chat_id do canal é o username do canal com `@` na frente (ex: `@meucanaldeai`) ou um ID negativo — o getUpdates também mostra isso depois que o bot postar/receber algo no canal.

### 3. Pegar sua API key da Anthropic
1. Acessa [console.anthropic.com](https://console.anthropic.com)
2. Cria uma API key (Settings > API Keys)

### 4. Subir esse código pro GitHub
O código já está neste repositório (`Jullio2025/ai-newsletter---BRMT`). Se precisar clonar noutra máquina:
```bash
git clone https://github.com/Jullio2025/ai-newsletter---BRMT.git
cd ai-newsletter---BRMT
```

> ⚠️ **Nunca** coloque o token do bot, o chat_id ou a API key dentro de arquivos do repositório.
> Eles vivem só nos **GitHub Secrets** (passo 5) — o `newsletter.py` os lê de variáveis de ambiente.
> Se um token vazar (print, chat, commit), revogue na hora: `/revoke` no @BotFather para o Telegram,
> e Settings > API Keys no console da Anthropic para a key.

### 5. Configurar os secrets no GitHub
No repositório, vai em **Settings > Secrets and variables > Actions > New repository secret** e cria:

| Nome | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | o token do passo 1 |
| `TELEGRAM_CHAT_ID` | o chat_id do passo 2 |
| `ANTHROPIC_API_KEY` | a key do passo 3 |

Esse é o único lugar onde esses valores devem existir. O workflow os injeta como variáveis de
ambiente na hora de rodar (ver `.github/workflows/newsletter.yml`), e o GitHub mascara os valores
nos logs do Actions.

### 6. Testar manualmente
Vai na aba **Actions** do repositório, clica no workflow "Newsletter IA" > **Run workflow**.
Isso dispara na hora, sem esperar a segunda-feira.

### 7. Automático dali pra frente
O workflow já está configurado pra rodar **todo dia às 09:00 (horário de MT)**.
Pra mudar o horário, edita o `cron` em `.github/workflows/newsletter.yml`
(formato: minuto hora dia-do-mês mês dia-da-semana, sempre em UTC).

## Customizações fáceis

- **Frequência**: muda o `cron` no workflow (ex: `0 12 * * *` = todo dia)
- **Fontes**: edita o dicionário `RSS_FEEDS` no `newsletter.py` — pode adicionar qualquer feed RSS
- **Modelo Claude usado pra resumir**: variável `model=` dentro de `build_newsletter()`
- **Janela de dias**: variável `DAYS_WINDOW` no workflow (padrão: 7 dias)

## Custo

- GitHub Actions: grátis (uso muito abaixo do limite free de repositórios públicos/privados pessoais)
- Telegram Bot API: grátis
- Anthropic API: cobra por uso — uma execução semanal com esse volume de texto fica na casa de
  poucos centavos de dólar por mês

## Como funciona por dentro

1. `collect_news()` baixa cada feed de `RSS_FEEDS` e fica só com os itens publicados dentro da
   janela `DAYS_WINDOW` (padrão do workflow: 1 dia). Item sem data legível é mantido, pra não
   perder notícia por causa de feed mal formatado. Máximo de 15 itens por fonte.
2. `fetch_rankings()` puxa uma amostra de modelos do OpenRouter como contexto extra.
3. `build_newsletter()` manda tudo pro Claude, que seleciona e escreve a newsletter em português.
4. `send_telegram()` envia em blocos de 4000 caracteres. Se o Telegram recusar o Markdown
   (formatação quebrada na hora de fatiar, por exemplo), o bloco é reenviado como texto puro em vez
   de a mensagem se perder.

Falha em um feed individual não derruba a execução — aparece como `[erro] <fonte>` no log do Actions.
