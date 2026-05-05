#!/usr/bin/env python3
"""
Game Deals Telegram Bot
Полностью независимый бот — работает без ИИ, 24/7 на сервере.
"""

import os
import json
import logging
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ─── Config ───────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["BOT_TOKEN"]
ITAD_API_KEY = os.environ["ITAD_API_KEY"]
BASE_URL = "https://api.isthereanydeal.com"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище вишлистов и уведомлений (в памяти — для persistence можно добавить SQLite)
# { user_id: { "game_title": { "id": ..., "max_price": ..., "max_cut": ... } } }
watchlist: dict[int, dict] = {}

# Популярные магазины (id → название)
KNOWN_SHOPS = {}  # будет заполнен при старте

SHOP_ALIASES = {
    "steam": ["steam"],
    "epic": ["epic game store", "epic games store", "epic"],
    "gog": ["gog"],
    "humble": ["humble store", "humble bundle"],
    "fanatical": ["fanatical"],
    "gmg": ["green man gaming", "greenmangaming"],
    "playstation": ["playstation store", "playstation"],
    "xbox": ["xbox", "microsoft store"],
    "nintendo": ["nintendo eshop", "nintendo"],
    "nuuvem": ["nuuvem"],
    "gamebillet": ["gamebillet"],
    "indiegala": ["indiegala"],
}

# ─── ITAD API ─────────────────────────────────────────────────────────────────

