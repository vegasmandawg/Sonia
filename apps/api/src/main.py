from fastapi import FastAPI

app = FastAPI(title="Sonia API Gateway", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "api-gateway"}

@app.get("/version")
def version():
    return {"name": "sonia-final", "version": "0.1.0"}
