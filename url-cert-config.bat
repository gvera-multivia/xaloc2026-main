@echo off
:: Forzamos codificacion para evitar problemas con el CN
chcp 65001 >nul

set "CN=35059210B MARIA TERESA MORENTE (R: B62798210)"

:: Ejecutamos comandos de forma silenciosa mandando la salida a nul
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul

reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 2 /t REG_SZ /d "{\"pattern\":\"https://servcla.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 3 /t REG_SZ /d "{\"pattern\":\"https://servpub.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 4 /t REG_SZ /d "{\"pattern\":\"https://www.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 5 /t REG_SZ /d "{\"pattern\":\"https://seu.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 6 /t REG_SZ /d "{\"pattern\":\"https://www.base.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 7 /t REG_SZ /d "{\"pattern\":\"https://www.baseonline.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 8 /t REG_SZ /d "{\"pattern\":\"https://valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 9 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 10 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 11 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 12 /t REG_SZ /d "{\"pattern\":\"https://[*.]madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 13 /t REG_SZ /d "{\"pattern\":\"https://[*.]clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 14 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 15 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 16 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul

:: Solo imprimimos esto si llegamos aqui
echo EXITOSOS