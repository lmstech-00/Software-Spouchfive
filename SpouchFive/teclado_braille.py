"""
Teclado Braille v3 — 6 pontos, teclado físico, toques duplos e sons

Instalar:   pip install -U pynput
Opcional:   pip install pygame      (para tocar .ogg/.mp3 e sons sobrepostos)
Rodar:      python teclado_braille_v3.py

TECLADO FÍSICO (Windows)          F D S  =  pontos 1 2 3
                                  J K L  =  pontos 4 5 6
                                  F8     =  liga/desliga a captura

COMANDOS = 2 toques seguidos no MESMO ponto, sem outro ponto junto:
    ponto 1 x2 = Espaço      ponto 2 x2 = Backspace
    ponto 4 x2 = Enter       ponto 5 x2 = Caps Lock (liga/desliga)

SONS: pasta "PASTA_SONS" ao lado deste arquivo. O NOME do arquivo diz qual som é
(maiúscula/minúscula no nome não importa: ESPACO.wav = espaco.wav):
    ESPACO   ENTER   APAGAR   MAIUSCULA   MINUSCULA        (comandos)
    A B C ... Z                                             (letras)
MAIUSCULA toca ao ligar o Caps e MINUSCULA ao desligar.
Se a pasta não existir, ela é criada com bipes de teste para os 5 comandos.
Arquivo que não existe = sem som para aquele comando.
"""
import sys
import time
import math
import wave
import struct
import queue
import unicodedata
import tkinter as tk
from pathlib import Path
from pynput import keyboard
from pynput.keyboard import Controller, Key

kb = Controller()

# ======================= CONFIGURAÇÃO =======================
ACORDE = False          # False: pontos em sequência, confirma após DELAY_MS parado
                        # True : aperta os pontos JUNTOS e solta (estilo Perkins)
DELAY_MS = 1200         # modo sequência: tempo parado até confirmar a cela
JANELA_DUPLO_MS = 350   # modo acorde: tempo máximo entre os 2 toques de um comando
PASTA_SONS = Path(__file__).resolve().parent / "PASTA_SONS"   # nome da pasta de sons
EXT_SONS = {".wav", ".ogg", ".mp3"}
# ============================================================

# Combinação de pontos -> caractere
BRAILLE = {
    # alfabeto
    "1": "a", "12": "b", "14": "c", "145": "d", "15": "e", "124": "f",
    "1245": "g", "125": "h", "24": "i", "245": "j", "13": "k", "123": "l",
    "134": "m", "1345": "n", "135": "o", "1234": "p", "12345": "q",
    "1235": "r", "234": "s", "2345": "t", "136": "u", "1236": "v",
    "2456": "w", "1346": "x", "13456": "y", "1356": "z",
}

# Comando de cada ponto quando tocado 2 vezes
ESPECIAIS = {1: "espaco", 2: "apagar", 4: "enter", 5: "caps"}
NOMES = {"espaco": "Espaço", "apagar": "Apagar", "enter": "Enter", "caps": "Caps"}

# Posição de cada ponto na grade (linha, coluna)
POSICAO = {1: (0, 0), 2: (1, 0), 3: (2, 0), 4: (0, 1), 5: (1, 1), 6: (2, 1)}

# Teclas físicas (códigos virtuais do Windows; independem do layout ABNT2/US)
ACOES = {
    0x46: ("ponto", 1),       # F
    0x44: ("ponto", 2),       # D
    0x53: ("ponto", 3),       # S
    0x4A: ("ponto", 4),       # J
    0x4B: ("ponto", 5),       # K
    0x4C: ("ponto", 6),       # L
    0x77: ("captura", None),  # F8
}

WM_KEYDOWN, WM_SYSKEYDOWN = 0x100, 0x104
WM_KEYUP, WM_SYSKEYUP = 0x101, 0x105
LLKHF_INJECTED = 0x10

COR_BG = "#1e1e2e"
COR_TECLA = "#313244"
COR_ATIVA = "#89b4fa"
COR_TEXTO = "#cdd6f4"
COR_ERRO = "#f38ba8"
COR_OK = "#a6e3a1"


