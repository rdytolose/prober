# Установка с нуля на двух VPS (Ubuntu 22.04)

Этот гайд проводит тебя от свежесозданных VPS до работающей системы:
- **Сервер A** — главный координатор. Должен быть доступен из интернета по
  HTTPS. Желательно иметь домен (например, `coordinator.example.com`).
- **Сервер B** — пробер. Достаточно SSH-доступа; ничего наружу слушать не будет.

Команды выполняй точно как написано, под обычным пользователем (НЕ под root)
с правом `sudo`. Если у тебя под root — ниже первый раздел показывает,
как создать пользователя.

> Все плейсхолдеры в `<угловых скобках>` — это значения, которые ты
> подставишь сам. Например, `<DOMAIN>` → `coordinator.example.com`.

---

## ⚡ Быстрый путь — одной командой через `scripts/install.sh`

Если хочешь без ручных шагов — на каждом VPS после распаковки архива
запусти один скрипт. Он сам поставит Docker, настроит ufw, сгенерирует
токены, поднимет сервис и в конце напечатает дашборд + команду установки
для второго сервера.

```bash
# Один раз на ЛОКАЛЬНОЙ машине: положи код на каждый VPS.
scp vpn-prober.tar.gz vpn@<IP-A>:~
scp vpn-prober.tar.gz vpn@<IP-B>:~

# СЕРВЕР A (координатор):
ssh vpn@<IP-A>
mkdir -p ~/code && cd ~/code && tar -xzf ~/vpn-prober.tar.gz && cd vpn-prober
bash scripts/install.sh --role coordinator \
    --domain coordinator.example.com \
    --email you@example.com

# СЕРВЕР B (пробер):  скрипт на сервере A напечатает точную команду,
# скопируй её прямо из терминала, например:
ssh vpn@<IP-B>
mkdir -p ~/code && cd ~/code && tar -xzf ~/vpn-prober.tar.gz && cd vpn-prober
bash scripts/install.sh --role prober \
    --prober-name de-1 \
    --coordinator-url https://coordinator.example.com \
    --prober-token <TOKEN-ИЗ-ВЫВОДА-СЕРВЕРА-A>
```

Полезные флаги:

| Флаг | Что делает |
| --- | --- |
| `--help` | Показать все опции скрипта. |
| `--no-tls` | (только координатор) Поднять без Caddy/HTTPS на `:8080`. Только для теста. |
| `--overwrite-env` | Перезаписать существующий `.env` (по умолчанию скрипт его сохраняет). |
| `--yes` | Без интерактивных вопросов (все параметры должны быть переданы аргументами). |

> ⚠️ DNS-запись (`<DOMAIN>` → IP сервера A) ты всё равно должен создать
> заранее: скрипт сам это сделать не может. См. Шаг A1 ниже.

Если что-то пошло не так в автоматическом режиме — можно всё то же
самое сделать **руками по шагам ниже**, чтобы понять, где именно проблема.

---

## Что тебе понадобится перед началом

| Что | Зачем |
| --- | --- |
| Два VPS с Ubuntu 22.04 | Сервер A (координатор) и Сервер B (пробер). Минимум 1 GB RAM / 1 vCPU. |
| Доменное имя | Чтобы получить TLS-сертификат для координатора. Если домена нет — см. раздел «Без домена» в конце. |
| A-запись DNS | `<DOMAIN>` → IP сервера A. Подожди ~10 минут после изменения, чтобы DNS прорезолвился. |
| SSH-ключ | Для входа на оба сервера без пароля. Если ещё нет: `ssh-keygen -t ed25519` локально. |
| Архив с кодом | `vpn-prober.tar.gz` (присылал отдельным сообщением) либо `git clone …`. |

---

## ЧАСТЬ I. Подготовка ОБОИХ серверов (выполняется на каждом)

Все шаги в этом разделе делай **на сервере A**, потом полностью повтори
**на сервере B**.

### Шаг 1. Зайди по SSH

С локальной машины:

```bash
ssh root@<IP>
```

Если у тебя сразу есть обычный пользователь — используй его и пропусти шаг 2.

### Шаг 2. (если зашёл под root) Создай не-рутового пользователя

```bash
# создаём пользователя `vpn` и добавляем в sudo
adduser vpn
usermod -aG sudo vpn

# копируем твой SSH-ключ из root в нового пользователя
rsync --archive --chown=vpn:vpn ~/.ssh /home/vpn

# проверяем — отдельным окном с локальной машины:
#   ssh vpn@<IP>
# должно пустить без пароля.  Только после этого продолжай.

# выходим из root
exit
```

