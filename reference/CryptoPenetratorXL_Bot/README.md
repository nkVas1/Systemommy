# CryptoPenetratorXL v2.1

**Портативный десктоп-терминал для автоматизированной торговли криптовалютными фьючерсами на Bybit.**

Профессиональное PyQt6-приложение для Windows 11 с тёмной темой, японскими свечами,
встроенной стратегией на основе 4 индикаторов и системой полного баланса (full-balance).

---

## Основные возможности

- **Графики японских свечей** с 5 панелями: цена, объём, Stochastic, MACD, CCI
- **Персональная стратегия** — 4 индикатора с весами конфлюэнции:
  - **Volume** (0.15) — объём, OBV, спайки
  - **Stochastic** (14, 1, 3) (0.30) — зоны перекупленности/перепроданности, кроссоверы
  - **MACD** (12, 26, 9) (0.30) — гистограмма, кроссоверы, нулевая линия
  - **CCI** (20) (0.25) — зоны, тренд, дивергенции
- **Сигналы**: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL с уровнем уверенности
- **Автоматическая торговля** — непрерывный цикл анализа + исполнения (paper / live)
- **Full-Balance стратегия** — 100% эквити × плечо, без SL, TP 0.3-0.6% нетто
- **Paper-режим** — безопасное тестирование стратегии без реальных ордеров
- **Bybit V5 API** — REST + WebSocket, фьючерсы (linear / USDT)
- **SQLite** — локальная БД, история сделок и сигналов
- **Аналитика сессии** — P&L в реальном времени, кривая эквити, статистика
- **Паттерны свечей** — Hammer, Doji, Engulfing, Morning/Evening Star и др.
- **Тёмная тема** — профессиональный дизайн в стиле TradingView

---

## Архитектура

```
main.py                     # Точка входа
app/
├── core/
│   ├── config.py           # Pydantic Settings (.env)
│   ├── constants.py        # Enum'ы, пороговые значения
│   ├── exceptions.py       # Кастомные исключения
│   └── logger.py           # RotatingFileHandler + консоль
├── api/
│   ├── bybit_client.py     # Bybit V5 REST (pybit)
│   └── bybit_ws.py         # Bybit WebSocket
├── indicators/
│   ├── volume.py           # Volume, OBV, Volume Ratio
│   ├── stochastic.py       # Stochastic (K, D)
│   ├── macd.py             # MACD, Signal, Histogram
│   ├── cci.py              # CCI
│   └── engine.py           # IndicatorEngine — оркестратор
├── strategy/
│   └── signal_generator.py # TradeSignal + TP (no SL)
├── trading/
│   ├── risk_manager.py     # Full-balance sizing
│   └── executor.py         # Исполнение ордеров (paper/live)
├── db/
│   ├── models.py           # SQLAlchemy модели (SQLite)
│   └── database.py         # CRUD + статистика
├── gui/
│   ├── styles.py           # QSS тёмная тема
│   ├── chart_widget.py     # Matplotlib 5-панельный график
│   ├── analytics_widget.py # Аналитика сессии в реальном времени
│   └── main_window.py      # Главное окно терминала
└── utils/
    └── helpers.py           # Форматирование, утилиты
```

---

## Установка

### Требования

- **Windows 11** (x64)
- **Python 3.11+**
- Аккаунт **Bybit** с API-ключами

### Шаги

```powershell
# 1. Клонировать репозиторий
git clone <url> CryptoPenetratorXL_Bot
cd CryptoPenetratorXL_Bot

# 2. Создать виртуальное окружение
python -m venv .venv
.\.venv\Scripts\activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить конфигурацию
copy .env.example .env
# Отредактировать .env — вставить API-ключи Bybit
```

### Деактивация / удаление venv

```powershell
deactivate                          # Деактивировать
Remove-Item -Recurse -Force .venv   # Удалить полностью
```

---

## Конфигурация (.env)

