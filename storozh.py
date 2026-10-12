#!/usr/bin/env python3
"""Сторож сайта doctorpavlovskii.ru снаружи (GitHub Actions, раз в 10 минут).

Решение Ивана 12.10.2026 (вариант 3): если упадёт наш сервер rabota (Германия), сайт уходит
на страницу-заглушку на хостинге SpaceWeb. Сторож живёт не на сервере: умрёт сервер - сторож нет.

  сервер не отвечает 15 мин  -> Ивану «слежу»
  60 мин                     -> проверка из России тремя способами (хостинг SpaceWeb в Петербурге,
                                check-host.net, globalping.io)
     из России открывается   -> сбой связи, ничего не делаю
     из России лежит         -> ночью (23-08 Мадрид) заглушка сама, днём спрашиваю Ивана
     проверить не вышло      -> ночью через 90 мин простоя заглушка сама
  на заглушке: сервер 30 мин работает -> возвращаю сайт сам и пишу Ивану
  раз в день (будни, после 09:00) - самопроверка: проверка из России и сама заглушка живы.

Ручное: python3 storozh.py pokazat | na-zaglushku | na-server
Окружение: SWEB_LOGIN, SWEB_PASSWORD, TG_TOKEN, TG_CHAT, STATE (файл состояния).
"""
import json, os, socket, ssl, subprocess, sys, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

DOMAIN = "doctorpavlovskii.ru"
SERVER_IP = "2.31.62.117"
ZAGL_IP = "77.222.62.121"
PROBA_RU = "http://playsicru.temp.swtest.ru/cgi-bin/proverka.py"
MADRID = ZoneInfo("Europe/Madrid")
NOCH = (23, 8)
STATE = os.environ.get("STATE", "state.json")


def log(*a):
    print(datetime.now(MADRID).strftime("%d.%m %H:%M"), *a, flush=True)


def tg(text):
    try:
        data = json.dumps({"chat_id": os.environ["TG_CHAT"], "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % os.environ["TG_TOKEN"], data=data,
            headers={"Content-Type": "application/json"}), timeout=20)
        log("Ивану:", text.split("\n")[0])
    except Exception as e:
        log("telegram не принял:", type(e).__name__)


def curl_kod(url, ip):
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
                        "--resolve", "%s:443:%s" % (DOMAIN, ip), url], capture_output=True, text=True)
    return r.stdout.strip() or "000"


def server_zhiv():
    for _ in range(2):
        if curl_kod("https://%s/" % DOMAIN, SERVER_IP) == "200" and \
                curl_kod("https://%s/blog/api/health" % DOMAIN, SERVER_IP) == "200":
            return True
        time.sleep(10)
    return False


def zaglushka_ok():
    """(ok, дней до конца сертификата)."""
    kod = curl_kod("https://%s/" % DOMAIN, ZAGL_IP)
    dnej = None
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((ZAGL_IP, 443), timeout=20) as s:
            with ctx.wrap_socket(s, server_hostname=DOMAIN) as ss:
                konec = ssl.cert_time_to_seconds(ss.getpeercert()["notAfter"])
                dnej = int((konec - time.time()) / 86400)
    except Exception as e:
        log("сертификат заглушки:", type(e).__name__)
    return kod == "503" and dnej is not None, dnej


# --- проверка из России: True - лежит, False - открывается, None - не вышло -----------

def ru_sweb():
    try:
        d = json.load(urllib.request.urlopen(PROBA_RU, timeout=60))
        return not d["zhiv"]
    except Exception as e:
        log("хостинг SpaceWeb:", type(e).__name__)
        return None


def ru_checkhost():
    try:
        h = {"Accept": "application/json"}
        q = ("https://check-host.net/check-http?host=https://%s/blog/api/health&max_nodes=3"
             "&node=ru1.node.check-host.net&node=ru2.node.check-host.net&node=ru3.node.check-host.net" % DOMAIN)
        rid = json.load(urllib.request.urlopen(urllib.request.Request(q, headers=h), timeout=30))["request_id"]
        time.sleep(25)
        res = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://check-host.net/check-result/" + rid, headers=h), timeout=30))
        otvety = [v for v in res.values() if v]
        if len(otvety) < 2:
            return None
        return sum(1 for v in otvety if v[0] and v[0][0] == 1 and str(v[0][3]) == "200") == 0
    except Exception as e:
        log("check-host:", type(e).__name__, str(e)[:60])
        return None


