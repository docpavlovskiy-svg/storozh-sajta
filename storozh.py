#!/usr/bin/env python3
"""Сторож сайта doctorpavlovskii.ru снаружи (GitHub Actions, раз в 2 минуты).

Решение Ивана 12.10.2026 (вариант 3): если упадёт наш сервер rabota (Германия), сайт уходит
на страницу-заглушку на хостинге SpaceWeb. Сторож живёт не на сервере: умрёт сервер - сторож нет.
Будит его внешний будильник cron-job.org раз в 2 минуты (запуск workflow по ключу), расписание
GitHub */10 - страховка: само по себе оно будит 4-6 раз в сутки (17.10.2026).

Три состояния сервера (кабинет без сети, этап 3, 17.10.2026):
  zhiv     главная и /blog/api/health отвечают 200
  dvizhok  главная 200, health нет - лежит движок кабинета или база. Заглушка тут не поможет:
           адрес сайта НЕ трогаю никогда. Первые минуты тревогу даёт сторож воркера на rabota
           через Дежурного; не ожило за 60 мин - одно сообщение Ивану, «🟢» - только если оно было
  lezhit   не отвечает сама главная (сервер или nginx):
    15 мин                   -> Ивану «слежу»
    60 мин                   -> проверка из России тремя способами по главной (хостинг SpaceWeb
                                в Петербурге, check-host.net, globalping.io)
       из России открывается -> сбой связи, ничего не делаю
       из России лежит       -> ночью (23-08 Мадрид) заглушка сама, днём спрашиваю Ивана
       проверить не вышло    -> ночью через 90 мин простоя заглушка сама
  на заглушке: главная 30 мин подряд 200 -> возвращаю сайт сам и пишу Ивану (кабинет может ещё
               лежать - тогда в сообщении хвост «кабинет пока не отвечает»)
  раз в день (будни, после 09:00) - самопроверка: проверка из России, сама заглушка, DNS SpaceWeb
  и самый длинный перерыв между прогонами за сутки (он же журнал приёмки 3.1).

Адрес сайта в норме читаю у DNS SpaceWeb (dig), без входа в SpaceWeb: вход паролем Ивана каждые
2 минуты - риск блокировки аккаунта. Вход - только для переключения, pokazat и запасного пути.
Сбой прохода не роняет прогон (код 0); сбои 30 минут подряд - одно сообщение «сторож сломался».

Почта на заглушке (17.10.2026): на заглушке клиентам дан inbox@doctorpavlovskii.ru, а читает ящик
только гейт-бот с rabota, который в это время мёртв. Пока режим «заглушка», каждый проход смотрит
ящик (только чтение) и о каждом письме, пришедшем после включения заглушки, пишет Ивану.

Адрес сервера - переменная репозитория SERVER_IP (переезд сайта, 17.10.2026), пустая - прежний
2.31.62.117. Им пользуются все проверки: curl напрямую, сверка DNS, возврат с заглушки, точка
проверки из России (?ip=).

Будильник: python3 storozh.py budilnik (= prohod + отметка начала ритма для самопроверки).
Ручное: python3 storozh.py pokazat | na-zaglushku | na-server. Две последние - только с кодом
(RUCHNOJ_KOD): в GitHub он приходит полем kod запуска и читается из файла события, локально - KOD.
Окружение: SWEB_LOGIN, SWEB_PASSWORD, TG_TOKEN, TG_CHAT, STATE (файл состояния), RUCHNOJ_KOD,
GH_TOKEN (журнал прогонов для самопроверки), SWEB_INBOX_PASSWORD (ящик inbox@, нет - почту не
смотрю), SERVER_IP. Стенд без сети: test_storozh.py.
"""
import email, email.header, email.utils, hmac, html, imaplib, json, os, re, socket, ssl, subprocess, sys, time
import urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DOMAIN = "doctorpavlovskii.ru"
PREZHNIJ_IP = "2.31.62.117"
# Адрес сервера сайта: переменная репозитория SERVER_IP, пустая - прежний (сервер rabota в Германии).
SERVER_IP = (os.environ.get("SERVER_IP") or "").strip() or PREZHNIJ_IP
ZAGL_IP = "77.222.62.121"
PROBA_RU = "http://playsicru.temp.swtest.ru/cgi-bin/proverka.py"
NS_SWEB = ("ns1.spaceweb.ru", "ns2.spaceweb.ru", "ns3.spaceweb.pro")
REPO = os.environ.get("GITHUB_REPOSITORY") or "docpavlovskiy-svg/storozh-sajta"
MADRID = ZoneInfo("Europe/Madrid")
NOCH = (23, 8)
STATE = os.environ.get("STATE", "state.json")
# budilnik - тот же prohod, так зовёт будильник cron-job.org: с первого такого запуска
# самопроверка считает перерывы между прогонами (ручной prohod при выкате их не включает).
KOMANDY = ("prohod", "budilnik", "pokazat", "na-zaglushku", "na-server")
RUCHNYE = ("na-zaglushku", "na-server")
# TTL записей при переключении. Сейчас у SpaceWeb 600 с. У editMain есть prefix «Префикс или TTL
# записи» - гипотеза, проверяется опытом на тестовой записи при выкате 3.1. None - не передавать
# (как до 17.10). Подтвердится - поставить "120" и поправить «~10 минут» в тексте заглушки.
TTL = None
# Ящик, который дан клиентам на заглушке. Вход - полный адрес, пароль - секрет SWEB_INBOX_PASSWORD.
INBOX = "inbox@doctorpavlovskii.ru"
IMAP_HOST = "imap.spaceweb.ru"
POCHTA_MAX = 200        # UID писем, о которых уже сказал Ивану, в состоянии не больше стольких
POCHTA_BAJT = 65536     # начала письма хватает на отправителя, тему и первые строки текста
MESYACY = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Ключи состояния по видам аварии: сбрасываются, когда авария кончилась.
LEZHIT_KLYUCHI = ("lezhit_s", "preduprezhden", "rossiya_s", "skazal_svyaz", "skazal_net_proverki",
                  "sprosil", "skazal_zagl_slomana", "skazal_ne_pereklyuchil")
