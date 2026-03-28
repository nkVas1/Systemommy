# CryptoPenetratorXL — Development Plan & Architecture Guide

> Документ для быстрого восстановления контекста и планирования дальнейшей разработки.

---

## 1. О проекте

**CryptoPenetratorXL** — полностью автономный торговый бот для криптобиржи Bybit (USDT Linear Perpetual).
Работает на Python 3.11+ с GUI на PyQt6. Не требует внешних серверов, баз данных или платных сервисов.

### Ключевые характеристики

| Параметр | Значение |
|----------|----------|
| **Биржа** | Bybit V5 API (Linear USDT Perpetual) |
| **GUI** | PyQt6 + matplotlib (5-панельный график) |
| **БД** | SQLite (локальная, `data/crypto_pen.db`) |
| **Стратегия** | Full-balance (100% equity × leverage), no SL, TP 0.3–0.6% net |
| **Индикаторы** | Volume(MA20) + Stochastic(14,1,3) + MACD(12,26,9) + CCI(20) |
| **Плечо** | 2x (настраиваемое) |
| **Позиции** | Максимум 1 одновременно |
| **Ордера** | Лимитные (с отступом 0.01% от рынка для снижения комиссии) |
| **Режимы** | Paper (симуляция) и Live (реальная торговля) |

---

## 2. Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                     PyQt6 GUI (main_window.py)               │
│   Chart · Signals · Positions · History · Analytics · Log    │
└────────────┬──────────────────────────────────────┬──────────┘
             │                                      │
        Background Workers (QThread)          User Controls
             │                                      │
┌────────────┴──────────────────────────────────────┴──────────┐
│  AnalysisWorker · AutoTradeWorker · PositionsWorker          │
│  MTFWorker · EnhancedWorker · LatencyWorker                  │
└────────────┬──────────────────────┬──────────────────────────┘
             │                      │
             ↓                      ↓
┌──────────────────┐    ┌──────────────────┐
│ Signal Generator │    │  Trade Executor  │
│ + Indicator      │    │  + Risk Manager  │
│   Engine         │    │  + Paper Manager │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
    Klines (OHLCV) ←─────────── │ ──→ Bybit API
         │                       │
    ┌────┴────┬──────┬──────┬───┘
    ↓         ↓      ↓      ↓
  Volume  Stochastic MACD   CCI
    │         │      │      │
    └─────────┴──────┴──────┘
              │
        Confluence Score (-1..+1)
        + Zone Suppression
        + Signal Classification
```

### Поток данных

1. **AnalysisWorker** каждые N секунд запрашивает klines с Bybit (mainnet).
2. **IndicatorEngine** обогащает DataFrame 4 индикаторами и вычисляет confluence score.
3. **SignalGenerator** формирует `TradeSignal` (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL).
4. **RiskManager** проверяет лимиты и рассчитывает размер позиции (full-balance).
5. **TradeExecutor** размещает лимитный ордер (live) или симулирует (paper).
6. **Database** сохраняет TradeRecord и SignalRecord в SQLite.

---

## 3. Структура файлов

```
app/
├── core/
│   ├── config.py          — Pydantic Settings, загрузка .env
│   ├── constants.py       — Enums (Signal, Side, OrderType), пороги
│   ├── exceptions.py      — Кастомные исключения
│   └── logger.py          — Трёхуровневое логирование
├── api/
│   ├── bybit_client.py    — REST API обёртка (klines, orders, wallet)
│   └── bybit_ws.py        — WebSocket (опционально)
├── indicators/
│   ├── engine.py          — Оркестратор + confluence scoring + zone suppression
│   ├── volume.py          — Volume MA, OBV, spikes
│   ├── stochastic.py      — Stochastic(14,1,3) + divergence
│   ├── macd.py            — MACD(12,26,9) + histogram
│   └── cci.py             — CCI(20) + zero-cross
├── strategy/
│   └── signal_generator.py — Генерация TradeSignal с TP расчётом
├── trading/
│   ├── executor.py        — Мост: signal → risk → order (limit ордера)
│   ├── risk_manager.py    — Размер позиции, проверки баланса
│   └── paper_manager.py   — In-memory трекер paper позиций
├── db/
│   ├── models.py          — SQLAlchemy модели (TradeRecord, SignalRecord)
│   └── database.py        — CRUD операции (фильтрация по mode)
├── gui/
│   ├── main_window.py     — Главное окно приложения
│   ├── chart_widget.py    — 5-панельный график
│   ├── analytics_widget.py — Сессионная аналитика
│   └── styles.py          — Тёмная тема
├── analysis/
│   └── enhanced_analysis.py — Расширенный анализ (опционально)
└── utils/
    └── helpers.py         — Форматирование (price, qty, %)
