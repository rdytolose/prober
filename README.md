# vpn-prober

Распределённый VPN/прокси-пробер. Принимает на вход ссылки-подключения,
поднимает локальный SOCKS5 через нужный протокол, прогоняет список сайтов
и отправляет результаты в центральный координатор. Без обработки подписок —
только прямые ссылки.

> Если предпочитаешь английский, см. [README.en.md](./README.en.md).

## Возможности

- **Модульная архитектура.** Парсеры протоколов, движки (sing-box / openvpn),
  тестер сайтов, FastAPI-сервис и координатор разнесены по отдельным модулям —
  добавить новый протокол = один файл-парсер + регистрация в `registry.py`.
- **Горизонтальное масштабирование.** Поднимаешь N контейнеров `prober`,
  каждый регистрируется у одного координатора и тянет задачи через REST.
- **Поддерживаемые протоколы.**
  - `ss://` (Shadowsocks SIP002 + legacy base64)
  - `ssr://` (ShadowsocksR — парсится; sing-box нативно не запускает, помечается как unsupported при отсутствии бинарника)
  - `vmess://` (V2RayN JSON и URI-форма; ws/grpc/h2/quic, TLS)
  - `vless://` (XTLS-Vision, Reality, ws/grpc/h2)
  - `trojan://`, `trojan-go://`
  - `hysteria://` (v1) и `hysteria2://` / `hy2://`
  - `tuic://` (v4/v5)
  - `socks://`, `socks4://`, `socks5://`, `socks5h://`
  - `httpproxy://`, `httpsproxy://`
  - `naive+https://`
  - `wireguard://` / `wg://`
  - `anytls://`
  - `openvpn://` (наш формат: `openvpn://BASE64(.ovpn)` или `openvpn://?url=<https://.../client.ovpn>`)
- **Метрики результата.** Видимый egress-IP, страна (ipinfo.io), HTTP-статус, размер
  ответа, латентность и время поднятия туннеля на каждую ссылку.
- **HTML-дашборд** на координаторе: drag-and-drop загрузка `.txt` со ссылками,
  ручной ввод, прогресс-бары с авто-обновлением, кнопка **Stop** для отмены
  работающей джобы, генерация токенов проберов прямо из UI.
- **Инкрементальные результаты** — пробер шлёт исходы батчами по 10 ссылок,
  дашборд показывает «X / N done · K ok · L fail» по ходу проверки.
- **Docker + docker-compose** для одной команды запуска. CLI-скрипты:
  `scripts/submit_job.py` (одна джоба), `scripts/split_and_submit.py` (большой
  файл → батчи по 500), `scripts/watch_job.py` (живой прогресс-бар в терминале).

## Архитектура

```
┌────────────────────────┐
│      Coordinator       │   FastAPI + SQLite + Jinja-дашборд
│  /api/v1/jobs          │   - принимает джобы от админа
│  /api/v1/jobs/next     │   - раздаёт задачи проберам
│  /api/v1/results       │   - сохраняет результаты
│  /dashboard            │   - HTML
└─────────▲──────┬───────┘
          │      │
   Bearer-токен │ (TLS — на твой реверс-прокси)
          │      ▼
   ┌──────┴───┐ ┌──────────┐  ┌──────────┐
   │ prober-1 │ │ prober-2 │… │ prober-N │
   └──────────┘ └──────────┘  └──────────┘
        │ sing-box / openvpn
        ▼
   локальный SOCKS5 :10808
        │
        ▼
   тест-URL'ы через httpx
```

Пробер на каждую ссылку:
1. Парсит URL в `ParsedLink` (нормализованная dataclass).
2. Подбирает движок (`sing-box` для большинства, `openvpn` для `openvpn://`).
3. Спавнит отдельный процесс sing-box с минимальным конфигом — inbound:mixed,
   outbound:proxy, route:final=proxy. Ждёт открытия SOCKS-порта.
4. Через `httpx` ходит на список тест-URL'ов и на ipinfo.io, измеряет латентность.
5. Глушит процесс, чистит tempdir, шлёт `LinkOutcome` на координатор.

Один пробер обслуживает ссылки **последовательно** (общий локальный SOCKS-порт).
Для параллелизма поднимай несколько контейнеров.

## Быстрый старт (Docker)

Требуется Docker 20.10+ и docker-compose v2. Для `openvpn://` контейнеру нужен `NET_ADMIN`
и `/dev/net/tun` (по умолчанию уже добавлены в `docker-compose.yml`).