Дальше всегда заходи как `ssh vpn@<IP>` и используй `sudo`.

### Шаг 3. Обнови систему

```bash
sudo apt-get update
sudo apt-get -y upgrade
```

### Шаг 4. Поставь Docker и docker-compose-plugin

Это официальные команды Docker для Ubuntu 22.04. Скопируй блоком, не по
одной строке:

```bash
# Зависимости
sudo apt-get -y install ca-certificates curl gnupg

# Ключ от Docker репозитория
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Сам репозиторий
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

# Установка
sudo apt-get update
sudo apt-get -y install docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# Чтобы запускать docker без sudo
sudo usermod -aG docker $USER
```

**Выйди из SSH-сессии и зайди заново** (`exit`, потом `ssh vpn@<IP>`) —
групповое членство применится только после нового логина.

Проверь:

```bash
docker version
docker compose version
```

Должны показать версии без ошибок.

### Шаг 5. Настрой firewall (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH      # порт 22

# На координаторе (сервер A) откроем 80 и 443 — для HTTPS и Let's Encrypt.
# На пробере (сервер B) ничего больше открывать не нужно.

sudo ufw enable
sudo ufw status
```

Сразу проверь, что SSH ещё работает (открой второе окно и зайди ещё раз).
Если случайно отрезался — у большинства провайдеров есть веб-консоль для
аварийного восстановления.

### Шаг 6. (опционально) Закрой root-логин по SSH

```bash
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl reload ssh
```

Теперь зайти можно только под своим пользователем и только по ключу.

### Шаг 7. Создай рабочую папку и положи туда код

Самый простой путь — `scp` архив с локальной машины:

```bash
# На локальной машине:
scp vpn-prober.tar.gz vpn@<IP>:~

# На сервере:
mkdir -p ~/code && cd ~/code
tar -xzf ~/vpn-prober.tar.gz
cd vpn-prober
ls
```

Альтернативно, если ты залил репозиторий на свой GitHub:

```bash
sudo apt-get -y install git
git clone https://github.com/<твой-юзер>/vpn-prober.git
cd vpn-prober
```

> С этого момента **сервер A и сервер B расходятся**. Дальше делай разные
> вещи на каждом.

---

## ЧАСТЬ II. Сервер A — установка координатора

### Шаг A1. Настрой DNS

В админке твоего DNS-провайдера (Cloudflare, Namecheap, etc.) добавь
A-запись:

```
coordinator.example.com   A   <IP сервера A>   TTL: 3600
```

Подожди 5–10 минут. Проверь:

```bash
dig +short coordinator.example.com
# должна выйти строка с IP твоего VPS
```

Если используешь Cloudflare — поставь **«DNS only» (серое облачко)**,
а не «Proxied»: иначе Let's Encrypt не сможет выдать сертификат напрямую.

### Шаг A2. Сгенерируй токены

На сервере:

```bash
echo "PROBER:   $(openssl rand -hex 24)"
echo "ADMIN:    $(openssl rand -hex 32)"
```

Запиши себе оба значения (потом нужны).

### Шаг A3. Заполни `.env` для координатора

```bash
cd ~/code/vpn-prober/deploy/coordinator
cp .env.example .env
nano .env
```

Поставь в `.env`:

```
DOMAIN=coordinator.example.com
ACME_EMAIL=you@example.com
COORDINATOR_API_TOKENS=<PROBER-TOKEN-СГЕНЕРИРОВАННЫЙ-ВЫШЕ>
COORDINATOR_ADMIN_TOKEN=<ADMIN-TOKEN-СГЕНЕРИРОВАННЫЙ-ВЫШЕ>
```

Сохрани (`Ctrl+O`, `Enter`, `Ctrl+X` в nano) и закрой.

```bash
chmod 600 .env   # никому, кроме тебя, не читать
```

### Шаг A4. Подними координатор и Caddy

```bash
cd ~/code/vpn-prober/deploy/coordinator
docker compose up -d --build
```

Первая сборка займёт 1–2 минуты (Docker скачает базовые образы и поставит
Python-пакеты).

Проверь, что оба контейнера запущены:

```bash
docker compose ps
# должны быть статусы Up для coordinator и caddy
```

Посмотри логи Caddy — там увидишь, как он получает TLS-сертификат:

```bash
docker compose logs caddy
```

Должна быть строка вроде:

```
certificate obtained successfully ... subject coordinator.example.com
```

Если выходит ошибка — обычно это: (1) DNS ещё не обновился — подожди 10 минут;
(2) порты 80/443 закрыты файрволом — проверь `sudo ufw status`.

### Шаг A5. Открой дашборд

В браузере на локальной машине:

```
https://coordinator.example.com/dashboard?token=<ADMIN-TOKEN>
```

Должна открыться страница «VPN Prober — Dashboard». Сейчас в ней:
- «No probers have registered yet» — нормально, мы ещё не подняли пробер.
- «No results yet» — тоже норма.

Если страница пишет «Pass `?token=…`» — ты передал не тот токен.

### Шаг A6. Проверь, что HTTPS работает

```bash
curl https://coordinator.example.com/health
# ожидаемый ответ: {"status":"ok"}
```

Если выходит ошибка сертификата — попробуй через минуту: иногда Caddy ещё
не успел применить сертификат.

> На этом сервер A готов. Запиши себе `<DOMAIN>` и оба токена — они нужны
> для сервера B.

---

## ЧАСТЬ III. Сервер B — установка пробера

Заходишь на сервер B по SSH (`ssh vpn@<IP-B>`). Шаги I.1–I.7 ты уже
сделал заранее (если нет — выполни сейчас).

### Шаг B1. Заполни `.env` для пробера

```bash
cd ~/code/vpn-prober/deploy/prober
cp .env.example .env
nano .env
```

В `.env`:

```
PROBER_NAME=de-1
COORDINATOR_URL=https://coordinator.example.com
PROBER_API_TOKEN=<PROBER-TOKEN-С-СЕРВЕРА-A>
```

- `PROBER_NAME` — любая уникальная строка. Удобно ставить страну/номер
  (`de-1`, `us-2`, `sg-1`).
- `COORDINATOR_URL` — обязательно с `https://`.
- `PROBER_API_TOKEN` — **тот же** PROBER-токен, который ты прописал на
  сервере A в `COORDINATOR_API_TOKENS`.