# ====================================================================
# SONS
# ====================================================================
def _norm(texto):
    return unicodedata.normalize("NFC", texto).lower()


class Sons:
    """Lê a pasta de sons e toca o arquivo cujo nome bate com o comando."""

    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.indice = {}
        self.cache = {}
        self.avisados = set()
        self.pygame = None
        self.winsound = None
        self._iniciar_backend()
        self.recarregar()

    def _iniciar_backend(self):
        try:
            import pygame
            pygame.mixer.init()
            self.pygame = pygame
            return
        except Exception:
            self.pygame = None
        if sys.platform == "win32":
            import winsound
            self.winsound = winsound

    @property
    def backend(self):
        if self.pygame:
            return "pygame"
        if self.winsound:
            return "winsound (só .wav)"
        return "sem áudio"

    def recarregar(self):
        self.indice.clear()
        if self.pasta.is_dir():
            for arq in sorted(self.pasta.iterdir()):
                if arq.suffix.lower() in EXT_SONS:
                    self.indice[_norm(arq.stem)] = arq

    def tocar(self, nome):
        caminho = self.indice.get(_norm(nome))
        if caminho is None:
            return
        try:
            if self.pygame:
                som = self.cache.get(caminho)
                if som is None:
                    som = self.pygame.mixer.Sound(str(caminho))
                    self.cache[caminho] = som
                self.pygame.mixer.stop()      # som novo corta o anterior
                som.play()
            elif self.winsound and caminho.suffix.lower() == ".wav":
                self.winsound.PlaySound(
                    str(caminho), self.winsound.SND_FILENAME | self.winsound.SND_ASYNC)
            elif caminho not in self.avisados:
                self.avisados.add(caminho)
                print(f"[sons] não consigo tocar {caminho.name}: "
                      "só .wav sem pygame (pip install pygame)")
        except Exception as erro:
            if caminho not in self.avisados:
                self.avisados.add(caminho)
                print(f"[sons] erro ao tocar {caminho.name}: {erro}")