def ru_globalping():
    try:
        body = json.dumps({"type": "http", "target": DOMAIN, "locations": [{"country": "RU", "limit": 3}],
                           "measurementOptions": {"protocol": "HTTPS", "request": {"path": "/blog/api/health"}}}).encode()
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://api.globalping.io/v1/measurements", data=body,
            headers={"Content-Type": "application/json"}), timeout=30))
        for _ in range(12):
            time.sleep(5)
            m = json.load(urllib.request.urlopen("https://api.globalping.io/v1/measurements/" + r["id"], timeout=30))
            if m.get("status") == "finished":
                break
        kody = [x["result"].get("statusCode") for x in m.get("results", []) if x.get("result")]
        if len(kody) < 2:
            return None
        return sum(1 for k in kody if k == 200) == 0
    except Exception as e:
        log("globalping:", type(e).__name__, str(e)[:60])
        return None


def iz_rossii():
    """Сводка трёх способов: 'lezhit' | 'otkryvaetsya' | None, и сколько способов ответило."""
    otv = {"SpaceWeb": ru_sweb(), "check-host": ru_checkhost(), "globalping": ru_globalping()}
    log("из России:", otv)
    est = [v for v in otv.values() if v is not None]
    if any(v is False for v in est):
        return "otkryvaetsya", len(est)
    if est:
        return "lezhit", len(est)
    return None, 0


# --- адрес сайта у SpaceWeb ----------------------------------------------------------

def sweb(path, method, params, tok=None):
    h = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    body = json.dumps({"jsonrpc": "2.0", "version": "1.0", "method": method, "params": params}).encode()
    d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.sweb.ru/" + path, data=body, headers=h),
                                         timeout=30))
    if "error" in d:
        raise RuntimeError("SpaceWeb %s: %s" % (method, d["error"].get("message")))
    return d["result"]


def sweb_tok():
    return sweb("notAuthorized/", "getToken", {"login": os.environ["SWEB_LOGIN"], "password": os.environ["SWEB_PASSWORD"]})


def zapisi(tok):
    out = {}
    for x in sweb("domains/dns", "info", {"domain": DOMAIN}, tok):
        if x.get("category") == "zoneMain" and x.get("type") == "A" and x.get("name") in ("", "@", "www"):
            out["www" if x["name"] == "www" else "@"] = x
    return out


def rezhim(tok):
    ip = zapisi(tok)["@"]["value"]
    return {SERVER_IP: "server", ZAGL_IP: "zaglushka"}.get(ip, "drugoj:" + ip)


def postavit(tok, ip):
    for k, rec in zapisi(tok).items():
        if rec["value"] != ip:
            sweb("domains/dns", "editMain", {"domain": DOMAIN, "action": "edit", "index": rec["index"],
                                             "type": "A", "value": ip}, tok)
    seichas = {k: r["value"] for k, r in zapisi(tok).items()}
    if set(seichas.values()) != {ip}:
        raise RuntimeError("SpaceWeb принял правку, но записи показывают %s" % seichas)
    log("адрес сайта ->", ip)


# --- решения -------------------------------------------------------------------------

def minut(s, kl):
    return int((time.time() - s[kl]) / 60)