```bash
chmod 600 .env
```

### Шаг B2. Подними пробер

```bash
cd ~/code/vpn-prober/deploy/prober
docker compose up -d --build
```

Снова 1–2 минуты — Docker скачает sing-box и поставит зависимости.

### Шаг B3. Проверь, что пробер зарегистрировался

```bash
docker compose logs --tail=30 prober
```

Должна появиться строка:

```
INFO ... registered with coordinator at https://coordinator.example.com
```

Если есть `401 Unauthorized` — токен не совпадает. Если `connect: connection
refused` — DNS не резолвится или порт 443 закрыт. Если `ssl: ...` — TLS не
готов; проверь сертификат на сервере A.

Заодно открой дашборд:

```
https://coordinator.example.com/dashboard?token=<ADMIN-TOKEN>
```

Теперь в разделе «Probers» должен появиться `de-1` с временем «Last seen».

---

## ЧАСТЬ IV. Первая задача — проверь, что всё работает

### Вариант 1 — через скрипт submit_job.py (любой компьютер с Python)

На локальной машине:

```bash
cd ~/Downloads/vpn-prober   # папка с распакованным архивом
echo 'ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443#demo' > links.txt

python3 scripts/submit_job.py \
  --coordinator https://coordinator.example.com \
  --token "<ADMIN-TOKEN>" \
  --links-file links.txt \
  --urls https://www.google.com https://www.cloudflare.com \
  --label "first-test"
```

Скрипт вернёт `{"id": "<uuid>", "status": "pending"}`.

### Вариант 2 — голым curl

```bash
curl -X POST https://coordinator.example.com/api/v1/jobs \
  -H "Authorization: Bearer <ADMIN-TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "links": ["ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443#demo"],
    "test_urls": ["https://www.google.com"],
    "label": "first-test"
  }'
```

### Проверь в дашборде

Через 5–15 секунд (зависит от таймаутов и того, отвечает ли сервер по
ссылке) обнови страницу `https://coordinator.example.com/dashboard?token=…`:

- В разделе «Recent jobs» будет твой джоб со статусом `done`.
- Клик по ID откроет страницу job — там будет таблица исходов с
  IP/страной/HTTP-статусом каждого тест-URL.

Демо-ссылка из примера не работает (сервер `example.com` не Shadowsocks),
поэтому увидишь `engine_error` или `all_sites_failed`. Это **нормально**
— главное, что пайплайн прошёл от начала до конца. Подставь рабочую ссылку
— и в дашборде увидишь IP и страну выхода + время загрузки сайтов.

---

## ЧАСТЬ V. Что делать дальше

### Добавить ещё пробер в другой стране

Купи третий VPS (например, в Сингапуре). На сервере A добавь второй
токен в `.env`:

```
COORDINATOR_API_TOKENS=<tok-de>,<tok-sg>
```

Перезапусти координатор, чтобы он подхватил новые токены:

