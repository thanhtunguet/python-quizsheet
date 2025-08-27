import io
import os
import re
import zipfile
from typing import List, Dict

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv

import urllib.parse

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
GOOGLE_SHEETS_API_KEY = os.getenv("GOOGLE_SHEETS_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY env var")
if not GOOGLE_SHEETS_API_KEY:
    raise RuntimeError("Missing GOOGLE_SHEETS_API_KEY env var")


# --------- Load System Prompt from HBS file ----------
def _load_system_prompt() -> str:
    """Load system prompt from system_prompt.hbs file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "system_prompt.hbs")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise RuntimeError(f"System prompt file not found: {prompt_path}")
    except Exception as e:
        raise RuntimeError(f"Error loading system prompt: {e}")


SYSTEM_PROMPT = _load_system_prompt()

# --------- FastAPI ----------
app = FastAPI(title="Quiz Sheet → Gemini → XLSX (per language)")

# Removed ProcessBody BaseModel - using Form parameters instead


# --------- Helpers ----------
def _extract_sheet_id(sheet_url: str) -> str:
    """
    Extract Google Sheet ID from various URL formats.
    """
    # Handle different URL formats
    if "/d/" in sheet_url:
        # Standard format: https://docs.google.com/spreadsheets/d/SHEET_ID/edit#gid=0
        return sheet_url.split("/d/")[1].split("/")[0]
    elif "key=" in sheet_url:
        # Legacy format: https://docs.google.com/spreadsheets/ccc?key=SHEET_ID
        return sheet_url.split("key=")[1].split("&")[0]
    else:
        raise ValueError(f"Invalid Google Sheets URL format: {sheet_url}")


async def _read_sheet_columns(sheet_url: str, sheet_name: str) -> List[List[str]]:
    """
    Read sheet data using Google Sheets API v4 with API key authentication.
    Returns list of columns (max 3), each column is a list of cells by row order.
    """
    try:
        sheet_id = _extract_sheet_id(sheet_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Encode sheet name for URL
    encoded_sheet_name = urllib.parse.quote(sheet_name)

    # Google Sheets API v4 endpoint
    api_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{encoded_sheet_name}?key={GOOGLE_SHEETS_API_KEY}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(api_url)
        if resp.status_code != 200:
            if resp.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied. Make sure the sheet is public and API key is valid.",
                )
            elif resp.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Sheet '{sheet_name}' not found in the spreadsheet.",
                )
            else:
                raise HTTPException(
                    status_code=502, detail=f"Google Sheets API error: {resp.text}"
                )

        data = resp.json()

    # Extract values from API response
    values = data.get("values", [])
    if not values:
        return []

    # Convert rows to columns (transpose matrix)
    # Limit to max 3 columns with actual data
    max_cols = min(3, max(len(r) for r in values) if values else 0)
    cols = []
    for c in range(max_cols):
        col_vals = []
        for r in values:
            val = r[c] if c < len(r) else ""
            col_vals.append(val)
        # Remove empty trailing cells
        while col_vals and (col_vals[-1] is None or str(col_vals[-1]).strip() == ""):
            col_vals.pop()
        if any(v.strip() for v in col_vals):
            cols.append(col_vals)
    return cols


def _columns_to_payloads(cols: List[List[str]]) -> List[Dict[str, str]]:
    """
    Chuyển mỗi cột thành {language, rawText}
    Row1 = language; các rows sau ghép bằng 2 newline.
    """
    payloads = []
    for col in cols:
        if not col:
            continue
        language = (col[0] or "").strip()
        body_lines = [str(x).strip() for x in col[1:] if str(x).strip()]
        raw = "\n\n".join(body_lines)
        if language and body_lines:
            payloads.append({"language": language, "rawText": raw})
    return payloads


async def _call_gemini(language: str, raw_text: str) -> str:
    """
    Gọi Gemini generateContent (REST) với system_instruction,
    trả về chuỗi Markdown table (text).
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"Ngôn ngữ đầu vào: {language}\n\n"
                            "Dữ liệu cột (plain text) bên dưới. Hãy CHỈ trả về một bảng Markdown đúng theo Output format ở system prompt, giữ nguyên thứ tự câu hỏi.\n\n"
                            "---\n"
                            f"{raw_text}\n"
                            "---"
                        )
                    }
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=body)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502, detail=f"Gemini API error: {resp.text}"
            )
        data = resp.json()
    # Lấy text từ candidates[0].content.parts[].text
    try:
        candidates = data.get("candidates", [])
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts).strip()
        return text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini response parse error: {e}")


