"""
APP.PY — versão corrigida (mantive textos e comportamento)
"""

import os
import time
import sqlite3
import logging
import asyncio
import random
import base64
import io

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
import mercadopago

# === CONFIG ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID") or 0)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not TELEGRAM_TOKEN or not MP_ACCESS_TOKEN or not GROUP_CHAT_ID:
    logger.error("Erro: configure TELEGRAM_TOKEN, MP_ACCESS_TOKEN e GROUP_CHAT_ID no .env")
    raise SystemExit(1)

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
    )
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
MAIN_TEXT = """🜂 *⚛ Bem-vindo à irmandade mais foda do Brasil.*
Aqui não existe Gados — só homens que Pegam Mulheres, Facil.💪

Para manter tudo funcionando e afastar curiosos, cobramos apenas um valor simbólico de R$10.
Quem entra aqui não paga… *investe em si mesmo*🔞
"""

# Contador (valores que estavam no seu código)
START_COUNTER = 135920
STOP_COUNTER = 137500
counter_value = START_COUNTER

PLANS = {
    "vip": {"label": "🔥 Quero entrar!", "amount": 10.00},
}

PROMO_CODES = {"THG100", "FLP100"}

awaiting_promo = {}

# === /START ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton(PLANS["vip"]["label"], callback_data="buy_vip")],
        [InlineKeyboardButton("🎟️ Código Promocional", callback_data="promo")],
    ]

    # 1️⃣ MENSAGEM PRINCIPAL (fixa, não editada)
    await update.message.reply_text(
        MAIN_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    # 2️⃣ MENSAGEM DO CONTADOR (editável)
    counter_msg = await update.message.reply_text(
        f"🔥🔞 *Membros Mensais👥⬆:* {START_COUNTER:,}".replace(",", "."),
        parse_mode="Markdown"
    )

    asyncio.create_task(
        counter_task(context, counter_msg.chat_id, counter_msg.message_id)
    )

# === CONTADOR ANIMADO ===
async def counter_task(context, chat_id, message_id):
    global counter_value

    while counter_value < STOP_COUNTER:
        await asyncio.sleep(1.8)

        counter_value += random.randint(1, 3)
        if counter_value > STOP_COUNTER:
            counter_value = STOP_COUNTER

        new_text = f"🔥🔞 *Membros Mensais👥⬆:* {counter_value:,}".replace(",", ".")

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=new_text,
                parse_mode="Markdown"
            )
        except Exception:
            # se falhar (usuário bloqueou bot, mensagem deletada, etc.) interrompe o loop
            break

# === PAGAMENTO ===
async def process_payment(update, context, plan_key):
    plan = PLANS.get(plan_key)
    amount = plan["amount"]
    label = plan["label"]
    user_id = update.effective_user.id

    data = {
        "transaction_amount": float(amount),
        "description": f"VIP {label} user:{user_id}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@mail.com"},
    }

    try:
        result = mp.payment().create(data)
        response = result.get("response", {})

        payment_id = response.get("id")
        qr = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
        qr_b64 = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64")

        save_payment(payment_id, user_id, amount)

        # prefira responder via callback_query.message se a ação vier de botão
        target_chat = None
        try:
            target_chat = update.callback_query.message
        except Exception:
            try:
                target_chat = update.message
            except Exception:
                target_chat = None

        if target_chat:
            await target_chat.reply_text(
                f"🔥 *{label}*\n💰 *R$ {amount:.2f}*\n\n"
                f"🪙 *PIX Copia e Cola:*\n`{qr}`",
                parse_mode="Markdown"
            )

            if qr_b64:
                img = io.BytesIO(base64.b64decode(qr_b64))
                await target_chat.reply_photo(img)
        else:
            logger.warning("Não foi possível localizar a mensagem alvo para enviar o PIX.")

    except Exception as e:
        logger.exception(e)
        # tenta notificar o usuário de forma segura
        try:
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text("⚠️ Erro ao gerar pagamento.")
            elif update.message:
                await update.message.reply_text("⚠️ Erro ao gerar pagamento.")
        except Exception:
            pass

# === CALLBACKS ===
async def button(update: Update, context):
    q = update.callback_query
    await q.answer()

    if q.data == "promo":
        awaiting_promo[q.from_user.id] = True
        await q.message.reply_text("🎟️ Envie seu código promocional:")
        return

    if q.data == "buy_vip":
        await process_payment(update, context, "vip")
        return

# === PROMO CODE ===
async def handle_message(update: Update, context):
    uid = update.effective_user.id
    if not awaiting_promo.get(uid):
        return

    awaiting_promo[uid] = False
    code = update.message.text.strip().upper()

    if code in PROMO_CODES:
        invite = await context.bot.create_chat_invite_link(GROUP_CHAT_ID, member_limit=1)
        await update.message.reply_text("🎉 Código aceito! Aqui está seu link:")
        await update.message.reply_text(invite.invite_link)
    else:
        await update.message.reply_text("❌ Código inválido.")

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
