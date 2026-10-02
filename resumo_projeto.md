# Sistema de Autorização de Entrada de Veículo de Turismo — Guarapari/ES

## O que o sistema faz
Script Python com interface gráfica (tkinter) que gera a "Autorização de Entrada
de Veículo de Turismo" da Prefeitura de Guarapari — documento oficial baseado na
Lei 5.111/2025 e no Decreto nº 645/2025. Gera um PDF com:
- Cabeçalho com o brasão municipal
- Texto legal fixo (considerando, autorização, advertências) extraído do modelo oficial
- Tabelas com dados da excursão, do transporte e do período autorizado
- Página 2 "Senha de Acesso — Identificação de Para-brisa": placa em destaque,
  entrada, saída, Zona (ZAC) e QR Code grande, para ficar no para-brisa
- QR Code (na página 2) com link para a página de validação + hash de
  autenticidade no rodapé de todas as páginas (ver "Validação pelo QR Code")
- Brasão como marca d'água nas páginas da autorização
- Destino final com a Zona de Acesso Controlado (ZAC: Verde, Amarela ou Vermelha).
  A zona sai no PDF e no QR Code, e os horários de entrada/saída são validados
  contra as janelas da zona (Art. 17). Tabelas em `DESTINOS_ZAC` e `JANELAS_ZAC`
- Calendário (tkcalendar, em português) para as datas e seletores de hora/minuto
- Numeração sequencial automática (NNNN/AAAA, reinicia por ano), com trava
  (lock) em arquivo de controle no servidor para evitar duplicidade entre
  usuários simultâneos
- Mescla o PDF gerado com o comprovante de pagamento (PDF ou imagem) anexado
  pelo usuário, formando um documento único de duas páginas
- Salva o resultado na pasta centralizada de rede (organizada por ano/mês). Só
  se o servidor falhar, salva na Área de Trabalho e avisa para copiar o arquivo
  ao servidor depois. Só dá erro se nenhum dos dois funcionar.
- Se o servidor estiver inacessível na hora de numerar, usa um contador local
  (`%LOCALAPPDATA%\EmissorAutorizacao\_controle`) e o número sai marcado como
  provisório (`PROV-NNNN/AAAA`), para não colidir com a sequência oficial

## Stack
Python 3.12 ou 3.14 (ambos testados). O travamento antes atribuído ao Python 3.14
/ Tcl/Tk 9.0 era, na verdade, do computador de desenvolvimento (ver abaixo). Bibliotecas: `tkinter`, `reportlab` (usando Platypus/Table, não
canvas puro), `qrcode`, `pypdf`, `Pillow`, `tkcalendar`, `cryptography`.
```
py -m pip install -r requirements.txt
```

## Arquivos do projeto
- `sistema_onibus.py` — script principal
- `brasao_guarapari.png` — brasão usado no cabeçalho do PDF (precisa estar na
  mesma pasta do script, ou embutido no .exe via `--add-data`)
- `brasao_guarapari.ico` — ícone do executável

## Configuração
- O caminho do servidor fica em `emissor_config.ini`, na MESMA pasta do `.exe`
  (seção `[armazenamento]`, chave `caminho`). Trocar o servidor não exige gerar
  outro `.exe`: basta editar o arquivo e reabrir o programa. Sem o arquivo, o
  sistema usa o padrão `\\SRV-ARQ\Autorizacoes` (placeholder).
- Pasta de armazenamento precisa ter permissão de escrita para os usuários/
  máquinas que rodam o `.exe` (grupo AD sugerido: `GG-Autorizacoes-Usuarios`).
- Pasta `_controle` dentro do armazenamento é criada automaticamente pelo
  script na primeira execução (guarda `contador.txt` e o lock da numeração).

## Geração do .exe (automática)
O GitHub gera o `.exe` sozinho (`.github/workflows/gerar-exe.yml`, Windows +
Python 3.12 + versões fixadas em `requirements.txt`):
- **Pedido de junção (pull request):** gera e roda o autoteste; o `.exe` fica
  disponível para teste na aba "Actions" do pedido (por 14 dias).
