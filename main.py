from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

app = FastAPI(title="Sistema de Encomendas - Banco Permanente")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚠️ COLE AQUI O SEU LINK DO NEON TECH ENTRE AS ASPAS
# Exemplo: DATABASE_URL = "postgresql://usuario:senha@ep-cool-darkness...neon.tech/neondb?sslmode=require"
DATABASE_URL = "postgresql://neondb_owner:npg_i0MgPWlm6UBK@ep-twilight-wildflower-ac9ra3lq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Ajuste técnico para garantir compatibilidade com o Render
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configuração do Banco de Dados usando SQLAlchemy
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Definição das Tabelas Reais no Banco de Dados
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

# Cria as tabelas na nuvem se elas não existirem
Base.metadata.create_all(bind=engine)

# Modelos para recebimento de dados da tela
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
        raise HTTPException(status_code=400, detail=value="Envie um arquivo Excel válido (.xlsx)")
    try:
        conteudo = await file.read()
        df = pd.read_excel(io.BytesIO(conteudo))
        colunas_esperadas = ["Nome Completo", "Quadra", "Conjunto", "Casa/Lote", "Telefone (WhatsApp)"]
        for col in colunas_esperadas:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Coluna ausente: {col}")
        
        db = SessionLocal()
        for _, linha in df.iterrows():
            tel_limpo = ''.join(filter(str.isdigit, str(linha["Telefone (WhatsApp)"])))
            novo_morador = MoradorDB(
                nome_completo=str(linha["Nome Completo"]).strip(),
                quadra=str(linha["Quadra"]).strip(),
                conjunto=str(linha["Conjunto"]).strip(),
                casa_lote=str(linha["Casa/Lote"]).strip(),
                telefone=tel_limpo
            )
            db.add(novo_morador)
        db.commit()
        db.close()
        return {"sucesso": True, "mensagem": "Moradores importados com sucesso na nuvem!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@app.post("/moradores/cadastrar-manual")
def cadastrar_manual(morador: MoradorManualInput):
    tel_limpo = ''.join(filter(str.isdigit, morador.telefone))
    db = SessionLocal()
    novo = MoradorDB(
        nome_completo=morador.nome_completo.strip(),
        quadra=morador.quadra.strip(),
        conjunto=morador.conjunto.strip(),
        casa_lote=morador.casa_lote.strip(),
        telefone=tel_limpo
    )
    db.add(novo)
    db.commit()
    db.close()
    return {"sucesso": True, "mensagem": "Morador cadastrado na nuvem!"}


@app.get("/moradores", response_model=List[Morador])
def listar_moradores():
    db = SessionLocal()
    linhas = db.query(MoradorDB).all()
    db.close()
    return [{
        "id": l.id, "nome_completo": l.nome_completo, "quadra": l.quadra,
        "conjunto": l.conjunto, "casa_lote": l.casa_lote, "telefone": l.telefone
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
    
    endereco_completo = f"Qd. {morador.quadra} - Cj. {morador.conjunto} - Casa {morador.casa_lote}"
    
    nova_encomenda = EncomendaDB(
        morador_id=encomenda.morador_id,
        nome_morador=morador.nome_completo,
        endereco=endereco_completo,
        codigo_rastreio=encomenda.codigo_rastreio,
        descricao=encomenda.descricao,
        status="PENDENTE"
    )
    db.add(nova_encomenda)
    db.commit()
    db.refresh(nova_encomenda)
    
    texto_whatsapp = (
        f"Olá, {morador.nome_completo}! 📦\n\n"
        f"Informamos que uma nova encomenda chegou para você e já está disponível para retirada na portaria.\n\n"
        f"🔹 Endereço: Qd. {morador.quadra} - Conj. {morador.conjunto} - Casa/Lote {morador_lote := morador.casa_lote}\n"
        f"🔹 Identificação/Rastreio: {encomenda.codigo_rastreio}\n\n"
        f"Por gentileza, compareça à portaria portando um documento para retirar o seu pacote.\n\n"
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
        "descricao": l.descricao, "status": l.status
    } for l in linhas]
