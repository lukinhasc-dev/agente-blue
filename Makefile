# Makefile — Agente Blue
# Atalhos para compilar o agente. Requer Python + PyInstaller instalados.
# (No Windows, precisa do GNU Make. Sem make, rode os comandos powershell direto.)
#
# Uso rapido:
#   make            -> compila ONEDIR  (dev/testes)   dist\AgenteBlue\AgenteBlue.exe
#   make onefile    -> compila ONEFILE (entrega)      dist\AgenteBlue.exe   <- use no Sandbox
#   make assets     -> atualiza HTML/JS/CSS sem recompilar
#   make run        -> executa o agente compilado (onedir)
#   make clean      -> remove dist/ e build/

PS = powershell -ExecutionPolicy Bypass

.PHONY: build onefile assets run clean help

build:
	$(PS) -File compilar.ps1

onefile:
	$(PS) -File compilar.ps1 -Onefile

assets:
	$(PS) -File compilar.ps1 -AssetsOnly

run:
	$(PS) -Command "Start-Process dist\AgenteBlue\AgenteBlue.exe"

clean:
	$(PS) -Command "Remove-Item -Recurse -Force dist,build -ErrorAction SilentlyContinue"

help:
	@echo make          - compila ONEDIR  (dev)      dist\AgenteBlue\
	@echo make onefile  - compila ONEFILE (entrega)  dist\AgenteBlue.exe
	@echo make assets   - atualiza html/js/css sem recompilar
	@echo make run      - executa o agente (onedir)
	@echo make clean    - remove dist e build