def _strip_code_fences(md: str) -> str:
    if not md:
        return ""
    # gỡ ```markdown ... ``` hoặc ``` ... ```
    pattern = r"^```(?:[\w-]+)?\n([\s\S]*?)\n```$"
    m = re.search(pattern, md.strip(), re.MULTILINE)
    return m.group(1).strip() if m else md.strip()


def _parse_markdown_table(md: str) -> List[Dict[str, str]]:
    """
    Parser đơn giản cho bảng Markdown dạng chuẩn.
    Trả list dict có keys: STT, Câu hỏi, Đáp án A/B/C/D, Đáp án đúng, Ghi chú (hoặc biến thể key).
    """
    if not md:
        return []

    md = _strip_code_fences(md)
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    # Tìm header + separator
    header_idx = -1
    for i in range(len(lines) - 1):
        if lines[i].startswith("|") and lines[i].endswith("|"):
            sep = lines[i + 1]
            if re.match(r"^\|?\s*[:\-\|\s]+$", sep):
                header_idx = i
                break
    if header_idx < 0:
        raise ValueError("Không tìm thấy header của bảng Markdown.")

    header_cells = [c.strip() for c in lines[header_idx].split("|")][1:-1]

    def canon(h: str) -> str:
        t = h.lower()
        if "stt" in t:
            return "STT"
        if "câu hỏi" in t or "question" in t:
            return "Câu hỏi"
        if t.endswith("a") or t.endswith(" a"):
            return "Đáp án A"
        if t.endswith("b") or t.endswith(" b"):
            return "Đáp án B"
        if t.endswith("c") or t.endswith(" c"):
            return "Đáp án C"
        if t.endswith("d") or t.endswith(" d"):
            return "Đáp án D"
        if "đúng" in t or "correct" in t:
            return "Đáp án đúng"
        if "ghi chú" in t or "note" in t:
            return "Ghi chú"
        return h.strip()

    keys = [canon(h) for h in header_cells]

    rows = []
    for i in range(header_idx + 2, len(lines)):
        if not (lines[i].startswith("|") and lines[i].endswith("|")):
            continue
        cells = [c.strip() for c in lines[i].split("|")][1:-1]
        if len(cells) < len(keys):
            # thiếu ô; bỏ qua
            continue
        row = {keys[j]: cells[j] for j in range(len(keys))}
        # Chuẩn hoá STT → int nếu có
        if "STT" in row:
            row["STT"] = re.sub(r"\D+", "", row["STT"]) or row["STT"]
        rows.append(row)

    return rows


def _rows_to_xlsx_bytes(language: str, rows: List[Dict[str, str]]) -> bytes:
    if not rows:
        # tạo file rỗng vẫn có header
        rows = []
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Quiz")
    buf.seek(0)
    return buf.read()


# --------- Endpoints ----------
@app.get("/")
def root():
    return {"ok": True, "service": "Quiz Sheet → Gemini → XLSX per language"}


@app.post("/process")
async def process(
    sheet_url: str = Form(
        ...,
        description="Google Sheets URL (must be public)",
        example="https://docs.google.com/spreadsheets/d/your-sheet-id/edit",
    ),
    sheet_name: str = Form(
        ..., description="Name of the worksheet/tab", example="Sheet1"
    ),
):
    """
    Process a public Google Sheet and convert quiz data to XLSX files.

    - **sheet_url**: Google Sheets URL (make sure it's publicly accessible)
    - **sheet_name**: Name of the worksheet/tab to process

    Returns a ZIP file containing XLSX files for each language column found.
    """
    try:
        cols = await _read_sheet_columns(sheet_url, sheet_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không đọc được Google Sheet: {e}")

    payloads = _columns_to_payloads(cols)
    if not payloads:
        return JSONResponse(
            status_code=200,
            content={"message": "Không tìm thấy dữ liệu hợp lệ trong tối đa 3 cột."},
        )

    # Gọi Gemini cho từng cột
    results = []
    for p in payloads:
        md = await _call_gemini(p["language"], p["rawText"])
        rows = _parse_markdown_table(md)
        xlsx_bytes = _rows_to_xlsx_bytes(p["language"], rows)
        results.append((p["language"], xlsx_bytes))

    # Đóng gói ZIP in-memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for lang, blob in results:
            filename = f"{lang}.xlsx".replace("/", "_")
            zf.writestr(filename, blob)
    zip_buf.seek(0)

    # Get zip content as bytes
    zip_content = zip_buf.getvalue()

    return StreamingResponse(
        io.BytesIO(zip_content),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="quiz_exports.zip"',
            "Content-Length": str(len(zip_content)),
        },
    )
