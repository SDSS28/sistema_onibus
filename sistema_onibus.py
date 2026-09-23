import io
import os
import re
import sys
import time
import uuid
import tempfile
from datetime import datetime, time as dt_time

import qrcode
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkcalendar import DateEntry
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak,
    KeepTogether
)
from pypdf import PdfWriter, PdfReader
from PIL import Image as PILImage

PADRAO_DATA = "%d/%m/%Y"
PADRAO_DATA_HORA = "%d/%m/%Y %H:%M"
PADRAO_PLACA = re.compile(r"^[A-Z]{3}-?\d[A-Z0-9]\d{2}$")  # aceita padrão antigo e Mercosul

# O brasão precisa estar na mesma pasta deste script (ou embutido no .exe via --add-data).
PASTA_SCRIPT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
CAMINHO_BRASAO = os.path.join(PASTA_SCRIPT, "brasao_guarapari.png")

# AJUSTE AQUI: caminho UNC do servidor central de armazenamento.
CAMINHO_ARMAZENAMENTO = r"\\SRV-ARQ\Autorizacoes"

# Textos fixos do documento (extraídos do modelo aprovado pela diretoria).
# Ajuste aqui se a lei, o decreto ou o signatário mudarem — não precisa tocar no resto do código.
NOME_ASSINANTE = "WELINGTON BARBOSA PESSANHA"
CARGO_ASSINANTE = "Subsecretário Municipal de Segurança, Trânsito e Transporte"

TEXTO_CONSIDERANDO = (
    "CONSIDERANDO o disposto na Lei 5.111/2025, a PREFEITURA MUNICIPAL DE GUARAPARI, por intermédio da "
    "SECRETARIA MUNICIPAL DE SEGURANÇA, TRÂNSITO E TRANSPORTE – SEMSET, no uso das atribuições legais que lhe "
    "são conferidas pela legislação municipal vigente,"
)

TEXTO_INTRO = (
    "a entrada, circulação e permanência de excursão turística no território do Município de Guarapari/ES, "
    "conforme dados abaixo especificados, mediante o cumprimento integral do Decreto nº 654/2025 e das normas "
    "de trânsito, segurança pública, ordenamento urbano e demais disposições legais aplicáveis."
)

TEXTO_ADVERTENCIA_1 = (
    "A presente autorização não exime o responsável do cumprimento das normas legais vigentes, especialmente "
    "as relativas à segurança viária, uso de áreas públicas, meio ambiente e ordem pública."
)

TEXTO_ADVERTENCIA_2 = (
    "O descumprimento das condições estabelecidas poderá acarretar a revogação imediata da autorização, bem "
    "como a aplicação das sanções administrativas cabíveis."
)

# Zona de Acesso Controlado (ZAC) de cada destino e os horários em que cada zona permite circulação (Art. 17).
DESTINOS_ZAC = {
    "Centro de Guarapari": "Amarela",
    "Praia do Morro": "Amarela",
    "Meaípe / Nova Guarapari": "Amarela",
    "SESC / Hotel Guarapousada": "Amarela",
    "Pousadas e casas de excursão (vias amarelas)": "Amarela",
    "Interior (Buenos Aires, Todos os Santos, Rio Calado)": "Verde",
    "Village do Sol / Palmeiras / Recanto da Sereia": "Verde",
    "Santa Mônica (rotas autorizadas)": "Verde",
    "Rodoviária Municipal / Estacionamento Oficial": "Verde",
    "Zona Vermelha (acesso excepcional)": "Vermelha",
}

JANELAS_ZAC = {
    "Vermelha": [(dt_time(5, 0), dt_time(8, 0))],
    "Amarela": [(dt_time(5, 0), dt_time(8, 0)), (dt_time(12, 0), dt_time(14, 0))],
    "Verde": [(dt_time(0, 0), dt_time(23, 59))],
}

# Texto exibido e horários sugeridos (entrada, saída) ao escolher cada zona na tela.
DESCRICAO_JANELA_ZAC = {
    "Vermelha": ("somente 05h–08h", "06", "07"),
    "Amarela": ("05h–08h e 12h–14h", "07", "13"),
    "Verde": ("qualquer horário (estacionamento oficial obrigatório)", None, None),
}