- **Juntado no ramo principal:** gera, testa e publica em **Releases**
  (`EmissorAutorizacaoOnibus.exe` + `emissor_config.ini`), com versão `vN`.
- A versão aparece no título da janela do programa.
- Autoteste: `EmissorAutorizacaoOnibus.exe --autoteste` abre a janela sem
  exibi-la, gera um PDF de exemplo e grava o resultado (incluindo o caminho do
  servidor configurado) em `%TEMP%\autoteste_resultado.txt`.
- O brasão (`brasao_guarapari.png` / `.ico`) precisa estar no repositório para
  entrar no `.exe`; sem ele, o documento sai sem brasão (a geração avisa).

Geração manual (só se necessário), na pasta do projeto:
```
py -m pip install -r requirements.txt pyinstaller==6.22.3
py -m PyInstaller --onedir --windowed --name "EmissorAutorizacaoOnibus" ^
    --icon="brasao_guarapari.ico" --add-data "brasao_guarapari.png;." ^
    --add-data "validador.html;." --hidden-import babel.numbers sistema_onibus.py
```

## Distribuição
- Formato **pasta** (PyInstaller `--onedir`): `EmissorAutorizacaoOnibus.exe` + pasta
  `_internal\` com as bibliotecas já descompactadas. Abre em ~1 s, contra 2,5-7 s do
  antigo arquivo único (`--onefile`), que lia ~30 MB pela rede e descompactava tudo
  em `%TEMP%` a cada abertura (com nova análise do antivírus).
- Release publica `EmissorAutorizacaoOnibus.zip` (com o `.exe` e `_internal\` na raiz)
  e o `emissor_config.ini` de modelo. Para atualizar: desbloquear o .zip
  (Propriedades > Desbloquear) e extrair dentro da pasta do programa no servidor,
  substituindo; `emissor_config.ini` e `chave_assinatura.pem` não são tocados.
  Atualizar fora do horário de uso (arquivos em uso não podem ser substituídos).
- Atalho no Desktop dos usuários via GPO (Group Policy Preferences → Shortcuts)
  apontando para o `.exe` na pasta do servidor
- Servidor adicionado à zona "Intranet Local" via GPO (`file://VSRV-SIS-ONIBUS` = 1)
  para evitar o aviso "Deseja executar este arquivo?"; arquivos baixados da internet
  também precisam ser desbloqueados (`Unblock-File`), senão o aviso aparece sempre

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

## Validação pelo QR Code
O QR Code é um link para a página de validação publicada no site da prefeitura
(`[validacao] url` no `emissor_config.ini`). Depois do `#` vão os dados do
documento (nº, placa, tipo, empresas, destino, zona, entrada/saída, passageiros,
emissão e código de autenticidade; **sem CPF, RG ou telefone**) e uma assinatura
digital ECDSA P-256. A página (`validador.html`, arquivo único, sem dependências)
confere a assinatura no próprio celular com a chave pública embutida e mostra
"DOCUMENTO AUTÊNTICO" (com os dados e se está dentro do período) ou "DOCUMENTO
INVÁLIDO". Nada é armazenado na internet e o navegador não envia ao site a parte
depois do `#`. Não há como revogar um documento já emitido (não há banco de dados).

Implantação (uma única vez):
1. Na pasta do `.exe` no servidor: `EmissorAutorizacaoOnibus.exe --gerar-chave`.
   Cria `chave_assinatura.pem` (chave privada; fazer backup, nunca publicar) e
   `validar-autorizacao.html` (página com a chave pública e o brasão embutidos).
   O programa se recusa a sobrescrever uma chave existente.
2. A equipe do site publica o `validar-autorizacao.html` por **HTTPS** como arquivo
   estático (não colar no editor do CMS, que remove o JavaScript).
3. O endereço publicado deve ser exatamente o da linha `url` do `emissor_config.ini`
   (ele fica gravado em cada QR Code emitido; não mudar depois).
Sem a chave, o programa não emite documentos (avisa antes de consumir o número).