DVIZHOK_KLYUCHI = ("dvizhok_s", "dvizhok_chas", "dvizhok_znaet")
# Переживают возврат на сервер: отметка самопроверки и начало ритма будильника.
VECHNYE = ("samoproverka", "budilnik_s")


def log(*a):
    print(datetime.now(MADRID).strftime("%d.%m %H:%M"), *a, flush=True)


def tg(text):
    """True - Telegram принял. В журнал (он публичный) - только первая строка."""
    try:
        data = json.dumps({"chat_id": os.environ["TG_CHAT"], "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % os.environ["TG_TOKEN"], data=data,
            headers={"Content-Type": "application/json"}), timeout=20)
        log("Ивану:", text.split("\n")[0])
        return True
    except Exception as e:
        log("telegram не принял:", type(e).__name__)
        return False


def curl_kod(url, ip):
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
                        "--resolve", "%s:443:%s" % (DOMAIN, ip), url], capture_output=True, text=True)
    return r.stdout.strip() or "000"


def server_sost():
    """('zhiv' | 'dvizhok' | 'lezhit', код главной, код health). Две попытки через 10 с, берётся лучшая.
    Главная 200 = живы сервер и портал; health за ней - движок кабинета и база."""
    luchshe = None
    for i in range(2):
        g = curl_kod("https://%s/" % DOMAIN, SERVER_IP)
        h = curl_kod("https://%s/blog/api/health" % DOMAIN, SERVER_IP) if g == "200" else "-"
        st = "zhiv" if h == "200" else ("dvizhok" if g == "200" else "lezhit")
        if st == "zhiv":
            return st, g, h
        if luchshe is None or st == "dvizhok":
            luchshe = (st, g, h)
        if i == 0:
            time.sleep(10)
    return luchshe


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
# Решает главная: лежит только движок - не повод для заглушки (17.10.2026).

