# Абстракция провайдеров цен

## Назначение

Сервис работает с ценами через абстрактный интерфейс `PriceProvider`. Это позволяет:
- Подключать разные источники данных (БД, внешние API, файлы) без изменения бизнес-логики
- Тестировать `PricingService` с mock-провайдерами
- В будущем агрегировать несколько провайдеров в один

---

## Интерфейс PriceProvider

Расположение: `src/domain/interfaces/price_provider.py`

```python
class PriceProvider(ABC):
    """Абстрактный интерфейс для источников ценовых данных."""

    @abstractmethod
    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Получить цены по точному совпадению (code, kind, unit, region)."""
        ...

    @abstractmethod
    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Получить цены по категории (для fallback уровней 4 и 5)."""
        ...
```

### Структура PriceLookupQuery

```python
@dataclass
class PriceLookupQuery:
    code: str           # Артикул позиции
    kind: str           # 'material' или 'work'
    unit: str           # Каноническая единица измерения
    country_code: str   # Двухбуквенный код страны (ISO 3166-1 alpha-2)
    region_code: str | None = None   # Код региона (ISO 3166-2), None = поиск по стране
    city: str | None = None          # Город (опционально)
    category: str | None = None      # Категория для category fallback
```

### Структура PriceEntry

```python
@dataclass
class PriceEntry:
    code: str           # Артикул
    kind: str           # 'material' или 'work'
    unit: str           # Единица измерения
    unit_price: Decimal # Цена за единицу
    currency: str       # Валюта (например, 'RUB')
    country_code: str   # Страна
    region_code: str | None = None   # Регион (None = страновая цена)
    city: str | None = None
    provider_name: str = ""  # Название провайдера для трассировки
    category: str = ""       # Категория
```

---

## Текущая реализация: StaticPriceProvider

Расположение: `src/infrastructure/providers/static_price_provider.py`

Читает данные из таблицы `price_catalog` в PostgreSQL через SQLAlchemy.

```python
class StaticPriceProvider(PriceProvider):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        # SELECT * FROM price_catalog
        # WHERE code = :code AND kind = :kind AND unit = :unit
        #   AND country_code = :country_code
        #   [AND region_code = :region_code]  -- если задан
        ...

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        # SELECT * FROM price_catalog
        # WHERE category = :category AND kind = :kind
        #   AND country_code = :country_code
        #   [AND region_code = :region_code]  -- если задан
        ...
```

**Особенности:**
- Использует асинхронные сессии SQLAlchemy (`AsyncSession`)
- Не кэширует результаты — каждый вызов идёт в БД
- Поддерживает опциональную фильтрацию по `region_code` (если `None` — не фильтрует)

### Подключение провайдера

`StaticPriceProvider` создаётся в зависимостях FastAPI и инжектируется в `PricingService`:

```python
# src/api/dependencies.py (упрощённо)
async def get_pricing_service(session: AsyncSession = Depends(get_session)):
    provider = StaticPriceProvider(session)
    return PricingService(provider)
```

---

## Заготовка: PriceAggregator (для будущего использования)

`PriceAggregator` позволит объединить несколько провайдеров и возвращать лучший результат.

```python
class PriceAggregator(PriceProvider):
    """Агрегирует данные из нескольких провайдеров."""

    def __init__(self, providers: list[PriceProvider]) -> None:
        self.providers = providers

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        results = []
        for provider in self.providers:
            entries = await provider.get_prices(query)
            results.extend(entries)
        # Дедупликация по (code, unit, region_code, provider_name)
        return self._deduplicate(results)

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        results = []
        for provider in self.providers:
            entries = await provider.get_prices_by_category(query)
            results.extend(entries)
        return self._deduplicate(results)

    def _deduplicate(self, entries: list[PriceEntry]) -> list[PriceEntry]:
        seen = set()
        unique = []
        for e in entries:
            key = (e.code, e.unit, e.region_code, e.provider_name)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique
```

---

## Как добавить новый провайдер

### Шаг 1: Создать класс провайдера

```python
# src/infrastructure/providers/my_provider.py

from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider


class MyExternalPriceProvider(PriceProvider):
    """Провайдер цен из внешнего API."""

    def __init__(self, api_url: str, api_key: str) -> None:
        self.api_url = api_url
        self.api_key = api_key

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        # Вызов внешнего API и маппинг ответа в list[PriceEntry]
        response = await self._fetch(
            f"{self.api_url}/prices",
            params={"code": query.code, "region": query.region_code},
        )
        return [
            PriceEntry(
                code=item["code"],
                kind=query.kind,
                unit=item["unit"],
                unit_price=Decimal(str(item["price"])),
                currency=item["currency"],
                country_code=query.country_code,
                region_code=query.region_code,
                provider_name="my_external_api",
                category=item.get("category", ""),
            )
            for item in response["items"]
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        # Аналогично, по категории
        ...
```

### Шаг 2: Подключить в зависимостях

```python
# src/api/dependencies.py

async def get_pricing_service(session: AsyncSession = Depends(get_session)):
    static = StaticPriceProvider(session)
    external = MyExternalPriceProvider(
        api_url=settings.external_price_api_url,
        api_key=settings.external_price_api_key,
    )
    aggregator = PriceAggregator([static, external])
    return PricingService(aggregator)
```

### Шаг 3: Добавить настройки в config

```python
# src/config.py
class Settings(BaseSettings):
    external_price_api_url: str = ""
    external_price_api_key: str = ""
```

### Шаг 4: Добавить тест

```python
# tests/unit/test_my_provider.py

class MockMyExternalPriceProvider(PriceProvider):
    async def get_prices(self, query):
        return [PriceEntry(code=query.code, ..., provider_name="mock_external")]

    async def get_prices_by_category(self, query):
        return []
```

---

## Timeout провайдера

`PricingService` оборачивает каждый вызов провайдера в `asyncio.wait_for()`:

```python
async def _get_prices(self, query: PriceLookupQuery) -> list:
    try:
        return await asyncio.wait_for(
            self.price_provider.get_prices(query),
            timeout=settings.price_provider_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning("price_provider_timeout", query=query)
        return []  # Timeout трактуется как "цена не найдена"
```

Таймаут настраивается через `PRICE_PROVIDER_TIMEOUT_SECONDS` (по умолчанию 5 секунд). При таймауте на одном уровне pipeline продолжается к следующему уровню fallback.
