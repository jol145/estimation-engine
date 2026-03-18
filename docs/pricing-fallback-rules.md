# Правила Pricing Fallback Pipeline

## Обзор

Для каждой позиции спецификации сервис проходит **6 уровней** поиска цены, от наиболее точного к наименее. Как только цена найдена — pipeline останавливается.

```
┌─────────────────────────────────────────────────────────────┐
│ Уровень 1: Exact Match (code + region + unit)              │
│ ──► найдено? → STOP, confidence: high                      │
├─────────────────────────────────────────────────────────────┤
│ Уровень 2: Country Fallback (code + country + unit)        │
│ ──► найдено? → STOP, confidence: medium                    │
├─────────────────────────────────────────────────────────────┤
│ Уровень 3: Unit Conversion (конвертируемые единицы)        │
│ ──► найдено? → STOP, confidence: medium                    │
├─────────────────────────────────────────────────────────────┤
│ Уровень 4: Category Fallback (регион + категория)          │
│ ──► найдено? → STOP, confidence: low                       │
├─────────────────────────────────────────────────────────────┤
│ Уровень 5: Coefficient Fallback (страна × коэффициент)     │
│ ──► найдено? → STOP, confidence: low                       │
├─────────────────────────────────────────────────────────────┤
│ Уровень 6: Unpriced                                        │
│ ──► всегда, если ничего не нашли, confidence: none         │
└─────────────────────────────────────────────────────────────┘
```

---

## Уровень 1: Exact Match

**Что ищем:** Запись в price_catalog с точным совпадением `code + kind + unit + country_code + region_code`

**Условие запроса:**
```sql
WHERE code = :code
  AND kind = :kind
  AND unit = :unit
  AND country_code = :country_code
  AND region_code = :region_code
```

| Поле             | Значение                    |
|------------------|-----------------------------|
| `pricing_method` | `exact_match`               |
| `confidence`     | `high`                      |
| `match_path`     | `{country}/{region}/{unit}` |
| `fallback_reason`| `null`                      |

---

## Уровень 2: Country Fallback

**Что ищем:** Запись с совпадением `code + kind + unit + country_code`, без привязки к региону.

Используется, если для региона нет данных, но страновая цена есть.

**Условие запроса:**
```sql
WHERE code = :code
  AND kind = :kind
  AND unit = :unit
  AND country_code = :country_code
  -- region_code не фильтруется
```

| Поле             | Значение                 |
|------------------|--------------------------|
| `pricing_method` | `country_fallback`       |
| `confidence`     | `medium`                 |
| `match_path`     | `{country}/{unit}`       |
| `fallback_reason`| `no_regional_price`      |

---

## Уровень 3: Unit Conversion

**Что ищем:** Цену для того же `code + kind`, но в **конвертируемой единице** (например, если запрошены `kg`, ищем в `t` и конвертируем обратно).

Перебираются все конверсии из `UNIT_CONVERSIONS`. Для каждой конвертируемой единицы сначала пробуется региональный уровень, затем страновой.

**Конвертация цены:**
```
price_in_original = price_in_converted * conversion_factor
```

Пример: цена в `t` = 95 000 RUB/т, коэффициент `kg→t` = 0.001
→ цена в `kg` = 95 000 × 0.001 = 95 RUB/кг

| Поле             | Значение                                       |
|------------------|------------------------------------------------|
| `pricing_method` | `unit_conversion`                              |
| `confidence`     | `medium`                                       |
| `match_path`     | `{country}/{converted_unit}->converted_to_{unit}` |
| `fallback_reason`| `unit_converted`                               |
| `unit_converted` | `true`                                         |
| `original_unit`  | исходная единица в каталоге (до конверсии)     |

---

## Уровень 4: Category Fallback

**Что ищем:** Любые записи в той же `category + kind` в том же регионе, не обязательно с тем же `code`.

Используется, когда точного артикула нет, но есть аналоги в категории.

**Условие запроса:**
```sql
WHERE category = :category
  AND kind = :kind
  AND country_code = :country_code
  AND region_code = :region_code
```

| Поле             | Значение                                        |
|------------------|-------------------------------------------------|
| `pricing_method` | `category_fallback`                             |
| `confidence`     | `low`                                           |
| `match_path`     | `{country}/{region}/category:{category}`        |
| `fallback_reason`| `no_exact_code_match`                           |

---

## Уровень 5: Coefficient Fallback

**Что ищем:** Страновые цены в той же `category + kind` (без региона), умноженные на региональный коэффициент.

Используется, когда и в регионе, и в стране нет точных данных, но известно среднее по стране и коэффициент региона.

**Формула:**
```
adjusted_price = country_average_price × regional_coefficient
```

**Таблица региональных коэффициентов:**

| Код региона | Регион                      | Коэффициент |
|-------------|-----------------------------|-------------|
| `RU-MOW`    | Москва                      | 1.15        |
| `RU-SPE`    | Санкт-Петербург             | 1.10        |
| `RU-KDA`    | Краснодарский край          | 1.05        |
| `RU-SVE`    | Свердловская обл. (Екатеринбург) | 0.95   |
| `RU-NSO`    | Новосибирская обл.          | 0.90        |
| прочие      | Не в таблице                | 1.0 (без коэффициента) |

**Условие запроса (страновой уровень):**
```sql
WHERE category = :category
  AND kind = :kind
  AND country_code = :country_code
  -- region_code не фильтруется
```

| Поле             | Значение                                             |
|------------------|------------------------------------------------------|
| `pricing_method` | `coefficient_fallback`                               |
| `confidence`     | `low`                                                |
| `match_path`     | `{country}/category:{category}*coeff:{coefficient}`  |
| `fallback_reason`| `regional_coefficient_applied`                       |

---

## Уровень 6: Unpriced

Если ни один из предыдущих уровней не нашёл цену — позиция помечается как `unpriced`.

| Поле             | Значение           |
|------------------|--------------------|
| `pricing_method` | `unpriced`         |
| `confidence`     | `none`             |
| `average_unit_price` | `0`            |
| `line_total`     | `0`                |
| `fallback_reason`| `no_price_found`   |
| `match_path`     | `null`             |

---

## Сводная таблица уровней

| Уровень | Метод                | Confidence | Что проверяем                                |
|---------|----------------------|------------|----------------------------------------------|
| 1       | `exact_match`        | high       | code + region + unit                         |
| 2       | `country_fallback`   | medium     | code + country + unit                        |
| 3       | `unit_conversion`    | medium     | code + конвертируемая единица                |
| 4       | `category_fallback`  | low        | category + region                            |
| 5       | `coefficient_fallback` | low      | category + country × региональный коэффициент |
| 6       | `unpriced`           | none       | цена не найдена                              |