| Параметр | Описание | По умолчанию |
|---|---|---|
| `BYBIT_API_KEY` | API-ключ Bybit | — |
| `BYBIT_SECRET_KEY` | Секретный ключ Bybit | — |
| `BYBIT_TESTNET` | Использовать тестнет | `false` |
| `TRADING_MODE` | Режим: `paper` / `live` | `paper` |
| `DEFAULT_LEVERAGE` | Кредитное плечо | `2.0` |
| `MAX_LEVERAGE` | Максимальное плечо | `2.0` |
| `DEFAULT_SYMBOLS` | Торговые пары (JSON) | `["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]` |
| `DEFAULT_TIMEFRAME` | Таймфрейм (мин) | `15` |
| `USE_FULL_BALANCE` | 100% эквити на позицию | `true` |
| `USE_STOP_LOSS` | Использовать стоп-лосс | `false` |
| `TAKE_PROFIT_PCT` | Тейк-профит (гросс) | `0.005` (0.5%) |
| `TP_MIN_PCT` | Минимум TP | `0.003` (0.3%) |
| `TP_MAX_PCT` | Максимум TP | `0.006` (0.6%) |
| `EXCHANGE_FEE_PCT` | Биржевая комиссия maker (1 сторона) | `0.0002` (0.02%) |
| `MAX_OPEN_POSITIONS` | Макс. открытых позиций | `1` |

---

## Запуск

### Быстрый запуск (рекомендуется)

```
start.bat
```

### Ручной запуск

```powershell
.\.venv\Scripts\activate
python main.py
```

Приложение запустится в **paper-режиме** по умолчанию — все сделки симулируются.

### Режимы

- **Paper** — безопасное тестирование, ордера не отправляются на биржу
- **Live** — реальная торговля (переключается в настройках или через `.env`)

---

## Использование

1. **Выберите пару** и **таймфрейм** в верхней панели
2. Нажмите **Analyse** — бот загрузит свечи, рассчитает индикаторы, выдаст сигнал
3. Панель **Signal** покажет:
   - Направление (BUY / SELL / HOLD) с уровнем уверенности
   - Оценки каждого индикатора
   - Конфлюэнцию (совпадение сигналов)
   - Точки входа, SL, TP, R:R
4. **Manual Long / Short** — ручное открытие позиции по текущему сигналу
5. **Auto Trade** — автоматический цикл анализа + исполнения
6. **Positions** — текущие позиции и баланс кошелька
7. **History** — статистика и история сделок

---

## Стратегия

Конфлюэнция 4 индикаторов с весами:

| Индикатор | Вес | Параметры |
|---|---|---|
| Volume | 0.15 | MA(20), OBV, спайки |
| Stochastic | 0.30 | K=14, Smooth=1, D=3 |
| MACD | 0.30 | Fast=12, Slow=26, Signal=9 |
| CCI | 0.25 | Period=20 |

**Пороги конфлюэнции:**
- `score ≥ 0.45` → STRONG_BUY / STRONG_SELL
- `score ≥ 0.20` → BUY / SELL
- `score < 0.20` → HOLD

**Защита от ложных сигналов:**
- Если Stochastic и CCI одновременно в зоне перекупленности → BUY подавляется
- Если Stochastic и CCI одновременно в зоне перепроданности → SELL подавляется
- 3+ индикатора в одном направлении → повышение confidence (но с учётом зон)

**Торговая стратегия (v2.1):**
- **Full-balance** — 100% эквити × плечо (напр. $100 × 2x = $200)
- **Лимитные ордера** — с отступом 0.01% от рынка (maker fee 0.02%)
- **Без стоп-лосса** — удержание позиции при просадке
- **TP: 0.3-0.6% нетто** — после вычета комиссий (maker 0.02% × 2 стороны)
- **1 позиция** — одновременно может быть открыта только одна
- **Нет лимита сделок** — без ограничений по количеству сделок в день
- **История по режимам** — Paper и Live сделки отображаются раздельно

---

## Технологии

| Компонент | Технология |
|---|---|
| GUI | PyQt6 6.6+ |
| Графики | matplotlib (QtAgg) |
| API | pybit 5.7+ (Bybit V5) |
| Данные | pandas, numpy |
| Конфигурация | pydantic-settings 2.1+ |
| БД | SQLAlchemy 2.0 + SQLite |
| Логирование | logging (RotatingFileHandler) |

---

## Лицензия

Проект для личного использования.