def ru_sweb():
    try:
        d = json.load(urllib.request.urlopen(PROBA_RU + "?ip=" + urllib.parse.quote(SERVER_IP), timeout=60))
        # Точка до 17.10 знает только прежний адрес и поля ip не отдаёт. Проверила не тот адрес
        # (новая proverka.py ещё не залита на хостинг) - ответ не в счёт.
        ip = d.get("ip") or PREZHNIJ_IP
        if ip != SERVER_IP:
            log("хостинг SpaceWeb: точка проверила", ip, "а не", SERVER_IP, "- залить новую proverka.py")
            return None
        return d["glavnaya"] != "200"
    except Exception as e:
        log("хостинг SpaceWeb:", type(e).__name__)
        return None


def ru_checkhost():
    try:
        h = {"Accept": "application/json"}
        q = ("https://check-host.net/check-http?host=https://%s/&max_nodes=3"
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
                           "measurementOptions": {"protocol": "HTTPS", "request": {"path": "/"}}}).encode()
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


def po_ip(ip):
    return {SERVER_IP: "server", ZAGL_IP: "zaglushka"}.get(ip, "drugoj:" + ip)


def rezhim(tok):
    return po_ip(zapisi(tok)["@"]["value"])


def rezhim_dns():
    """Режим по ответу DNS SpaceWeb, без входа в SpaceWeb. None - ни один NS не ответил."""
    for ns in NS_SWEB:
        try:
            r = subprocess.run(["dig", "+short", "+time=5", "+tries=1", "@" + ns, DOMAIN, "A"],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            log("dig", ns, type(e).__name__)
            continue
        ips = sorted({x for x in r.stdout.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x)})
        if r.returncode == 0 and ips:
            return po_ip(",".join(ips))
        log("dig", ns, "не ответил")
    return None


def uznat_rezhim(s):
    """Режим сайта. В норме - по DNS. DNS молчит или расходится с моим состоянием (переключение ещё
    не дошло до NS, правка руками в панели) - по API SpaceWeb, оно главнее, и состояние догоняет его."""
    ozhid = "zaglushka" if s.get("na_zaglushke_s") else "server"
    rz = rezhim_dns()
    if rz == ozhid or (rz or "").startswith("drugoj:"):
        return rz
    log("DNS SpaceWeb:", rz or "не ответил", "- сверяю через вход в SpaceWeb")
    rz = rezhim(sweb_tok())
    if rz == "server":
        for k in ("na_zaglushke_s", "podnyalsya_s", "skazal_ne_vernul"):
            s.pop(k, None)
    elif rz == "zaglushka":
        s.setdefault("na_zaglushke_s", time.time())
    return rz


def postavit(tok, ip):
    for k, rec in zapisi(tok).items():
        if rec["value"] != ip:
            p = {"domain": DOMAIN, "action": "edit", "index": rec["index"], "type": "A", "value": ip}
            if TTL:
                p["prefix"] = TTL
            sweb("domains/dns", "editMain", p, tok)
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


def sbros(s):
    """Авария кончилась: забываю всё, кроме вечных отметок."""
    for k in [k for k in s if k not in VECHNYE]:
        del s[k]


def na_zaglushku(s, prichina):
    """True - адрес сайта переведён на заглушку."""
    ok, dnej = zaglushka_ok()
    if not ok:
        if not s.get("skazal_zagl_slomana"):
            tg("🔴 Сайт лежит, а заглушка на хостинге SpaceWeb сама не отвечает - переключать некуда. "
               "Напишите Клоду «сайт лежит, заглушка не отвечает».")
            s["skazal_zagl_slomana"] = True
        return False
    try:
        postavit(sweb_tok(), ZAGL_IP)
    except Exception as e:
        log("включить заглушку не вышло:", type(e).__name__, str(e)[:200])
        if not s.get("skazal_ne_pereklyuchil"):
            tg("🔴 %s Включить заглушку не вышло: SpaceWeb не принял правку адреса сайта. "
               "Скажите в рабочем чате «заглушка не включилась»." % prichina)
            s["skazal_ne_pereklyuchil"] = True
        return False
    s.update(na_zaglushke_s=time.time(), podnyalsya_s=None)
    s.pop("skazal_ne_pereklyuchil", None)
    tg("🔴 %s Включил заглушку: через ~10 минут посетители увидят страницу с кнопками на бота, канал и запись. "
       "Когда сервер проработает 30 минут, верну сайт сам." % prichina)
    return True


