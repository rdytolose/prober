"""URL parser smoke tests.  These cover the surface shape of each protocol
URL; they don't actually open network connections."""

from __future__ import annotations

import base64
import json

import pytest

from prober.parsers import ParseError, parse


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def test_unsupported_raises():
    with pytest.raises(ParseError):
        parse("xyzzy://nope")


def test_ss_sip002():
    url = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443#tag"
    link = parse(url)
    assert link.protocol == "shadowsocks"
    assert link.server == "example.com"
    assert link.port == 443
    assert link.outbound["method"] == "aes-256-gcm"
    assert link.outbound["password"] == "password"
    assert link.remark == "tag"


def test_ss_sip002_plain_userinfo():
    # Plain method:password without base64.
    url = "ss://aes-128-gcm:secret@host.example:8388"
    link = parse(url)
    assert link.outbound["method"] == "aes-128-gcm"
    assert link.outbound["password"] == "secret"


def test_ss_legacy():
    inner = "aes-256-gcm:pwd@example.com:8388"
    url = "ss://" + _b64(inner) + "#legacy"
    link = parse(url)
    assert link.outbound["method"] == "aes-256-gcm"
    assert link.outbound["password"] == "pwd"
    assert link.port == 8388
    assert link.remark == "legacy"


def test_ssr():
    pwd_b64 = _b64("hunter2")
    body = f"host.example:8443:auth_aes128_md5:aes-256-cfb:tls1.2_ticket_auth:{pwd_b64}"
    qs = "?obfsparam=&protoparam=&remarks=" + _b64("hello") + "&group="
    url = "ssr://" + _b64(body + "/" + qs)
    link = parse(url)
    assert link.protocol == "shadowsocksr"
    assert link.outbound["method"] == "aes-256-cfb"
    assert link.outbound["password"] == "hunter2"
    assert link.remark == "hello"


def test_vmess_json():
    payload = {
        "v": "2", "ps": "node-de", "add": "1.2.3.4", "port": "443", "id": "uuid-x",
        "aid": "0", "net": "ws", "type": "none", "host": "cdn.example",
        "path": "/ws", "tls": "tls", "sni": "cdn.example",
    }
    url = "vmess://" + _b64(json.dumps(payload))
    link = parse(url)
    assert link.protocol == "vmess"
    assert link.server == "1.2.3.4"
    assert link.port == 443
    assert link.outbound["uuid"] == "uuid-x"
    assert link.outbound["transport"]["type"] == "ws"
    assert link.outbound["tls"]["enabled"] is True


def test_vmess_uri():
    url = "vmess://uuid-x@host.example:443?type=ws&path=%2Fws&host=cdn.example&security=tls&aid=0#tag"
    link = parse(url)
    assert link.outbound["uuid"] == "uuid-x"
    assert link.outbound["transport"]["type"] == "ws"
    assert link.outbound["transport"]["path"] == "/ws"
    assert link.outbound["tls"]["enabled"] is True


def test_vless_reality():
    url = (
        "vless://uuid-x@host.example:443?"
        "type=tcp&security=reality&pbk=PUBKEY&sid=abcd&sni=www.cloudflare.com&fp=chrome&flow=xtls-rprx-vision#node"
    )
    link = parse(url)
    assert link.protocol == "vless"
    assert link.outbound["flow"] == "xtls-rprx-vision"
    assert link.outbound["tls"]["reality"]["public_key"] == "PUBKEY"
    assert link.outbound["tls"]["utls"]["fingerprint"] == "chrome"


def test_trojan_ws():
    url = "trojan://pwd@host.example:443?sni=host.example&type=ws&path=%2Fwss#tag"
    link = parse(url)
    assert link.protocol == "trojan"
    assert link.outbound["password"] == "pwd"
    assert link.outbound["transport"]["type"] == "ws"
    assert link.outbound["transport"]["path"] == "/wss"


def test_hysteria2():
    url = "hysteria2://pwd@host.example:443?sni=host.example&insecure=0&obfs=salamander&obfs-password=xx#node"
    link = parse(url)
    assert link.protocol == "hysteria2"
    assert link.outbound["password"] == "pwd"
    assert link.outbound["obfs"]["type"] == "salamander"


def test_hy2_alias():
    url = "hy2://pwd@host.example:443"
    link = parse(url)
    assert link.protocol == "hysteria2"


def test_hysteria_v1():
    url = "hysteria://host.example:443?upmbps=50&downmbps=200&auth=secret&peer=host.example#h1"
    link = parse(url)
    assert link.protocol == "hysteria"
    assert link.outbound["auth_str"] == "secret"
    assert link.outbound["up_mbps"] == 50


def test_tuic():
    url = "tuic://uuid:pwd@host.example:443?congestion_control=bbr&alpn=h3&sni=host.example#t"
    link = parse(url)
    assert link.protocol == "tuic"
    assert link.outbound["uuid"] == "uuid"
    assert link.outbound["password"] == "pwd"
    assert link.outbound["tls"]["alpn"] == ["h3"]


def test_socks5():
    url = "socks5://user:pass@host.example:1080#s"
    link = parse(url)
    assert link.protocol == "socks5"
    assert link.outbound["version"] == "5"
    assert link.outbound["username"] == "user"
    assert link.outbound["password"] == "pass"


def test_https_proxy():
    url = "httpsproxy://user:pass@proxy.example:8443"
    link = parse(url)
    assert link.protocol == "https"
    assert link.outbound["tls"]["enabled"] is True
    assert link.outbound["username"] == "user"


def test_wireguard():
    url = (
        "wireguard://aGVsbG8=@host.example:51820?"
        "publickey=ZHNk&address=10.13.13.2%2F32&mtu=1280&reserved=1,2,3#wg"
    )
    link = parse(url)
    assert link.protocol == "wireguard"
    assert link.outbound["mtu"] == 1280
    assert link.outbound["local_address"] == ["10.13.13.2/32"]
    assert link.outbound["reserved"] == [1, 2, 3]


def test_anytls():
    url = "anytls://pwd@host.example:443?sni=host.example#x"
    link = parse(url)
    assert link.protocol == "anytls"
    assert link.outbound["password"] == "pwd"


def test_naive():
    url = "naive+https://user:pass@host.example:443?sni=host.example#n"
    link = parse(url)
    assert link.protocol == "naive"
    assert link.outbound["username"] == "user"
    assert link.outbound["password"] == "pass"
    assert link.outbound["tls"]["enabled"] is True


def test_openvpn_inline():
    cfg = "client\nremote vpn.example 1194\nproto udp\n"
    url = "openvpn://" + _b64(cfg) + "#ovpn"
    link = parse(url)
    assert link.protocol == "openvpn"
    assert link.outbound["config_text"].startswith("client")
    assert link.server == "vpn.example"
    assert link.port == 1194


def test_singbox_config_shape():
    """Round-trip a parsed link through the singbox config builder."""
    from prober.engines.singbox import build_config

    link = parse("ss://aes-128-gcm:secret@host.example:8388")
    cfg = build_config(link, local_socks_port=10808)
    assert cfg["inbounds"][0]["listen_port"] == 10808
    assert cfg["outbounds"][0]["server"] == "host.example"
    assert cfg["route"]["final"] == "proxy"