def chas(n):
    return "%d мин" % n if n < 120 else "%d ч %d мин" % (n // 60, n % 60)


def noch(t):
    return t.hour >= NOCH[0] or t.hour < NOCH[1]


def na_zaglushku(tok, s, prichina):
    ok, dnej = zaglushka_ok()
    if not ok:
        if not s.get("skazal_zagl_slomana"):
            tg("🔴 Сайт лежит, а заглушка на хостинге SpaceWeb сама не отвечает - переключать некуда. "
               "Напишите Клоду «сайт лежит, заглушка не отвечает».")
            s["skazal_zagl_slomana"] = True
        return
    postavit(tok, ZAGL_IP)
    s.update(na_zaglushke_s=time.time(), podnyalsya_s=None)
    tg("🔴 %s Включил заглушку: через ~10 минут посетители увидят страницу с кнопками на бота, канал и запись. "
       "Когда сервер проработает 30 минут, верну сайт сам." % prichina)


def prohod(s):
    t = datetime.now(MADRID)
    tok = sweb_tok()
    rz = rezhim(tok)
    zhiv = server_zhiv()
    log("режим", rz, "сервер", "жив" if zhiv else "НЕ отвечает")

    if rz == "server":
        if zhiv:
            if s.get("lezhit_s") and s.get("preduprezhden"):
                tg("🟢 Сайт снова отвечает (лежал %s). Ничего не переключал." % chas(minut(s, "lezhit_s")))
            for k in ("lezhit_s", "preduprezhden", "rossiya_s", "skazal_svyaz", "skazal_net_proverki",
                      "sprosil", "skazal_zagl_slomana"):
                s.pop(k, None)
            return
        s.setdefault("lezhit_s", time.time())
        m = minut(s, "lezhit_s")
        if m >= 15 and not s.get("preduprezhden"):
            tg("🟠 Сайт не отвечает %s (сервер в Германии). Слежу. Если пролежит час: ночью (23-08) включу "
               "заглушку сам, днём спрошу Вас." % chas(m))
            s["preduprezhden"] = True
        if m < 60 or time.time() - s.get("rossiya_s", 0) < 15 * 60:
            return
        s["rossiya_s"] = time.time()
        r, skolko = iz_rossii()
        if r == "otkryvaetsya":
            if not s.get("skazal_svyaz"):
                tg("ℹ️ Снаружи сервер не виден %s, но из России сайт открывается - это сбой связи, не сервер. "
                   "Ничего не переключаю." % chas(m))
                s["skazal_svyaz"] = True
        elif r == "lezhit":
            if noch(t):
                na_zaglushku(tok, s, "Сайт лежит %s, из России тоже (ответили %d из 3 проверок)." % (chas(m), skolko))
            elif not s.get("sprosil"):
                tg("🔴 Сайт лежит %s (проверено из России). Заглушка готова. Чтобы включить, напишите Клоду "
                   "«включай заглушку». Если не ответите до 23:00, ночью включу сам." % chas(m))
                s["sprosil"] = True
        else:
            if noch(t) and m >= 90:
                na_zaglushku(tok, s, "Сайт лежит %s, проверить из России не удалось ни одним способом." % chas(m))
            elif not s.get("skazal_net_proverki"):
                tg("🟠 Сайт лежит %s, проверить из России не удалось. Ночью через 90 минут простоя включу "
                   "заглушку сам. Днём - напишите Клоду «включай заглушку», если сайт у Вас не открывается." % chas(m))
                s["skazal_net_proverki"] = True
        return

    if rz == "zaglushka":
        if not zhiv:
            s["podnyalsya_s"] = None
            return
        if not s.get("podnyalsya_s"):
            s["podnyalsya_s"] = time.time()
        if minut(s, "podnyalsya_s") >= 30:
            postavit(tok, SERVER_IP)
            dolgo = chas(minut(s, "na_zaglushke_s")) if s.get("na_zaglushke_s") else "?"
            tg("🟢 Сервер работает 30 минут без сбоев - вернул сайт с заглушки (заглушка висела %s)." % dolgo)
            s.clear()
        return
    log("адрес сайта указывает на", rz, "- это ручная настройка, ничего не трогаю")


def samoproverka(s):
    t = datetime.now(MADRID)
    segodnya = t.strftime("%Y-%m-%d")
    if s.get("samoproverka") == segodnya or t.hour < 9 or t.weekday() >= 5:
        return
    s["samoproverka"] = segodnya
    bedy = []
    rab = {"SpaceWeb": ru_sweb(), "check-host": ru_checkhost(), "globalping": ru_globalping()}
    slomany = [k for k, v in rab.items() if v is None]
    if len(slomany) >= 2:
        bedy.append("проверка из России работает только %d из 3 способами (не отвечают: %s)"
                    % (3 - len(slomany), ", ".join(slomany)))
    ok, dnej = zaglushka_ok()
    if not ok:
        bedy.append("заглушка на хостинге SpaceWeb не отвечает как надо")
    elif dnej < 14:
        bedy.append("сертификат заглушки кончается через %d дн." % dnej)
    log("самопроверка:", rab, "заглушка", ok, dnej)
    if bedy:
        tg("⚠️ Сторож сайта, утренняя самопроверка: " + "; ".join(bedy) +
           ". Сайт работает, это запасной путь. Напишите Клоду «почини сторожа сайта».")


def main():
    try:
        s = json.load(open(STATE))
    except (OSError, ValueError):
        s = {}
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prohod"
    if cmd == "pokazat":
        tok = sweb_tok()
        log("режим", rezhim(tok), "сервер жив", server_zhiv(), "заглушка", zaglushka_ok(), "состояние", s)
        return
    if cmd == "na-zaglushku":
        tok = sweb_tok()
        na_zaglushku(tok, s, "По команде Ивана.")
    elif cmd == "na-server":
        postavit(sweb_tok(), SERVER_IP)
        tg("🟢 Вернул сайт на сервер по команде.")
        s.clear()
    else:
        prohod(s)
        samoproverka(s)
    json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
