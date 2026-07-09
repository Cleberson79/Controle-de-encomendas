from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import os
import random
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

app = FastAPI(title="Sistema de Encomendas - Correção de Comunicação")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "postgresql://neondb_owner:npg_i0MgPWlm6UBK@ep-twilight-wildflower-ac9ra3lq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MoradorDB(Base):
    __tablename__ = "moradores"
    id = Column(Integer, primary_key=True, index=True)
    nome_completo = Column(String)
    quadra = Column(String)
    conjunto = Column(String)
    casa_lote = Column(String)
    telefone = Column(String)

class EncomendaDB(Base):
    __tablename__ = "encomendas"
    id = Column(Integer, primary_key=True, index=True)
    morador_id = Column(Integer, ForeignKey("moradores.id"))
    nome_morador = Column(String)
    endereco = Column(String)
    codigo_rastreio = Column(String)
    descricao = Column(String)
    status = Column(String, default="PENDENTE")
    pin_retirada = Column(String)

Base.metadata.create_all(bind=engine)

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
        
        db = SessionLocal()
        contagem_novos = 0
        contagem_duplicados = 0
        
        for _, linha in df.iterrows():
            nome_limpo = str(linha["Nome Completo"]).strip().lower()
            quadra_limpa = str(linha["Quadra"]).strip().lower()
            conjunto_limpa = str(linha["Conjunto"]).strip().lower()
            casa_limpa = str(linha["Casa/Lote"]).strip().lower()
            tel_limpo = ''.join(filter(str.isdigit, str(linha["Telefone (WhatsApp)"])))
            
            existe = db.query(MoradorDB).filter(
                MoradorDB.nome_completo == nome_limpo,
                MoradorDB.quadra == quadra_limpa,
                MoradorDB.conjunto == conjunto_limpa,
                MoradorDB.casa_lote == casa_limpa,
                MoradorDB.telefone == tel_limpo
            ).first()
            
            if existe:
                contagem_duplicados += 1
                continue
                
            novo_morador = MoradorDB(
                nome_completo=nome_limpo,
                quadra=quadra_limpa,
                conjunto=conjunto_limpa,
                casa_lote=casa_limpa,
                telefone=tel_limpo
            )
            db.add(novo_morador)
            contagem_novos += 1
            
        db.commit()
        db.close()
        
        msg = f"Importação concluída! {contagem_novos} novos moradores adicionados."
        if contagem_duplicados > 0:
            msg += f" ({contagem_duplicados} registros duplicados foram ignorados)."
            
        return {"sucesso": True, "mensagem": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@app.post("/moradores/cadastrar-manual")
def cadastrar_manual(morador: MoradorManualInput):
    nome_limpo = morador.nome_completo.strip().lower()
    quadra_limpa = morador.quadra.strip().lower()
    conjunto_limpa = morador.conjunto.strip().lower()
    casa_limpa = morador.casa_lote.strip().lower()
    tel_limpo = ''.join(filter(str.isdigit, morador.telefone))
    
    db = SessionLocal()
    
    existe = db.query(MoradorDB).filter(
        MoradorDB.nome_completo == nome_limpo,
        MoradorDB.quadra == quadra_limpa,
        MoradorDB.conjunto == conjunto_limpa,
        MoradorDB.casa_lote == casa_limpa,
        MoradorDB.telefone == tel_limpo
    ).first()
    
    if existe:
        db.close()
        raise HTTPException(status_code=400, detail="Atenção: Este morador com estes mesmos dados já está cadastrado no sistema!")
        
    novo = MoradorDB(
        nome_completo=nome_limpo,
        quadra=quadra_limpa,
        conjunto=conjunto_limpa,
        casa_lote=casa_limpa,
        telefone=tel_limpo
    )
    db.add(novo)
    db.commit()
    db.close()
    return {"sucesso": True, "mensagem": "Morador cadastrado na nuvem!"}


@app.get("/moradores")
def listar_moradores():
    db = SessionLocal()
    linhas = db.query(MoradorDB).all()
    db.close()
    return [{
        "id": l.id, 
        "nome_completo": l.nome_completo.title(), 
        "quadra": l.quadra.upper(), 
        "conjunto": l.conjunto.upper(), 
        "casa_lote": l.casa_lote.upper(), 
        "telefone": l.telefone
    } for l in linhas]


@app.delete("/moradores/{morador_id}")
def deletar_morador(morador_id: int):
    db = SessionLocal()
    morador = db.query(MoradorDB).filter(MoradorDB.id == morador_id).first()
    if morador:
        db.delete(morador)
        db.commit()
    db.close()
    return {"sucesso": True, "mensagem": "Morador removido!"}


@app.post("/encomendas/registrar")
def registrar_encomenda(encomenda: EncomendaInput):
    db = SessionLocal()
    morador = db.query(MoradorDB).filter(MoradorDB.id == encomenda.morador_id).first()
    
    if not morador:
        db.close()
        raise HTTPException(status_code=404, detail="Morador não encontrado.")
    
    nome_bonito = morador.nome_completo.title()
    endereco_completo = f"Qd. {morador.quadra.upper()} - Cj. {morador.conjunto.upper()} - Casa {morador.casa_lote.upper()}"
    pin_gerado = str(random.randint(1000, 9999))
    
    nova_encomenda = EncomendaDB(
        morador_id=encomenda.morador_id,
        nome_morador=nome_bonito,
        endereco=endereco_completo,
        codigo_rastreio=encomenda.codigo_rastreio,
        descricao=encomenda.descricao,
        status="PENDENTE",
        pin_retirada=pin_gerado
    )
    db.add(nova_encomenda)
    db.commit()
    db.refresh(nova_encomenda)
    
    texto_whatsapp = (
        f"Olá, {nome_bonito}! 📦\n\n"
        f"Informamos que uma nova encomenda chegou para você e já está disponível para retirada na portaria.\n\n"
        f"🔹 Endereço: {endereco_completo}\n"
        f"🔹 Identificação/Rastreio: {encomenda.codigo_rastreio}\n\n"
        f"⚠️ CÓDIGO DE RETIRADA (PIN): {pin_gerado}\n"
        f"Por gentileza, informe este código ao porteiro e assine o livro de protocolo no ato da retirada.\n\n"
        f"Atenciosamente,\nAdministração do Condomínio"
    )
    
    tel_morador = morador.telefone
    db.close()
    return {"sucesso": True, "encomenda_id": nova_encomenda.id, "telefone": tel_morador, "mensagem_texto": texto_whatsapp}


@app.post("/encomendas/{encomenda_id}/baixa")
def dar_baixa_encomenda(encomenda_id: int):
    db = SessionLocal()
    encomenda = db.query(EncomendaDB).filter(EncomendaDB.id == encomenda_id).first()
    if encomenda:
        encomenda.status = "ENTREGUE"
        db.commit()
    db.close()
    return {"sucesso": True, "mensagem": "Baixa registrada!"}


@app.get("/encomendas/pendentes")
def listar_pendentes():
    db = SessionLocal()
    linhas = db.query(EncomendaDB).filter(EncomendaDB.status == "PENDENTE").all()
    db.close()
    return [{
        "id": l.id, "morador_id": l.morador_id, "nome_morador": l.nome_morador,
        "endereco": l.endereco, "codigo_rastreio": l.codigo_rastreio,
        "descricao": l.descricao, "status": l.status, "pin_retirada": l.pin_retirada
    } for l in linhas]