def criar_sons_teste(pasta):
    """Cria bipes .wav simples para os comandos (não sobrescreve nada)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    taxa = 22050

    def bip(nome, notas):
        caminho = pasta / f"{nome}.wav"
        if caminho.exists():
            return
        with wave.open(str(caminho), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(taxa)
            for freq, dur in notas:
                n = int(taxa * dur)
                frames = bytearray()
                for i in range(n):
                    env = min(1.0, i / 200, (n - i) / 200)
                    frames += struct.pack(
                        "<h", int(9000 * env * math.sin(2 * math.pi * freq * i / taxa)))
                w.writeframes(bytes(frames))

    bip("espaco", [(440, .08)])
    bip("apagar", [(300, .12)])
    bip("enter", [(660, .08), (660, .08)])
    bip("maiuscula", [(520, .08), (780, .10)])
    bip("minuscula", [(780, .08), (520, .10)])


# ====================================================================
# MOTOR (lógica pura: sem Tk, sem teclado — por isso dá pra testar)
# ====================================================================
class Motor:
    """
    cela      : {ponto: nº de toques} da cela em construção
    pendente  : (ponto, instante) — toque simples de 1/2/4/5 no modo acorde,
                esperando um possível 2º toque que o transformaria em comando

    saida(tipo, texto=None, som=None) é chamada para cada resultado:
      "letra" (texto com maiúscula/minúscula, som = letra base), "espaco",
      "apagar", "enter", "maiuscula", "minuscula", "erro" (texto = pontos).
    """

    def __init__(self, agendar, cancelar, agora, saida, ao_mudar, acorde=ACORDE):
        self.agendar, self.cancelar, self.agora = agendar, cancelar, agora
        self.saida, self.ao_mudar = saida, ao_mudar
        self.acorde = acorde
        self.cela = {}
        self.segurados = set()
        self.caps = False
        self.pendente = None
        self.timer = None
        self.timer_pend = None

    # ---------- entrada ----------
    def apertar(self, ponto, fisico=False):
        if self.pendente and not self.cela:
            if self.agora() - self.pendente[1] > JANELA_DUPLO_MS / 1000:
                self._descarregar_pendente()
            else:
                self._cancelar_timer_pend()   # 2º toque começou dentro da janela
        self._cancelar_timer()
        self.cela[ponto] = self.cela.get(ponto, 0) + 1
        if fisico:
            self.segurados.add(ponto)
        self.ao_mudar()
        if not (fisico and self.acorde):
            self.timer = self.agendar(DELAY_MS, self._por_tempo)

    def soltar(self, ponto):
        self.segurados.discard(ponto)
        if self.acorde and not self.segurados and self.cela:
            self._finalizar(True)

    def confirmar(self):
        self._descarregar_pendente()
        self._finalizar(False)

    def limpar(self):
        self._cancelar_timer()
        self._cancelar_timer_pend()
        self.cela.clear()
        self.pendente = None
        self.ao_mudar()

    def alternar_caps(self):
        self._comando("caps")

    # ---------- internos ----------
    def _por_tempo(self):
        self.timer = None
        self._finalizar(False)

    def _cancelar_timer(self):
        if self.timer is not None:
            self.cancelar(self.timer)
            self.timer = None

    def _cancelar_timer_pend(self):
        if self.timer_pend is not None:
            self.cancelar(self.timer_pend)
            self.timer_pend = None

    def _finalizar(self, acorde):
        self._cancelar_timer()
        if not self.cela:
            return
        cela, self.cela = self.cela, {}
        pontos = frozenset(cela)
        unico = next(iter(pontos)) if len(pontos) == 1 else None
        self.ao_mudar()

        # 1) dois toques no mesmo ponto dentro da mesma cela
        if unico in ESPECIAIS and cela[unico] == 2:
            self._descarregar_pendente()
            self._comando(ESPECIAIS[unico])
            return

        # 2) modo acorde: este é o 2º toque de um comando já pendente
        if self.pendente:
            p_pend = self.pendente[0]
            if unico == p_pend and cela[unico] == 1:
                self.pendente = None
                self._cancelar_timer_pend()
                self._comando(ESPECIAIS[p_pend])
                return
            self._descarregar_pendente()

        # 3) modo acorde: toque simples que pode virar comando -> espera
        if acorde and unico in ESPECIAIS and cela[unico] == 1:
            self.pendente = (unico, self.agora())
            self.timer_pend = self.agendar(JANELA_DUPLO_MS, self._descarregar_pendente)
            self.ao_mudar()
            return

        self._emitir_cela(pontos)

    def _descarregar_pendente(self):
        if self.pendente is None:
            return
        ponto = self.pendente[0]
        self.pendente = None
        self.timer_pend = None
        self._emitir_cela(frozenset([ponto]))
        self.ao_mudar()

    def _emitir_cela(self, pontos):
        chave = "".join(str(p) for p in sorted(pontos))
        letra = BRAILLE.get(chave)
        if letra is None:
            self.saida("erro", chave)
        else:
            self.saida("letra", letra.upper() if self.caps else letra, letra)

    def _comando(self, nome):
        if nome == "caps":
            self.caps = not self.caps
            self.saida("maiuscula" if self.caps else "minuscula")
        else:
            self.saida(nome)
        self.ao_mudar()


# ====================================================================
# INTERFACE + TECLADO FÍSICO
# ====================================================================
class TecladoBraille:
    def __init__(self, root):
        self.root = root
        self.botoes = {}
        self.mensagem = ("Clique nos pontos", COR_TEXTO)

        self.sons = Sons(PASTA_SONS)
        self.motor = Motor(
            agendar=root.after, cancelar=root.after_cancel, agora=time.monotonic,
            saida=self._saida, ao_mudar=self._atualizar,
        )

        # teclado físico
        self.fila = queue.Queue()
        self.seguradas = set()   # só na thread do gancho
        self.captura = True
        self.listener = None
        self.user32 = None

        root.title("Teclado Braille")
        root.configure(bg=COR_BG, padx=10, pady=10)
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._fechar)

        self._montar()
        root.update()
        self._nao_roubar_foco()
        self._iniciar_teclado_fisico()
        self._processar_fila()
        self._atualizar()

    # ---------- construção ----------
    def _montar(self):
        self.info = tk.Label(
            self.root, text="", bg=COR_BG, fg=COR_TEXTO,
            font=("Segoe UI", 12), width=28, height=2,
        )
        self.info.pack()

        grade = tk.Frame(self.root, bg=COR_BG)
        grade.pack(pady=6)
        legenda = {1: "1  (F)", 2: "2  (D)", 3: "3  (S)",
                   4: "4  (J)", 5: "5  (K)", 6: "6  (L)"}
        for ponto, (lin, col) in POSICAO.items():
            b = tk.Button(
                grade, text=legenda[ponto], width=8, height=3,
                bg=COR_TECLA, fg=COR_TEXTO, activebackground=COR_ATIVA,
                activeforeground="#000", relief="flat", takefocus=0,
                font=("Segoe UI", 14, "bold"),
                command=lambda p=ponto: self.motor.apertar(p),
            )
            b.grid(row=lin, column=col, padx=6, pady=4)
            self.botoes[ponto] = b

        barra = tk.Frame(self.root, bg=COR_BG)
        barra.pack(pady=(6, 0))
        self.btn_caps = self._acao(barra, "Caps", self.motor.alternar_caps)
        self._acao(barra, "OK", self.motor.confirmar)
        self._acao(barra, "Limpar", self.motor.limpar)

        barra2 = tk.Frame(self.root, bg=COR_BG)
        barra2.pack(pady=(4, 0))
        self._acao(barra2, "Espaço", lambda: self._botao_cmd("espaco"))
        self._acao(barra2, "Apagar", lambda: self._botao_cmd("apagar"))
        self._acao(barra2, "Enter", lambda: self._botao_cmd("enter"))

        self.status = tk.Label(
            self.root, text="", bg=COR_BG, fg=COR_TEXTO,
            font=("Segoe UI", 9), justify="center",
        )
        self.status.pack(pady=(8, 0))
        self._atualizar_status()

    def _acao(self, frame, texto, comando):
        b = tk.Button(
            frame, text=texto, width=9, height=2, command=comando,
            bg=COR_TECLA, fg=COR_TEXTO, activebackground=COR_ATIVA,
            activeforeground="#000", relief="flat", takefocus=0,
            font=("Segoe UI", 10, "bold"),
        )
        b.pack(side="left", padx=3, pady=2)
        return b

    def _botao_cmd(self, nome):
        self.motor.confirmar()
        self._saida(nome)
        self._atualizar()

    # ---------- saída (digita + som) ----------
    def _saida(self, tipo, texto=None, som=None):
        if tipo == "letra":
            kb.type(texto)
            self.mensagem = (f"→  {texto}", COR_OK)
        elif tipo in ("espaco", "apagar", "enter"):
            tecla = {"espaco": Key.space, "apagar": Key.backspace, "enter": Key.enter}[tipo]
            kb.press(tecla)
            kb.release(tecla)
            self.mensagem = (f"→  {NOMES[tipo]}", COR_OK)
        elif tipo in ("maiuscula", "minuscula"):
            self.mensagem = ("Caps LIGADO" if tipo == "maiuscula" else "Caps desligado", COR_OK)
        elif tipo == "erro":
            self.mensagem = (f"Pontos {texto}: sem letra", COR_ERRO)
        self.sons.tocar(som or tipo)

    # ---------- visual ----------
    def _atualizar(self):
        cela = self.motor.cela
        for p, b in self.botoes.items():
            ativo = p in cela
            b.config(bg=COR_ATIVA if ativo else COR_TECLA,
                     fg="#000" if ativo else COR_TEXTO)
        self.btn_caps.config(bg=COR_ATIVA if self.motor.caps else COR_TECLA,
                             fg="#000" if self.motor.caps else COR_TEXTO)

        if cela:
            chave = "".join(str(p) for p in sorted(cela))
            if len(cela) == 1:
                p, n = next(iter(cela.items()))
                if p in ESPECIAIS and n == 2:
                    texto = f"Ponto {p} ×2  →  {NOMES[ESPECIAIS[p]]}"
                else:
                    texto = f"Pontos {chave}  →  {BRAILLE.get(chave, '?')}"
            else:
                texto = f"Pontos {chave}  →  {BRAILLE.get(chave, '?')}"
            self.info.config(text=texto, fg=COR_TEXTO)
        elif self.motor.pendente:
            p = self.motor.pendente[0]
            self.info.config(
                text=f"Ponto {p}…  (de novo = {NOMES[ESPECIAIS[p]]})", fg=COR_TEXTO)
        else:
            self.info.config(text=self.mensagem[0], fg=self.mensagem[1])

    def _atualizar_status(self, texto=None):
        if texto is None:
            if self.captura:
                texto = ("Teclado físico: LIGADO (F8 desliga)\n"
                         "F D S = 1 2 3   ·   J K L = 4 5 6\n"
                         "2 toques: 1=espaço 2=apagar 4=enter 5=caps")
            else:
                texto = "Teclado físico: DESLIGADO (F8 liga)"
        texto += f"\nSons: {self.sons.backend}, {len(self.sons.indice)} arquivo(s)"
        self.status.config(text=texto, fg=COR_OK if self.captura else COR_ERRO)

    # ---------- foco (Windows) ----------
    def _nao_roubar_foco(self):
        if sys.platform != "win32":
            return
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
        estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo | WS_EX_NOACTIVATE)

    # ---------- teclado físico ----------
    def _iniciar_teclado_fisico(self):
        if sys.platform != "win32":
            self.captura = False
            self._atualizar_status("Teclado físico: só no Windows")
            return
        import ctypes
        self.user32 = ctypes.windll.user32
        self.listener = keyboard.Listener(win32_event_filter=self._filtro)
        self.listener.start()

    def _modificador_pressionado(self):
        g = self.user32.GetAsyncKeyState
        return any(g(vk) & 0x8000 for vk in (0x11, 0x12, 0x5B, 0x5C))  # Ctrl Alt Win

    def _filtro(self, msg, data):
        """Roda na thread do gancho: só enfileira. Retornar False deixa o evento
        passar para o sistema; suppress_event() engole (o app em foco não vê)."""
        if data.flags & LLKHF_INJECTED:      # eventos criados por nós mesmos
            return False

        vk = data.vkCode
        acao = ACOES.get(vk)
        if acao is None:
            return False

        descendo = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        subindo = msg in (WM_KEYUP, WM_SYSKEYUP)

        if subindo:
            if vk not in self.seguradas:
                return False                  # a descida não foi capturada
            self.seguradas.discard(vk)
            self.fila.put(("solta", acao))
            self.listener.suppress_event()

        if not descendo:
            return False

        if acao[0] != "captura":
            if not self.captura or self._modificador_pressionado():
                return False

        if vk not in self.seguradas:          # ignora auto-repetição
            self.seguradas.add(vk)
            self.fila.put(("aperta", acao))
        self.listener.suppress_event()

    def _processar_fila(self):
        try:
            while True:
                evento, (tipo, valor) = self.fila.get_nowait()
                if evento == "aperta":
                    if tipo == "ponto":
                        self.motor.apertar(valor, fisico=True)
                    elif tipo == "captura":
                        self._alternar_captura()
                elif tipo == "ponto":
                    self.motor.soltar(valor)
        except queue.Empty:
            pass
        self.root.after(15, self._processar_fila)

    def _alternar_captura(self):
        self.captura = not self.captura
        self._atualizar_status()

    def _fechar(self):
        if self.listener is not None:
            self.listener.stop()
        self.root.destroy()


if __name__ == "__main__":
    if not PASTA_SONS.exists():
        criar_sons_teste(PASTA_SONS)
        print(f"Pasta de sons criada com bipes de teste: {PASTA_SONS}")
    root = tk.Tk()
    TecladoBraille(root)
    root.mainloop()