def itad_get(path, params=None):
    p = {"key": ITAD_API_KEY}
    if params:
        p.update(params)
    url = BASE_URL + path + "?" + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers={"User-Agent": "GameDealsBot/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        logger.error(f"ITAD GET {path} error {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        logger.error(f"ITAD GET {path} exception: {e}")
        return None

def itad_post(path, body, params=None):
    p = {"key": ITAD_API_KEY}
    if params:
        p.update(params)
    url = BASE_URL + path + "?" + urllib.parse.urlencode(p)
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "GameDealsBot/2.0", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        logger.error(f"ITAD POST {path} error {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        logger.error(f"ITAD POST {path} exception: {e}")
        return None

def load_shops():
    """Загрузить список всех магазинов"""
    global KNOWN_SHOPS
    shops = itad_get("/service/shops/v1")
    if shops:
        KNOWN_SHOPS = {s["id"]: s["title"] for s in shops}
        logger.info(f"Loaded {len(KNOWN_SHOPS)} shops")

def resolve_shop_ids(shop_alias: str) -> list[int]:
    """Найти ID магазинов по псевдониму"""
    alias_lower = shop_alias.lower().strip()
    matches = []
    for shop_id, shop_name in KNOWN_SHOPS.items():
        if alias_lower in shop_name.lower():
            matches.append(shop_id)
    return matches

def get_deals(limit=15, min_cut=30, shop_ids=None):
    params = {"limit": limit, "sort": "-cut", "nondeals": "false"}
    if shop_ids:
        params["shops"] = ",".join(str(s) for s in shop_ids)
    return itad_get("/deals/v2", params)

def search_games(query: str, limit=8):
    """Поиск игры — поддерживает частичное совпадение"""
    return itad_get("/games/search/v1", {"title": query, "results": limit})

def get_prices(game_ids: list):
    return itad_post("/games/prices/v3", game_ids, {"deals": "false", "vouchers": "true"})

def get_epic_free():
    """Бесплатные игры Epic — скидка 100% в Epic Game Store"""
    # Ищем Epic shop id
    epic_ids = resolve_shop_ids("epic")
    if not epic_ids:
        return None
    params = {
        "limit": 20,
        "sort": "-cut",
        "nondeals": "false",
        "shops": ",".join(str(s) for s in epic_ids)
    }
    result = itad_get("/deals/v2", params)
    if not result:
        return None
    # Фильтруем только бесплатные
    free = [d for d in result.get("list", []) if d.get("deal", {}).get("cut", 0) == 100]
    return free

# ─── Formatters ───────────────────────────────────────────────────────────────

def esc(text: str) -> str:
    """Escape markdown v1 special chars"""
    for ch in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(ch, f"\\{ch}")
    return text

def fmt_deals(items: list, title="🔥 Топ скидки прямо сейчас:") -> str:
    if not items:
        return "😔 Скидок по этому фильтру не найдено. Попробуй позже!"

    lines = [f"*{title}*\n"]
    for i, item in enumerate(items[:15], 1):
        game_title = item.get("title", "?")
        game_type = item.get("type", "game")
        deal = item.get("deal", {})
        shop = deal.get("shop", {}).get("name", "?")
        cut = deal.get("cut", 0)
        price = deal.get("price", {})
        regular = deal.get("regular", {})
        amt = price.get("amount", 0)
        reg_amt = regular.get("amount", 0)
        cur = price.get("currency", "USD")
        url = deal.get("url", "")
        flag = deal.get("flag", "")

        badge = " 🏆" if flag == "H" else (" ⭐" if flag == "S" else "")
        type_emoji = "🎮" if game_type == "game" else "📦"
        price_str = f"БЕСПЛАТНО" if amt == 0 else f"{amt} {cur}"
        reg_str = f"~~{reg_amt} {cur}~~" if reg_amt > 0 and amt != reg_amt else ""

        line = f"{i}\\. {type_emoji} *{game_title}*{badge}\n"
        line += f"   🏪 {shop} \\| 💸 `\\-{cut}%` \\| {price_str} {reg_str}\n"
        if url:
            line += f"   [🛒 Купить]({url})\n"
        lines.append(line)

    lines.append("\n_Данные: IsThereAnyDeal\\.com_")
    return "\n".join(lines)

def fmt_game_prices(game_title: str, prices_data: list) -> str:
    if not prices_data:
        return f"❌ Нет данных о ценах на *{game_title}*"

    item = prices_data[0]
    deals = item.get("deals", [])
    history_low = item.get("historyLow", {}).get("all", {})

    lines = [f"🎮 *{game_title}*\n"]

    if history_low:
        hl = history_low.get("amount", "?")
        cur = history_low.get("currency", "USD")
        lines.append(f"🏆 Исторический минимум: `{hl} {cur}`\n")

    if not deals:
        lines.append("😔 Сейчас нигде нет скидок на эту игру\\.")
        return "\n".join(lines)

    lines.append("💰 *Цены по магазинам:*\n")
    deals_sorted = sorted(deals, key=lambda d: d.get("price", {}).get("amount", 9999))

    for deal in deals_sorted:
        shop = deal.get("shop", {}).get("name", "?")
        cut = deal.get("cut", 0)
        price = deal.get("price", {})
        regular = deal.get("regular", {})
        amt = price.get("amount", "?")
        reg_amt = regular.get("amount", "?")
        cur = price.get("currency", "USD")
        url = deal.get("url", "")
        flag = deal.get("flag", "")

        badge = " 🏆" if flag == "H" else (" ⭐" if flag == "S" else "")

        if cut > 0:
            line = f"🔥 *{shop}*{badge}: `\\-{cut}%` \\| `{amt} {cur}` ~~{reg_amt}~~"
        else:
            line = f"📦 *{shop}*: `{amt} {cur}`"

        if url:
            line += f" [→]({url})"
        lines.append(line)

    lines.append("\n_Данные: IsThereAnyDeal\\.com_")
    return "\n".join(lines)

def fmt_free_epic(items: list) -> str:
    if not items:
        return "😔 Сейчас нет бесплатных игр в Epic Games Store."

    lines = ["🎁 *Бесплатные игры в Epic Games Store:*\n"]
    for i, item in enumerate(items, 1):
        title = item.get("title", "?")
        deal = item.get("deal", {})
        url = deal.get("url", "")
        expiry = deal.get("expiry", "")

        line = f"{i}\\. 🎮 *{title}*"
        if expiry:
            try:
                dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                line += f"\n   ⏰ До: {dt.strftime('%d.%m.%Y %H:%M')}"
            except:
                pass
        if url:
            line += f"\n   [🛒 Забрать бесплатно]({url})"
        lines.append(line)

    lines.append("\n_Данные: IsThereAnyDeal\\.com_")
    return "\n".join(lines)

# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Привет\\! Я бот для поиска скидок на игры\\.*\n\n"
        "📋 *Команды:*\n\n"
        "🔥 *Скидки*\n"
        "`/deals` — топ скидки со всех магазинов\n"
        "`/deals steam` — скидки только в Steam\n"
        "`/deals epic` — скидки в Epic Games\n"
        "`/deals gog` — скидки на GOG\n"
        "`/deals humble` — скидки в Humble Store\n\n"
        "🎁 *Epic Games*\n"
        "`/free` — бесплатные игры в Epic прямо сейчас\n\n"
        "🔍 *Поиск*\n"
        "`/search <название>` — найти цены на игру\n"
        "Например: `/search cyber` или `/search witcher`\n\n"
        "🔔 *Уведомления*\n"
        "`/watch <игра>` — следить за скидкой на игру\n"
        "`/watch <игра> <макс цена>` — уведомить когда цена ниже\n"
        "`/watch <игра> <макс цена> <мин скидка%>` — с условием\n"
        "Например: `/watch witcher 10` или `/watch cyberpunk 30 50`\n\n"
        "`/watchlist` — мой список отслеживания\n"
        "`/unwatch <игра>` — убрать игру из списка\n\n"
        "ℹ️ `/help` — это сообщение"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

async def cmd_deals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    shop_filter = " ".join(args).strip().lower() if args else ""

    shop_ids = []
    shop_label = "всех магазинов"

    if shop_filter:
        shop_ids = resolve_shop_ids(shop_filter)
        shop_label = shop_filter.capitalize()
        if not shop_ids:
            await update.message.reply_text(
                f"❌ Магазин *{shop_filter}* не найден\\.\n"
                f"Попробуй: `steam`, `epic`, `gog`, `humble`, `fanatical`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

    msg = await update.message.reply_text("⏳ Загружаю скидки...")
    result = get_deals(limit=15, min_cut=30, shop_ids=shop_ids if shop_ids else None)

    if not result:
        await msg.edit_text("❌ Не удалось получить данные. Попробуй позже.")
        return

    items = result.get("list", [])
    title = f"🔥 Топ скидки — {shop_label}:"
    text = fmt_deals(items, title=title)
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

async def cmd_free(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Ищу бесплатные игры в Epic...")
    items = get_epic_free()
    if items is None:
        await msg.edit_text("❌ Не удалось получить данные. Попробуй позже.")
        return
    text = fmt_free_epic(items)
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "🔍 Напиши название игры после команды\\.\nПример: `/search witcher`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    query = " ".join(ctx.args).strip()
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    games = search_games(query, limit=8)
    if not games:
        await msg.edit_text(f"❌ Ничего не найдено по запросу *{query}*", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if len(games) == 1:
        # Сразу показываем цены
        game = games[0]
        prices = get_prices([game["id"]])
        text = fmt_game_prices(game["title"], prices or [])
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    else:
        # Показываем список — пользователь выбирает
        keyboard = []
        for g in games:
            keyboard.append([InlineKeyboardButton(g["title"], callback_data=f"price:{g['id']}:{g['title'][:40]}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(
            f"🔍 Найдено *{len(games)}* игр по запросу *{query}*\\.\nВыбери нужную:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def callback_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return

    _, game_id, game_title = parts
    await query.edit_message_text(f"⏳ Загружаю цены на *{game_title}*\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    prices = get_prices([game_id])
    text = fmt_game_prices(game_title, prices or [])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /watch <игра>
    /watch <игра> <макс цена>
    /watch <игра> <макс цена> <мин скидка%>
    """
    if not ctx.args:
        await update.message.reply_text(
            "📌 *Использование:*\n"
            "`/watch <название игры>`\n"
            "`/watch <название игры> <макс цена>`\n"
            "`/watch <название игры> <макс цена> <мин скидка%>`\n\n"
            "Примеры:\n"
            "`/watch witcher`\n"
            "`/watch cyberpunk 20`\n"
            "`/watch elden ring 30 50`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Парсим аргументы — последние 1-2 могут быть числами
    args = ctx.args
    max_price = None
    min_cut = None

    # Проверяем последние аргументы
    try:
        if len(args) >= 2 and args[-1].replace(".", "").isdigit() and args[-2].replace(".", "").isdigit():
            min_cut = int(float(args[-1]))
            max_price = float(args[-2])
            query = " ".join(args[:-2])
        elif len(args) >= 1 and args[-1].replace(".", "").isdigit():
            max_price = float(args[-1])
            query = " ".join(args[:-1])
        else:
            query = " ".join(args)
    except:
        query = " ".join(args)

    if not query:
        await update.message.reply_text("❌ Напиши название игры.")
        return

    msg = await update.message.reply_text(f"🔍 Ищу *{query}*\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    games = search_games(query, limit=5)
    if not games:
        await msg.edit_text(f"❌ Игра *{query}* не найдена\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    user_id = update.effective_user.id

    if len(games) == 1:
        game = games[0]
        _add_to_watchlist(user_id, game["id"], game["title"], max_price, min_cut)
        cond = _format_condition(max_price, min_cut)
        await msg.edit_text(
            f"✅ *{game['title']}* добавлена в список отслеживания\\!\n{cond}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        keyboard = []
        extra = f":{max_price or ''}:{min_cut or ''}"
        for g in games:
            keyboard.append([InlineKeyboardButton(
                g["title"],
                callback_data=f"watch:{g['id']}:{g['title'][:30]}{extra}"
            )])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(
            f"🔍 Найдено *{len(games)}* игр\\. Выбери нужную:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

def _add_to_watchlist(user_id: int, game_id: str, game_title: str, max_price=None, min_cut=None):
    if user_id not in watchlist:
        watchlist[user_id] = {}
    watchlist[user_id][game_title.lower()] = {
        "id": game_id,
        "title": game_title,
        "max_price": max_price,
        "min_cut": min_cut,
    }

def _format_condition(max_price, min_cut) -> str:
    parts = []
    if max_price:
        parts.append(f"💰 Цена ниже `{max_price} USD`")
    if min_cut:
        parts.append(f"💸 Скидка от `{min_cut}%`")
    if not parts:
        parts.append("🔔 Уведомлю при любой скидке")
    return "\n".join(parts)

async def callback_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 4)
    # watch:game_id:title:max_price:min_cut
    if len(parts) < 3:
        return

    game_id = parts[1]
    game_title = parts[2]
    max_price = float(parts[3]) if len(parts) > 3 and parts[3] else None
    min_cut = int(parts[4]) if len(parts) > 4 and parts[4] else None

    user_id = update.effective_user.id
    _add_to_watchlist(user_id, game_id, game_title, max_price, min_cut)

    cond = _format_condition(max_price, min_cut)
    await query.edit_message_text(
        f"✅ *{game_title}* добавлена в список отслеживания\\!\n{cond}",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = watchlist.get(user_id, {})

    if not items:
        await update.message.reply_text(
            "📋 Твой список пуст\\.\nДобавь игры командой `/watch <название>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    lines = ["📋 *Твой список отслеживания:*\n"]
    for i, (_, info) in enumerate(items.items(), 1):
        title = info["title"]
        max_price = info.get("max_price")
        min_cut = info.get("min_cut")

        cond_parts = []
        if max_price:
            cond_parts.append(f"до {max_price} USD")
        if min_cut:
            cond_parts.append(f"скидка от {min_cut}%")
        cond = f" \\({', '.join(cond_parts)}\\)" if cond_parts else ""

        lines.append(f"{i}\\. 🎮 *{title}*{cond}")

    lines.append("\n`/unwatch <название>` — удалить игру")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Использование: `/unwatch <название игры>`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    query = " ".join(ctx.args).lower()
    user_id = update.effective_user.id
    items = watchlist.get(user_id, {})

    # Поиск по частичному совпадению
    matches = [k for k in items if query in k]
    if not matches:
        await update.message.reply_text(
            f"❌ *{query}* не найдена в списке отслеживания\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    for k in matches:
        title = items[k]["title"]
        del watchlist[user_id][k]
        await update.message.reply_text(
            f"✅ *{title}* удалена из списка\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

# ─── Watchlist Checker ────────────────────────────────────────────────────────

async def check_watchlist(ctx: ContextTypes.DEFAULT_TYPE):
    """Проверяет вишлист каждые 6 часов и отправляет уведомления"""
    logger.info("Checking watchlist for all users...")

    for user_id, items in watchlist.items():
        if not items:
            continue

        game_ids = [info["id"] for info in items.values()]
        prices_data = get_prices(game_ids)
        if not prices_data:
            continue

        # Индексируем по game_id
        prices_by_id = {p["id"]: p for p in prices_data}

        for key, info in items.items():
            game_id = info["id"]
            game_title = info["title"]
            max_price = info.get("max_price")
            min_cut = info.get("min_cut")

            price_info = prices_by_id.get(game_id)
            if not price_info:
                continue

            deals = price_info.get("deals", [])
            best_deals = [d for d in deals if d.get("cut", 0) > 0]
            if not best_deals:
                continue

            # Сортируем по цене
            best_deals.sort(key=lambda d: d.get("price", {}).get("amount", 9999))
            best = best_deals[0]
            best_price = best.get("price", {}).get("amount", 9999)
            best_cut = best.get("cut", 0)
            best_shop = best.get("shop", {}).get("name", "?")
            best_url = best.get("url", "")
            currency = best.get("price", {}).get("currency", "USD")

            # Проверяем условия
            notify = False
            if max_price and best_price <= max_price:
                notify = True
            if min_cut and best_cut >= min_cut:
                notify = True
            if not max_price and not min_cut and best_cut > 0:
                notify = True

            if notify:
                text = (
                    f"🔔 *Скидка на* *{game_title}*\\!\n\n"
                    f"🏪 {best_shop}\n"
                    f"💸 `\\-{best_cut}%` \\| `{best_price} {currency}`\n"
                )
                if best_url:
                    text += f"[🛒 Купить]({best_url})"

                try:
                    await ctx.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")

# ─── Unknown message handler ──────────────────────────────────────────────────

async def handle_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    # Если пользователь написал просто текст — предлагаем поиск
    await update.message.reply_text(
        f"🔍 Ищешь игру? Используй команду:\n`/search {text}`\n\n"
        f"Или напиши `/help` для списка всех команд\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    load_shops()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("deals", cmd_deals))
    app.add_handler(CommandHandler("free", cmd_free))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))

    # Callback buttons
    app.add_handler(CallbackQueryHandler(callback_price, pattern="^price:"))
    app.add_handler(CallbackQueryHandler(callback_watch, pattern="^watch:"))

    # Unknown text → suggest /search
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # Job: check watchlist every 6 hours
    app.job_queue.run_repeating(check_watchlist, interval=6 * 3600, first=60)

    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
