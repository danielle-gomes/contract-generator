"""
Gerador de Contratos - Juridico
Engine generica: le schemas JSON + templates .docx e renderiza tudo dinamicamente.
Adicionar um contrato novo = adicionar 1 .json + 1 .docx em /contracts. Zero codigo.
"""
import io
import json
import re
from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from fastapi import Depends
from app.auth import get_user

BASE_DIR = Path(__file__).parent
CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"

app = FastAPI(title="Gerador de Contratos - Juridico")
views = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@app.get("/whoami")
def whoami(user: dict = Depends(get_user)):
    return user

def load_schemas() -> dict:
    """Le todos os *.json de /contracts. Sem cache: Juridico sobe arquivo e ja aparece."""
    schemas = {}
    for path in sorted(CONTRACTS_DIR.glob("*.json")):
        try:
            schemas[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            schemas[path.stem] = {"_error": f"JSON invalido: {exc}"}
    return schemas


def get_schema(contract_id: str) -> dict:
    schema = load_schemas().get(contract_id)
    if not schema or "_error" in schema:
        raise HTTPException(404, f"Contrato '{contract_id}' nao encontrado ou com JSON invalido.")
    return schema


def slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "contrato"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    schemas = load_schemas()
    options = [
        {"id": key, "label": val.get("label", key), "error": val.get("_error")}
        for key, val in schemas.items()
    ]
    return views.TemplateResponse("index.html", {"request": request, "options": options})


@app.get("/form/{contract_id}", response_class=HTMLResponse)
def form(request: Request, contract_id: str):
    schema = get_schema(contract_id)
    return views.TemplateResponse(
        "form.html", {"request": request, "contract_id": contract_id, "schema": schema}
    )


@app.post("/generate/{contract_id}")
async def generate(contract_id: str, request: Request):
    schema = get_schema(contract_id)
    form_data = await request.form()

    context, missing = {}, []
    for field in schema["fields"]:
        tag, ftype = field["tag"], field.get("type", "text")
        raw = form_data.get(tag)

        if ftype == "boolean":
            context[tag] = raw is not None          # checkbox marcado ou nao
            continue

        if not raw and field.get("required", True):
            missing.append(field.get("question", tag))
            continue

        if ftype == "number":
            context[tag] = float(str(raw).replace(".", "").replace(",", ".")) if raw else None
        elif ftype == "date" and raw:
            context[tag] = datetime.fromisoformat(raw).strftime("%d/%m/%Y")
        else:
            context[tag] = raw or ""

    # Business exception explicita: nada de contrato saindo com buraco silencioso
    if missing:
        raise HTTPException(422, {"erro": "Campos obrigatorios nao preenchidos", "campos": missing})

    template_path = CONTRACTS_DIR / schema["template"]
    if not template_path.exists():
        raise HTTPException(500, f"Template '{schema['template']}' nao encontrado no servidor.")

    doc = DocxTemplate(str(template_path))
    doc.render(context)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    filename = f"{slugify(schema.get('label', contract_id))}_{datetime.now():%Y%m%d_%H%M%S}.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/health")
def health():
    """Usado pelo readiness/liveness probe do Pergola."""
    return {"status": "ok", "contratos": len(load_schemas())}
