#!/usr/bin/env python3
"""Стенд сторожа сайта без сети и без DNS (кабинет без сети, этап 3, пункт 3.1, 17.10.2026).

Гоняет storozh.py по часам стенда: прогон раз в 2 минуты, ответы сервера - таблица по минутам.
Подменяет всё, что выходит наружу: curl_kod, rezhim_dns, sweb (записи DNS в памяти + журнал
editMain), tg, zaglushka_ok, time, datetime. urlopen и socket.create_connection - роутер: известные
адреса (проверка из России, check-host, globalping, журнал прогонов GitHub) отвечают по сценарию,
любой другой вызов - Mimo; subprocess.run в модуле - всегда Mimo. Mimo наследует BaseException:
её не проглотит ни один «except Exception» в стороже, стенд падает.

Сценарии A-K и контроль: старый storozh.py (последняя версия из git с server_zhiv, до 17.10) на
сценарии A обязан включить заглушку - значит, стенд ловит именно эту ошибку.

Почта на заглушке (пункт 3.5, 17.10.2026), сценарии P1-P7: imaplib.IMAP4_SSL подменён поддельным
ящиком (PoddelnyjImap). Любая запись в ящик - Mimo: STORE, select без readonly, FETCH тела без PEEK
(он ставит «прочитано», и гейт-бот потом не увидит письмо). Без настроенного ящика любой вызов
IMAP - тоже Mimo. Сценарий S - адрес сервера из переменной SERVER_IP; P0 - разбор ?ip= в
hosting/cgi-bin/proverka.py без сети.

Запуск: python3 tools/storozh-sajta/test_storozh.py   (python 3.9+, на Маке ~/miniforge3/bin/python3;
        код 0 - всё прошло)
        --staryj файл.py   контроль на своей старой версии вместо версии из git
"""
import base64, email.charset, email.header, email.utils, imaplib, importlib.util, io, json, os, re, runpy, socket
import ssl, subprocess, sys, tempfile, types, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

if sys.version_info < (3, 9):
    sys.exit("стенду и сторожу нужен python3 3.9+ (zoneinfo), на Маке: ~/miniforge3/bin/python3")
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ARGV = list(sys.argv)

PAPKA = os.path.dirname(os.path.abspath(__file__))
NOVYJ = os.path.join(PAPKA, "storozh.py")
YML = os.path.join(PAPKA, ".github", "workflows", "storozh.yml")
PROVERKA = os.path.join(PAPKA, "hosting", "cgi-bin", "proverka.py")
INBOX = "inbox@doctorpavlovskii.ru"
PAROL_INBOX = "parol-stend-7Qx"
NOVYJ_IP = "93.184.30.40"     # адрес «после переезда» для сценариев S и P0 (сети в стенде нет)
MADRID = ZoneInfo("Europe/Madrid")
SERVER_IP, ZAGL_IP = "2.31.62.117", "77.222.62.121"
PROBA_RU = "http://playsicru.temp.swtest.ru/cgi-bin/proverka.py"
NOCH_START = datetime(2026, 10, 19, 23, 30, tzinfo=MADRID).timestamp()   # понедельник, ночь
DEN_START = datetime(2026, 10, 19, 10, 0, tzinfo=MADRID).timestamp()     # понедельник, день
ZAGLUSHKA_TEXT = "Включил заглушку"

ITOG = []
REAL_URLOPEN = urllib.request.urlopen
REAL_CONNECT = socket.create_connection
REAL_RUN = subprocess.run
REAL_IMAP4 = imaplib.IMAP4
REAL_IMAP4_SSL = imaplib.IMAP4_SSL
REAL_CHECK_OUTPUT = subprocess.check_output


class Mimo(BaseException):
    """Вызов мимо подмен - стенд обязан упасть, сторож не должен его проглотить."""


def proverit(uslovie, opisanie):
    ITOG.append((bool(uslovie), opisanie))
    print("  %s %s" % ("ОК    " if uslovie else "ПРОВАЛ", opisanie))


class Otvet(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def otvet_json(d):
    return Otvet(json.dumps(d).encode())


class Dvoinik(io.TextIOBase):
    """Вывод сторожа - и на экран, и в журнал стенда (по журналу проверяю, что в него попало)."""

    def __init__(self, *kuda):
        self.kuda = kuda

    def write(self, t):
        for k in self.kuda:
            k.write(t)
        return len(t)

    def flush(self):
        for k in self.kuda:
            k.flush()


# --- поддельный ящик inbox@ ---------------------------------------------------------------

def internaldate(t):
    """Время письма так, как его пишет сервер почты SpaceWeb (Москва, +0300)."""
    x = datetime.fromtimestamp(t, timezone(timedelta(hours=3)))
    return "%02d-%s-%d %02d:%02d:%02d +0300" % (x.day, ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                                         "Sep", "Oct", "Nov", "Dec")[x.month - 1], x.year,
                                                x.hour, x.minute, x.second)


class PoddelnyjImap:
    """Подмена imaplib.IMAP4_SSL. Только чтение: любая запись в ящик - Mimo (STORE, COPY, MOVE, EXPUNGE,
    CLOSE, select без readonly, FETCH тела без PEEK - он поставил бы «прочитано»)."""

    def __init__(self, stend, host, port=993, *a, **k):
        self.stend = stend
        self.vybran = self.voshel = False
        stend.imap_podkl.append({"host": host, "port": port, "timeout": k.get("timeout"),
                                 "ssl_context": k.get("ssl_context"), "lishnee": a})
        if stend.imap_rezhim == "net":
            raise TimeoutError("стенд: imap.spaceweb.ru не отвечает")

    def __getattr__(self, imya):
        raise Mimo("IMAP %s - мимо подмен (запись или не та команда)" % imya)

    def login(self, user, parol):
        if self.stend.imap_rezhim == "parol" or (user, parol) != (INBOX, PAROL_INBOX):
            raise REAL_IMAP4.error("b'[AUTHENTICATIONFAILED] Authentication failed.'")
        self.voshel = True
        return "OK", [b"Logged in"]

    def select(self, mailbox="INBOX", readonly=False):
        if readonly is not True:
            raise Mimo("select без readonly=True")
        if not self.voshel or mailbox != "INBOX":
            raise Mimo("select не того ящика или без входа: %s" % mailbox)
        self.vybran = True
        return "OK", [str(len(self.stend.yashchik)).encode()]

    def logout(self):
        return "BYE", [b"Logging out"]

    def pisma(self, nabor):
        nuzhno = {int(x) for x in str(nabor).split(",")}
        return [(i + 1, p) for i, p in enumerate(self.stend.yashchik) if p["uid"] in nuzhno]

    def uid(self, command, *args):
        kom = command.upper()
        self.stend.imap_komandy.append((kom,) + args)
        if not self.vybran:
            raise Mimo("UID %s до select" % kom)
        if kom == "SEARCH":
            if len(args) != 2 or args[0].upper() != "SINCE":
                raise Mimo("неизвестный поиск: %s" % (args,))
            d, mes, g = args[1].split("-")
            mesyacy = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            s_dnya = (int(g), mesyacy.index(mes) + 1, int(d))
            # SINCE - по дате письма без часов и пояса, как у настоящего сервера.
            nashl = []
            for p in self.stend.yashchik:
                x = datetime.fromtimestamp(p["kogda"], timezone(timedelta(hours=3)))
                if (x.year, x.month, x.day) >= s_dnya:
                    nashl.append(str(p["uid"]))
            return "OK", [" ".join(nashl).encode()]
        if kom == "FETCH":
            nabor, chto = args
            bez_peek = re.sub(r"(?i)BODY\.PEEK\[", "", chto)
            if re.search(r"(?i)BODY\[|RFC822|BINARY\[", bez_peek):
                for _, p in self.pisma(nabor):
                    p["prochitano"] = True
                raise Mimo("FETCH тела без PEEK - письмо стало бы прочитанным: %s" % chto)
            if "BODY.PEEK[]" in chto.upper():
                otvet = []
                for n, p in self.pisma(nabor):
                    if p["uid"] in self.stend.imap_ne_otdaet:
                        return "NO", [b"stend: message unavailable"]
                    m = re.search(r"<0\.(\d+)>", chto)
                    kusok = p["syroe"][:int(m.group(1))] if m else p["syroe"]
                    otvet += [(b"%d (UID %d BODY[]<0> {%d}" % (n, p["uid"], len(kusok)), kusok), b")"]
                return "OK", otvet
            if "INTERNALDATE" in chto.upper():
                return "OK", [('%d (UID %d INTERNALDATE "%s")' % (n, p["uid"], internaldate(p["kogda"]))).encode()
                              for n, p in self.pisma(nabor)]
            raise Mimo("FETCH неизвестно чего: %s" % chto)
        raise Mimo("UID %s - запись в ящик или неизвестная команда" % kom)


