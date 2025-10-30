# BotVIP

Bot Telegram com integração Mercado Pago (PIX) + Flask Webhook.

## 🧩 Funcionalidades
- Criação de pagamentos via PIX (Mercado Pago)
- Webhook automático para confirmar pagamentos
- Envio de link de convite temporário para grupo VIP no Telegram

## ⚙️ Configuração
1. Crie um arquivo `.env` com base em `.env.example`.
2. Instale dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Execute localmente:
   ```bash
   python app.py
   ```
4. Para deploy no Render:
   - Suba o projeto no GitHub.
   - Configure as variáveis de ambiente no painel do Render.
   - Deploy automático.

⚠️ **Importante:** nunca publique seu `.env` com tokens reais.
