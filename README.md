# Сторож сайта doctorpavlovskii.ru

Снаружи нашего сервера: раз в 10 минут проверяет сайт. Если сервер в Германии лежит и это
подтверждено из России, переводит адрес сайта на страницу-заглушку (хостинг SpaceWeb), а когда
сервер полчаса работает - возвращает. Подробности - в начале `storozh.py`.

Здесь нет паролей: они в настройках репозитория (Secrets). Состояние - `sostoyanie/state.json` (пишет сам сторож).

## Хостинг SpaceWeb (vip49.sweb.ru, папка public_html)

`hosting/` - что лежит на хостинге: заглушка, `.htaccess` (любой адрес -> заглушка с кодом 503),
`cgi-bin/proverka.py` - точка проверки из России (http://playsicru.temp.swtest.ru/cgi-bin/proverka.py).
Заливка - FTP 77.222.62.121, вход из `~/.negipertonia/sweb-panel-login`. Python у веб-сервера старый
(без capture_output). SSH включается на 3-24 часа через API `vh/utils sshOn`. Старый сайт «Практикум» -
в `~/arhiv-praktikum-2026-10-12/` на хостинге. Сертификат AlphaSSL на хостинге до 14.12.2026 (оплачен до
06.2027) - перевыпустить; самопроверка сторожа предупредит за 14 дней.
Telegram с хостинга заблокирован, поэтому сам сторож живёт на GitHub: github.com/docpavlovskiy-svg/storozh-sajta.
Ручные команды: `gh workflow run storozh.yml -R docpavlovskiy-svg/storozh-sajta -f deistvie=na-zaglushku`
(или na-server, pokazat).
