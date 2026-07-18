import os
import io
import random
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# Token do Robô do Telegram
TELEGRAM_TOKEN = "8997167927:AAH_0Y7IcqCS-3pGRds28EbNsZUoDQVEIug"

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("A variável de ambiente DATABASE_URL não foi definida!")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==================== MODELOS DO BANCO DE DADOS ====================

class Morador(Base):
    __tablename__ = "moradores"
    id = Column(Integer, primary_key=True, index=True)
    nome_completo = Column(String, nullable=False)
    quadra = Column(String, nullable=True)
    conjunto = Column(String, nullable=True)
    casa_lote = Column(String, nullable=False)
    telefone = Column(String, nullable=False) 
    encomendas = relationship("Encomenda", back_populates="morador", cascade="all, delete-orphan")

class Encomenda(Base):
    __tablename__ = "encomendas"
    id = Column(Integer, primary_key=True, index=True)
    morador_id = Column(Integer, ForeignKey("moradores.id"), nullable=False)
    codigo_rastreio = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    pin_retirada = Column(String, nullable=False)
    status = Column(String, default="PENDENTE")
    data_entrada = Column(DateTime, default=datetime.utcnow)
    data_entrega = Column(DateTime, nullable=True)
    morador = relationship("Morador", back_populates="encomendas")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Portaria Digital Condomínio - Transição Suave")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== FUNÇÃO AUXILIAR DISPARO TELEGRAM ====================

def enviar_mensagem_telegram(chat_id: str, texto: str):
    if not chat_id:
        print("Erro no disparo: O campo chat_id está completamente vazio.")
        return False
        
    chat_id_str = str(chat_id).strip()
    
    # Remove o '.0' flutuante caso venha do Excel/Pandas
    if chat_id_str.endswith('.0'):
        chat_id_limpo = chat_id_str.split('.')[0]
    else:
        chat_id_limpo = chat_id_str

    print(f"Tentando enviar mensagem do Telegram para o ID processado: '{chat_id_limpo}'")

    if not chat_id_limpo.isdigit():
        print(f"Aviso: O destino '{chat_id_limpo}' não contém apenas números. Pulando envio.")
        return False

    try:
        texto_codificado = urllib.parse.quote(texto)
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={chat_id_limpo}&text={texto_codificado}&parse_mode=Markdown"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            print("Mensagem enviada com sucesso para a API do Telegram!")
            return True
    except Exception as e:
        print(f"Erro ao disparar mensagem para o Telegram (Bot bloqueado ou ID inexistente): {e}")
        return False

# ==================== SCHEMAS PYDANTIC ====================

class MoradorManualCreate(BaseModel):
    nome_completo: str
    quadra: str = ""
    conjunto: str = ""
    casa_lote: str
    telefone: str

class AtualizarTelegramRequest(BaseModel):
    telegram_id: str

class EncomendaCreate(BaseModel):
    morador_id: int
    codigo_rastreio: str
    descricao: str = ""

# ==================== ROTAS DE INTERFACE (FRONTEND) ====================

@app.get("/", response_class=HTMLResponse)
def carregar_pagina_principal():
    caminho_index = "index.html"
    if not os.path.exists(caminho_index):
        return "<h1>Erro: Arquivo index.html não localizado na raiz do projeto!</h1>"
        
    with open(caminho_index, "r", encoding="utf-8") as f:
        return f.read()

# ==================== ROTAS DO SISTEMA (API) ====================

@app.get("/moradores")
def listar_moradores(db: Session = Depends(get_db)):
    return db.query(Morador).order_by(Morador.nome_completo).all()

@app.post("/moradores/cadastrar-manual")
def cadastrar_morador_manual(dados: MoradorManualCreate, db: Session = Depends(get_db)):
    existente = db.query(Morador).filter(
        Morador.nome_completo.ilike(dados.nome_completo.strip()),
        Morador.casa_lote == dados.casa_lote.strip()
    ).first()
    if existente:
         raise HTTPException(status_code=400, detail="Morador já cadastrado para esta unidade!")
    
    # Força a limpeza do ID do telegram enviado manualmente
    tel_limpo = dados.telefone.strip().split('.')[0] if dados.telefone.strip().endswith('.0') else dados.telefone.strip()
    
    novo = Morador(
        nome_completo=dados.nome_completo.strip(),
        quadra=dados.quadra.strip(),
        conjunto=dados.conjunto.strip(),
        casa_lote=dados.casa_lote.strip(),
        telefone=tel_limpo
    )
    db.add(novo)
    db.commit()
    return {"mensagem": "Morador adicionado com sucesso!"}