def server_lezhit(s, t):
    """Не отвечает сама главная, адрес сайта на сервере: прежняя ветка 12.10 без изменений."""
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
            na_zaglushku(s, "Сайт лежит %s, из России тоже (ответили %d из 3 проверок)." % (chas(m), skolko))
        elif not s.get("sprosil"):
            tg("🔴 Сайт лежит %s (проверено из России). Заглушка готова. Чтобы включить, напишите Клоду "
               "«включай заглушку». Если не ответите до 23:00, ночью включу сам." % chas(m))
            s["sprosil"] = True
    else:
        if noch(t) and m >= 90:
            na_zaglushku(s, "Сайт лежит %s, проверить из России не удалось ни одним способом." % chas(m))
        elif not s.get("skazal_net_proverki"):
            tg("🟠 Сайт лежит %s, проверить из России не удалось. Ночью через 90 минут простоя включу "
               "заглушку сам. Днём - напишите Клоду «включай заглушку», если сайт у Вас не открывается." % chas(m))
            s["skazal_net_proverki"] = True


def prohod(s):
    """Один проход. Возвращает режим сайта после него: 'server' | 'zaglushka' | 'drugoj:...'."""
    t = datetime.now(MADRID)
    rz = uznat_rezhim(s)
    st, g, h = server_sost()
    log("режим", rz, "сервер", SERVER_IP, st, "главная", g, "health", h)
    reshit(s, t, rz, st)
    # Вернул сайт с заглушки в этом проходе: sbros снял отметку заглушки.
    if rz == "zaglushka" and not s.get("na_zaglushke_s"):
        return "server"
    return rz


def reshit(s, t, rz, st):
    """Решения прохода по режиму сайта и состоянию сервера (до 17.10 - тело prohod)."""
    if rz == "server":
        if st == "lezhit":
            server_lezhit(s, t)
            return
        # Главная отвечает: адрес сайта не трогаю никогда, что бы ни было с кабинетом.
        if s.get("lezhit_s"):
            if s.get("preduprezhden"):
                lezhal = chas(minut(s, "lezhit_s"))
                if st == "zhiv":
                    tg("🟢 Сайт снова отвечает (лежал %s). Ничего не переключал." % lezhal)
                    for k in DVIZHOK_KLYUCHI:
                        s.pop(k, None)
                else:
                    tg("🟢 Сайт снова отвечает (лежал %s), кабинет пока нет. Ничего не переключал. "
                       "Если кабинет не оживёт за час, напишу." % lezhal)
                    s.update(dvizhok_s=time.time(), dvizhok_znaet=True)
            for k in LEZHIT_KLYUCHI:
                s.pop(k, None)
        if st == "dvizhok":
            s.setdefault("dvizhok_s", time.time())
            m = minut(s, "dvizhok_s")
            if m >= 60 and not s.get("dvizhok_chas"):
                # Страховка на случай, если лёг и сторож воркера на rabota: из GitHub к Дежурному
                # дороги нет (его ящик - файл на rabota или тот же лежащий движок), поэтому напрямую.
                tg("🟠 Кабинет и статьи блога не отвечают уже %s, главная страница сайта открывается. "
                   "Сервер жив, заглушка тут не поможет - адрес сайта не переключаю. "
                   "Скажите в рабочем чате «кабинет не отвечает час»." % chas(m))
                s.update(dvizhok_chas=True, dvizhok_znaet=True)
            return
        if s.get("dvizhok_s"):
            if s.get("dvizhok_znaet"):
                tg("🟢 Кабинет снова отвечает (не отвечал %s). Ничего не переключал." % chas(minut(s, "dvizhok_s")))
            for k in DVIZHOK_KLYUCHI:
                s.pop(k, None)
        return

    if rz == "zaglushka":
        # Возвращаю по главной: на сервере работают бот и вебхуки оплат, заглушка с 503 им мешает,
        # даже если кабинет ещё лежит.
        if st == "lezhit":
            s["podnyalsya_s"] = None
            return
        if not s.get("podnyalsya_s"):
            s["podnyalsya_s"] = time.time()
        if minut(s, "podnyalsya_s") < 30:
            return
        try:
            postavit(sweb_tok(), SERVER_IP)
        except Exception as e:
            log("вернуть сайт с заглушки не вышло:", type(e).__name__, str(e)[:200])
            if not s.get("skazal_ne_vernul"):
                tg("⚠️ Главная сайта на сервере снова открывается, а вернуть сайт с заглушки не вышло: "
                   "SpaceWeb не принял правку адреса. Посетители пока видят заглушку. "
                   "Скажите в рабочем чате «верни сайт с заглушки».")
                s["skazal_ne_vernul"] = True
            return
        dolgo = chas(minut(s, "na_zaglushke_s")) if s.get("na_zaglushke_s") else "?"
        if st == "zhiv":
            tg("🟢 Сервер работает 30 минут без сбоев - вернул сайт с заглушки (заглушка висела %s)." % dolgo)
        else:
            tg("🟢 Главная сайта открывается 30 минут подряд - вернул сайт с заглушки (заглушка висела %s). "
               "Кабинет пока не отвечает, если не оживёт за час - напишу." % dolgo)
        sbros(s)
        if st == "dvizhok":
            s.update(dvizhok_s=time.time(), dvizhok_znaet=True)
        return
    log("адрес сайта указывает на", rz, "- это ручная настройка, ничего не трогаю")


