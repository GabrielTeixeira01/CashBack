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

# Carrega as variáveis de ambiente (do arquivo .env, se houver)
load_dotenv()

# Configuração do banco de dados MySQL via SQLAlchemy
# No Railway, certifique-se de configurar a variável de ambiente DATABASE_URL
# Pega a URL do banco. O Railway costuma fornecer MYSQL_URL ou DATABASE_URL.
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL") or "sqlite:///./test.db"

# O SQLAlchemy com PyMySQL exige o prefixo mysql+pymysql:// em vez de apenas mysql://
if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

# Cria a engine de conexão. Se for erro de conexão, verificamos os parâmetros
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Modelos do Banco de Dados ---
class ConsultaCashback(Base):
    __tablename__ = "consultas_cashback"
    
    id = Column(Integer, primary_key=True, index=True)
    ip_usuario = Column(String(50), index=True) # Para poder buscar por IP dps
    nome = Column(String(100))
    tipo_cliente = Column(String(50))
    valor = Column(Float)
    cashback = Column(Float)
    criado_em = Column(DateTime, default=datetime.utcnow)

# Cria as tabelas se não existirem
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Aviso: Não foi possível conectar/criar tabelas no BD agora. Erro: {e}")


# --- Esquemas do Pydantic para a API ---
class CalcularRequest(BaseModel):
    nome: str
    tipo_cliente: str
    valor: float

class CalcularResponse(BaseModel):
    cashback: float

class ConsultaHistoricoResponse(BaseModel):
    id: int
    nome: str
    tipo_cliente: str
    valor: float
    cashback: float
    criado_em: datetime


# --- Inicialização da Aplicação FastAPI ---
app = FastAPI(title="Cashback API")

# Habilitando CORS para permitir conexões do frontend (estático/html)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permite tudo, pois o frontend está estático
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependência para pegar uma sessão no banco
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Rotas da API ---

@app.get("/health")
def health_check():
    return {"status": "ok", "database": str(engine.url.drivername)}

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

print("Iniciando aplicação...")

@app.post("/calcular", response_model=CalcularResponse)
def calcular_cashback(req_data: CalcularRequest, request: Request, db: Session = Depends(get_db)):
    # Pega o IP, em ambientes com proxy (ex: Railway), usa o header X-Forwarded-For se existir
    ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()

    # Diferencia regra baseada em tipo de cliente, Normal=5%, VIP=10% (conforme solicitado e padrão adotado)
    taxa = 0.05
    if req_data.tipo_cliente.lower() == "vip":
        taxa = 0.10
        
    valor_cashback = req_data.valor * taxa
    
    nova_consulta = ConsultaCashback(
        ip_usuario=ip,
        nome=req_data.nome,
        tipo_cliente=req_data.tipo_cliente.upper(),
        valor=req_data.valor,
        cashback=valor_cashback
    )
    
    # Salvar no DB
    try:
        db.add(nova_consulta)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao salvar no banco de dados. Verifique a conexão com o MySQL.")

    return CalcularResponse(cashback=valor_cashback)


@app.get("/historico")
def obter_historico(request: Request, db: Session = Depends(get_db)):
    # Pega o IP
    ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        
    try:
        # Busca registro histórico SOMENTE para esse IP acessando agora
        consultas = db.query(ConsultaCashback).filter(ConsultaCashback.ip_usuario == ip).order_by(ConsultaCashback.criado_em.desc()).all()
        
        # O HTML espera {"historico": [ ... ] }
        resultado = []
        for c in consultas:
            resultado.append({
                "tipo_cliente": c.tipo_cliente,
                "valor": c.valor,
                "cashback": c.cashback,
                "criado_em": c.criado_em.isoformat()
            })
            
        return {"historico": resultado}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erro ao acessar histórico. Banco inacessível.")
