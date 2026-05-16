# Установка и эксплуатация

## Вариант A. Docker (рекомендуется)

```bash
git clone <repo> vpn-prober && cd vpn-prober
cp .env.example .env

# 1. Замени значения:
#    COORDINATOR_API_TOKENS=token-prober-1,token-prober-2
#    COORDINATOR_ADMIN_TOKEN=long-random-string

docker compose up -d --build
docker compose logs -f coordinator prober-1
```

Дашборд: `http://<host>:8080/dashboard?token=<COORDINATOR_ADMIN_TOKEN>`.

Подать первую задачу:

```bash
echo 'vless://uuid@host:443?type=ws&security=tls&host=cdn&path=%2Fws#main' > links.txt
python3 scripts/submit_job.py \
  --coordinator http://localhost:8080 \
  --token "$COORDINATOR_ADMIN_TOKEN" \
  --links-file links.txt \
  --urls https://www.google.com https://www.youtube.com https://chatgpt.com \
  --label "smoke"
```

## Вариант B. Bare-metal (Ubuntu 22.04+)

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip openvpn microsocks curl

# sing-box
sudo ./scripts/install-singbox.sh

python3 -m venv .venv
. .venv/bin/activate
pip install -e .

cp .env.example .env
# отредактируй .env

# Координатор
python -m coordinator.main &

# Пробер
PROBER_NAME=local-1 PROBER_API_TOKEN=token-1 COORDINATOR_URL=http://127.0.0.1:8080 \
  python -m prober.main
```

## Вариант C. Развернуть проберы по разным странам

1. На сервере с публичным IP подними координатор (как в варианте A или B).
2. Поставь TLS-фронт (nginx/caddy) — это важно: пробер шлёт результаты по
   bearer-токену, и без HTTPS токены утекут.
3. На каждом удалённом узле:
   ```bash
   git clone <repo> && cd vpn-prober
   cp .env.example .env
   # Открой .env и установи:
   #   COORDINATOR_URL=https://coordinator.example.com
   #   PROBER_API_TOKEN=<тот же, что в COORDINATOR_API_TOKENS>
   #   PROBER_NAME=<уникальное имя, напр. de-1, sg-2>
   docker compose up -d --build prober-1
   ```

## Резервное копирование

`coordinator-data` (volume) содержит SQLite-файл со всеми результатами. Бэкап:

```bash
docker run --rm -v vpn-prober_coordinator-data:/data -v $PWD:/backup alpine \
  tar -czf /backup/coordinator-$(date +%F).tgz -C /data .
```

## Обновление

```bash
git pull
docker compose build
docker compose up -d
```

## Удаление

```bash
docker compose down -v
```

Volume `coordinator-data` будет удалён вместе со всеми результатами — забирай
бэкап заранее.

## Траблшутинг

| Симптом | Что делать |
| --- | --- |
| `engine_error: sing-box did not open socks port` | URL неправильный или сервер недоступен. Перепроверь руками: `sing-box check -c /tmp/...config.json`. |
| Все ссылки `parse_error` | Проверь, что URL не обёрнут в кавычки/префиксы — в `links.txt` должна быть только сама ссылка, по одной на строку. |
| OpenVPN: `engine_error: openvpn tunnel did not come up` | В контейнере должны быть `NET_ADMIN` и `/dev/net/tun` (см. docker-compose.yml). На bare metal нужен root. |
| Координатор 401 при `POST /api/v1/jobs` | Используй именно `COORDINATOR_ADMIN_TOKEN`, а не `COORDINATOR_API_TOKENS`. |
| Пробер видит 401 на регистрации | Его токен не входит в `COORDINATOR_API_TOKENS` координатора (список через запятую). |
| `ssr://` помечается unsupported | Sing-box не поддерживает SSR нативно; нужен отдельный `ssr-local` — на дорожной карте. |