def prohod_bezopasno(s):
    """Сбой прохода не роняет прогон: упавший прогон - письмо GitHub Ивану каждые 2 минуты.
    Сбои 30 минут подряд - одно сообщение «сторож сам сломался», починился - «🟢».
    Возвращает режим сайта после прохода, None - проход упал."""
    try:
        rz = prohod(s)
    except Exception as e:
        log("сбой прохода:", type(e).__name__, str(e)[:200])
        s.setdefault("sboj_s", time.time())
        if minut(s, "sboj_s") >= 30 and not s.get("skazal_sboj"):
            tg("⚠️ Сторож сайта сам сломался: уже 30 минут каждая его проверка падает с ошибкой. "
               "Пока он сломан, при падении сервера заглушка сама не включится. "
               "Скажите в рабочем чате «почини сторожа сайта».")
            s["skazal_sboj"] = True
        return None
    if s.get("sboj_s"):
        if s.get("skazal_sboj"):
            tg("🟢 Сторож сайта снова работает (был сломан %s)." % chas(minut(s, "sboj_s")))
        s.pop("sboj_s", None)
        s.pop("skazal_sboj", None)
    return rz


# --- почта inbox@ пока сайт на заглушке (17.10.2026) ---------------------------------
# На заглушке клиентам дан inbox@doctorpavlovskii.ru. Пересылки у ящика нет, читает его только
# гейт-бот с rabota, а заглушка висит именно тогда, когда rabota мёртв: без сторожа письмо до Ивана
# не дойдёт. Только чтение: ящик открыт readonly, тело - BODY.PEEK, ни одного STORE - флаг
# «прочитано» не ставится, вернётся rabota - гейт-бот увидит письма непрочитанными.
# Журнал прогона публичный: отправителя, тему и текст туда не пишу; в состоянии - только UID.

def internaldate_sek(x):
    """INTERNALDATE IMAP («17-Oct-2026 14:05:33 +0300») в секунды."""
    m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})\s*$", x)
    d, mes, g, hh, mm, ss, zn, zh, zm = m.groups()
    sdvig = (int(zh) * 60 + int(zm)) * (-1 if zn == "-" else 1)
    return datetime(int(g), MESYACY.index(mes.title()) + 1, int(d), int(hh), int(mm), int(ss),
                    tzinfo=timezone(timedelta(minutes=sdvig))).timestamp()


