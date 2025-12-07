### <a name="_b7urdng99y53"></a>**Название задачи:** Настройка механизмов выявления и устранеия горячих шардов
### <a name="_hjk0fkfyohdk"></a>**Автор:**
### <a name="_uanumrh8zrui"></a>**Дата:** 07.12.2025


# ADR: Мониторинг и балансировка шардов для коллекции products

## Контекст

Коллекция `products` шардирована по полю `region`. Необходимо отслеживать состояние шардов и обеспечить автоматическое перераспределение данных.

---

## 1. Метрики для мониторинга шардов

| Метрика                       | Описание                   | Команда MongoDB |
|-------------------------------|----------------------------|-----------------|
| Количество документов на шарде | Баланс данных между шардами | `db.products.getShardDistribution()` |
| Размер данных на шарде        | Объем хранилища            | `sh.status()` |
| Количество чанков             | Распределение чанков       | `db.chunks.find({ns: "somedb.products"}).count()` |
| Операции на шарде             | Нагрузка на шард           | `db.serverStatus().opcounters` |
| Задержка реликации            | Здоровье реплик            | `rs.printSlaveReplicationInfo()` |

### Пример скрипта мониторинга

```javascript
db.products.getShardDistribution()

sh.getBalancerState()

db.getSiblingDB("config").chunks.aggregate([
  { $match: { ns: "somedb.products" } },
  { $group: { _id: "$shard", count: { $sum: 1 } } }
])
```

---

## 2. Автоматическое перераспределение данных

### Настройка балансировщика

```javascript
sh.startBalancer()

db.getSiblingDB("config").settings.updateOne(
  { _id: "balancer" },
  { $set: { 
      activeWindow: { start: "02:00", stop: "06:00" } // устанвить балансировку ночью
  }},
  { upsert: true }
)

sh.isBalancerRunning()
```

### Настройка размера чанка

```javascript
db.getSiblingDB("config").settings.updateOne(
  { _id: "chunksize" },
  { $set: { value: 64 } },
  { upsert: true }
)
```

## Примененые решения

| Компонент        | Решение                                |
|------------------|----------------------------------------|
| Мониторинг       | `getShardDistribution()`, `sh.status()` |
| Автобалансировка | Встроенный балансировщик MongoDB       |
| Окно балансировки | 0200-06:00                             |
| Размер чанка     | 64MB                                   |