```bash
git clone <this-repo> vpn-prober && cd vpn-prober

# 1. Сгенерируй токены и положи их в .env.
cp .env.example .env
# отредактируй COORDINATOR_API_TOKENS=<токен-для-проберов>
# и COORDINATOR_ADMIN_TOKEN=<токен-для-админки>

# 2. Поднимай.
docker compose up -d --build

# 3. Дашборд:
open "http://localhost:8080/dashboard?token=<COORDINATOR_ADMIN_TOKEN>"

# 4. Отправь первую задачу.
echo 'ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443#demo' > links.txt
python scripts/submit_job.py \
  --coordinator http://localhost:8080 \
  --token "<COORDINATOR_ADMIN_TOKEN>" \
  --links-file links.txt \
  --urls https://www.google.com https://www.youtube.com https://www.cloudflare.com \
  --label "first run"
```

Через несколько секунд джоб появится в дашборде со списком исходов и сырым JSON.

### Запуск нескольких проберов

Каждому пробер-контейнеру нужен свой `PROBER_NAME` и свой токен (или один общий,
но уникальные имена обязательны). Скопируй сервис `prober-1` в `docker-compose.yml`:

```yaml
  prober-2:
    extends:
      service: prober-1
    container_name: vpn-prober-2
    environment:
      PROBER_NAME: prober-2
      PROBER_API_TOKEN: "${PROBER_API_TOKEN_2:-changeme-token-2}"
    ports:
      - "8091:8090"
```

И добавь `changeme-token-2` в `COORDINATOR_API_TOKENS` координатора (список через запятую).

Распределить проберы по разным регионам: сборщик из этого же репо запускается на любой
машине, которой просто нужен сетевой доступ к координатору.

## Запуск без Docker

```bash
# Зависимости системы
sudo apt-get install -y openvpn microsocks  # openvpn опционален

# sing-box
sudo ./scripts/install-singbox.sh

# Python
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

# Координатор
COORDINATOR_API_TOKENS=token-1 COORDINATOR_ADMIN_TOKEN=admin python -m coordinator.main &

# Пробер
PROBER_NAME=local-1 COORDINATOR_URL=http://localhost:8080 PROBER_API_TOKEN=token-1 \
  python -m prober.main
```

## REST API

Все эндпоинты используют Bearer-токены (`Authorization: Bearer <token>`):

| Метод | Путь | Кто | Описание |
| --- | --- | --- | --- |
| `POST` | `/api/v1/probers/register` | пробер | Регистрация. Тело `{"name": "prober-1"}`. |
| `GET`  | `/api/v1/jobs/next` | пробер | Забрать следующий джоб. `204` если пусто. |
| `POST` | `/api/v1/results` | пробер | Прислать исходы. |
| `POST` | `/api/v1/jobs` | админ | Создать джоб `{"links":[...], "test_urls":[...], "label":"…"}`. |
| `GET`  | `/api/v1/jobs/{id}` | админ | Один джоб + все его исходы. |
| `GET`  | `/api/v1/probers` | админ | Список зарегистрированных проберов. |
| `GET`  | `/dashboard?token=…` | админ | HTML. |

Пример исхода (`LinkOutcome`):

```json
{
  "link": "vless://...",
  "protocol": "vless",
  "remark": "node-de",
  "server": "1.2.3.4",
  "port": 443,
  "ok": true,
  "error": null,
  "engine_startup_ms": 312,
  "meta": {"network": "ws", "security": "tls"},
  "tests": {
    "connectivity": {"ip": "5.6.7.8", "country": "DE", "error": null},
    "sites": [
      {"url": "https://google.com", "ok": true, "status": 200, "latency_ms": 412, "size_bytes": 14872, "error": null}
    ]
  }
}
```

## Тесты

```bash
pip install -e ".[dev]"
pytest -q
```

Покрытие — парсеры всех протоколов + smoke-тест построения конфига sing-box.

## Безопасность

- Все токены передаются в `Authorization: Bearer …`. Перед публикацией наружу
  поставь HTTPS-реверс-прокси (nginx/caddy/traefik) перед координатором.
- В дашборд токен передаётся через `?token=…`. На публичных серверах используй
  путь под basic-auth или приватную сеть.
- Не коммить `.env`. Используй `docker secrets` или менеджер секретов в проде.
- OpenVPN внутри контейнера требует `cap_add: NET_ADMIN` и `/dev/net/tun`. Если
  не нужен — убери эти строки из compose.

## Как добавить новый протокол

1. `prober/parsers/<name>.py` — функция `parse_<name>(url) -> ParsedLink`.
2. Зарегистрируй её префикс(ы) в `prober/parsers/registry.py`.
3. Если sing-box умеет этот outbound — всё. Если нет, добавь движок
   в `prober/engines/<name>.py` и зарегистрируй в `Orchestrator._engine_for`.
4. Добавь тест в `tests/test_parsers.py`.

## Лицензия

MIT.