def pochta_novye(parol, ot, izvestnye):
    """[(uid, начало письма байтами или None)] - письма INBOX с INTERNALDATE не раньше ot, UID которых
    нет в izvestnye, по возрастанию UID. Сбой связи или входа - исключение наружу."""
    # Сертификат проверяю: у imaplib по умолчанию проверки нет, а по этой связи идёт пароль ящика.
    M = imaplib.IMAP4_SSL(IMAP_HOST, 993, ssl_context=ssl.create_default_context(), timeout=20)
    try:
        M.login(INBOX, parol)
        typ, _ = M.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("INBOX не открылся: %s" % typ)
        # SINCE сравнивает только дату, без часов и пояса сервера: ищу с суток раньше,
        # точный отбор - по INTERNALDATE ниже. 18 старых непрочитанных с 31.08 сюда не попадают.
        den = datetime.fromtimestamp(ot - 86400, timezone.utc)
        typ, d = M.uid("SEARCH", "SINCE", "%d-%s-%d" % (den.day, MESYACY[den.month - 1], den.year))
        if typ != "OK":
            raise RuntimeError("поиск писем не прошёл: %s" % typ)
        uids = sorted({int(x) for x in b" ".join(x for x in d if isinstance(x, bytes)).split()})
        # Список известных обрезан до POCHTA_MAX: всё, что ниже самого старого в нём, уже решено,
        # иначе выпавший из списка UID пришёл бы Ивану повторно.
        porog = min(int(x) for x in izvestnye) if len(izvestnye) >= POCHTA_MAX else 0
        izv = set(izvestnye)
        kandidaty = {u for u in uids if u > porog and str(u) not in izv}
        if not kandidaty:
            return []
        # Только время прихода, тело не трогаю: такой FETCH флагов не меняет.
        typ, d = M.uid("FETCH", ",".join(map(str, sorted(kandidaty))), "(UID INTERNALDATE)")
        if typ != "OK":
            raise RuntimeError("время писем не получил: %s" % typ)
        novye = set()
        for x in d:
            stroka = x[0] if isinstance(x, tuple) else x
            if not isinstance(stroka, bytes):
                continue
            mu, md = re.search(rb"UID (\d+)", stroka), re.search(rb'INTERNALDATE "([^"]+)"', stroka)
            if not (mu and md) or int(mu.group(1)) not in kandidaty:
                continue
            try:
                kogda = internaldate_sek(md.group(1).decode())
            except Exception:
                log("почта inbox: время письма", mu.group(1).decode(), "не разобрал")
                continue
            if kogda >= ot:
                novye.add(int(mu.group(1)))
        out = []
        for uid in sorted(novye):
            typ, d = M.uid("FETCH", str(uid), "(BODY.PEEK[]<0.%d>)" % POCHTA_BAJT)
            syroe = None
            if typ == "OK":
                syroe = next((x[1] for x in d if isinstance(x, tuple) and len(x) > 1
                              and isinstance(x[1], bytes)), None)
            out.append((str(uid), syroe))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def zagolovok(v):
    """Заголовок письма строкой: =?utf-8?b?...?= раскодирую; неизвестная кодировка - как получится."""
    if v is None:
        return ""
    try:
        tekst = str(email.header.make_header(email.header.decode_header(v)))
    except Exception:
        try:
            chasti = []
            for kusok, kod in email.header.decode_header(v):
                if isinstance(kusok, bytes):
                    try:
                        kusok = kusok.decode(kod or "utf-8", "replace")
                    except LookupError:
                        kusok = kusok.decode("utf-8", "replace")
                chasti.append(kusok)
            tekst = "".join(chasti)
        except Exception:
            tekst = str(v)
    return " ".join(tekst.split())


def bez_tegov(t):
    t = re.sub(r"(?is)<(style|script|head)\b.*?</\1\s*>", " ", t)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?i)<(br|/?p|/?div|/?tr|/?td|/?li|/?h[1-6]|/?table)\b[^>]*>", " ", t)
    return html.unescape(re.sub(r"(?s)<[^>]*>", "", t))