# Textos da página 2 (senha de acesso para o para-brisa).
TEXTO_SENHA_ARTIGOS = "(Art. 13, parágrafo único, e art. 24, II — Decreto nº 654/2025)"
TEXTO_SENHA_PROIBICAO = (
    "PROIBIDO TRANSPORTE DE ALIMENTOS, FOGÕES, BOTIJÕES DE GÁS, GELADEIRAS/FREEZERS E ITENS INFLAMÁVEIS "
    "(Art. 25 do Decreto nº 654/2025) — SUJEITO A RETENÇÃO E REMOÇÃO AO DEPÓSITO MUNICIPAL"
)


def validar_placa(placa: str) -> bool:
    return bool(PADRAO_PLACA.match(placa.upper().replace(" ", "")))


def validar_data(data_str: str) -> bool:
    try:
        datetime.strptime(data_str, PADRAO_DATA)
        return True
    except ValueError:
        return False


def validar_data_hora(data_hora_str: str) -> bool:
    try:
        datetime.strptime(data_hora_str, PADRAO_DATA_HORA)
        return True
    except ValueError:
        return False


def horario_permitido_zac(hora: dt_time, zona: str) -> bool:
    return any(inicio <= hora <= fim for inicio, fim in JANELAS_ZAC.get(zona, JANELAS_ZAC["Verde"]))


def validar_inteiro_positivo(valor_str: str) -> bool:
    return valor_str.strip().isdigit() and int(valor_str) > 0