def b_slovo(t):
    return "=?utf-8?b?%s?=" % base64.b64encode(t.encode()).decode()


def q_slovo(t):
    c = email.charset.Charset("utf-8")
    c.header_encoding = email.charset.QP
    return email.header.Header(t, c).encode()


def pismo(uid, kogda, ot, tema, telo, tip="plain", vlozhenie=False, syroe=None):
    """Письмо поддельного ящика. Тело - base64 utf-8, как шлют почтовые программы."""
    if syroe is None:
        chast = MIMEText(telo, tip, "utf-8")
        if vlozhenie:
            msg = MIMEMultipart("mixed")
            prilozh = MIMEText("ОТЧЁТ ИЗ ВЛОЖЕНИЯ - его в сообщении быть не должно", "plain", "utf-8")
            prilozh.add_header("Content-Disposition", "attachment", filename="analizy.txt")
            msg.attach(prilozh)
            msg.attach(chast)
        else:
            msg = chast
        msg["From"] = ot
        msg["To"] = INBOX
        msg["Subject"] = tema
        msg["Date"] = email.utils.formatdate(kogda)
        syroe = msg.as_bytes()
    return {"uid": uid, "kogda": kogda, "syroe": syroe, "prochitano": False}


class Stend:
    """Один прогон сценария. server(minuta) -> (код главной, код health) на сервере rabota.
    rossiya(minuta) -> JSON точки проверки на хостинге SpaceWeb или None (не ответила)."""

    def __init__(self, put, nachalo, server, rossiya=None, sostoyanie=None, zona="server", env=None,
                 dns_lag=0, dns_slomana=False, tok_slomana=None, edit_slomana=None, ru_vse=False,
                 runs=None, server_ip=None, yashchik=None, imap_rezhim="ok", tg_slomana=None):
        self.nachalo = nachalo
        self.chasy = [nachalo]
        self.server = server
        self.rossiya = rossiya or (lambda m: {"glavnaya": server(m)[0], "blog": server(m)[1],
                                              "zhiv": server(m) == ("200", "200")})
        # server_ip - переменная SERVER_IP при загрузке сторожа (None - не задана, прежний адрес).
        self.server_ip_env = server_ip
        self.server_ip = server_ip or SERVER_IP
        self.zona_ip = self.server_ip if zona == "server" else ZAGL_IP
        # Поддельный ящик inbox@: список писем {uid, kogda, syroe, prochitano}; None - IMAP не ждём.
        self.yashchik = yashchik
        self.imap_rezhim = imap_rezhim          # ok | net (не отвечает) | parol (вход не принят)
        self.imap_podkl, self.imap_komandy, self.imap_ne_otdaet = [], [], set()
        self.tg_slomana = tg_slomana or (lambda m: False)
        self.tg_otkazy, self.proba_ip = [], []
        self.istoriya = [(nachalo - 1, self.zona_ip)]          # (когда, ip) - для запаздывания DNS
        self.dns_lag = dns_lag
        self.dns_slomana = dns_slomana
        self.tok_slomana = tok_slomana or (lambda m: False)
        self.edit_slomana = edit_slomana or (lambda m: False)
        self.ru_vse = ru_vse
        self.runs = runs
        self.soobshcheniya, self.editmain, self.tokeny, self.mimo, self.adresa, self.tela = [], [], 0, [], [], []
        self.kody_vyhoda, self.izmenenij, self.zhurnal = [], 0, []
        self.env = env or {}
        self.tmp = tempfile.mkdtemp(prefix="stend-storozh-")
        self.state = os.path.join(self.tmp, "state.json")
        with open(self.state, "w") as f:
            json.dump(sostoyanie or {}, f)
        self.mod = zagruzit(put, self)

    # --- часы ------------------------------------------------------------------------
    def minuta(self):
        return (self.chasy[0] - self.nachalo) / 60

    # --- подмены ---------------------------------------------------------------------
    def curl_kod(self, url, ip):
        if ip == ZAGL_IP:
            return "503"
        if ip != self.server_ip:
            raise Mimo("curl на чужой адрес %s" % ip)
        g, h = self.server(self.minuta())
        if url == "https://doctorpavlovskii.ru/":
            return g
        if url == "https://doctorpavlovskii.ru/blog/api/health":
            return h
        raise Mimo("curl по неизвестному адресу %s" % url)

    def ip_dns(self):
        kogda = self.chasy[0] - self.dns_lag * 60
        ip = self.istoriya[0][1]
        for t, x in self.istoriya:
            if t <= kogda:
                ip = x
        return ip

    def rezhim_dns(self):
        if self.dns_slomana:
            return None
        ip = self.ip_dns()
        return {self.server_ip: "server", ZAGL_IP: "zaglushka"}.get(ip, "drugoj:" + ip)

    def sweb(self, path, method, params, tok=None):
        m = self.minuta()
        if (path, method) == ("notAuthorized/", "getToken"):
            self.tokeny += 1
            if self.tok_slomana(m):
                raise RuntimeError("SpaceWeb getToken: стенд - вход не работает")
            return "tok-stend"
        if tok != "tok-stend":
            raise Mimo("SpaceWeb без ключа: %s" % method)
        if (path, method) == ("domains/dns", "info"):
            return [{"category": "zoneMain", "type": "A", "name": "@", "value": self.zona_ip, "index": 1},
                    {"category": "zoneMain", "type": "A", "name": "www", "value": self.zona_ip, "index": 2},
                    {"category": "zoneMain", "type": "TXT", "name": "@", "value": "v=spf1", "index": 3}]
        if (path, method) == ("domains/dns", "editMain"):
            if self.edit_slomana(m):
                raise RuntimeError("SpaceWeb editMain: стенд - правка не принята")
            if params.get("type") != "A" or params.get("index") not in (1, 2):
                raise Mimo("editMain не той записи: %s" % params)
            self.editmain.append((m, params["index"], params["value"], params.get("prefix")))
            # Обе записи у стенда двигаются вместе: после правки www зона на новом адресе.
            if params["index"] == 2:
                self.zona_ip = params["value"]
                self.istoriya.append((self.chasy[0], self.zona_ip))
            return True
        raise Mimo("SpaceWeb: неизвестный вызов %s %s" % (path, method))

    def tg(self, text):
        if self.tg_slomana(self.minuta()):
            self.tg_otkazy.append((self.minuta(), text))
            return False
        self.soobshcheniya.append((self.minuta(), text))
        return True

    def zaglushka_ok(self):
        return True, 50

    def imap4_ssl(self, host="", port=993, *a, **k):
        if self.yashchik is None:
            raise Mimo("IMAP не ждали: %s:%s" % (host, port))
        return PoddelnyjImap(self, host, port, *a, **k)

    def urlopen(self, req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else req
        self.adresa.append(url)
        self.tela.append(getattr(req, "data", None) or b"")
        m = self.minuta()
        osnova, _, zapros = url.partition("?")
        if osnova == PROBA_RU:
            # Сторож с 17.10 передаёт адрес сервера (?ip=); старый - без него (контроль).
            ip = (urllib.parse.parse_qs(zapros).get("ip") or [None])[0]
            self.proba_ip.append(ip)
            if ip is not None and ip != self.server_ip:
                raise Mimo("точка проверки из России спрошена не про тот адрес: %s" % url)
            d = self.rossiya(m)
            if d is None:
                raise urllib.error.URLError("стенд: хостинг SpaceWeb не ответил")
            d = dict(d)
            if ip is not None:
                d.setdefault("ip", ip)        # новая proverka.py отвечает, какой адрес проверила
            return otvet_json(d)
        if url.startswith("https://check-host.net/"):
            if not self.ru_vse:
                raise urllib.error.URLError("стенд: check-host недоступен")
            if "check-http" in url:
                return otvet_json({"request_id": "r1"})
            return otvet_json({"ru1": [[1, 0.2, "OK", "200", SERVER_IP]], "ru2": [[1, 0.3, "OK", "200", SERVER_IP]]})
        if url.startswith("https://api.globalping.io/"):
            if not self.ru_vse:
                raise urllib.error.URLError("стенд: globalping недоступен")
            if url.endswith("/measurements"):
                return otvet_json({"id": "g1"})
            return otvet_json({"status": "finished", "results": [{"result": {"statusCode": 200}},
                                                                 {"result": {"statusCode": 200}}]})
        if url.startswith("https://api.github.com/repos/docpavlovskiy-svg/storozh-sajta/actions/workflows/storozh.yml/runs?"):
            if self.runs is None:
                raise Mimo("журнал прогонов не ждали")
            stranica = int(re.search(r"[?&]page=(\d+)", url).group(1))
            return otvet_json({"total_count": len(self.runs),
                               "workflow_runs": self.runs[(stranica - 1) * 100:stranica * 100]})
        raise Mimo("urlopen мимо подмен: %s" % url)

    def mimo_fn(self, chto):
        def f(*a, **k):
            raise Mimo("%s мимо подмен: %r" % (chto, a[:1]))
        return f

    # --- прогон ----------------------------------------------------------------------
    def prohod(self, kom="prohod"):
        do = open(self.state).read()
        sys.argv = ["storozh.py", kom]
        sohr = {k: os.environ.get(k) for k in ("RUCHNOJ_KOD", "KOD", "GITHUB_EVENT_PATH", "GITHUB_EVENT_NAME",
                                               "SWEB_LOGIN", "SWEB_PASSWORD", "SWEB_INBOX_PASSWORD", "SERVER_IP")}
        for k in sohr:
            os.environ.pop(k, None)
        os.environ.update({"SWEB_LOGIN": "stend", "SWEB_PASSWORD": "stend"})   # вход - подмена sweb
        os.environ.update(self.env)
        urllib.request.urlopen = self.urlopen
        socket.create_connection = self.mimo_fn("socket.create_connection")
        imaplib.IMAP4_SSL = self.imap4_ssl
        imaplib.IMAP4 = self.mimo_fn("imaplib.IMAP4 (без шифрования)")
        stdout, bufer = sys.stdout, io.StringIO()
        sys.stdout = Dvoinik(stdout, bufer)
        kod = 0
        try:
            self.mod.main()
        except SystemExit as e:
            kod = e.code if isinstance(e.code, int) else 1
        except Mimo as e:
            self.mimo.append(str(e))
            kod = "Mimo"
        except Exception as e:   # сторож не должен ронять прогон
            self.mimo.append("исключение наружу: %s %s" % (type(e).__name__, e))
            kod = "исключение"
        finally:
            sys.stdout = stdout
            self.zhurnal.append(bufer.getvalue())
            urllib.request.urlopen = REAL_URLOPEN
            socket.create_connection = REAL_CONNECT
            imaplib.IMAP4_SSL = REAL_IMAP4_SSL
            imaplib.IMAP4 = REAL_IMAP4
            for k, v in sohr.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v
        self.kody_vyhoda.append(kod)
        if open(self.state).read() != do:
            self.izmenenij += 1

    def gnat(self, minut_vsego, shag=2, kom="prohod"):
        start = len(self.kody_vyhoda)
        n0 = round(self.minuta())
        for i in range(0, int(minut_vsego / shag) + 1):
            self.chasy[0] = self.nachalo + (n0 + i * shag) * 60
            self.prohod(kom)
        return self.kody_vyhoda[start:]

    def sost(self):
        return json.load(open(self.state))

    def soobshch(self, ot=0, do=1e9):
        return [(m, t) for m, t in self.soobshcheniya if ot <= m < do]

    def novye(self, n):
        """Сообщения после n-го - то, что пришло на продолжении сценария."""
        return self.soobshcheniya[n:]


def s_server_ip(ip, f):
    """f() при переменной SERVER_IP = ip (None - переменной нет): сторож читает её при загрузке."""
    bylo = os.environ.pop("SERVER_IP", None)
    if ip is not None:
        os.environ["SERVER_IP"] = ip
    try:
        return f()
    finally:
        os.environ.pop("SERVER_IP", None)
        if bylo is not None:
            os.environ["SERVER_IP"] = bylo


def zagruzit(put, stend):
    imya = "storozh_stend_%d" % id(stend)
    spec = importlib.util.spec_from_file_location(imya, put)
    mod = importlib.util.module_from_spec(spec)
    s_server_ip(stend.server_ip_env, lambda: spec.loader.exec_module(mod))
    mod.STATE = stend.state

    class Chasy(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(stend.chasy[0], tz)

    def spat(sek):
        stend.chasy[0] += sek

    mod.datetime = Chasy
    mod.time = types.SimpleNamespace(time=lambda: stend.chasy[0], sleep=spat)
    mod.subprocess = types.SimpleNamespace(run=stend.mimo_fn("subprocess.run"),
                                           TimeoutExpired=subprocess.TimeoutExpired)
    mod.curl_kod = stend.curl_kod
    mod.sweb = stend.sweb
    mod.tg = stend.tg
    mod.zaglushka_ok = stend.zaglushka_ok
    if hasattr(mod, "rezhim_dns"):
        mod.rezhim_dns = stend.rezhim_dns
    return mod


def staryj_put(argv):
    """Старый storozh.py для контроля: --staryj файл или последняя версия из git с server_zhiv."""
    if "--staryj" in argv:
        return argv[argv.index("--staryj") + 1]
    git = lambda *a: REAL_RUN(["git", "-C", PAPKA] + list(a), capture_output=True, text=True)
    for h in [x for x in git("log", "--format=%H", "--", "./storozh.py").stdout.split() if x]:
        tekst = git("show", "%s:./storozh.py" % h).stdout
        if "def server_zhiv(" in tekst:
            put = os.path.join(tempfile.mkdtemp(prefix="stend-staryj-"), "storozh_staryj.py")
            with open(put, "w") as f:
                f.write(tekst)
            print("контроль: старая версия из git %s" % h[:7])
            return put
    return None


def postoyanno(g, h):
    return lambda m: (g, h)


# --- сценарии ----------------------------------------------------------------------------

def scenarij_a(put, health, imya):
    print("\n%s. Ночь, 3 ч главная 200, health %s, прогон раз в 2 мин" % (imya, health))
    st = Stend(put, NOCH_START, postoyanno("200", health), sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(180)
    s3 = st.soobshch()
    proverit(not st.editmain, "ни одного editMain (адрес сайта не тронут): %d" % len(st.editmain))
    proverit(st.tokeny == 0, "ни одного входа в SpaceWeb: %d" % st.tokeny)
    # ночью на 60-й переключает запасной сервер (rabota) - сторож говорит на 75-й, если тот не смог
    proverit(len(s3) == 1 and 75 <= s3[0][0] <= 77 and s3[0][1].startswith("🟠 Кабинет"),
             "Ивану ровно одно сообщение на 75-й минуте: %s" % [(int(m), t[:40]) for m, t in s3])
    proverit(st.izmenenij <= 3, "состояние меняется редко (коммитов за 3 ч): %d" % st.izmenenij)
    st.server = postoyanno("200", "200")
    n = len(st.soobshcheniya)
    st.gnat(10)
    s4 = st.novye(n)
    proverit(len(s4) == 1 and s4[0][1].startswith("🟢 Кабинет снова отвечает"),
             "кабинет ожил - одно «🟢»: %s" % [t[:45] for m, t in s4])
    proverit(st.sost() == {"samoproverka": "2026-10-19"}, "состояние чистое после аварии: %s" % st.sost())
    proverit(not st.mimo and set(st.kody_vyhoda) == {0}, "без вызовов мимо, коды 0: %s" % (st.mimo[:2] or "ок"))
    return st


def scenarij_a_kratko(put):
    print("\nA3. Движок лежит 30 мин и ожил - Ивану ничего, «🟢» только если было сообщение")
    st = Stend(put, NOCH_START, lambda m: ("200", "503" if m < 30 else "200"), sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(50)
    proverit(not st.soobshcheniya and not st.editmain, "тишина и адрес не тронут: %s" % st.soobshcheniya)


def scenarij_b(put):
    print("\nB. День, 3 ч главная 200, health 503")
    st = Stend(put, DEN_START, postoyanno("200", "503"), sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(180)
    s3 = st.soobshch()
    proverit(not st.editmain and st.tokeny == 0, "адрес не тронут, входов в SpaceWeb нет")
    proverit(len(s3) == 1 and 60 <= s3[0][0] <= 62, "ровно одно сообщение на 60-й минуте: %s"
             % [(int(m), t[:40]) for m, t in s3])
    proverit(not st.mimo, "без вызовов мимо")


def scenarij_c(put):
    print("\nC. Ночь, главная 000, из России тоже лежит")
    st = Stend(put, NOCH_START, postoyanno("000", "000"), sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(100)
    s = st.soobshch()
    proverit(s and 15 <= s[0][0] <= 17 and s[0][1].startswith("🟠 Сайт не отвечает"),
             "«🟠» на 15-й минуте: %s" % [(int(m), t[:30]) for m, t in s[:1]])
    zagl = [e for e in st.editmain if e[2] == ZAGL_IP]
    proverit(len(zagl) == 2 and {e[1] for e in zagl} == {1, 2} and all(90 <= e[0] <= 94 for e in zagl),
             "на 90-й минуте (после запасного сервера) обе записи -> 77.222.62.121: %s" % [(int(e[0]), e[1], e[2]) for e in st.editmain])
    proverit(len(st.editmain) == 2, "больше правок нет до конца сценария (100 мин)")
    proverit(sum(1 for m, t in s if ZAGLUSHKA_TEXT in t) == 1, "одно сообщение «Включил заглушку»")
    proverit(any("check-host.net/check-http?host=https://doctorpavlovskii.ru/&" in a for a in st.adresa)
             and any(b'"path": "/"}' in x for x in st.tela) and not any(b"/blog/api/health" in x for x in st.tela),
             "check-host и globalping меряют главную, а не health")
    proverit(not st.mimo, "без вызовов мимо: %s" % (st.mimo[:2] or "ок"))
    return st


def scenarij_d(put):
    print("\nD. Ночь, главная 000, проверить из России не удалось")
    st = Stend(put, NOCH_START, postoyanno("000", "000"), rossiya=lambda m: None,
               sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(100)
    s = st.soobshch()
    proverit(s and 15 <= s[0][0] <= 17, "«🟠» на 15-й минуте")
    proverit(any(60 <= m <= 62 and "проверить из России не удалось" in t for m, t in s),
             "на 60-й «проверить из России не удалось»")
    # Проверка из России идёт раз в 15 мин (60, 76, 92) - при прогоне раз в 2 мин 90-я минута это 92-я.
    proverit(st.editmain and all(90 <= e[0] <= 93 for e in st.editmain) and len(st.editmain) == 2,
             "заглушка на 90-й минуте: %s" % [(int(e[0]), e[1]) for e in st.editmain])
    proverit(not st.mimo, "без вызовов мимо")


def scenarij_e(put):
    print("\nE. На заглушке главная 200, health 503 полчаса - сайт возвращается на сервер")
    st = Stend(put, NOCH_START, postoyanno("200", "503"), zona="zaglushka",
               sostoyanie={"samoproverka": "2026-10-19", "na_zaglushke_s": NOCH_START - 3600})
    st.gnat(40)
    proverit([(e[1], e[2]) for e in st.editmain] == [(1, SERVER_IP), (2, SERVER_IP)]
             and all(30 <= e[0] <= 32 for e in st.editmain),
             "на 30-й минуте обе записи -> 2.31.62.117: %s" % [(int(e[0]), e[1], e[2]) for e in st.editmain])
    s = st.soobshch()
    proverit(len(s) == 1 and "вернул сайт с заглушки" in s[0][1] and "Кабинет пока не отвечает" in s[0][1],
             "одно сообщение с хвостом «кабинет пока не отвечает»: %s" % [t[:60] for m, t in s])
    proverit(st.tokeny == 1, "вход в SpaceWeb только для возврата: %d" % st.tokeny)
    n = len(st.soobshcheniya)
    st.gnat(70)
    s2 = st.novye(n)
    proverit(len(s2) == 1 and s2[0][1].startswith("🟠 Кабинет"), "кабинет не ожил за час после возврата - одно «🟠»: %s"
             % [(int(m), t[:30]) for m, t in s2])
    print("\nE2. На заглушке главная мигнула на 20-й минуте - отсчёт 30 минут заново")
    st2 = Stend(put, NOCH_START, lambda m: ("000", "000") if 19 < m < 21 else ("200", "200"), zona="zaglushka",
                sostoyanie={"samoproverka": "2026-10-19", "na_zaglushke_s": NOCH_START - 3600})
    st2.gnat(60)
    proverit(st2.editmain and all(52 <= e[0] <= 54 for e in st2.editmain),
             "возврат через 30 мин после сбоя (на 52-й): %s" % [int(e[0]) for e in st2.editmain])
    proverit(not st.mimo and not st2.mimo, "без вызовов мимо")
    print("\nE3. Вернуть с заглушки не вышло, потом сайт вернули руками в панели SpaceWeb")
    st3 = Stend(put, NOCH_START, postoyanno("200", "200"), zona="zaglushka", edit_slomana=lambda m: True,
                sostoyanie={"samoproverka": "2026-10-19", "na_zaglushke_s": NOCH_START - 3600})
    st3.gnat(40)
    ne = [t for m, t in st3.soobshcheniya if "вернуть сайт с заглушки не вышло" in t]
    proverit(len(ne) == 1, "одно «вернуть сайт с заглушки не вышло»: %d" % len(ne))
    st3.zona_ip = SERVER_IP
    st3.istoriya.append((st3.chasy[0], SERVER_IP))
    st3.gnat(6)
    proverit(st3.sost() == {"samoproverka": "2026-10-19"} and len(st3.soobshcheniya) == 1,
             "состояние догнало панель и чистое: %s" % st3.sost())
    proverit(not st3.mimo, "без вызовов мимо")


def scenarij_f(put):
    print("\nF. Ночь, норма, один плохой замер (окно boj, главная 502)")
    st = Stend(put, NOCH_START, lambda m: ("502", "502") if 9 < m < 11 else ("200", "200"),
               sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(40)
    proverit(not st.soobshcheniya and not st.editmain and st.tokeny == 0, "тишина, адрес и SpaceWeb не тронуты")
    print("\nF2. Три плохих прогона подряд (6 мин), health 503 и 502")
    st2 = Stend(put, NOCH_START, lambda m: ("502", "-") if 9 < m < 15 else ("200", "503" if 15 <= m < 19 else "200"),
                sostoyanie={"samoproverka": "2026-10-19"})
    st2.gnat(40)
    proverit(not st2.soobshcheniya and not st2.editmain, "тишина: %s" % st2.soobshcheniya)
    proverit(st2.sost() == {"samoproverka": "2026-10-19"}, "состояние чистое")
    proverit(not st.mimo and not st2.mimo, "без вызовов мимо")


def scenarij_g(put):
    print("\nG. Чужие команды и ручные без кода")
    zhiv = postoyanno("200", "200")
    for kom, env, opis in [
            ("x; id", {}, "команда «x; id»"),
            ("na-zaglushku", {}, "na-zaglushku без кода и без секрета"),
            ("na-zaglushku", {"RUCHNOJ_KOD": "", "KOD": ""}, "na-zaglushku, секрет пуст и код пуст"),
            ("na-zaglushku", {"RUCHNOJ_KOD": "verno-123"}, "na-zaglushku без кода"),
            ("na-zaglushku", {"RUCHNOJ_KOD": "verno-123", "KOD": "ne-to"}, "na-zaglushku с неверным кодом"),
            ("na-server", {"RUCHNOJ_KOD": "verno-123", "KOD": "ne-to"}, "na-server с неверным кодом")]:
        st = Stend(put, NOCH_START, zhiv, env=env, sostoyanie={"samoproverka": "2026-10-19"})
        st.prohod(kom)
        proverit(st.kody_vyhoda == [1] and not st.editmain and not st.soobshcheniya and st.tokeny == 0
                 and not st.adresa and not st.mimo, "%s: отказ, ни одного вызова (код %s)" % (opis, st.kody_vyhoda))
    sob = os.path.join(tempfile.mkdtemp(prefix="stend-sob-"), "event.json")
    with open(sob, "w") as f:
        json.dump({"inputs": {"deistvie": "na-zaglushku", "kod": "verno-123"}}, f)
    st = Stend(put, NOCH_START, zhiv, env={"RUCHNOJ_KOD": "verno-123", "GITHUB_EVENT_PATH": sob, "KOD": "ne-to"},
               sostoyanie={"samoproverka": "2026-10-19"})
    st.prohod("na-zaglushku")
    proverit(st.kody_vyhoda == [0] and len(st.editmain) == 2 and any(ZAGLUSHKA_TEXT in t for m, t in st.soobshcheniya),
             "na-zaglushku с верным кодом из файла события GitHub - выполнена")
    with open(sob, "w") as f:
        json.dump({"inputs": {"deistvie": "na-zaglushku"}}, f)
    st = Stend(put, NOCH_START, zhiv, env={"RUCHNOJ_KOD": "verno-123", "GITHUB_EVENT_PATH": sob, "KOD": "verno-123"},
               sostoyanie={"samoproverka": "2026-10-19"})
    st.prohod("na-zaglushku")
    proverit(st.kody_vyhoda == [1] and not st.editmain, "в GitHub код из env KOD не принимается (только из события)")


def scenarij_h(put):
    print("\nH. Ночь, сервер лежит, DNS SpaceWeb отстаёт от правки на 20 мин")
    st = Stend(put, NOCH_START, postoyanno("000", "000"), dns_lag=20, sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(110)
    proverit(len(st.editmain) == 2, "правок ровно 2: %d" % len(st.editmain))
    proverit(sum(1 for m, t in st.soobshcheniya if ZAGLUSHKA_TEXT in t) == 1, "одно «Включил заглушку», без повторов")
    proverit(st.tokeny <= 13, "входы в SpaceWeb только на время расхождения: %d" % st.tokeny)
    proverit(not st.mimo, "без вызовов мимо")


def scenarij_i(put):
    print("\nI. Сторож сам сломался: DNS не читается и вход в SpaceWeb не работает 40 мин")
    st = Stend(put, NOCH_START, postoyanno("200", "200"), dns_slomana=True, tok_slomana=lambda m: m < 40,
               sostoyanie={"samoproverka": "2026-10-19"})
    kody = st.gnat(38)
    s = st.soobshch()
    proverit(set(kody) == {0}, "каждый прогон завершён кодом 0: %s" % sorted(set(map(str, kody))))
    proverit(len(s) == 1 and 30 <= s[0][0] <= 32 and s[0][1].startswith("⚠️ Сторож сайта сам сломался"),
             "одно «сторож сам сломался» на 30-й минуте: %s" % [(int(m), t[:30]) for m, t in s])
    n = len(st.soobshcheniya)
    st.gnat(6)
    s2 = st.novye(n)
    proverit(len(s2) == 1 and s2[0][1].startswith("🟢 Сторож сайта снова работает"), "починился - одно «🟢»")
    proverit(not st.mimo, "без вызовов мимо")


def scenarij_j(put):
    print("\nJ. Ночь, сервер лежит, SpaceWeb не принимает правку адреса")
    st = Stend(put, NOCH_START, postoyanno("000", "000"), edit_slomana=lambda m: True,
               sostoyanie={"samoproverka": "2026-10-19"})
    kody = st.gnat(150)
    ne = [(m, t) for m, t in st.soobshcheniya if "Включить заглушку не вышло" in t]
    proverit(len(ne) == 1 and 90 <= ne[0][0] <= 94, "одно «включить заглушку не вышло»: %s" % [int(m) for m, t in ne])
    proverit(set(kody) == {0} and not any(ZAGLUSHKA_TEXT in t for m, t in st.soobshcheniya),
             "коды 0, ложного «Включил заглушку» нет")
    proverit(not st.mimo, "без вызовов мимо")


def run_(start_iso, conclusion="success"):
    return {"run_started_at": start_iso, "created_at": start_iso, "conclusion": conclusion, "status": "completed"}


def scenarij_k(put):
    print("\nK. Самопроверка: самый длинный перерыв между прогонами за сутки")
    t0 = datetime(2026, 10, 20, 9, 10, tzinfo=MADRID).timestamp()
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rovno = [run_(iso(t0 - 86000 + i * 120)) for i in range(0, 716)]
    s_dyroj = [r for r in rovno if not (40000 < iso_sek(r["run_started_at"]) - (t0 - 86000) < 40840)]
    s_dyroj.append(run_(iso(t0 - 86000 + 40400), "cancelled"))   # отменённый внутри дыры не в счёт
    for imya, runs, ozhid in [("ровный ритм 2 мин", rovno, False), ("дыра 16 мин", s_dyroj, True)]:
        st = Stend(put, t0, postoyanno("200", "200"), ru_vse=True, runs=runs,
                   sostoyanie={"budilnik_s": t0 - 5 * 86400})
        bufer = io.StringIO()
        stdout, sys.stdout = sys.stdout, bufer
        try:
            st.prohod("budilnik")
        finally:
            sys.stdout = stdout
        vyvod = bufer.getvalue()
        stroka = [l for l in vyvod.splitlines() if "самый длинный перерыв" in l]
        bedy = [t for m, t in st.soobshcheniya if "перерыв между проверками" in t]
        proverit(stroka and (bool(bedy) == ozhid), "%s: в логе «%s», беда в самопроверке: %s"
                 % (imya, stroka[0].split("сутки ")[-1] if stroka else "-", "да" if bedy else "нет"))
        proverit(not st.mimo and st.sost().get("samoproverka") == "2026-10-20", "%s: без вызовов мимо" % imya)
    st = Stend(put, t0, postoyanno("200", "200"), ru_vse=True, runs=[], sostoyanie={},
               env={"GITHUB_EVENT_NAME": "workflow_dispatch"})
    st.prohod()
    proverit(not st.soobshcheniya and "budilnik_s" not in st.sost() and st.kody_vyhoda == [0],
             "ручной prohod (выкат) ритм не включает: перерыв не считается, Ивану не пишется")
    st = Stend(put, t0 + 86400, postoyanno("200", "200"), ru_vse=True, runs=[], sostoyanie={})
    st.prohod("budilnik")
    proverit(st.sost().get("budilnik_s") == t0 + 86400 and st.kody_vyhoda == [0] and not st.soobshcheniya,
             "первый запуск командой budilnik ставит начало ритма, сам проходит как prohod")
    st = Stend(put, t0, postoyanno("200", "200"), ru_vse=True, runs=[], dns_slomana=True, sostoyanie={})
    st.prohod()
    proverit(any("не читается у DNS SpaceWeb" in t for m, t in st.soobshcheniya), "DNS SpaceWeb не читается - беда")


def iso_sek(x):
    return datetime.strptime(x + "+0000", "%Y-%m-%dT%H:%M:%SZ%z").timestamp()


# --- почта inbox@ пока сайт на заглушке (пункт 3.5) -------------------------------------------

ZAGL_VKL = NOCH_START - 600            # заглушку включили за 10 мин до начала сценария
SHAPKA = "📧 Пока сайт на заглушке, на inbox@doctorpavlovskii.ru пришло письмо."
HVOST = "Ответить можно с любой своей почты прямо на адрес отправителя."
TEKST_MARII = ("Здравствуйте, доктор! Сайт не открывается, поэтому пишу сюда. Сегодня утром давление было "
               "160/100, пульс 92, голова тяжёлая. Таблетки пью по схеме, вечернюю приняла вовремя. "
               "Подскажите, пожалуйста, что делать до нашей встречи и нужно ли что-то менять в схеме "
               "приёма, или подождать до четверга. Спасибо большое, с уважением, Мария. "
               "P.S. Дневник давления за неделю пришлю отдельным письмом.")


def starye_pisma():
    """3 старых письма: два непрочитанных с осени (в ящике их 18 с 31.08) и одно за 20 мин до заглушки."""
    return [pismo(11, datetime(2026, 8, 31, 9, 0, tzinfo=MADRID).timestamp(), "old1@example.ru", "Old 1", "old 1"),
            pismo(12, datetime(2026, 9, 15, 18, 0, tzinfo=MADRID).timestamp(), "old2@example.ru", "Old 2", "old 2"),
            pismo(13, ZAGL_VKL - 1200, "old3@example.ru", "Old 3", "old 3")]


def pismo_marii(uid, kogda):
    return pismo(uid, kogda, email.utils.formataddr(("Мария Иванова", "maria@example.ru")),
                 b_slovo("Давление 160/100 утром"), TEKST_MARII)


def pismo_petra(uid, kogda):
    telo = ("<html><head><style>p {color: red}</style><title>Письмо</title></head><body>"
            "<p>Добрый&nbsp;день!</p><p>Сайт <b>не открывается</b>, а мне нужна запись &laquo;на четверг&raquo;."
            "</p><br>Спасибо<!-- подпись --></body></html>")
    return pismo(uid, kogda, "%s <petr@example.org>" % q_slovo("Пётр Сидоров"),
                 b_slovo("Срочно: не могу записаться"), telo, tip="html", vlozhenie=True)


def stend_pochta(**k):
    k.setdefault("zona", "zaglushka")
    k.setdefault("sostoyanie", {"samoproverka": "2026-10-19", "na_zaglushke_s": ZAGL_VKL})
    k.setdefault("env", {"SWEB_INBOX_PASSWORD": PAROL_INBOX})
    server = k.pop("server", postoyanno("000", "000"))
    return Stend(NOVYJ, NOCH_START, server, **k)


def pochta_soobshch(st, ot=0):
    return [t for m, t in st.soobshcheniya[ot:] if t.startswith("📧")]


def scenarij_p1():
    print("\nP1. Сайт на заглушке, в ящике 3 старых письма, потом приходят два новых")
    st = stend_pochta(yashchik=starye_pisma())
    st.gnat(4)
    proverit(not pochta_soobshch(st) and len(st.imap_podkl) == 3,
             "старые письма Ивану не пересказаны, ящик смотрел каждый проход: подключений %d" % len(st.imap_podkl))
    p = st.imap_podkl[0]
    proverit(p["host"] == "imap.spaceweb.ru" and p["port"] == 993 and p["timeout"] == 20
             and isinstance(p["ssl_context"], ssl.SSLContext) and p["ssl_context"].verify_mode == ssl.CERT_REQUIRED
             and p["ssl_context"].check_hostname,
             "IMAP imap.spaceweb.ru:993, таймаут 20 с, сертификат проверяется (пароль не уйдёт подделке)")
    zaprosy = [a[1] for a in st.imap_komandy if a[0] == "FETCH"]
    proverit(zaprosy and all(z == "13" for z in zaprosy),
             "письма с 31.08 и 15.09 отсекает поиск по дате, время смотрю только у письма дня заглушки: %s"
             % sorted(set(zaprosy)))
    st.yashchik.append(pismo_marii(14, st.chasy[0] + 30))
    n = len(st.soobshcheniya)
    st.gnat(2)
    s1 = pochta_soobshch(st, n)
    stroki = s1[0].split("\n") if s1 else []
    proverit(len(s1) == 1, "новое письмо - ровно одно сообщение Ивану: %d" % len(s1))
    proverit(stroki[:3] == [SHAPKA, "От: Мария Иванова <maria@example.ru>", "Тема: Давление 160/100 утром"]
             and stroki[-1:] == [HVOST] and len(stroki) == 5, "От, Тема, шапка и хвост на месте: %s" % stroki[:3])
    citata = stroki[3] if len(stroki) == 5 else ""
    proverit(citata.startswith("«Здравствуйте, доктор! Сайт не открывается") and citata.endswith("…»")
             and len(citata) - 2 <= 300, "начало текста в «», до 300 знаков: %d знаков" % (len(citata) - 2))
    proverit(st.sost().get("pochta_uid") == ["14"], "в состоянии UID письма: %s" % st.sost().get("pochta_uid"))
    n = len(st.soobshcheniya)
    st.gnat(10)
    proverit(not pochta_soobshch(st, n), "следующие проходы - без повтора")
    st.yashchik.append(pismo_petra(15, st.chasy[0] + 10))
    n = len(st.soobshcheniya)
    st.gnat(2)
    s2 = pochta_soobshch(st, n)
    stroki = s2[0].split("\n") if s2 else []
    proverit(len(s2) == 1, "второе новое письмо - ещё одно сообщение: %d" % len(s2))
    proverit(stroki[1:3] == ["От: Пётр Сидоров <petr@example.org>", "Тема: Срочно: не могу записаться"],
             "тема =?utf-8?b?...?= и имя =?utf-8?q?...?= раскодированы: %s" % stroki[1:3])
    proverit(len(stroki) == 5 and stroki[3] == "«Добрый день! Сайт не открывается, а мне нужна запись «на четверг». "
             "Спасибо»", "html-тело без тегов, стилей и вложения: %s" % (stroki[3:4] or "-"))
    proverit(st.sost().get("pochta_uid") == ["14", "15"], "в состоянии оба UID")
    proverit(not any(p["prochitano"] for p in st.yashchik), "ни одно письмо не стало прочитанным (гейт-бот увидит все)")
    zhurnal = "".join(st.zhurnal)
    proverit(PAROL_INBOX not in zhurnal and "maria@example.ru" not in zhurnal and "Сидоров" not in zhurnal
             and "160/100" not in zhurnal, "в публичный журнал не попали пароль, адрес, имя и текст письма")
    proverit(not st.mimo and set(st.kody_vyhoda) == {0}, "без вызовов мимо, коды 0: %s" % (st.mimo[:2] or "ок"))
    print("\nP1. ...сервер ожил - сайт вернулся с заглушки")
    st.server = postoyanno("200", "200")
    st.gnat(34)
    proverit(any("вернул сайт с заглушки" in t for m, t in st.soobshcheniya) and "pochta_uid" not in st.sost(),
             "после возврата с заглушки список UID очищен: %s" % st.sost())
    podkl = len(st.imap_podkl)
    st.yashchik.append(pismo_marii(16, st.chasy[0] + 10))
    n = len(st.soobshcheniya)
    st.gnat(10)
    proverit(len(st.imap_podkl) == podkl and not pochta_soobshch(st, n),
             "на сервере ящик больше не открывается, письмо читает гейт-бот")
    proverit(not st.mimo and set(st.kody_vyhoda) == {0}, "без вызовов мимо, коды 0")


def scenarij_p2():
    for rezhim, opis in (("net", "imap.spaceweb.ru не отвечает"), ("parol", "пароль ящика не принят")):
        print("\nP2. На заглушке %s, сервер ожил" % opis)
        st = stend_pochta(server=postoyanno("200", "200"), imap_rezhim=rezhim,
                          yashchik=starye_pisma() + [pismo_marii(14, NOCH_START + 60)])
        kody = st.gnat(40)
        zhurnal = "".join(st.zhurnal)
        proverit(set(kody) == {0} and not st.mimo, "%s: каждый прогон - код 0, без вызовов мимо" % rezhim)
        proverit(not pochta_soobshch(st) and len(st.soobshcheniya) == 1
                 and "вернул сайт с заглушки" in st.soobshcheniya[0][1] and len(st.editmain) == 2,
                 "%s: Ивану о почте ничего, проход отработал - сайт вернулся на 30-й минуте" % rezhim)
        proverit("почта inbox: проверить не вышло" in zhurnal and PAROL_INBOX not in zhurnal
                 and "sboj_s" not in st.sost(), "%s: строка в журнал без пароля, «сторож сломался» не копится" % rezhim)


def scenarij_p3():
    print("\nP3. На заглушке, новое письмо есть, а пароля ящика нет")
    st = stend_pochta(env={}, yashchik=[pismo_marii(14, NOCH_START + 60)])
    st.gnat(10)
    proverit(not st.imap_podkl and not st.soobshcheniya and not st.mimo and set(st.kody_vyhoda) == {0},
             "без пароля проверки нет: подключений %d, сообщений %d" % (len(st.imap_podkl), len(st.soobshcheniya)))
    st = stend_pochta(env={"SWEB_INBOX_PASSWORD": ""}, yashchik=[pismo_marii(14, NOCH_START + 60)])
    st.gnat(4)
    proverit(not st.imap_podkl and not st.mimo, "пустой секрет (GitHub без секрета) - то же самое")


def scenarij_p4():
    print("\nP4. Режим «сервер»: пароль есть, в ящике новое письмо - IMAP не трогается вовсе")
    for imya, server in (("жив", postoyanno("200", "200")), ("лежит движок", postoyanno("200", "503")),
                         ("лежит главная", postoyanno("000", "000"))):
        st = stend_pochta(zona="server", server=server, sostoyanie={"samoproverka": "2026-10-19"},
                          yashchik=[pismo_marii(14, NOCH_START + 60)])
        st.gnat(20)
        proverit(not st.imap_podkl and not pochta_soobshch(st) and not st.mimo,
                 "сервер %s: подключений к ящику %d" % (imya, len(st.imap_podkl)))
    st = stend_pochta(yashchik=[pismo_marii(14, NOCH_START + 60)])
    st.zona_ip = "5.6.7.8"
    st.istoriya.append((st.chasy[0] - 1, "5.6.7.8"))
    st.gnat(10)
    proverit(not st.imap_podkl and not st.mimo and "na_zaglushke_s" in st.sost(),
             "адрес сайта руками на другом сервере (отметка заглушки осталась) - ящик тоже не открывается")


def scenarij_p8():
    print("\nP8. Сайт на заглушке, проход упал (DNS и вход в SpaceWeb не работают) - почта всё равно доходит")
    st = stend_pochta(yashchik=[pismo_marii(14, NOCH_START + 60)], dns_slomana=True, tok_slomana=lambda m: True)
    kody = st.gnat(4)
    proverit(len(pochta_soobshch(st)) == 1 and set(kody) == {0} and "sboj_s" in st.sost() and not st.mimo,
             "по состоянию сайт на заглушке: одно сообщение о письме, коды 0, сбой прохода копится как раньше")


def scenarij_p5():
    print("\nP5. Telegram не принял сообщение о письме - повтор на следующем проходе, без дублей")
    st = stend_pochta(yashchik=[pismo_marii(14, NOCH_START - 60)], tg_slomana=lambda m: m < 3)
    st.gnat(10)
    proverit(len(st.tg_otkazy) == 2 and len(pochta_soobshch(st)) == 1 and st.sost().get("pochta_uid") == ["14"],
             "2 отказа Telegram, потом ровно одно сообщение: %d" % len(pochta_soobshch(st)))


def scenarij_p6():
    print("\nP6. Список UID не длиннее 200, выпавшие из него письма Ивану не повторяются")
    yashchik = [pismo(u, ZAGL_VKL + u, "a%d@example.ru" % u, "T%d" % u, "t%d" % u) for u in range(1, 202)]
    st = stend_pochta(yashchik=yashchik, sostoyanie={"samoproverka": "2026-10-19", "na_zaglushke_s": ZAGL_VKL,
                                                     "pochta_uid": [str(u) for u in range(1, 201)]})
    st.gnat(6)
    uid = st.sost().get("pochta_uid") or []
    s = pochta_soobshch(st)
    proverit(len(s) == 1 and "a201@example.ru" in s[0], "одно сообщение - о письме 201: %d" % len(s))
    proverit(len(uid) == 200 and uid[-1] == "201" and "1" not in uid, "в состоянии 200 UID, старейший выпал")
    proverit(not st.mimo and set(st.kody_vyhoda) == {0}, "без вызовов мимо")


def scenarij_p7():
    print("\nP7. Одно письмо не разбирается, другое не отдаётся - остальные доходят")
    kriv = pismo(21, NOCH_START + 10, None, None, None, syroe=(
        "From: =?x-neizvestnaya?b?%s?= <kriv@example.ru>\r\nSubject: =?x-neizvestnaya?b?%s?=\r\n"
        "Content-Type: text/plain; charset=\"x-neizvestnaya\"\r\n\r\n" % (
            base64.b64encode("Кривой".encode()).decode(), base64.b64encode("Кривая тема".encode()).decode())
    ).encode() + "Текст в неизвестной кодировке".encode())
    st = stend_pochta(yashchik=[kriv, pismo_marii(22, NOCH_START + 20), pismo_petra(23, NOCH_START + 30)])
    st.imap_ne_otdaet.add(22)
    st.gnat(2)
    s = pochta_soobshch(st)
    proverit(len(s) == 3, "три письма - три сообщения: %d" % len(s))
    proverit(len(s) == 3 and "kriv@example.ru" in s[0] and "Тема: Кривая тема" in s[0]
             and "«Текст в неизвестной кодировке»" in s[0], "неизвестная кодировка - разобрано как utf-8")
    proverit(len(s) == 3 and "От: (не разобрал)" in s[1] and "Тема: (не разобрал)" in s[1] and HVOST in s[1],
             "письмо не отдалось - сообщение с пометкой «не разобрал»")
    proverit(len(s) == 3 and "От: Пётр Сидоров <petr@example.org>" in s[2], "следующее письмо разобрано полностью")
    proverit(not st.mimo and set(st.kody_vyhoda) == {0}, "без вызовов мимо")


# --- адрес сервера из переменной SERVER_IP ----------------------------------------------------

def scenarij_s():
    print("\nS. Адрес сервера из переменной репозитория SERVER_IP = %s (переезд)" % NOVYJ_IP)
    st = Stend(NOVYJ, NOCH_START, postoyanno("200", "200"), server_ip=NOVYJ_IP, sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(10)
    proverit(not st.mimo and not st.soobshcheniya and not st.editmain and st.tokeny == 0,
             "сервер на новом адресе: curl и сверка DNS - по нему, тишина: %s" % (st.mimo[:1] or "ок"))
    proverit("сервер %s zhiv" % NOVYJ_IP in "".join(st.zhurnal), "в журнале прохода - какой адрес проверяется")
    st = Stend(NOVYJ, NOCH_START, postoyanno("200", "200"), server_ip=NOVYJ_IP, zona="zaglushka",
               sostoyanie={"samoproverka": "2026-10-19", "na_zaglushke_s": NOCH_START - 3600})
    st.gnat(40)
    proverit([e[2] for e in st.editmain] == [NOVYJ_IP, NOVYJ_IP], "возврат с заглушки - на новый адрес: %s"
             % [e[2] for e in st.editmain])
    st = Stend(NOVYJ, NOCH_START, postoyanno("000", "000"), server_ip=NOVYJ_IP, sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(100)
    proverit(st.proba_ip and set(st.proba_ip) == {NOVYJ_IP} and len(st.editmain) == 2,
             "точку проверки из России спрашивает про новый адрес (?ip=), заглушка по прежним правилам")
    st = Stend(NOVYJ, NOCH_START, postoyanno("000", "000"), server_ip=NOVYJ_IP, sostoyanie={"samoproverka": "2026-10-19"})
    st.zona_ip = SERVER_IP
    st.istoriya.append((st.chasy[0] - 1, SERVER_IP))
    st.gnat(100)
    proverit(not st.editmain and st.tokeny == 0 and not st.mimo,
             "переменную сменили раньше DNS - сайт на чужом для сторожа адресе, ничего не трогает")


def kontrol(put):
    print("\nКОНТРОЛЬ. Старый storozh.py на сценарии A (ночь, главная 200, health 503)")
    if not put:
        proverit(False, "старая версия не найдена (git или --staryj)")
        return
    st = Stend(put, NOCH_START, postoyanno("200", "503"), sostoyanie={"samoproverka": "2026-10-19"})
    st.gnat(180)
    zagl = [e for e in st.editmain if e[2] == ZAGL_IP]
    proverit(len(zagl) == 2, "старый сторож включил заглушку на %s-й минуте (стенд ловит ошибку), входов в "
             "SpaceWeb за 3 ч: %d" % (int(zagl[0][0]) if zagl else "-", st.tokeny))


# --- без часов: разбор dig, проверка из России, yml ------------------------------------

def edinichnye():
    print("\nU. Разбор ответа dig, проверка из России по главной, файл workflow")
    mod = zagruzit_svezhij()
    otvety = []

    def dig(vyvody):
        it = iter(vyvody)

        def run(cmd, **k):
            otvety.append(cmd[4])
            x = next(it)
            if isinstance(x, BaseException):
                raise x
            return types.SimpleNamespace(stdout=x[0], returncode=x[1])
        mod.subprocess = types.SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
        return mod.rezhim_dns()

    proverit(dig([("2.31.62.117\n", 0)]) == "server", "dig: сервер")
    proverit(dig([(";; connection timed out; no servers could be reached\n", 9), ("77.222.62.121\n", 0)])
             == "zaglushka", "dig: ns1 молчит, ns2 - заглушка")
    proverit(dig([("", 0), ("", 0), ("", 0)]) is None, "dig: ни один NS не ответил - None (запасной путь API)")
    proverit(dig([FileNotFoundError("dig"), FileNotFoundError("dig"), FileNotFoundError("dig")]) is None,
             "dig нет в образе - None")
    proverit(dig([("2.31.62.117\n77.222.62.121\n", 0)]) == "drugoj:2.31.62.117,77.222.62.121",
             "dig: два адреса - ручная настройка")
    proverit("@ns1.spaceweb.ru" in otvety and "@ns3.spaceweb.pro" in otvety, "опрашиваются NS SpaceWeb")
    urllib.request.urlopen = lambda u, timeout=0: otvet_json({"glavnaya": "200", "blog": "503", "zhiv": False})
    try:
        r1 = mod.ru_sweb()
        urllib.request.urlopen = lambda u, timeout=0: otvet_json({"glavnaya": "000", "blog": "000", "zhiv": False})
        r2 = mod.ru_sweb()
    finally:
        urllib.request.urlopen = REAL_URLOPEN
    proverit(r1 is False and r2 is True, "проверка из России решает по главной (200 при health 503 - открывается)")

    tekst = open(YML).read()
    run_bloki, v_run, otstup = [], False, 0
    for line in tekst.splitlines():
        ind = len(line) - len(line.lstrip())
        if re.match(r"\s*(- )?run:", line):
            v_run, otstup = True, ind
            run_bloki.append(line)
            continue
        if v_run and line.strip() and ind <= otstup:
            v_run = False
        if v_run:
            run_bloki.append(line)
    proverit(run_bloki and not any("${{" in l for l in run_bloki), "yml: внутри run нет подстановок ${{ }}")
    proverit('python3 storozh.py "$DEISTVIE"' in tekst, "yml: команда в кавычках из env")
    proverit(re.search(r"checkout@v4\n\s+with:\n\s+ref: main", tekst), "yml: checkout с ref: main")
    proverit(re.search(r"deistvie:\n.*\n\s+default: \"prohod\"", tekst), "yml: по умолчанию prohod")
    proverit("actions: read" in tekst and "cancel-in-progress: false" in tekst and '"*/10 * * * *"' in tekst,
             "yml: actions: read, cancel-in-progress: false, страховка */10")
    proverit(not re.search(r"^\s+KOD:", tekst, re.M) and "inputs.kod" not in tekst,
             "yml: поле kod не попадает в env шага (публичный журнал)")
    proverit(mod.TTL is None, "TTL выключен по умолчанию")
    proverit(re.search(r"^\s+SWEB_INBOX_PASSWORD: \$\{\{ secrets\.SWEB_INBOX_PASSWORD \}\}$", tekst, re.M)
             and re.search(r"^\s+SERVER_IP: \$\{\{ vars\.SERVER_IP \}\}$", tekst, re.M),
             "yml: пароль ящика из secrets и SERVER_IP из vars - только через env")

    print("\nS0. Переменная SERVER_IP при загрузке сторожа, адрес в запросе к точке проверки из России")
    proverit(zagruzit_svezhij(None).SERVER_IP == SERVER_IP and zagruzit_svezhij("").SERVER_IP == SERVER_IP
             and zagruzit_svezhij(" \n").SERVER_IP == SERVER_IP,
             "переменной нет, она пустая (так её отдаёт GitHub) или из пробелов - прежний 2.31.62.117")
    novyj = zagruzit_svezhij(NOVYJ_IP)
    proverit(novyj.SERVER_IP == NOVYJ_IP and novyj.po_ip(NOVYJ_IP) == "server"
             and novyj.po_ip(SERVER_IP) == "drugoj:" + SERVER_IP, "SERVER_IP задана - DNS сверяется с ней")
    urly = []

    def otvet(d):
        def f(u, timeout=0):
            urly.append(u)
            return otvet_json(d)
        return f
    try:
        urllib.request.urlopen = otvet({"glavnaya": "000", "blog": "000", "zhiv": False, "ip": SERVER_IP})
        r_star = mod.ru_sweb()
        urllib.request.urlopen = otvet({"glavnaya": "000", "blog": "000", "zhiv": False, "ip": NOVYJ_IP})
        r_nov = novyj.ru_sweb()
        urllib.request.urlopen = otvet({"glavnaya": "000", "blog": "000", "zhiv": False})
        r_nov_staraya_tochka = novyj.ru_sweb()
        urllib.request.urlopen = otvet({"glavnaya": "000", "blog": "000", "zhiv": False, "ip": SERVER_IP})
        r_ne_tot = novyj.ru_sweb()
    finally:
        urllib.request.urlopen = REAL_URLOPEN
    proverit(urly[:2] == [PROBA_RU + "?ip=" + SERVER_IP, PROBA_RU + "?ip=" + NOVYJ_IP],
             "адрес сервера уходит в точку проверки: %s" % [u.split("?")[-1] for u in urly[:2]])
    proverit(r_star is True and r_nov is True, "точка проверила нужный адрес - ответ в счёт")
    proverit(r_nov_staraya_tochka is None and r_ne_tot is None,
             "точка старая (без поля ip) или проверила другой адрес - ответ не в счёт (None)")


def zagruzit_svezhij(server_ip=None):
    spec = importlib.util.spec_from_file_location("storozh_svezhij", NOVYJ)
    mod = importlib.util.module_from_spec(spec)
    s_server_ip(server_ip, lambda: spec.loader.exec_module(mod))
    return mod


def proverka_hosting():
    print("\nP0. hosting/cgi-bin/proverka.py: адрес из ?ip=, кривой не проходит (без сети)")
    zapuski = []

    def check_output(cmd, *a, **k):
        zapuski.append(cmd)
        return b"200"
    subprocess.check_output = check_output
    try:
        spec = importlib.util.spec_from_file_location("proverka_stend", PROVERKA)
        pr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pr)
        proverit(not zapuski, "загрузка модуля curl не зовёт (разбор проверяется отдельно)")
        sluchai = [("", SERVER_IP), ("ip=" + NOVYJ_IP, NOVYJ_IP),
                   ("ip=2.31.62.117", SERVER_IP), ("ip=256.1.1.1", SERVER_IP), ("ip=1.2.3", SERVER_IP),
                   ("ip=1.2.3.4.5", SERVER_IP), ("ip=1.2.3.4%0A", SERVER_IP), ("ip=1.2.3.4;id", SERVER_IP),
                   ("ip=1.2.3.4%20", SERVER_IP), ("ip=01.2.3.4", SERVER_IP), ("ip=%D9%A1.2.3.4", SERVER_IP),
                   ("ip=%s&ip=5.6.7.8" % NOVYJ_IP, SERVER_IP), ("ip=localhost", SERVER_IP),
                   ("ip=127.0.0.1", SERVER_IP), ("ip=10.0.0.5", SERVER_IP), ("ip=192.168.1.1", SERVER_IP),
                   ("ip=169.254.169.254", SERVER_IP), ("ip=0.0.0.0", SERVER_IP), ("ip=", SERVER_IP),
                   ("x=1&ip=8.8.8.8", "8.8.8.8")]
        plohie = [(q, pr.ip_iz_zaprosa(q)) for q, nado in sluchai if pr.ip_iz_zaprosa(q) != nado]
        proverit(not plohie, "строгий IPv4 публичного адреса, иначе прежний (%d случаев): %s" % (len(sluchai),
                                                                                              plohie or "ок"))
        # Старый Python хостинга: ipaddress может не быть, а до 3.9.5 он пропускал ведущие нули -
        # строгость формата держится и без него.
        pr.ipaddress = None
        bez = [(q, pr.ip_iz_zaprosa(q)) for q, nado in sluchai
               if nado == SERVER_IP and not re.search(r"ip=(127|10|192\.168|169\.254|0)\.", q)
               and pr.ip_iz_zaprosa(q) != nado]
        proverit(not bez and pr.ip_iz_zaprosa("ip=" + NOVYJ_IP) == NOVYJ_IP,
                 "без модуля ipaddress кривой формат тоже не проходит: %s" % (bez or "ок"))
        for zapros, ip in (("ip=" + NOVYJ_IP, NOVYJ_IP), ("ip=10.0.0.5%0A", SERVER_IP)):
            del zapuski[:]
            bylo = os.environ.get("QUERY_STRING")
            os.environ["QUERY_STRING"] = zapros
            stdout, bufer = sys.stdout, io.StringIO()
            sys.stdout = bufer
            try:
                runpy.run_path(PROVERKA, run_name="__main__")
            finally:
                sys.stdout = stdout
                os.environ.pop("QUERY_STRING", None)
                if bylo is not None:
                    os.environ["QUERY_STRING"] = bylo
            d = json.loads(bufer.getvalue().split("\n\n", 1)[1])
            proverit(len(zapuski) == 2 and all("doctorpavlovskii.ru:443:%s" % ip in c for c in zapuski)
                     and d == {"glavnaya": "200", "blog": "200", "zhiv": True, "ip": ip},
                     "CGI ?%s: curl --resolve на %s, в ответе ip" % (zapros, ip))
    finally:
        subprocess.check_output = REAL_CHECK_OUTPUT


def main():
    print("Стенд сторожа сайта: %s" % NOVYJ)
    edinichnye()
    scenarij_a(NOVYJ, "503", "A")
    scenarij_a(NOVYJ, "502", "A2 (до этапа 1 nginx отдаёт 502)")
    scenarij_a_kratko(NOVYJ)
    scenarij_b(NOVYJ)
    scenarij_c(NOVYJ)
    scenarij_d(NOVYJ)
    scenarij_e(NOVYJ)
    scenarij_f(NOVYJ)
    scenarij_g(NOVYJ)
    scenarij_h(NOVYJ)
    scenarij_i(NOVYJ)
    scenarij_j(NOVYJ)
    scenarij_k(NOVYJ)
    proverka_hosting()
    scenarij_p1()
    scenarij_p2()
    scenarij_p3()
    scenarij_p4()
    scenarij_p5()
    scenarij_p6()
    scenarij_p7()
    scenarij_p8()
    scenarij_s()
    kontrol(staryj_put(ARGV))
    plohie = [o for ok, o in ITOG if not ok]
    print("\nИТОГ: %d проверок, провалов %d" % (len(ITOG), len(plohie)))
    for o in plohie:
        print("  ПРОВАЛ:", o)
    return 1 if plohie else 0


if __name__ == "__main__":
    sys.exit(main())