def nachalo_teksta(msg):
    """Начало текста письма: первая часть text/plain, пустая или нет её - text/html без тегов."""
    chasti = {}
    for chast in msg.walk():
        if chast.is_multipart() or "attachment" in str(chast.get("Content-Disposition", "")).lower():
            continue
        chasti.setdefault(chast.get_content_type(), chast)
    for tip in ("text/plain", "text/html"):
        chast = chasti.get(tip)
        if chast is None:
            continue
        dannye = chast.get_payload(decode=True) or b""
        try:
            tekst = dannye.decode(chast.get_content_charset() or "utf-8", "replace")
        except LookupError:
            tekst = dannye.decode("utf-8", "replace")
        if tip == "text/html":
            tekst = bez_tegov(tekst)
        tekst = " ".join(tekst.split())
        if tekst:
            return tekst if len(tekst) <= 300 else tekst[:299].rstrip() + "…"
    return ""


def pismo_ivanu(syroe):
    """Текст Ивану о письме. Разбор best-effort: что не разобралось - пометка, не сбой."""
    ot = tema = nachalo = None
    msg = None
    if syroe:
        try:
            msg = email.message_from_bytes(syroe)
        except Exception:
            msg = None
    if msg is not None:
        try:
            v = msg.get("From")
            ot = ""
            if v is not None:
                imya, adres = email.utils.parseaddr(str(v))
                imya = zagolovok(imya)
                ot = ("%s <%s>" % (imya, adres) if imya and adres else adres or zagolovok(v))[:200]
        except Exception:
            ot = None
        try:
            tema = zagolovok(msg.get("Subject"))[:200]
        except Exception:
            tema = None
        try:
            nachalo = nachalo_teksta(msg)
        except Exception:
            nachalo = None
    stroki = ["📧 Пока сайт на заглушке, на %s пришло письмо." % INBOX,
              "От: %s" % (ot or ("(не указан)" if ot == "" else "(не разобрал)")),
              "Тема: %s" % (tema or ("(без темы)" if tema == "" else "(не разобрал)"))]
    if nachalo:
        stroki.append("«%s»" % nachalo)
    stroki.append("Ответить можно с любой своей почты прямо на адрес отправителя.")
    return "\n".join(stroki)


def pochta(s, rz):
    """Пока сайт на заглушке - новые письма inbox@ Ивану, по одному сообщению на письмо.
    Сбой IMAP - строка в журнал и всё: проход идёт дальше, Ивану ничего."""
    if rz == "server":
        # Сайт на сервере (вернул сам или руками в панели): письма читает гейт-бот, список не нужен.
        s.pop("pochta_uid", None)
        return
    parol = (os.environ.get("SWEB_INBOX_PASSWORD") or "").strip("\r\n")
    if rz != "zaglushka" or not parol or not s.get("na_zaglushke_s"):
        return
    izvestnye = [str(x) for x in s.get("pochta_uid") or []]
    try:
        novye = pochta_novye(parol, s["na_zaglushke_s"], izvestnye)
    except Exception as e:
        log("почта inbox: проверить не вышло:", type(e).__name__, str(e)[:80])
        return
    log("почта inbox: новых писем", len(novye))
    skazal = False
    for uid, syroe in novye:
        try:
            tekst = pismo_ivanu(syroe)
        except Exception as e:
            log("почта inbox: письмо", uid, "не разобрал:", type(e).__name__)
            tekst = pismo_ivanu(None)
        if tg(tekst) is False:
            continue        # Telegram не принял - это письмо повторю на следующем проходе
        izvestnye.append(uid)
        skazal = True
    if skazal:
        # Оставляю самые свежие UID: выпавшие все ниже самого старого оставшегося (см. porog).
        s["pochta_uid"] = sorted(set(izvestnye), key=int)[-POCHTA_MAX:]


