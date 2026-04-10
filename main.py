import os
from datetime import datetime
from typing import List

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

# Prioridade para MYSQL_URL (padrão Railway) sobre DATABASE_URL
DATABASE_URL = os.getenv("MYSQL_URL") or os.getenv("DATABASE_URL") or "sqlite:///./test.db"

if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

# Debug state global
last_db_error = "Nenhum erro registrado até agora."

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    last_db_error = f"Erro na criação da engine: {str(e)}"
    Base = declarative_base() # Fallback

class ConsultaCashback(Base):
    __tablename__ = "consultas_cashback"
    id = Column(Integer, primary_key=True, index=True)
    ip_usuario = Column(String(50), index=True)
    nome = Column(String(100))
    tipo_cliente = Column(String(50))
    valor = Column(Float)
    cashback = Column(Float)
    criado_em = Column(DateTime, default=datetime.utcnow)

app = FastAPI(title="Cashback API")

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

def get_client_ip(request: Request):
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host

@app.on_event("startup")
def startup_event():
    global last_db_error
    try:
        if "sqlite" not in DATABASE_URL:
            Base.metadata.create_all(bind=engine)
            last_db_error = "Banco de dados MySQL conectado e tabelas criadas com sucesso."
    except Exception as e:
        last_db_error = f"Erro ao criar tabelas no MySQL: {str(e)}"

# --- Rotas ---

@app.get("/health")
def health_check(request: Request):
    return {
        "status": "ok",
        "ip_atual": get_client_ip(request),
        "banco_info": last_db_error,
        "database_url_used": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "local_sqlite"
    }

@app.get("/")
def serve_frontend():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "index.html nao encontrado"}

@app.post("/calcular", response_model=CalcularResponse if 'CalcularResponse' in globals() else dict)
def calcular_cashback(req_data: dict, request: Request, db: Session = Depends(get_db)):
    global last_db_error
    ip = get_client_ip(request)
    
    taxa = 0.10 if req_data.get("tipo_cliente", "").lower() == "vip" else 0.05
    valor = float(req_data.get("valor", 0))
    valor_cashback = valor * taxa
    
    nova_consulta = ConsultaCashback(
        ip_usuario=ip,
        nome=req_data.get("nome", "Sem Nome"),
        tipo_cliente=req_data.get("tipo_cliente", "NORMAL").upper(),
        valor=valor,
        cashback=valor_cashback
    )
    
    try:
        db.add(nova_consulta)
        db.commit()
    except Exception as e:
        db.rollback()
        last_db_error = f"Falha ao salvar consulta as {datetime.now()}: {str(e)}"
    
    return {"cashback": valor_cashback}

@app.get("/historico")
def obter_historico(request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    try:
        consultas = db.query(ConsultaCashback).filter(ConsultaCashback.ip_usuario == ip).order_by(ConsultaCashback.criado_em.desc()).limit(20).all()
        return {"historico": [{
            "nome": c.nome,
            "tipo_cliente": c.tipo_cliente,
            "valor": c.valor,
            "cashback": c.cashback,
            "criado_em": c.criado_em.isoformat()
        } for c in consultas]}
    except Exception as e:
        return {"historico": [], "error": str(e)}

# Re-declarando os modelos Pydantic no final para evitar erro de escopo no dict acima se necessário
class CalcularRequest(BaseModel):
    nome: str
    tipo_cliente: str
    valor: float

class CalcularResponse(BaseModel):
    cashback: float
