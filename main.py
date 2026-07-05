from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
import os

app = FastAPI(title="Sistema de Encomendas - Condomínio Horizontal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

banco_moradores = []
banco_encomendas = []

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


# 🌟 ALTERAÇÃO CRUCIAL: Agora a página inicial carrega o seu arquivo index.html na internet!
@app.get("/", response_class=HTMLResponse)
def pagina_inicial():
    caminho_index = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(caminho_index):
        with open(caminho_index, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Erro: Arquivo index.html não encontrado no servidor.</h1>"


@app.post("/moradores/importar-excel")
async def importar_excel(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Por favor, envie um arquivo Excel válido (.xlsx)")
    try:
        conteudo = await file.read()
        df = pd.read_excel(io.BytesIO(conteudo))
        colunas_esperadas = ["Nome Completo", "Quadra", "Conjunto", "Casa/Lote", "Telefone (WhatsApp)"]
        for col in colunas_esperadas:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Coluna ausente: {col}")
        
        contagem_novos = 0
        for _, linha in df.iterrows():
            tel_limpo = ''.join(filter(str.isdigit, str(linha["Telefone (WhatsApp)"])))
            novo_id = max([m["id"] for m in banco_moradores], default=0) + 1
            novo_morador = {
                "id": novo_id,
                "nome_completo": str(linha["Nome Completo"]).strip(),
                "quadra": str(linha["Quadra"]).strip(),
                "conjunto": str(linha["Conjunto"]).strip(),
                "casa_lote": str(linha["Casa/Lote"]).strip(),
                "telefone": tel_limpo
            }
            banco_moradores.append(novo_morador)
            contagem_novos += 1
        return {"sucesso": True, "mensagem": f"{contagem_novos} moradores importados!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")

@app.post("/moradores/cadastrar-manual")
def cadastrar_manual(morador: MoradorManualInput):
    tel_limpo = ''.join(filter(str.isdigit, morador.telefone))
    novo_id = max([m["id"] for m in banco_moradores], default=0) + 1
    novo_morador = {
        "id": novo_id,
        "nome_completo": morador.nome_completo.strip(),
        "quadra": morador.quadra.strip(),
        "conjunto": morador.conjunto.strip(),
        "casa_lote": morador.casa_lote.strip(),
        "telefone": tel_limpo
    }
    banco_moradores.append(novo_morador)
    return {"sucesso": True, "mensagem": "Morador cadastrado!"}

@app.get("/moradores", response_model=List[Morador])
def listar_moradores():
    return banco_moradores

@app.delete("/moradores/{morador_id}")
def deletar_morador(morador_id: int):
    global banco_moradores
    banco_moradores = [m for m in banco_moradores if m["id"] != morador_id]
    return {"sucesso": True, "mensagem": "Morador removido!"}

@app.post("/encomendas/registrar")
def registrar_encomenda(encomenda: EncomendaInput):
    morador_encontrado = next((m for m in banco_moradores if m["id"] == encomenda.morador_id), None)
    if not morador_encontrado:
        raise HTTPException(status_code=404, detail="Morador não encontrado.")
    
    enc_id = len(banco_encomendas) + 1
    nova_encomenda = {
        "id": enc_id,
        "morador_id": encomenda.morador_id,
        "nome_morador": morador_encontrado['nome_completo'],
        "endereco": f"Qd. {morador_encontrado['quadra']} - Cj. {morador_encontrado['conjunto']} - Casa {morador_encontrado['casa_lote']}",
        "codigo_rastreio": encomenda.codigo_rastreio,
        "descricao": encomenda.descricao,
        "status": "PENDENTE"
    }
    banco_encomendas.append(nova_encomenda)
    
    texto_whatsapp = (
        f"Olá, {morador_encontrado['nome_completo']}! 📦\n\n"
        f"Informamos que uma nova encomenda chegou para você e já está disponível para retirada na portaria.\n\n"
        f"🔹 Endereço: Qd. {morador_encontrado['quadra']} - Conj. {morador_encontrado['conjunto']} - Casa/Lote {morador_encontrado['casa_lote']}\n"
        f"🔹 Identificação/Rastreio: {encomenda.codigo_rastreio}\n\n"
        f"Por gentileza, compareça à portaria portando um documento para retirar o seu pacote.\n\n"
        f"Atenciosamente,\nAdministração do Condomínio"
    )
    return {"sucesso": True, "encomenda_id": enc_id, "telefone": morador_encontrado['telefone'], "mensagem_texto": texto_whatsapp}

@app.post("/encomendas/{encomenda_id}/baixa")
def dar_baixa_encomenda(encomenda_id: int):
    encomenda = next((e for e in banco_encomendas if e["id"] == encomenda_id), None)
    if not encomenda:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada.")
    encomenda["status"] = "ENTREGUE"
    return {"sucesso": True, "mensagem": "Baixa registrada!"}

@app.get("/encomendas/pendentes")
def listar_pendentes():
    return [e for e in banco_encomendas if e["status"] == "PENDENTE"]