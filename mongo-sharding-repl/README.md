# pymongo-api

## Как запустить

Перейти в директорию с проектом
```
cd ./mongo-sharding-repl
```

Запускаем mongodb и приложение

```shell
docker compose up -d
```

Заполняем mongodb данными

```shell
./scripts/mongo-init.sh
```

## Как проверить

Откройте в браузере http://localhost:8080

## Доступные эндпоинты

Список доступных эндпоинтов, swagger http://<ip виртуальной машины>:8080/docs

## Очистка окружения

По завершению

```shell
docker compose down -v
```
