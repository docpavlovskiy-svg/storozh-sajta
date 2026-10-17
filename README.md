# Сторож сайта doctorpavlovskii.ru

Снаружи нашего сервера: раз в 2 минуты проверяет сайт. Если сервер в Германии лежит и это
подтверждено из России, переводит адрес сайта на страницу-заглушку (хостинг SpaceWeb), а когда
главная сайта полчаса отвечает - возвращает. Подробности - в начале `storozh.py`.

Три состояния (17.10.2026): **жив** (главная и `/blog/api/health` - 200); **лежит движок** (главная 200,
health нет) - адрес сайта не трогается никогда, Ивану одно сообщение, если не ожило за час (первые
минуты это ловит сторож воркера на rabota через Дежурного); **лежит сервер** (не отвечает главная) -
заглушка по прежним правилам 12.10.

Здесь нет паролей: они в настройках репозитория (Secrets): SWEB_LOGIN, SWEB_PASSWORD, TG_TOKEN, TG_CHAT,
RUCHNOJ_KOD, SWEB_INBOX_PASSWORD. Переменная репозитория (Variables, не секрет): SERVER_IP.
Состояние - `sostoyanie/state.json` (пишет сам сторож, коммит только при изменении).

## Почта на заглушке (17.10.2026)

На заглушке клиентам дан `inbox@doctorpavlovskii.ru` (ящик SpaceWeb, IMAP `imap.spaceweb.ru:993`). Читает
его только гейт-бот с rabota, а заглушка висит, когда rabota мёртв. Поэтому, пока режим «заглушка», каждый
проход сторожа смотрит ящик и о каждом письме, пришедшем после включения заглушки (по времени прихода
письма), шлёт Ивану одно сообщение: от кого, тема, начало текста до 300 знаков. Только чтение: ящик
открыт readonly, тело - `BODY.PEEK`, флаги не трогаются, после возврата гейт-бот видит письма
непрочитанными. Старые непрочитанные письма в ящике не пересказываются. Пароль - секрет
SWEB_INBOX_PASSWORD (копия `~/.negipertonia/sweb-inbox-password` на Маке); нет секрета - проверки нет.
Сбой IMAP - только строка в журнал. В журнал прогона (он публичный) не пишутся ни отправитель, ни тема,
в состоянии - только UID писем (не больше 200, при возврате с заглушки список чистится).

## Адрес сервера: SERVER_IP

Адрес сервера сайта - переменная репозитория SERVER_IP; пустая - прежний `2.31.62.117` (rabota). По ней
идут все проверки: curl напрямую на сервер, сверка DNS, возврат с заглушки, точка проверки из России
(`proverka.py?ip=<SERVER_IP>`, отвечает полем `ip`, какой адрес проверила; старая точка без этого поля
для нового адреса не в счёт). При переезде адрес меняется в одном месте:
`gh variable set SERVER_IP -R docpavlovskiy-svg/storozh-sajta --body <адрес>` - одновременно со сменой
A-записей: пока DNS и переменная расходятся, сторож считает адрес сайта ручной настройкой и ничего
не трогает.

## Ритм: будильник cron-job.org

Расписание GitHub (`*/10`) само по себе будит 4-6 раз в сутки - оно оставлено страховкой. Основной ритм -
задание на cron-job.org раз в 2 минуты: `POST https://api.github.com/repos/docpavlovskiy-svg/storozh-sajta/actions/workflows/storozh.yml/dispatches`,
заголовки `Accept: application/vnd.github+json`, `Authorization: Bearer <ключ>`, `X-GitHub-Api-Version: 2022-11-28`,
`Content-Type: application/json`, тело `{"ref":"main","inputs":{"deistvie":"budilnik"}}`, ответ 204.
Ключ - fine-grained аккаунта docpavlovskiy-svg, только этот репозиторий, Actions: Read and write, срок 1 год;
копия - `~/.negipertonia/storozh-budilnik-github` на Маке. Письма cron-job.org о сбоях выключены: пропуски
ловит самопроверка (самый длинный перерыв между прогонами за сутки больше 10 мин - беда) и сторож Мака.

В норме прогон не входит в SpaceWeb: адрес сайта читается `dig` у NS SpaceWeb. Вход паролем - только
для переключения, `pokazat` и запасного пути, если DNS не ответил.

## Хостинг SpaceWeb (vip49.sweb.ru, папка public_html)

`hosting/` - что лежит на хостинге: заглушка, `.htaccess` (любой адрес -> заглушка с кодом 503),
`cgi-bin/proverka.py` - точка проверки из России (http://playsicru.temp.swtest.ru/cgi-bin/proverka.py);
сторож решает по её полю `glavnaya`. Адрес сервера берёт из `?ip=` (только строгий публичный IPv4,
иначе `2.31.62.117`).
Заливка - FTP 77.222.62.121, вход из `~/.negipertonia/sweb-panel-login`. Python у веб-сервера старый
(без capture_output). SSH включается на 3-24 часа через API `vh/utils sshOn`. Старый сайт «Практикум» -
в `~/arhiv-praktikum-2026-10-12/` на хостинге. Сертификат AlphaSSL на хостинге до 14.12.2026 (оплачен до
06.2027) - перевыпустить; самопроверка сторожа предупредит за 14 дней.
Telegram с хостинга заблокирован, поэтому сам сторож живёт на GitHub: github.com/docpavlovskiy-svg/storozh-sajta.

## Ручные команды

`pokazat` - без кода; `na-zaglushku` и `na-server` - только с кодом (секрет RUCHNOJ_KOD, копия на Маке
`~/.negipertonia/storozh-ruchnoj-kod`). Код идёт полем `kod` и в журнал прогона не печатается.

```
gh workflow run storozh.yml -R docpavlovskiy-svg/storozh-sajta -f deistvie=pokazat
gh workflow run storozh.yml -R docpavlovskiy-svg/storozh-sajta -f deistvie=na-zaglushku -f kod="$(cat ~/.negipertonia/storozh-ruchnoj-kod)"
gh workflow run storozh.yml -R docpavlovskiy-svg/storozh-sajta -f deistvie=na-server -f kod="$(cat ~/.negipertonia/storozh-ruchnoj-kod)"
```

## Стенд

`test_storozh.py` - без сети и без DNS (python 3.9+, на Маке `~/miniforge3/bin/python3`): сценарии
«движок лежит», «сервер лежит», возврат с заглушки, окно выката, чужие команды, сбои SpaceWeb,
самопроверка, почта на заглушке (поддельный ящик: любая запись в него, select без readonly или
FETCH тела без PEEK - провал), SERVER_IP и разбор `?ip=` в `proverka.py`; контроль - старая версия
из git на сценарии «движок лежит» обязана включить заглушку. Гонять перед каждым пушем в storozh-sajta.
