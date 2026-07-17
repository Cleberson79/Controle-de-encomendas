import os
import io
import random
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# Token do Robô do Telegram fornecido pelo usuário
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
    # A coluna telefone agora armazena explicitamente o Chat ID do Telegram do morador
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

app = FastAPI(title="Portaria Digital Condomínio - Telegram Automatic")

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
    """Envia uma notificação direta e automatizada via API do Telegram"""
    try:
        texto_codificado = urllib.parse.quote(texto)
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={chat_id}&text={texto_codificado}&parse_mode=Markdown"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read()
    except Exception as e:
        print(f"Erro ao disparar mensagem para o Telegram: {e}")
        # Não trava a execução do endpoint para evitar falhas críticas de salvamento
        return None

# ==================== SCHEMAS PYDANTIC ====================

class MoradorManualCreate(BaseModel):
    nome_completo: str
    quadra: str = ""
    conjunto: str = ""
    casa_lote: str
    telefone: str  # Representa o Telegram Chat ID informado pelo operador

class EncomendaCreate(BaseModel):
    morador_id: int
    codigo_rastreio: str
    descricao: str = ""

# ==================== ROTAS DO SISTEMA ====================

@app.get("/moradores")
def listar_moradores(db: Session = Depends(get_db)):
    moradores = db.query(Morador).order_by(Morador.nome_completo).all()
    return moradores

@app.post("/moradores/cadastrar-manual")
def cadastrar_morador_manual(dados: MoradorManualCreate, db: Session = Depends(get_db)):
    # Evita duplicidade simples de moradores idênticos
    existente = db.query(Morador).filter(
        Morador.nome_completo.ilike(dados.nome_completo.strip()),
        Morador.casa_lote == dados.casa_lote.strip()
    ).first()
    if existente:
         raise HTTPException(status_code=400, detail="Morador já cadastrado para esta unidade!")
    
    novo = Morador(
        nome_completo=dados.nome_completo.strip(),
        quadra=dados.quadra.strip(),
        conjunto=dados.conjunto.strip(),
        casa_lote=dados.casa_lote.strip(),
        telefone=dados.telefone.strip()
    )
    db.add(novo)
    db.commit()
    return {"mensagem": "Morador adicionado com sucesso!"}

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
        
        colunas_obrigatorias = ['Nome', 'Casa', 'Telegram ID']
        for col in colunas_obrigatorias:
            if col not in df.columns:
                 raise HTTPException(status_code=400, detail=f"A planilha precisa conter a coluna '{col}'")
        
        contador = 0
        for _, row in df.iterrows():
            nome = str(row['Nome']).strip()
            casa = str(row['Casa']).strip()
            telegram_id = str(row['Telegram ID']).strip()
            
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
    
    # Monta a mensagem formatada para o Telegram
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
    
    # Dispara AUTOMATICAMENTE a notificação em segundo plano
    enviar_mensagem_telegram(chat_id=morador.telefone, texto=mensagem)
    
    return {"mensagem": "Encomenda registrada e notificação enviada com sucesso!"}

@app.get("/encomendas/pendentes")
def listar_encomendas_pendentes(db: Session = Depends(get_db)):
    encomendas = db.query(Encomenda).filter(Encomenda.status == "PENDENTE").all()
    resultado = []
    for e in encomendas:
        db.refresh(e)
        db.refresh(e.morador)
        m = e.morador
        end = f"Casa {m.casa_lote}"
        if m.quadra:
            end = f"Qd: {m.quadra} | Conj: {m.conjunto} | Casa: {m.casa_lote}"
        resultado.append({
            "id": e.id,
            "nome_morador": m.nome_completo,
            "endereco": end,
            "codigo_rastreio": e.codigo_rastreio,
            "pin_retirada": e.pin_retirada
        })
    return resultado

@app.post("/encomendas/{encomenda_id}/baixa")
def dar_baixa_encomenda(encomenda_id: int, db: Session = Depends(get_db)):
    enc = db.query(Encomenda).filter(Encomenda.id == encomenda_id, Encomenda.status == "PENDENTE").first()
    if not enc:
        raise HTTPException(status_code=404, detail="Encomenda não localizada ou já retirada.")
    
    enc.status = "ENTREGUE"
    enc.data_entrega = datetime.utcnow()
    db.commit()
    return {"mensagem": "Baixa realizada com sucesso!"}

@app.get("/encomendas/historico")
def obter_historico_recente(db: Session = Depends(get_db)):
    encomendas = db.query(Encomenda).order_by(Encomenda.data_entrada.desc()).limit(50).all()
    resultado = []
    for e in encomendas:
        m = e.morador
        end = f"Casa {m.casa_lote}"
        if m.quadra:
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