```

---

## 4. Стиль кода

- **Python 3.11+** с полной типизацией (`from __future__ import annotations`)
- **Type hints** на все функции и методы
- **Docstrings** в формате Google
- **Логирование** через `app.core.logger.get_logger()` — не `print()`
- **Именование**: `snake_case` для функций/переменных, `PascalCase` для классов
- **Constants**: `UPPER_SNAKE_CASE` в `constants.py`
- **Imports**: stdlib → third-party → local (sorted)
- **Line length**: 100–120 символов
- **Комментарии**: только для неочевидной логики

---

## 5. Текущее состояние (v2.1)

### Что работает

- ✅ Paper trading с реальными ценами (mainnet)
- ✅ Live trading с лимитными ордерами
- ✅ Автоматическая торговля с confluence scoring
- ✅ 5-панельный график (Price, Volume, Stochastic, MACD, CCI)
- ✅ История сделок с фильтрацией по режиму (paper/live)
- ✅ Реал-тайм баланс и позиции
- ✅ Настройки через GUI (Settings Dialog)
- ✅ Сессионная аналитика (P&L, win rate, equity curve)
- ✅ Zone suppression (защита от входов в overbought/oversold)

### Недавние исправления

1. **История по режимам** — History и Statistics теперь фильтруются по текущему режиму (paper/live).
2. **Баланс для live** — Исправлен `get_wallet_balance()`: используется `availableToOrder` с fallback на equity.
3. **Лимитные ордера** — Все ордера теперь лимитные (0.01% offset) вместо маркет. Комиссия: maker 0.02%.
4. **Zone suppression** — Алгоритм больше не открывает BUY при overbought (Stochastic + CCI) и SELL при oversold.
5. **Плечо 2x** — Дефолт изменён с 2.5x на 2.0x.

---

## 6. Планы развития

### Phase 1: Стабилизация (текущая)

- [x] Фильтрация истории по режиму
- [x] Исправление баланса для live
- [x] Лимитные ордера
- [x] Zone suppression в алгоритме
- [ ] Юнит-тесты для индикаторов и risk manager
- [ ] Integration-тесты для paper trading loop
- [ ] Тестирование live trading на малых суммах

### Phase 2: Улучшение алгоритма

- [ ] Динамический TP на основе ATR (вместо фиксированного %)
- [ ] Адаптивные пороги confluence в зависимости от волатильности
- [ ] Backtesting-модуль: прогон стратегии на исторических данных
- [ ] Учёт объёма при определении силы сигнала (volume confirmation)
- [ ] Multi-timeframe confirmation (MTF) как обязательное условие
- [ ] Анализ структуры свечей (price action patterns) с весом в confluence

### Phase 3: Инфраструктура

- [ ] WebSocket для real-time обновления позиций и цен
- [ ] Telegram-бот для уведомлений о сделках и сигналах
- [ ] REST API для удалённого управления (FastAPI)
- [ ] Docker-контейнеризация
- [ ] CI/CD пайплайн (GitHub Actions: lint, test, build)

### Phase 4: Расширение

- [ ] Поддержка нескольких бирж (Binance, OKX)
- [ ] Портфельная торговля (несколько символов одновременно)
- [ ] Machine Learning: модель для предсказания качества сигнала
- [ ] Web-интерфейс (React/Vue) как альтернатива desktop GUI
- [ ] Мониторинг и алерты (Prometheus + Grafana)

### Phase 5: Совершенство

- [ ] A/B тестирование параметров стратегии
- [ ] Автоматическая оптимизация гиперпараметров (Optuna)
- [ ] Sentiment-анализ (Twitter/Telegram/News)
- [ ] Order flow analysis (tape reading)
- [ ] Market microstructure indicators (bid/ask imbalance)

---

## 7. Алгоритм торговли (подробно)

### Индикаторы и веса

| Индикатор | Вес | Компоненты |
|-----------|-----|------------|
| **Volume** | 0.15 | OBV trend (±0.4), spike detection (±0.3), delta sum (±0.3) |
| **Stochastic** | 0.30 | Zone (±0.35), crossover (±0.40), divergence (±0.25) |
| **MACD** | 0.30 | Crossover (±0.45), histogram (±0.20), zero-line (±0.10), divergence (±0.25) |
| **CCI** | 0.25 | Zone (±0.30), zero-cross (±0.35), trend (±0.15), divergence (±0.20) |

### Классификация сигнала

1. **Confluence score** = weighted sum of all indicator scores (clipped to [-1, +1])
2. **Zone suppression**: если Stochastic И CCI одновременно в overbought → BUY подавляется. Аналогично для oversold + SELL.
3. **Agreement bonus**: 3+ индикатора в одном направлении → confidence +15%. 4 из 4 → ещё +10%.
4. **Thresholds**: ≥0.45 = STRONG_BUY, ≥0.20 = BUY, else HOLD.

### Управление позицией

- **Размер**: 100% equity × leverage (2x)
- **Ордер**: Limit с 0.01% отступом от рынка
- **TP**: 0.5% gross от entry price (автоматическое закрытие)
- **SL**: отключён (hold through drawdowns)
- **Мониторинг**: каждые 5 секунд проверка TP hit

---

## 8. Конфигурация (.env)

Все параметры загружаются из `.env` через Pydantic Settings. Ключевые:

```env
TRADING_MODE=paper|live       # Режим торговли
DEFAULT_LEVERAGE=2.0          # Плечо по умолчанию
TAKE_PROFIT_PCT=0.005         # TP 0.5% gross
EXCHANGE_FEE_PCT=0.0002       # Комиссия maker 0.02%
MONITOR_INTERVAL_SEC=60       # Интервал анализа (сек)
```

---

## 9. Быстрый старт для разработки

```bash
# 1. Клонировать
git clone https://github.com/nkVas1/CryptoPenetratorXL_Bot.git
cd CryptoPenetratorXL_Bot

# 2. Создать виртуальное окружение
python -m venv venv
venv\Scripts\activate  # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить конфигурацию
cp .env.example .env
# Заполнить BYBIT_API_KEY и BYBIT_SECRET_KEY

# 5. Запустить
python main.py
```

---

*Последнее обновление: 2026-03-27*
