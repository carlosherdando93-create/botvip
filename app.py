"""
app.py FINAL MASTER
"""

import os
import time
import sqlite3
import logging
import base64
import io
import asyncio
from typing import Dict, Any

from flask import Flask
import mercadopago
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# === CONFIG ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID") or 0)
WEBHOOK_PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL")

if not TELEGRAM_TOKEN or not MP_ACCESS_TOKEN or not GROUP_CHAT_ID:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.error("⚠️ Configure TELEGRAM_TOKEN, MP_ACCESS_TOKEN e GROUP_CHAT_ID nas variáveis de ambiente.")
    raise SystemExit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mp = mercadopago.SDK(MP_ACCESS_TOKEN)
DB_PATH = "payments.db"

# === BANCO DE DADOS ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        amount REAL,
        status TEXT,
        created_at INTEGER
    );
    """)
    conn.commit()
    conn.close()

def save_payment(payment_id, user_id, amount, status="pending"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO payments(payment_id, user_id, amount, status, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (str(payment_id), str(user_id), float(amount), status, int(time.time())))
    conn.commit()
    conn.close()

# === TEXTOS ===
START_IMAGE = "https://files.catbox.moe/mlbwwv.jpg"

WELCOME_MESSAGE = """🔱 *Desperte o Poder Que Está em Você!*

Três forças regem tudo — quem as domina, domina a vida.

🧠 *Poder.*  
Não é o que você fala, é o que transmite.  
Sua presença impõe respeito, não pede.

🍷 *Sedução.*  
Mais que aparência — é energia e influência.  
Quem entende a mente, conquista corações e oportunidades.

♟️ *Guerra.*  
A vida é um tabuleiro. Cada ação é uma estratégia.  
Quem enxerga o jogo, vence.

⚡ *Este grupo é para quem está pronto para comandar a própria história.*  
🔥 *As vagas são limitadas. O poder não espera por indecisos.*
"""

PLANS = {
    "30": {"label": "💎 VIP 30 dias — R$37,90", "amount": 37.90},
    "life": {"label": "♾️ VIP Vitalício — R$98,50", "amount": 98.50},
    "flash": {"label": "⚡ Oferta Relâmpago — R$10,00", "amount": 10.00},
}

PROMO_CODES = {"THG100", "FLP100"}

user_offer_info: Dict[int, Dict[str, Any]] = {}
awaiting_promo: Dict[int, bool] = {}

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_offer_info[user_id] = {"start": time.time()}

    keyboard = [
        [InlineKeyboardButton(PLANS["30"]["label"], callback_data="buy_30")],
        [InlineKeyboardButton(PLANS["life"]["label"], callback_data="buy_life")],
        [InlineKeyboardButton("🎟️ Código Promocional", callback_data="promo")],
    ]

    await update.message.reply_photo(photo=START_IMAGE)
    await update.message.reply_text(WELCOME_MESSAGE, reply_markup=InlineKeyboardMarkup(keyboard))

    # Mensagem da oferta relâmpago separada com cronômetro
    offer_msg = await update.message.reply_text(
        "🔥 *OFERTA RELÂMPAGO: VIP Vitalício por apenas R$10,00!* 🔥\n\n"
        "⏳ Essa oportunidade expira em 5 minutos!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(PLANS["flash"]["label"], callback_data="buy_flash")]])
    )

    asyncio.create_task(show_timer(context, offer_msg.chat_id, offer_msg.message_id, 5 * 60))

# === TIMER ===
async def show_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, duration: int):
    for remaining in range(duration, 0, -1):
        mins, secs = divmod(remaining, 60)
        text = (
            f"🔥 *OFERTA RELÂMPAGO: VIP Vitalício por apenas R$10,00!* 🔥\n\n"
            f"⏳ Expira em *{mins:02d}:{secs:02d}*!"
        )
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown",
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Comprar Agora", callback_data="buy_flash")]]))
        except:
            break
        await asyncio.sleep(1)

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text="⏰ *A oferta relâmpago expirou.*",
        parse_mode="Markdown"
    )

# === PAGAMENTO PIX ===
async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str):
    user_id = update.effective_user.id
    plan = PLANS.get(plan_key)
    if not plan:
        await update.message.reply_text("❌ Plano inválido.")
        return

    amount = plan["amount"]
    label = plan["label"]

    payment_data = {
        "transaction_amount": float(amount),
        "description": f"VIP {label}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@example.com"},
    }

    try:
        result = mp.payment().create(payment_data)
        response = result["response"]
        payment_id = response.get("id")
        qr_code = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
        qr_code_base64 = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64")

        if not qr_code:
            await update.message.reply_text("⚠️ Erro ao gerar o código PIX. Tente novamente mais tarde.")
            return

        save_payment(payment_id, user_id, amount, status="pending")

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"{label}\n💰 *R${amount:.2f}*\n\n"
                f"🪙 *Copie e cole este código PIX no seu banco:*\n"
                f"`{qr_code}`\n\n"
                f"Ou escaneie o QR Code abaixo 👇\n\n"
                f"Após o pagamento confirmado, seu acesso VIP será liberado automaticamente ⚡"
            ),
            parse_mode="Markdown"
        )

        if qr_code_base64:
            img_data = base64.b64decode(qr_code_base64)
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=io.BytesIO(img_data),
                caption="📸 Escaneie este QR Code com o app do seu banco"
            )

    except Exception as e:
        logger.exception("Erro ao criar pagamento PIX:")
        await update.message.reply_text("❌ Ocorreu um erro ao processar o pagamento. Tente novamente em alguns instantes.")

# === CALLBACKS ===
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("buy_"):
        plan_key = data.split("_")[1]
        await process_payment(update, context, plan_key)
    elif data == "promo":
        user_id = query.from_user.id
        awaiting_promo[user_id] = True
        await query.message.reply_text("🎟️ Envie seu código promocional:")

# === PROMO CODE ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().upper()

    if awaiting_promo.get(user_id):
        awaiting_promo[user_id] = False

        # 🟢 Código especial VIP10 - Vitalício por R$10
        if text == "VIP10":
            await update.message.reply_text(
                "🎟️ Código *VIP10* aplicado!\n"
                "🔥 Você pode comprar o acesso *Vitalício por apenas R$10,00!*"
            )
            await process_payment(update, context, "flash")
            return

        # 🟢 Códigos de dono (acesso grátis)
        elif text in {"THG100", "FLP100"}:
            await update.message.reply_text("✅ Código De Dono! Você ganhou acesso VIP gratuito.")
            invite_link = await context.bot.create_chat_invite_link(GROUP_CHAT_ID, member_limit=1, expire_date=None)
            await update.message.reply_text(
                f"Aqui está seu link de acesso ao grupo VIP:\n{invite_link.invite_link}"
            )

        else:
            await update.message.reply_text("❌ Código inválido. Tente novamente.")

# === MAIN ===
def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
