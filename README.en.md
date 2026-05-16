# vpn-prober (English summary)

Distributed VPN/proxy prober.  Takes connection URLs as input, brings up a
local SOCKS5 proxy through the requested protocol, fetches a list of test
sites through it and reports results to a central coordinator.  No
subscription handling — only direct connection links.

See [README.md](./README.md) for the full Russian-language guide.  A short
English version follows.

## Layout

```
prober/        — worker service (FastAPI + sing-box + openvpn engines)
  parsers/     — one file per protocol URL scheme
  engines/     — sing-box & openvpn process drivers
coordinator/   — central server (FastAPI + SQLite + HTML dashboard)
tests/         — pure-python parser tests
scripts/       — install-singbox, submit-job CLIs
docker-compose.yml
```

## Quick start (Docker)

```bash
cp .env.example .env  # set COORDINATOR_API_TOKENS / COORDINATOR_ADMIN_TOKEN
docker compose up -d --build

# Open: http://localhost:8080/dashboard?token=<ADMIN>
# Submit a job:
echo 'ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443#demo' > links.txt
python scripts/submit_job.py \
  --coordinator http://localhost:8080 \
  --token "<ADMIN>" \
  --links-file links.txt \
  --urls https://www.google.com https://www.cloudflare.com
```

## Supported URL schemes

`ss://`, `ssr://`, `vmess://`, `vless://` (XTLS + Reality), `trojan://`,
`trojan-go://`, `hysteria://`, `hysteria2://`, `hy2://`, `tuic://`,
`socks(4|4a|5|5h)://`, `httpproxy://`, `httpsproxy://`, `naive+https://`,
`wireguard://`, `wg://`, `anytls://`, `openvpn://`.

## Scaling out

Copy the `prober-1` service in `docker-compose.yml`, bump the name, and add
its token to `COORDINATOR_API_TOKENS`.  Probers can also live on entirely
separate machines as long as they can reach the coordinator over HTTP(S).

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## License

MIT.
