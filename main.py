from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import os
import sqlite3

app = FastAPI(title="Sistema de Encomendas - Condomínio Horizontal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "portaria.db"

# Função para conectar ao banco de dados e criar as tabelas se não existirem
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabela de Moradores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS moradores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_completo TEXT,
            quadra TEXT,
            conjunto TEXT,
            casa_lote TEXT,
            telefone TEXT
        )
    """)
    # Tabela de Encomendas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS encomendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            morador_id INTEGER,
            nome_morador TEXT,
            endereco TEXT,
            codigo_rastreio TEXT,
            descricao TEXT,
            status TEXT,
            FOREIGN KEY (morador_id) REFERENCES moradores (id)
        )
    """)
    conn.commit()
    conn.close()

# Inicializa o banco de dados assim que o script roda
init_db()

class Morador(BaseModel):
    id: int
    nome_completo: str
    quadra: str
    conjunto: str
    casa_lote: str
    telefone: str

class MoradorManualInput(BaseModel):
    nome_completo: str
    quadra: str
    conjunto: str
    casa_lote: str
    telefone: str

class EncomendaInput(BaseModel):
    morador_id: int
    codigo_rastreio: str
    descricao: Optional[str] = "Não informada"


@app.get("/", response_class=HTMLResponse)
def pagina_inicial():
    caminho_index = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(caminho_index):
        with open(caminho_index, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Erro: Arquivo index.html não encontrado.</h1>"


@app.post("/moradores/importar-excel")
async def importar_excel(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Envie um arquivo Excel válido (.xlsx)")
    try:
        conteudo = await file.read()
        df = pd.read_excel(io.BytesIO(conteudo))
        colunas_esperadas = ["Nome Completo", "Quadra", "Conjunto", "Casa/Lote", "Telefone (WhatsApp)"]
        for col in colunas_esperadas:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Coluna ausente: {col}")
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        contagem_novos = 0
        for _, linha in df.iterrows():
            tel_limpo = ''.join(filter(str.isdigit, str(linha["Telefone (WhatsApp)"])))
            
            cursor.execute("""
                INSERT INTO moradores (nome_completo, quadra, conjunto, casa_lote, telefone)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(linha["Nome Completo"]).strip(),
                str(linha["Quadra"]).strip(),
                str(linha["Conjunto"]).strip(),
                str(linha["Casa/Lote"]).strip(),
                tel_limpo
            ))
            contagem_novos += 1
            
        conn.commit()
        conn.close()
        return {"sucesso": True, "mensagem": f"{contagem_novos} moradores importados com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@app.post("/moradores/cadastrar-manual")
def cadastrar_manual(morador: MoradorManualInput):
    tel_limpo = ''.join(filter(str.isdigit, morador.telefone))
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO moradores (nome_completo, quadra, conjunto, casa_lote, telefone)
        VALUES (?, ?, ?, ?, ?)
    """, (morador.nome_completo.strip(), morador.quadra.strip(), morador.conjunto.strip(), morador.casa_lote.strip(), tel_limpo))
    conn.commit()
    conn.close()
    
    return {"sucesso": True, "mensagem": "Morador cadastrado!"}


@app.get("/moradores", response_model=List[Morador])
def listar_moradores():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome_completo, quadra, conjunto, casa_lote, telefone FROM moradores")
    linhas = cursor.fetchall()
    conn.close()
    
    moradores = []
    for l in linhas:
        moradores.append({
            "id": l[0], "nome_completo": l[1], "quadra": l[2], "conjunto": l[3], "casa_lote": l[4], "telefone": l[5]
        })
    return moradores


@app.delete("/moradores/{morador_id}")
def deletar_morador(morador_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM moradores WHERE id = ?", (morador_id,))
    conn.commit()
    conn.close()
    return {"sucesso": True, "mensagem": "Morador removido!"}


@app.post("/encomendas/registrar")
def registrar_encomenda(encomenda: EncomendaInput):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Busca o morador no banco
    cursor.execute("SELECT nome_completo, quadra, conjunto, casa_lote, telefone FROM moradores WHERE id = ?", (encomenda.morador_id,))
    morador = cursor.fetchone()
    
    if not morador:
        conn.close()
        raise HTTPException(status_code=404, detail="Morador não encontrado.")
    
    nome_morador, quadra, conjunto, casa_lote, telefone = morador
    endereco_completo = f"Qd. {quadra} - Cj. {conjunto} - Casa {casa_lote}"
    
    # Salva a encomenda
    cursor.execute("""
        INSERT INTO encomendas (morador_id, nome_morador, endereco, codigo_rastreio, descricao, status)
        VALUES (?, ?, ?, ?, ?, 'PENDENTE')
    """, (encomenda.morador_id, nome_morador, endereco_completo, encomenda.codigo_rastreio, encomenda.descricao))
    
    enc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    texto_whatsapp = (
        f"Olá, {nome_morador}! 📦\n\n"
        f"Informamos que uma nova encomenda chegou para você e já está disponível para retirada na portaria.\n\n"
        f"🔹 Endereço: Qd. {quadra} - Conj. {conjunto} - Casa/Lote {casa_lote}\n"
        f"🔹 Identificação/Rastreio: {encomenda.codigo_rastreio}\n\n"
        f"Por gentileza, compareça à portaria portando um documento para retirar o seu pacote.\n\n"
        f"Atenciosamente,\nAdministração do Condomínio"
    )
    return {"sucesso": True, "encomenda_id": enc_id, "telefone": telefone, "mensagem_texto": texto_whatsapp}


@app.post("/encomendas/{encomenda_id}/baixa")
def dar_baixa_encomenda(encomenda_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE encomendas SET status = 'ENTREGUE' WHERE id = ?", (encomenda_id,))
    conn.commit()
    conn.close()
    return {"sucesso": True, "mensagem": "Baixa registrada!"}


@app.get("/encomendas/pendentes")
def listar_pendentes():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, morador_id, nome_morador, endereco, codigo_rastreio, descricao, status FROM encomendas WHERE status = 'PENDENTE'")
    linhas = cursor.fetchall()
    conn.close()
    
    pendentes = []
    for l in linhas:
        pendentes.append({
            "id": l[0], "morador_id": l[1], "nome_morador": l[2], "endereco": l[3], "codigo_rastreio": l[4], "descricao": l[5], "status": l[6]
        })
    return pendentes
