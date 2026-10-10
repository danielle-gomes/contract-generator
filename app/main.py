"""
Gerador de Contratos - Juridico
Adicionar contrato = 1 .json + 1 .docx em /contracts. Zero codigo.
"""
import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from docx.oxml.ns import qn
from docxtpl import DocxTemplate
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from decimal import Decimal, InvalidOperation 
from num2words import num2words


from auth import get_user_name

BASE_DIR = Path(__file__).parent
CONTRACTS_DIR = BASE_DIR.parent / "contracts"

app = FastAPI(title="Gerador de Contratos - Juridico")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")
views = Jinja2Templates(directory=BASE_DIR / "templates")


def load_schemas() -> dict:
    """Le todos os *.json de /contracts (sem cache) e aplica defaults nos campos."""
    schemas = {}
    for path in sorted(CONTRACTS_DIR.glob("*.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            for f in schema.get("fields", []):
                f.setdefault("type", "text")
                f.setdefault("required", f["type"] != "boolean")
            schemas[path.stem] = schema
        except json.JSONDecodeError as exc:
            schemas[path.stem] = {"_error": f"JSON invalido: {exc}"}
    return schemas


def get_schema(contract_id: str) -> dict:
    schema = load_schemas().get(contract_id)
    if not schema or "_error" in schema:
        raise HTTPException(404, f"Contrato '{contract_id}' nao encontrado ou com JSON invalido.")
    return schema


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "contrato"


def format_brl(raw: str) -> str:
    """'R$ 1.234,56' -> 'R$ 1.234,56 (mil, duzentos e trinta e quatro reais e cinquenta e seis centavos)'."""
    clean = re.sub(r"[^\d,]", "", raw).replace(",", ".")
    try:
        value = Decimal(clean)
    except InvalidOperation:
        raise HTTPException(422, f"Valor inválido: {raw}")
    numero = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    extenso = num2words(value, lang="pt_BR", to="currency")
    return f"R$ {numero} ({extenso})"


def strip_comments(docx) -> None:
    """Remove os comentarios internos do Juridico do arquivo final (template continua anotado)."""
    for tag in ("w:commentRangeStart", "w:commentRangeEnd", "w:commentReference"):
        for el in list(docx.element.body.iter(qn(tag))):
            el.getparent().remove(el)
    for rid, rel in list(docx.part.rels.items()):
        if "comments" in rel.reltype:
            docx.part.drop_rel(rid)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    options = [
        {"id": k, "label": v.get("label", k), "error": v.get("_error")}
        for k, v in load_schemas().items()
    ]
    return views.TemplateResponse(
        "index.html",
        {"request": request, "options": options, "user_name": get_user_name(request)},
    )


@app.get("/form/{contract_id}", response_class=HTMLResponse)
def form(request: Request, contract_id: str):
    return views.TemplateResponse(
        "form.html",
        {
            "request": request,
            "contract_id": contract_id,
            "schema": get_schema(contract_id),
            "user_name": get_user_name(request),
        },
    )


@app.post("/generate/{contract_id}")
async def generate(contract_id: str, request: Request):
    schema = get_schema(contract_id)
    form_data = await request.form()
    context, missing = {}, []

    for field in schema["fields"]:
        tag, ftype = field["tag"], field["type"]
        if ftype == "boolean":
            context[tag] = tag in form_data
            continue

        raw = (form_data.get(tag) or "").strip()
        if not raw:
            if field["required"]:
                missing.append(field.get("question", tag))
            context[tag] = ""
        elif ftype == "number":
            context[tag] = float(raw)  # input type=number ja envia com ponto decimal
        elif ftype == "date":
            context[tag] = datetime.fromisoformat(raw).strftime("%d/%m/%Y")
        elif ftype == "money":
            context[tag] = format_brl(raw)
        else:
            context[tag] = raw.replace("\r\n", "\n")

    if missing:
        raise HTTPException(422, {"erro": "Campos obrigatorios nao preenchidos", "campos": missing})

    template_path = CONTRACTS_DIR / schema["template"]
    if not template_path.exists():
        raise HTTPException(500, f"Template '{schema['template']}' nao encontrado no servidor.")

    doc = DocxTemplate(str(template_path))
    doc.render(context, autoescape=True)  # '&' e '<' nao corrompem mais o docx
    strip_comments(doc.docx)

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
    """Readiness/liveness probe do Pergola."""
    return {"status": "ok", "contratos": len(load_schemas())}