def iso_v_sek(x):
    return datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def pereryv_minut(ot):
    """Самый длинный перерыв между стартами прогонов (без отменённых) от момента ot до сейчас, мин.
    None - меньше двух прогонов."""
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
         "User-Agent": "storozh-sajta"}
    if os.environ.get("GH_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    s_iso = datetime.fromtimestamp(ot, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    starty = []
    for stranica in range(1, 11):
        url = ("https://api.github.com/repos/%s/actions/workflows/storozh.yml/runs"
               "?created=%%3E%%3D%s&per_page=100&page=%d" % (REPO, s_iso, stranica))
        runs = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30)).get(
            "workflow_runs") or []
        starty += [iso_v_sek(r["run_started_at"]) for r in runs
                   if r.get("conclusion") != "cancelled" and r.get("run_started_at")]
        if len(runs) < 100:
            break
    starty.sort()
    if len(starty) < 2:
        return None
    return max(b - a for a, b in zip(starty, starty[1:])) / 60


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
    if rezhim_dns() is None:
        bedy.append("адрес сайта не читается у DNS SpaceWeb - сторож входит в SpaceWeb паролем на каждой проверке")
    # Ритм будильника: считаю с первого запуска по будильнику, иначе первые сутки поймают
    # многочасовые перерывы старого расписания.
    pereryv = None
    if s.get("budilnik_s"):
        try:
            pereryv = pereryv_minut(max(time.time() - 86400, s["budilnik_s"]))
        except Exception as e:
            log("журнал прогонов:", type(e).__name__, str(e)[:60])
    log("самопроверка: самый длинный перерыв между прогонами за сутки",
        "%.1f мин" % pereryv if pereryv is not None else "не посчитан")
    if pereryv is not None and pereryv > 10:
        bedy.append("за сутки был перерыв между проверками %d мин (будильник сторожа сбоит, должно быть 2 мин)"
                    % pereryv)
    log("самопроверка:", rab, "заглушка", ok, dnej)
    if bedy:
        tg("⚠️ Сторож сайта, утренняя самопроверка: " + "; ".join(bedy) +
           ". Сайт работает, это запасной путь. Напишите Клоду «почини сторожа сайта».")


def vvedennyj_kod():
    """Код ручной команды. В GitHub - только из файла события (поле kod запуска): env шага GitHub
    печатает в публичном журнале прогона. Локально - из KOD."""
    p = os.environ.get("GITHUB_EVENT_PATH")
    if p:
        try:
            return str((json.load(open(p)).get("inputs") or {}).get("kod") or "")
        except (OSError, ValueError, AttributeError):
            return ""
    return os.environ.get("KOD", "")


def kod_veren():
    nado = os.environ.get("RUCHNOJ_KOD", "")
    return bool(nado) and hmac.compare_digest(vvedennyj_kod().encode(), nado.encode())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prohod"
    # Белый список: вход запуска приходит снаружи. Саму команду в журнал не печатаю.
    if cmd not in KOMANDY:
        sys.exit("неизвестная команда - отказ")
    if cmd in RUCHNYE and not kod_veren():
        sys.exit("ручная команда без верного кода - отказ")
    try:
        s = json.load(open(STATE))
    except (OSError, ValueError):
        s = {}
    kod = 0
    if cmd == "pokazat":
        log("DNS", rezhim_dns(), "SpaceWeb", rezhim(sweb_tok()), "сервер", SERVER_IP, server_sost(),
            "заглушка", zaglushka_ok(), "состояние", s)
        return
    if cmd == "na-zaglushku":
        kod = 0 if na_zaglushku(s, "По команде Ивана.") else 1
    elif cmd == "na-server":
        postavit(sweb_tok(), SERVER_IP)
        tg("🟢 Вернул сайт на сервер по команде.")
        sbros(s)
    else:
        if cmd == "budilnik":
            s.setdefault("budilnik_s", time.time())
        rz = prohod_bezopasno(s)
        if rz is None and s.get("na_zaglushke_s"):
            rz = "zaglushka"    # проход упал, а по состоянию сайт на заглушке - почту всё равно смотрю
        try:
            pochta(s, rz)
        except Exception as e:
            log("сбой проверки почты:", type(e).__name__)
        try:
            samoproverka(s)
        except Exception as e:
            log("сбой самопроверки:", type(e).__name__, str(e)[:200])
    json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=1)
    sys.exit(kod)


if __name__ == "__main__":
    main()
