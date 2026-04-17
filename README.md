# KupovinaBot

Telegram-бот для общего семейного списка покупок.

Бот умеет:
- хранить общий список покупок на уровне чата;
- добавлять товары через `/add`;
- показывать активный список через `/list`;
- отмечать покупки через `/buy`;
- очищать список через `/clear`;
- принимать список товаров из сообщения с упоминанием бота;
- отправлять интерактивный чеклист по простому упоминанию бота;
- сохранять историю действий в SQLite для последующей аналитики.

## Требования

- Python 3.12+
- Telegram Bot Token от `@BotFather`
- Linux-сервер с `systemd` для постоянного запуска

## Локальный запуск

1. Перейдите в папку проекта.
2. Создайте и активируйте виртуальное окружение.
3. Установите зависимости.
4. Укажите токен бота.
5. Запустите `main.py`.

Пример для PowerShell:

```powershell
cd "c:\Users\mrkis\Проекты\KupovinaBot"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_TOKEN"
python main.py
```

Если нужно явно указать путь к базе:

```powershell
$env:SHOPPING_BOT_DB_PATH="c:\Users\mrkis\Проекты\KupovinaBot\shopping_bot.db"
```

## Использование в Telegram

- `/start` — показать подсказку
- `/add молоко` — добавить товар
- `/list` — показать активные товары
- `/buy 2` — отметить товар купленным по номеру
- `/buy молоко` — отметить товар купленным по названию
- `/clear` — очистить активный список

Новый интерфейс:
- `@ВашБот` + список строк — массовое добавление товаров
- `@ВашБот` без текста — интерактивный чеклист с кнопками

Для работы в группе отключите `Privacy Mode` через `@BotFather`:

1. `@BotFather`
2. `/mybots`
3. Выбрать бота
4. `Bot Settings`
5. `Group Privacy`
6. `Turn off`

## Переменные окружения

- `TELEGRAM_BOT_TOKEN` — обязательный токен бота
- `SHOPPING_BOT_DB_PATH` — необязательный путь к SQLite-базе

## Деплой на Ubuntu

В репозитории есть скрипт [deploy.sh](/abs/path/c:/Users/mrkis/Проекты/KupovinaBot/deploy.sh), который:
- создаёт `.venv`;
- устанавливает зависимости;
- создаёт `.env`, если его ещё нет;
- создаёт или обновляет `systemd`-сервис;
- включает автозапуск;
- перезапускает бота.

### Быстрый деплой

1. Перенесите проект на сервер.
2. Установите системные пакеты:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

3. Перейдите в папку проекта и сделайте скрипт исполняемым:

```bash
cd ~/KupovinaBot
chmod +x deploy.sh
```

4. Запустите деплой:

```bash
./deploy.sh
```

По умолчанию сервис будет называться `kupovinabot`, а база данных будет лежать в папке проекта.

Если хотите задать имя сервиса или пользователя явно:

```bash
SERVICE_NAME=kupovinabot APP_USER=$USER ./deploy.sh
```

## Файл .env

Скрипт создаёт `.env`, если файла ещё нет. После первого запуска откройте его и укажите токен:

```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_TOKEN
SHOPPING_BOT_DB_PATH=/home/your-user/KupovinaBot/shopping_bot.db
```

Затем перезапустите сервис:

```bash
sudo systemctl restart kupovinabot
```

## Полезные команды на сервере

Проверить статус:

```bash
sudo systemctl status kupovinabot
```

Посмотреть логи:

```bash
journalctl -u kupovinabot -f
```

Перезапустить после обновления:

```bash
sudo systemctl restart kupovinabot
```

## Что не нужно коммитить

Уже исключено через `.gitignore`:
- `.venv/`
- `__pycache__/`
- `.env`
- `shopping_bot.db`
- другие `.db`-файлы
