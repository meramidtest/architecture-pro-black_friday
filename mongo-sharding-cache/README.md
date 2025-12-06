# pymongo-api

## Как запустить

Запускаем mongodb и приложение

```shell
docker compose up -d
```

Заполняем mongodb данными и Инициалазируем redis cluster

```shell
./scripts/redis-init.sh
./scripts/mongo-init.sh
```

## Как проверить

Откройте в браузере http://localhost:8080

## Доступные эндпоинты

Список доступных эндпоинтов, swagger http://<ip виртуальной машины>:8080/docs

## Посмотреть работу кеширования

1. Сделать несколько запросов на http://localhost:8080/helloDoc/users и убедиться что последующие выполняются <= 5ms
