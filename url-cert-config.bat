@echo off
:: Cambiamos el código de páginas a UTF-8 para evitar problemas con nombres y rutas
chcp 65001 >nul

set "CN=35059210B MARIA TERESA MORENTE (R: B62798210)"

echo ======================================================
echo Aplicando configuración de Certificados para Edge
echo CN: %CN%
echo ======================================================

:: Limpiamos la rama anterior para evitar conflictos de índices duplicados
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f

:: Aplicación de reglas
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 2 /t REG_SZ /d "{\"pattern\":\"https://servcla.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 3 /t REG_SZ /d "{\"pattern\":\"https://servpub.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 4 /t REG_SZ /d "{\"pattern\":\"https://www.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 5 /t REG_SZ /d "{\"pattern\":\"https://seu.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 6 /t REG_SZ /d "{\"pattern\":\"https://www.base.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 7 /t REG_SZ /d "{\"pattern\":\"https://www.baseonline.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 8 /t REG_SZ /d "{\"pattern\":\"https://valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 9 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 10 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 11 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 12 /t REG_SZ /d "{\"pattern\":\"https://[*.]madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 13 /t REG_SZ /d "{\"pattern\":\"https://[*.]clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 14 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 15 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 16 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f

echo ======================================================
echo Configuración completada con éxito.
echo ======================================================