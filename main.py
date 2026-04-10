import os
from datetime import datetime
from typing import List

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()


DATABASE_URL = os.getenv("MYSQL_URL") or os.getenv("DATABASE_URL") or "sqlite:///./test.db"

if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ConsultaCashback(Base):
    __tablename__ = "consultas_cashback"
    id = Column(Integer, primary_key=True, index=True)
    ip_usuario = Column(String(50), index=True)
    nome = Column(String(100))
    tipo_cliente = Column(String(50))
    valor = Column(Float)
    cashback = Column(Float)
    criado_em = Column(DateTime, default=datetime.utcnow)


class CalcularRequest(BaseModel):
    nome: str
    tipo_cliente: str
    valor: float

class CalcularResponse(BaseModel):
    cashback: float


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
    try:
        if "sqlite" not in DATABASE_URL:
            Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Erro na conexão com o banco de dados: {e}")

@app.get("/")
def serve_frontend():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "Frontend not found"}

@app.post("/calcular", response_model=CalcularResponse)
def calcular_cashback(req_data: CalcularRequest, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    
    taxa = 0.10 if req_data.tipo_cliente.lower() == "vip" else 0.05
    valor_cashback = req_data.valor * taxa
    
    nova_consulta = ConsultaCashback(
        ip_usuario=ip,
        nome=req_data.nome,
        tipo_cliente=req_data.tipo_cliente.upper(),
        valor=req_data.valor,
        cashback=valor_cashback
    )
    
    try:
        db.add(nova_consulta)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Erro ao salvar consulta: {e}")
    
    return CalcularResponse(cashback=valor_cashback)

@app.get("/historico")
def obter_historico(request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    try:
        consultas = db.query(ConsultaCashback).filter(ConsultaCashback.ip_usuario == ip).order_by(ConsultaCashback.criado_em.desc()).limit(20).all()
        return {"historico": [{
            "id": c.id,
            "nome": c.nome,
            "tipo_cliente": c.tipo_cliente,
            "valor": c.valor,
            "cashback": c.cashback,
            "criado_em": c.criado_em.isoformat()
        } for c in consultas]}
    except Exception:
        return {"historico": []}

@app.delete("/historico")
def limpar_historico(request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    try:
        db.query(ConsultaCashback).filter(ConsultaCashback.ip_usuario == ip).delete()
        db.commit()
        return {"status": "ok"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500)

@app.delete("/historico/{item_id}")
def deletar_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    try:
        item = db.query(ConsultaCashback).filter(ConsultaCashback.id == item_id, ConsultaCashback.ip_usuario == ip).first()
        if not item:
            raise HTTPException(status_code=404)
        db.delete(item)
        db.commit()
        return {"status": "ok"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500)