def obter_pasta_area_de_trabalho() -> str:
    """Retorna a Área de Trabalho real do usuário. No Windows consulta o sistema,
    pois ela pode estar redirecionada (OneDrive, GPO) e não ser ~\\Desktop."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            CSIDL_DESKTOPDIRECTORY = 0x0010
            buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buffer) == 0:
                return buffer.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def obter_proximo_numero() -> tuple[str, bool]:
    """Retorna (numero, provisorio). Usa a numeração oficial do servidor; se o
    servidor estiver inacessível, usa um contador local e marca o número como
    provisório (prefixo PROV-) para não colidir com a sequência oficial."""
    try:
        return _proximo_numero_em(os.path.join(CAMINHO_ARMAZENAMENTO, "_controle")), False
    except OSError:
        base_local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        pasta_local = os.path.join(base_local, "EmissorAutorizacao", "_controle")
        return f"PROV-{_proximo_numero_em(pasta_local)}", True


def _proximo_numero_em(pasta_controle: str) -> str:
    """Gera o próximo número sequencial (NNNN/AAAA), reiniciando a cada ano.
    Usa um arquivo de controle + lock para evitar números duplicados quando
    duas pessoas geram documentos ao mesmo tempo."""
    os.makedirs(pasta_controle, exist_ok=True)
    caminho_contador = os.path.join(pasta_controle, "contador.txt")
    caminho_lock = os.path.join(pasta_controle, "contador.lock")

    ano_atual = datetime.now().year

    tentativas = 0
    while True:
        try:
            with open(caminho_lock, "x"):
                pass
            break
        except FileExistsError:
            tentativas += 1
            if tentativas > 50:  # ~10s de espera
                raise RuntimeError(
                    "Não foi possível obter a trava do contador de numeração "
                    "(outro usuário pode estar gerando um documento agora, ou o "
                    "arquivo _controle\\contador.lock ficou travado no servidor — "
                    "nesse caso, avise o TI para removê-lo manualmente)."
                )
            time.sleep(0.2)

    try:
        ultimo_ano, ultimo_numero = ano_atual, 0
        if os.path.exists(caminho_contador):
            with open(caminho_contador, "r", encoding="utf-8") as f:
                conteudo = f.read().strip()
            if conteudo:
                ano_salvo, numero_salvo = conteudo.split("/")
                ultimo_ano, ultimo_numero = int(ano_salvo), int(numero_salvo)

        novo_numero = 1 if ultimo_ano != ano_atual else ultimo_numero + 1

        with open(caminho_contador, "w", encoding="utf-8") as f:
            f.write(f"{ano_atual}/{novo_numero}")

        return f"{novo_numero:04d}/{ano_atual}"
    finally:
        try:
            os.remove(caminho_lock)
        except OSError:
            pass


def gerar_qr_code(dados: str, caminho_qr: str) -> None:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(dados)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(caminho_qr)


def _tabela_secao(titulo, linhas, estilo_titulo, estilo_label, estilo_valor):
    dados = [[Paragraph(titulo, estilo_titulo), ""]]
    for rotulo, valor in linhas:
        dados.append([Paragraph(rotulo, estilo_label), Paragraph(str(valor), estilo_valor)])

    tabela = Table(dados, colWidths=[180, 320])
    tabela.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tabela


def criar_autorizacao(dados: dict, hash_seguranca: str, caminho_qr: str, arquivo_saida: str) -> None:
    styles = getSampleStyleSheet()

    estilo_centro = ParagraphStyle("centro", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10, leading=13)
    estilo_centro_bold = ParagraphStyle("centro_bold", parent=estilo_centro, fontName="Helvetica-Bold")
    estilo_titulo_doc = ParagraphStyle("titulo_doc", parent=estilo_centro_bold, fontSize=13, leading=16)
    estilo_autoriza = ParagraphStyle("autoriza", parent=estilo_centro_bold, fontSize=20, leading=24)
    estilo_justificado = ParagraphStyle("justificado", parent=styles["Normal"], alignment=TA_JUSTIFY, fontSize=10, leading=13)
    estilo_rodape = ParagraphStyle("rodape", parent=estilo_justificado, fontSize=8, leading=10)
    estilo_assinatura = ParagraphStyle("assinatura", parent=estilo_centro_bold, fontSize=10)
    estilo_cargo = ParagraphStyle("cargo", parent=estilo_centro, fontSize=9)
    estilo_hash = ParagraphStyle("hash", parent=estilo_centro, fontSize=8)

    estilo_secao = ParagraphStyle("secao", parent=estilo_centro_bold, fontSize=10)
    estilo_label = ParagraphStyle("label", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=11)
    estilo_valor = ParagraphStyle("valor", parent=styles["Normal"], fontSize=9, leading=11)

    elementos = []

    if os.path.exists(CAMINHO_BRASAO):
        img_brasao = RLImage(CAMINHO_BRASAO, width=55, height=62)
        img_brasao.hAlign = "CENTER"
        elementos.append(img_brasao)
        elementos.append(Spacer(1, 4))

    elementos.append(Paragraph("ESTADO DO ESPÍRITO SANTO", estilo_centro_bold))
    elementos.append(Paragraph("PREFEITURA MUNICIPAL DE GUARAPARI", estilo_centro_bold))
    elementos.append(Paragraph("SECRETARIA MUNICIPAL DE SEGURANÇA, TRÂNSITO E TRANSPORTE – SEMSET", estilo_centro_bold))
    elementos.append(Spacer(1, 6))

    elementos.append(Paragraph(f"AUTORIZAÇÃO DE ENTRADA DE VEÍCULO DE TURISMO Nº {dados['numero']}", estilo_titulo_doc))
    elementos.append(Spacer(1, 6))

    elementos.append(Paragraph(TEXTO_CONSIDERANDO, estilo_justificado))
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph("AUTORIZA", estilo_autoriza))
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph(TEXTO_INTRO, estilo_justificado))
    elementos.append(Spacer(1, 8))

    elementos.append(_tabela_secao(
        "Identificação da Excursão",
        [
            ("Empresa / Entidade Responsável", dados["empresa_responsavel"]),
            ("CNPJ / CPF", dados["cnpj_cpf"]),
            ("Responsável Legal", dados["responsavel_legal"]),
            ("Documento (CPF/RG)", dados["documento_responsavel"]),
            ("Telefone de contato", dados["telefone"]),
        ],
        estilo_secao, estilo_label, estilo_valor
    ))
    elementos.append(Spacer(1, 5))

    elementos.append(_tabela_secao(
        "Dados do Transporte",
        [
            ("Tipo de Veículo", dados["tipo_veiculo"]),
            ("Placa", dados["placa"]),
            ("Empresa de Transporte", dados["empresa_transporte"]),
        ],
        estilo_secao, estilo_label, estilo_valor
    ))
    elementos.append(Spacer(1, 5))

    linhas_periodo = [
        ("Destino / Zona (ZAC)", f"{dados['destino']} — Zona {dados['zona_zac']}"),
        ("Entrada – Data/Hora", dados["entrada"]),
        ("Saída – Data/Hora", dados["saida"]),
        ("Quantidade de Passageiros", dados["passageiros"]),
    ]
    if dados.get("cadastur_veiculo"):
        linhas_periodo.append(("CADASTUR – Veículo", dados["cadastur_veiculo"]))
    if dados.get("cadastur_imovel"):
        linhas_periodo.append(("CADASTUR – Imóvel", dados["cadastur_imovel"]))

    elementos.append(_tabela_secao("Período Autorizado", linhas_periodo, estilo_secao, estilo_label, estilo_valor))
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph(TEXTO_ADVERTENCIA_1, estilo_rodape))
    elementos.append(Spacer(1, 4))
    elementos.append(Paragraph(TEXTO_ADVERTENCIA_2, estilo_rodape))
    elementos.append(Spacer(1, 14))

    # Nome e cargo do assinante nunca se separam em páginas diferentes.
    elementos.append(KeepTogether([
        Paragraph(NOME_ASSINANTE, estilo_assinatura),
        Paragraph(CARGO_ASSINANTE, estilo_cargo),
    ]))

    # ================= PÁGINA 2: senha de acesso para o para-brisa =================
    estilo_senha_titulo = ParagraphStyle("senha_titulo", parent=estilo_centro_bold, fontSize=14, leading=16)
    estilo_senha_destaque = ParagraphStyle("senha_destaque", parent=estilo_centro_bold, fontSize=14, leading=18)
    estilo_senha_placa = ParagraphStyle("senha_placa", parent=estilo_centro_bold, fontSize=44, leading=50)
    estilo_senha_info = ParagraphStyle("senha_info", parent=estilo_centro_bold, fontSize=16, leading=20)
    estilo_senha_artigos = ParagraphStyle("senha_artigos", parent=estilo_centro, fontSize=9, leading=10)
    estilo_senha_alerta = ParagraphStyle("senha_alerta", parent=estilo_justificado, fontSize=7, leading=8.5)

    elementos.append(PageBreak())
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph("SENHA DE ACESSO — IDENTIFICAÇÃO DE PARA-BRISA", estilo_senha_titulo))
    elementos.append(Spacer(1, 4))
    elementos.append(Paragraph("PROJETO RUAS LIVRES - GUARAPARI/ES", estilo_senha_destaque))
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(f"PLACA: {dados['placa']}", estilo_senha_placa))
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"ENTRADA: {dados['entrada']}", estilo_senha_info))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(f"SAÍDA: {dados['saida']}", estilo_senha_info))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(f"ZAC: ZONA {dados['zona_zac'].upper()}", estilo_senha_info))
    elementos.append(Spacer(1, 12))

    img_qr_grande = RLImage(caminho_qr, width=160, height=160)
    img_qr_grande.hAlign = "CENTER"
    elementos.append(img_qr_grande)
    elementos.append(Spacer(1, 4))
    elementos.append(Paragraph("Escaneie para validar", estilo_hash))
    elementos.append(Spacer(1, 8))

    elementos.append(Paragraph("USO OBRIGATÓRIO E VISÍVEL NO PARA-BRISA", estilo_senha_destaque))
    elementos.append(Paragraph(TEXTO_SENHA_ARTIGOS, estilo_senha_artigos))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(TEXTO_SENHA_PROIBICAO, estilo_senha_alerta))

    def _rodape(canvas_obj, doc_obj):
        # Hash fixada na margem inferior da página, independente do tamanho do conteúdo acima.
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.drawCentredString(letter[0] / 2, 18, f"Código de Autenticidade: {hash_seguranca}")
        canvas_obj.restoreState()

    doc = SimpleDocTemplate(
        arquivo_saida, pagesize=letter,
        topMargin=32, bottomMargin=32, leftMargin=54, rightMargin=54
    )
    doc.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)


def imagem_para_pdf(caminho_imagem: str, caminho_pdf: str) -> None:
    # Normaliza para RGB: PNGs com transparência (RGBA/P) quebram o reportlab/Image em alguns casos
    with PILImage.open(caminho_imagem) as img:
        if img.mode in ("RGBA", "P", "LA"):
            fundo = PILImage.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            fundo.paste(img, mask=img.split()[-1])
            imagem_convertida = fundo
        else:
            imagem_convertida = img.convert("RGB")

        caminho_temp_rgb = caminho_pdf.replace(".pdf", "_src.jpg")
        imagem_convertida.save(caminho_temp_rgb, quality=95)

    doc = SimpleDocTemplate(caminho_pdf, pagesize=letter)
    img_element = RLImage(caminho_temp_rgb, width=400, height=550, kind="proportional")
    doc.build([img_element])
    os.remove(caminho_temp_rgb)


class AppTurismo:
    def __init__(self, root):
        self.root = root
        self.root.title("Emissor de Autorização - Entrada de Veículo de Turismo")
        self.root.geometry("680x780")

        self.comprovante_path = ""

        # --- Área rolável (o formulário ficou grande demais para uma janela fixa) ---
        container = tk.Frame(root)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor="nw")
        self.frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 40), "units"))

        tk.Label(
            self.frame, text="Autorização de Entrada de Veículo de Turismo",
            font=("Helvetica", 13, "bold")
        ).pack(pady=(15, 5), padx=20)

        # --- Identificação da Excursão ---
        secao_excursao = tk.LabelFrame(self.frame, text="Identificação da Excursão", font=("Helvetica", 10, "bold"), padx=10, pady=10)
        secao_excursao.pack(fill="x", padx=20, pady=8)
        self.entry_empresa_responsavel = self._linha_grid(secao_excursao, 0, "Empresa/Entidade Responsável:")
        self.entry_cnpj_cpf = self._linha_grid(secao_excursao, 1, "CNPJ/CPF:")
        self.entry_responsavel_legal = self._linha_grid(secao_excursao, 2, "Responsável Legal:")
        self.entry_documento_responsavel = self._linha_grid(secao_excursao, 3, "Documento (RG/CPF):")
        self.entry_telefone = self._linha_grid(secao_excursao, 4, "Telefone de Contato:")

        # --- Dados do Transporte ---
        secao_transporte = tk.LabelFrame(self.frame, text="Dados do Transporte", font=("Helvetica", 10, "bold"), padx=10, pady=10)
        secao_transporte.pack(fill="x", padx=20, pady=8)

        tk.Label(secao_transporte, text="Tipo de Veículo:", anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        self.var_tipo_veiculo = tk.StringVar(value="Ônibus")
        frame_radios = tk.Frame(secao_transporte)
        frame_radios.grid(row=0, column=1, sticky="w")
        for opcao in ("Ônibus", "Micro-ônibus", "Van"):
            tk.Radiobutton(frame_radios, text=opcao, variable=self.var_tipo_veiculo, value=opcao).pack(side="left", padx=(0, 8))

        self.entry_placa = self._linha_grid(secao_transporte, 1, "Placa:")
        self.entry_empresa_transporte = self._linha_grid(secao_transporte, 2, "Empresa de Transporte:")

        # --- Período Autorizado e Zona ---
        secao_periodo = tk.LabelFrame(self.frame, text="Período Autorizado e Zona", font=("Helvetica", 10, "bold"), padx=10, pady=10)
        secao_periodo.pack(fill="x", padx=20, pady=8)

        tk.Label(secao_periodo, text="Destino final:", anchor="w").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        self.var_destino = tk.StringVar(value="Rodoviária Municipal / Estacionamento Oficial")
        self.combo_destino = ttk.Combobox(
            secao_periodo, textvariable=self.var_destino, width=38, state="readonly", values=list(DESTINOS_ZAC.keys())
        )
        self.combo_destino.grid(row=0, column=1, sticky="w", pady=4)
        self.combo_destino.bind("<<ComboboxSelected>>", lambda e: self._atualizar_zona(sugerir_horarios=True))
        self.lbl_zac = tk.Label(secao_periodo, text="", fg="#1a5276", font=("Helvetica", 8, "bold"))
        self.lbl_zac.grid(row=1, column=0, columnspan=2, sticky="w")

        self.cal_entrada, self.hora_entrada, self.min_entrada = self._linha_data_hora(secao_periodo, 2, "Entrada (Data/Hora):", "08")
        self.cal_saida, self.hora_saida, self.min_saida = self._linha_data_hora(secao_periodo, 3, "Saída (Data/Hora):", "18")
        self.entry_passageiros = self._linha_grid(secao_periodo, 4, "Quantidade de Passageiros:")
        self.entry_cadastur_veiculo = self._linha_grid(secao_periodo, 5, "CADASTUR – Veículo (opcional):")
        self.entry_cadastur_imovel = self._linha_grid(secao_periodo, 6, "CADASTUR – Imóvel (opcional):")
        self._atualizar_zona(sugerir_horarios=False)

        # --- Controle interno (não impresso no documento) ---
        secao_interna = tk.LabelFrame(
            self.frame, text="Controle de Pagamento (uso interno — não aparece no PDF)",
            font=("Helvetica", 9, "bold"), padx=10, pady=10, fg="#555555"
        )
        secao_interna.pack(fill="x", padx=20, pady=8)
        self.cal_pagamento = self._linha_data(secao_interna, 0, "Data de Pagamento:")
        self.cal_validade = self._linha_data(secao_interna, 1, "Data de Validade:")

        self.btn_comprovante = tk.Button(
            self.frame, text="Selecionar Comprovante (PDF/Imagem)",
            command=self.selecionar_comprovante, width=40, bg="#e0e0e0"
        )
        self.btn_comprovante.pack(pady=(15, 5))

        self.lbl_arquivo = tk.Label(self.frame, text="Nenhum comprovante selecionado", font=("Helvetica", 8), fg="gray")
        self.lbl_arquivo.pack()

        self.btn_gerar = tk.Button(
            self.frame, text="Gerar Documento Final", command=self.processar,
            font=("Helvetica", 11, "bold"), bg="#4CAF50", fg="white", width=30, height=2
        )
        self.btn_gerar.pack(pady=20)

    @staticmethod
    def _linha_simples(pai, texto_label):
        tk.Label(pai, text=texto_label, font=("Helvetica", 10)).pack(anchor="w", padx=20, pady=(10, 0))
        entrada = tk.Entry(pai, font=("Helvetica", 11), width=40)
        entrada.pack(anchor="w", padx=20, pady=(0, 5))
        return entrada

    @staticmethod
    def _linha_grid(pai, linha, texto_label):
        tk.Label(pai, text=texto_label, anchor="w").grid(row=linha, column=0, sticky="w", pady=4, padx=(0, 8))
        entrada = tk.Entry(pai, font=("Helvetica", 10), width=35)
        entrada.grid(row=linha, column=1, sticky="w", pady=4)
        return entrada

    @staticmethod
    def _calendario(pai):
        cal = DateEntry(
            pai, width=12, background="darkblue", foreground="white", borderwidth=2,
            date_pattern="dd/mm/yyyy", locale="pt_BR"
        )
        cal.set_date(datetime.now().date())
        return cal

    def _linha_data(self, pai, linha, texto_label):
        tk.Label(pai, text=texto_label, anchor="w").grid(row=linha, column=0, sticky="w", pady=4, padx=(0, 8))
        cal = self._calendario(pai)
        cal.grid(row=linha, column=1, sticky="w", pady=4)
        return cal

    def _linha_data_hora(self, pai, linha, texto_label, hora_padrao):
        tk.Label(pai, text=texto_label, anchor="w").grid(row=linha, column=0, sticky="w", pady=4, padx=(0, 8))
        frame = tk.Frame(pai)
        frame.grid(row=linha, column=1, sticky="w", pady=4)

        cal = self._calendario(frame)
        cal.pack(side="left", padx=(0, 10))

        tk.Label(frame, text="H:").pack(side="left")
        hora = ttk.Spinbox(frame, from_=0, to=23, width=3, format="%02.0f", wrap=True)
        hora.set(hora_padrao)
        hora.pack(side="left", padx=(0, 5))

        tk.Label(frame, text="M:").pack(side="left")
        minuto = ttk.Spinbox(frame, from_=0, to=59, width=3, format="%02.0f", wrap=True)
        minuto.set("00")
        minuto.pack(side="left")
        return cal, hora, minuto

    def _zona_atual(self):
        return DESTINOS_ZAC.get(self.var_destino.get(), "Verde")

    def _atualizar_zona(self, sugerir_horarios):
        zona = self._zona_atual()
        janela, hora_entrada, hora_saida = DESCRICAO_JANELA_ZAC[zona]
        self.lbl_zac.config(text=f"Zona {zona}: circulação permitida {janela} (Art. 17).")
        # Só sugere horários quando o usuário troca o destino, para não sobrescrever o que ele já escolheu.
        if sugerir_horarios and hora_entrada:
            self.hora_entrada.set(hora_entrada)
            self.hora_saida.set(hora_saida)

    def selecionar_comprovante(self):
        # Diálogo nativo: precisa rodar na thread principal, junto do mainloop.
        arquivo = filedialog.askopenfilename(
            title="Selecione o comprovante",
            filetypes=[("Arquivos PDF ou Imagens", "*.pdf *.jpg *.jpeg *.png")]
        )
        if arquivo:
            self.comprovante_path = arquivo
            self.lbl_arquivo.config(text=f"Selecionado: {os.path.basename(arquivo)}", fg="green")

    def _coletar_dados(self):
        return {
            "empresa_responsavel": self.entry_empresa_responsavel.get().strip(),
            "cnpj_cpf": self.entry_cnpj_cpf.get().strip(),
            "responsavel_legal": self.entry_responsavel_legal.get().strip(),
            "documento_responsavel": self.entry_documento_responsavel.get().strip(),
            "telefone": self.entry_telefone.get().strip(),
            "tipo_veiculo": self.var_tipo_veiculo.get(),
            "placa": self.entry_placa.get().strip().upper(),
            "empresa_transporte": self.entry_empresa_transporte.get().strip(),
            "entrada": f"{self.cal_entrada.get().strip()} {self.hora_entrada.get().strip().zfill(2)}:{self.min_entrada.get().strip().zfill(2)}",
            "saida": f"{self.cal_saida.get().strip()} {self.hora_saida.get().strip().zfill(2)}:{self.min_saida.get().strip().zfill(2)}",
            "passageiros": self.entry_passageiros.get().strip(),
            "cadastur_veiculo": self.entry_cadastur_veiculo.get().strip(),
            "cadastur_imovel": self.entry_cadastur_imovel.get().strip(),
            "destino": self.var_destino.get(),
            "zona_zac": self._zona_atual(),
        }

    def processar(self):
        dados = self._coletar_dados()
        pagamento = self.cal_pagamento.get().strip()
        validade = self.cal_validade.get().strip()

        campos_obrigatorios = [
            dados["empresa_responsavel"], dados["cnpj_cpf"], dados["responsavel_legal"],
            dados["documento_responsavel"], dados["telefone"], dados["placa"], dados["empresa_transporte"],
            dados["entrada"], dados["saida"], dados["passageiros"], pagamento, validade,
        ]
        if not all(campos_obrigatorios):
            messagebox.showerror("Erro", "Preencha todos os campos obrigatórios!")
            return

        if not validar_placa(dados["placa"]):
            messagebox.showerror("Erro", "Placa inválida. Use o formato ABC-1234 ou ABC1D23.")
            return

        if not validar_data_hora(dados["entrada"]) or not validar_data_hora(dados["saida"]):
            messagebox.showerror("Erro", "Data/hora de entrada ou saída inválida. Confira a data e se a hora vai de 00 a 23 e os minutos de 00 a 59.")
            return

        dt_entrada = datetime.strptime(dados["entrada"], PADRAO_DATA_HORA)
        dt_saida = datetime.strptime(dados["saida"], PADRAO_DATA_HORA)
        if dt_saida <= dt_entrada:
            messagebox.showerror("Erro", "A saída deve ser posterior à entrada.")
            return

        zona = dados["zona_zac"]
        if not horario_permitido_zac(dt_entrada.time(), zona) or not horario_permitido_zac(dt_saida.time(), zona):
            messagebox.showerror(
                "Erro",
                f"Horário fora do permitido para a Zona {zona}: {DESCRICAO_JANELA_ZAC[zona][0]} (Art. 17).\n"
                "Ajuste a hora de entrada e/ou de saída."
            )
            return

        if not validar_inteiro_positivo(dados["passageiros"]):
            messagebox.showerror("Erro", "Quantidade de Passageiros deve ser um número inteiro maior que zero.")
            return

        if not validar_data(pagamento) or not validar_data(validade):
            messagebox.showerror("Erro", "Datas de pagamento/validade devem estar no formato DD/MM/AAAA.")
            return

        if not self.comprovante_path:
            messagebox.showerror("Erro", "Você precisa selecionar o arquivo do comprovante!")
            return

        self.btn_gerar.config(state="disabled", text="Gerando...")
        self.root.update_idletasks()

        arquivos_temp = []
        try:
            dados["numero"], numero_provisorio = obter_proximo_numero()

            tmp_dir = tempfile.gettempdir()
            sufixo = uuid.uuid4().hex[:8]

            hash_unica = str(uuid.uuid4()).upper()
            conteudo_qr = (
                f"AUTORIZACAO|NUMERO:{dados['numero']}|PLACA:{dados['placa']}|"
                f"ENTRADA:{dados['entrada']}|SAIDA:{dados['saida']}|ZAC:{dados['zona_zac']}|HASH:{hash_unica}"
            )

            caminho_qr = os.path.join(tmp_dir, f"qr_{sufixo}.png")
            gerar_qr_code(conteudo_qr, caminho_qr)
            arquivos_temp.append(caminho_qr)

            pdf_autorizacao = os.path.join(tmp_dir, f"autorizacao_{sufixo}.pdf")
            criar_autorizacao(dados, hash_unica, caminho_qr, pdf_autorizacao)
            arquivos_temp.append(pdf_autorizacao)

            extensao = os.path.splitext(self.comprovante_path)[1].lower()
            comprovante_pdf_pronto = self.comprovante_path

            if extensao in [".jpg", ".jpeg", ".png"]:
                comprovante_pdf_pronto = os.path.join(tmp_dir, f"comprovante_{sufixo}.pdf")
                imagem_para_pdf(self.comprovante_path, comprovante_pdf_pronto)
                arquivos_temp.append(comprovante_pdf_pronto)

            escritor = PdfWriter()
            for pagina in PdfReader(pdf_autorizacao).pages:
                escritor.add_page(pagina)
            for pagina in PdfReader(comprovante_pdf_pronto).pages:
                escritor.add_page(pagina)

            buffer_pdf = io.BytesIO()
            escritor.write(buffer_pdf)
            conteudo_pdf = buffer_pdf.getvalue()

            numero_arquivo = dados["numero"].replace("/", "-").replace("\\", "-")
            nome_arquivo = f"Autorizacao_Turismo_{numero_arquivo}_{dados['placa'].replace('-', '_')}_{sufixo}.pdf"

            # O documento é salvo nos dois locais; a falha em um deles não impede o outro.
            agora = datetime.now()
            destinos = [
                ("Servidor", os.path.join(CAMINHO_ARMAZENAMENTO, f"{agora.year:04d}", f"{agora.month:02d}")),
                ("Área de Trabalho", obter_pasta_area_de_trabalho()),
            ]
            salvos, falhas = [], []
            for nome_local, pasta in destinos:
                caminho = os.path.join(pasta, nome_arquivo)
                try:
                    os.makedirs(pasta, exist_ok=True)
                    with open(caminho, "wb") as saida:
                        saida.write(conteudo_pdf)
                    salvos.append((nome_local, caminho))
                except OSError as erro:
                    falhas.append((nome_local, pasta, erro))

            if not salvos:
                detalhes = "\n".join(f"- {nome} ({pasta}): {erro}" for nome, pasta, erro in falhas)
                raise RuntimeError(f"O documento não pôde ser salvo em nenhum local:\n{detalhes}")

            texto_salvos = "\n\n".join(f"{nome}:\n{caminho}" for nome, caminho in salvos)
            aviso_numero = (
                "\n\nComo o servidor estava inacessível, o documento recebeu uma numeração "
                f"PROVISÓRIA ({dados['numero']})."
                if numero_provisorio else ""
            )

            if falhas:
                nome_falha, pasta_falha, erro_falha = falhas[0]
                messagebox.showwarning(
                    f"Não foi possível salvar em: {nome_falha}",
                    f"O documento foi gerado, mas NÃO foi possível salvá-lo em: {nome_falha}\n"
                    f"({pasta_falha})\nMotivo: {erro_falha}\n\n"
                    f"Salvo com sucesso em:\n{texto_salvos}{aviso_numero}"
                )
            else:
                messagebox.showinfo("Sucesso!", f"Documento gerado e salvo em:\n\n{texto_salvos}{aviso_numero}")

        except Exception as e:
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro ao gerar o documento:\n{str(e)}")

        finally:
            for f in arquivos_temp:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
            self.btn_gerar.config(state="normal", text="Gerar Documento Final")


if __name__ == "__main__":
    if not os.path.exists(CAMINHO_BRASAO):
        print(f"Aviso: brasao_guarapari.png não encontrado em {PASTA_SCRIPT}. "
              f"O documento será gerado sem o brasão no cabeçalho.", file=sys.stderr)
    root = tk.Tk()
    app = AppTurismo(root)
    root.mainloop()
