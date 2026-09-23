# Sistema de Autorização de Entrada de Veículo de Turismo — Guarapari/ES

## O que o sistema faz
Script Python com interface gráfica (tkinter) que gera a "Autorização de Entrada
de Veículo de Turismo" da Prefeitura de Guarapari — documento oficial baseado na
Lei 5.111/2025 e no Decreto nº 654/2025. Gera um PDF com:
- Cabeçalho com o brasão municipal
- Texto legal fixo (considerando, autorização, advertências) extraído do modelo oficial
- Tabelas com dados da excursão, do transporte e do período autorizado
- QR Code + hash de autenticidade (hash fixada no rodapé/margem inferior da página)
- Numeração sequencial automática (NNNN/AAAA, reinicia por ano), com trava
  (lock) em arquivo de controle no servidor para evitar duplicidade entre
  usuários simultâneos
- Mescla o PDF gerado com o comprovante de pagamento (PDF ou imagem) anexado
  pelo usuário, formando um documento único de duas páginas
- Salva o resultado em DOIS locais: pasta centralizada de rede (organizada por
  ano/mês) E Área de Trabalho do computador que executa o sistema. Se um dos
  dois falhar, o documento é salvo no outro e aparece um único aviso dizendo
  qual local falhou. Só dá erro se nenhum dos dois funcionar.
- Se o servidor estiver inacessível na hora de numerar, usa um contador local
  (`%LOCALAPPDATA%\EmissorAutorizacao\_controle`) e o número sai marcado como
  provisório (`PROV-NNNN/AAAA`), para não colidir com a sequência oficial

## Stack
Python 3.12 ou 3.14 (ambos testados). O travamento antes atribuído ao Python 3.14
/ Tcl/Tk 9.0 era, na verdade, do computador de desenvolvimento (ver abaixo). Bibliotecas: `tkinter`, `reportlab` (usando Platypus/Table, não
canvas puro), `qrcode`, `pypdf`, `Pillow`.

## Arquivos do projeto
- `sistema_onibus.py` — script principal
- `brasao_guarapari.png` — brasão usado no cabeçalho do PDF (precisa estar na
  mesma pasta do script, ou embutido no .exe via `--add-data`)
- `brasao_guarapari.ico` — ícone do executável

## Configuração pendente
- `CAMINHO_ARMAZENAMENTO` no topo do script está com valor placeholder
  (`\\SRV-ARQ\Autorizacoes`) — precisa apontar para o servidor real antes de
  ir para produção.
- Pasta de armazenamento precisa ter permissão de escrita para os usuários/
  máquinas que rodam o `.exe` (grupo AD sugerido: `GG-Autorizacoes-Write`).
- Pasta `_controle` dentro do armazenamento é criada automaticamente pelo
  script na primeira execução (guarda `contador.txt` e o lock da numeração).

## Empacotamento (.exe)
```
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "EmissorAutorizacaoOnibus" ^
    --icon="brasao_guarapari.ico" --add-data "brasao_guarapari.png;." sistema_onibus.py
```
Saída em `dist\EmissorAutorizacaoOnibus.exe` — único arquivo a distribuir.

## Distribuição planejada
- `.exe` copiado para pasta de rede somente-leitura (ex: `\\SRV-APPS\Deploy\Autorizacoes\`)
- Atalho no Desktop dos usuários via GPO (Group Policy Preferences → Shortcuts)
- Servidor adicionado à zona "Intranet Local" via GPO para evitar aviso de
  segurança do Windows ao executar .exe de rede

## Travamento da interface (investigado)
A janela congelava sozinha, sem interação, poucos segundos após abrir. Diagnóstico
com faulthandler mostrou o programa parado dentro do `mainloop` do Tk, sem nenhuma
linha do sistema em execução. Resultados:
- Computador de desenvolvimento (Windows 11 build 26200): trava com Python 3.12/Tk 8.6,
  3.14/Tk 9.0, com o `.exe` e até com `python -m tkinter` (sem código do sistema).
- VM Windows Server 2025 e outro PC com Windows 11: funciona normalmente.
Conclusão: problema do ambiente daquele computador (provável programa/recurso do
Windows interferindo), não do sistema.

Obs.: ao transferir o `.exe`, compactar em .zip (ou usar pendrive). Um `.exe`
corrompido na cópia gera o erro do PyInstaller "Error -3 while decompressing data".

## Adiado para depois
QR Code apontando para uma URL que abra o documento (hoje só guarda dados de
texto) — decisão de arquitetura pendente sobre hospedagem pública/interna e
sobre não expor o comprovante de pagamento (dados sensíveis) publicamente.