@app.post("/moradores/{morador_id}/atualizar-telegram")
def atualizar_telegram_morador(morador_id: int, dados: AtualizarTelegramRequest, db: Session = Depends(get_db)):
    morador = db.query(Morador).filter(Morador.id == morador_id).first()
    if not morador:
        raise HTTPException(status_code=404, detail="Morador não localizado.")
    
    tel_limpo = dados.telegram_id.strip().split('.')[0] if dados.telegram_id.strip().endswith('.0') else dados.telegram_id.strip()
    morador.telefone = tel_limpo
    db.commit()
    return {"mensagem": "Telegram ID updated successfully!"}

@app.delete("/moradores/{morador_id}")
def deletar_morador(morador_id: int, db: Session = Depends(get_db)):
    morador = db.query(Morador).filter(Morador.id == morador_id).first()
    if not morador:
        raise HTTPException(status_code=404, detail="Morador não localizado.")
    db.delete(morador)
    db.commit()
    return {"mensagem": "Morador removido com sucesso!"}

@app.post("/moradores/importar-excel")
async def importar_excel_moradores(file: UploadFile = File(...), db: Session = Depends(get_db)):
    import pandas as pd
    try:
        conteudo = await file.read()
        df = pd.read_excel(io.BytesIO(conteudo))
        
        # Mapeamento inteligente para aceitar tanto o modelo antigo quanto o novo de planilha
        col_nome = next((c for c in df.columns if c.lower() in ['nome completo', 'nome']), None)
        col_casa = next((c for c in df.columns if c.lower() in ['casa lote', 'casa']), None)
        col_telegram = next((c for c in df.columns if c.lower() in ['telegram id', 'telegram_id', 'id telegram']), None)
        
        if not col_nome or not col_casa or not col_telegram:
            raise HTTPException(
                status_code=400, 
                detail="A planilha precisa conter as colunas de Nome (ou Nome Completo), Casa (ou Casa Lote) e Telegram ID."
            )
        
        contador = 0
        for _, row in df.iterrows():
            nome = str(row[col_nome]).strip()
            casa = str(row[col_casa]).strip()
            
            raw_telegram_id = str(row[col_telegram]).strip()
            telegram_id = raw_telegram_id.split('.')[0] if raw_telegram_id.endswith('.0') else raw_telegram_id
                
            qd = str(row.get('Quadra', '')).strip() if pd.notna(row.get('Quadra')) else ""
            conj = str(row.get('Conjunto', '')).strip() if pd.notna(row.get('Conjunto')) else ""
            
            if not nome or not casa or not telegram_id or nome.lower() == "nan" or telegram_id.lower() == "nan":
                continue
            
            existe = db.query(Morador).filter(
                Morador.nome_completo.ilike(nome),
                Morador.casa_lote == casa
            ).first()
            
            if not existe:
                novo = Morador(nome_completo=nome, quadra=qd, conjunto=conj, casa_lote=casa, telefone=telegram_id)
                db.add(novo)
                contador += 1
                
        db.add_all([])
        db.commit()
        return {"mensagem": f"Importação finalizada! {contador} novos moradores adicionados."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")

@app.post("/encomendas/registrar")
def registrar_encomenda(dados: EncomendaCreate, db: Session = Depends(get_db)):
    morador = db.query(Morador).filter(Morador.id == dados.morador_id).first()
    if not morador:
        raise HTTPException(status_code=404, detail="Destinatário inválido.")
    
    pin = str(random.randint(1000, 9999))
    
    nova = Encomenda(
        morador_id=dados.morador_id,
        codigo_rastreio=dados.codigo_rastreio.strip(),
        descricao=dados.descricao.strip(),
        pin_retirada=pin,
        status="PENDENTE",
        data_entrada=datetime.utcnow()
    )
    db.add(nova)
    db.commit()
    db.refresh(nova)
    
    endereco_formatado = f"Casa {morador.casa_lote}"
    if morador.quadra:
        endereco_formatado = f"Qd: {morador.quadra} | Conj: {morador.conjunto} | Casa: {morador.casa_lote}"
        
    mensagem = (
        f"📦 *OLÁ, {morador.nome_completo.upper()}!*\n\n"
        f"Uma nova encomenda chegou para você na portaria!\n\n"
        f"📍 *Endereço:* {endereco_formatado}\n"
        f"🔢 *Rastreio:* `{nova.codigo_rastreio}`\n"
        f"🔑 *CÓDIGO PIN PARA RETIRADA:* `{nova.pin_retirada}`\n\n"
        f"_Por favor, apresente este PIN ao porteiro no momento da retirada para fins de auditoria e segurança._"
    )
    
    print(f"Log Registro: Morador {morador.nome_completo} possui o valor '{morador.telefone}' guardado no campo telefone.")
    enviado = enviar_mensagem_telegram(chat_id=morador.telefone, texto=mensagem)
    
    if enviado:
        return {"mensagem": "Encomenda registrada e notificação enviada com sucesso!"}
    else:
        return {"mensagem": "Encomenda registrada! (Morador com telefone antigo ou sem Telegram ID configurado)"}

@app.get("/encomendas/pendentes")
def listar_encomendas_pendentes(db: Session = Depends(get_db)):
    encomendas = db.query(Encomenda).filter(Encomenda.status == "PENDENTE").all()
    resultado = []
    for e in encomendas:
        m = e.morador
        end = f"Casa {m.casa_lote}" if m else "N/A"
        if m and m.quadra:
            end = f"Qd: {m.quadra} | Conj: {m.conjunto} | Casa: {m.casa_lote}"
        resultado.append({
            "id": e.id,
            "nome_morador": m.nome_completo if m else "Morador Removido",
            "endereco": end,
            "codigo_rastreio": e.codigo_rastreio,
            "pin_retirada": e.pin_retirada
        })
    return resultado

@app.post("/encomendas/{encomenda_id}/baixa")
def dar_baixa_encomenda(encomenda_id: int, db: Session = Depends(get_db)):
    enc = db.query(Encomenda).filter(Encomenda.id == enigma_id if False else Encomenda.id == encomenda_id, Encomenda.status == "PENDENTE").first()
    if not enc:
        raise HTTPException(status_code=404, detail="Encomenda não localizada ou já retirada.")
    enc.status = "ENTREGUE"
    enc.data_entrega = datetime.utcnow()
    db.commit()
    return {"mensagem": "Baixa realizada com sucesso!"}

@app.get("/encomendas/historico")
def obtener_historico_recente(db: Session = Depends(get_db)):
    encomendas = db.query(Encomenda).order_by(Encomenda.data_entrada.desc()).limit(50).all()
    resultado = []
    for e in encomendas:
        m = e.morador
        end = f"Casa {m.casa_lote}" if m else "N/A"
        if m and m.quadra:
            end = f"Qd: {m.quadra} | Conj: {m.conjunto} | Casa: {m.casa_lote}"
            
        entrada_local = (e.data_entrada - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M") if e.data_entrada else "-"
        entrega_local = (e.data_entrega - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M") if e.data_entrega else "-"
        
        resultado.append({
            "nome_morador": m.nome_completo if m else "Morador Excluído",
            "endereco": end,
            "codigo_rastreio": e.codigo_rastreio,
            "data_entrada": entrada_local,
            "data_entrega": entrega_local,
            "status": e.status
        })
    return resultado

@app.post("/encomendas/backup-limpeza")
def backup_e_limpeza_cloud(db: Session = Depends(get_db)):
    import openpyxl
    limite_tempo = datetime.utcnow() - timedelta(days=30)
    encomendas_antigas = db.query(Encomenda).filter(
        Encomenda.status == "ENTREGUE",
        Encomenda.data_entrega <= limite_tempo
    ).all()
    
    if not encomendas_antigas:
        raise HTTPException(status_code=400, detail="Nenhum registro com mais de 30 dias encontrado para limpeza.")
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Auditoria Expurgo"
    ws.append(["ID", "Morador", "Código Rastreio", "Descrição", "PIN", "Data Entrada", "Data Entrega"])
    
    for e in encomendas_antigas:
        nome_m = e.morador.nome_completo if e.morador else "Removido"
        ws.append([
            e.id, nome_m, e.codigo_rastreio, e.descricao, e.pin_retirada,
            e.data_entrada.strftime("%Y-%m-%d %H:%M") if e.data_entrada else "",
            e.data_entrega.strftime("%Y-%m-%d %H:%M") if e.data_entrega else ""
        ])
        db.delete(e)
        
    db.commit()
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=backup_limpeza.xlsx"}
    )
