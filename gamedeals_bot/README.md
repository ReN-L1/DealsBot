# 🎮 Game Deals Bot

Telegram бот для поиска скидок на игры. Полностью независимый, работает 24/7.

## Команды

| Команда | Описание |
|---|---|
| `/deals` | Топ скидки со всех магазинов |
| `/deals steam` | Скидки только в Steam |
| `/deals epic` | Скидки в Epic Games |
| `/deals gog` | Скидки на GOG |
| `/free` | Бесплатные игры в Epic прямо сейчас |
| `/search <название>` | Найти цены на конкретную игру (поддерживает частичный поиск) |
| `/watch <игра>` | Следить за скидкой на игру |
| `/watch <игра> <макс цена>` | Уведомить когда цена ниже указанной |
| `/watch <игра> <макс цена> <мин скидка%>` | С условием по скидке |
| `/watchlist` | Мой список отслеживания |
| `/unwatch <игра>` | Убрать игру из списка |

## Деплой на Railway (бесплатно)

### 1. Создай бота в Telegram
- Напиши @BotFather в Telegram
- `/newbot` → введи имя → получи токен

### 2. Создай аккаунт на Railway
- Зайди на https://railway.app
- Зарегистрируйся через GitHub

### 3. Создай проект
- New Project → Deploy from GitHub repo
- Загрузи эти файлы в GitHub репозиторий
- Или: New Project → Empty Project → Add Service → GitHub Repo

### 4. Добавь переменные окружения
В Railway → Variables добавь:
```
BOT_TOKEN=твой_токен_от_botfather
ITAD_API_KEY=твой_ключ_от_isthereanydeal
```

### 5. Готово!
Railway автоматически запустит бота через Procfile.

## Локальный запуск

```bash
pip install -r requirements.txt
export BOT_TOKEN="твой_токен"
export ITAD_API_KEY="твой_ключ"
python bot.py
```