```bash
cd ~/code/vpn-prober/deploy/coordinator
docker compose up -d
```

(не пугайся — это нулевой даунтайм, контейнер пересоздастся за ~2 секунды).

На сингапурском VPS выполни всю **ЧАСТЬ I** (подготовка), потом **ЧАСТЬ III**
(пробер) — только в `.env` поставь `PROBER_NAME=sg-1` и
`PROBER_API_TOKEN=<tok-sg>`.

### Бэкапы базы координатора

На сервере A — крон каждые 6 часов:

```bash
sudo crontab -e
# добавь:
0 */6 * * * docker run --rm \
  -v vpn-prober_coordinator-data:/data \
  -v /home/vpn/backups:/backup \
  alpine tar -czf /backup/coord-$(date +\%F_\%H).tgz -C /data .
```

И каждую ночь синкай папку `/home/vpn/backups` в S3/Backblaze/куда удобно.

### Обновление кода

Когда меняешь код на стороне разработки — повторно `scp` архив (или
`git pull`, если из репы), потом:

```bash
cd ~/code/vpn-prober/deploy/coordinator   # или deploy/prober
docker compose build
docker compose up -d
```

Все volume сохранятся, данные не пропадут.

### Просмотр логов в реальном времени

```bash
# Координатор
cd ~/code/vpn-prober/deploy/coordinator
docker compose logs -f

# Пробер
cd ~/code/vpn-prober/deploy/prober
docker compose logs -f
```

---

## Без домена (для теста; не делай так в проде)

Если домена пока нет — координатор можно запустить **по голому HTTP**.
Это значит, что токены пойдут по сети открытым текстом — для прода не
годится.

На сервере A в `deploy/coordinator/docker-compose.yml` **временно**
убери сервис `caddy`, а сервису `coordinator` добавь:

```yaml
    ports:
      - "8080:8080"
```

Открой 8080 в файрволе: `sudo ufw allow 8080`.

В `.env` пробера на сервере B поставь:

```
COORDINATOR_URL=http://<IP-сервера-A>:8080
```

Дашборд: `http://<IP-сервера-A>:8080/dashboard?token=<ADMIN>`.

Когда заведёшь домен — верни Caddy и сделай `COORDINATOR_URL=https://…`.

---

## Возможные ошибки и что с ними делать

| Симптом | Решение |
| --- | --- |
| `docker: permission denied` | Ты не вышел из SSH после `usermod -aG docker`. Выйди и зайди заново. |
| Caddy: `obtain certificate ... no IP address found` | DNS ещё не обновился. Проверь `dig +short <DOMAIN>` — должен показать IP. Подожди 10 минут. |
| Caddy: `connection timed out` при ACME | Порт 80 или 443 закрыт. `sudo ufw status` → открой обоих. |
| Пробер: `401 Unauthorized` в логах | Токен в `PROBER_API_TOKEN` не совпадает с одним из `COORDINATOR_API_TOKENS` (внимательно, через запятую без пробелов). |
| Пробер: `connect: connection refused` | URL координатора неправильный или 443/80 закрыт на сервере A. |
| Дашборд показывает «Pass ?token=...» | Токен в URL неправильный или забыл его передать. |
| `docker compose ps` показывает `Restarting` | Что-то падает на старте. Смотри `docker compose logs --tail=100 <service>`. |
| Пробер видит ссылку как `parse_error` | URL подключения неправильный. Проверь, что он не обрезан и не обёрнут в кавычки в `links.txt`. |
| Тест проходит, но `ok: false` со всеми сайтами | Ссылка валидная, но сам сервер недоступен. Попробуй другую ссылку. |

---

## Чек-лист «всё ли я сделал правильно»

- [ ] У меня обновлён Ubuntu (`sudo apt-get upgrade` сделан) на обоих серверах.
- [ ] Docker работает без sudo на обоих серверах.
- [ ] UFW настроен, SSH открыт, на координаторе открыты 80/443, на пробере — только SSH.
- [ ] DNS A-запись для `<DOMAIN>` указывает на IP сервера A и резолвится (`dig`).
- [ ] `https://<DOMAIN>/health` отвечает `{"status":"ok"}` с валидным TLS.
- [ ] Дашборд открывается с правильным токеном.
- [ ] В дашборде в разделе «Probers» виден мой пробер с актуальным «Last seen».
- [ ] Тестовый джоб прошёл (даже если внутри `ok: false` — главное, что джоб не висит в `pending`).
- [ ] Бэкап БД координатора настроен.
- [ ] `.env` файлы имеют права 600 и не закоммичены в git.

Если все галочки — поздравляю, у тебя production-ready пробер-кластер. 🎉
