import io
import os
import re
import zipfile
from typing import List, Dict

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
GOOGLE_CREDS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY env var")
if not GOOGLE_CREDS_PATH or not os.path.exists(GOOGLE_CREDS_PATH):
    raise RuntimeError("Missing/invalid GOOGLE_APPLICATION_CREDENTIALS env var")

# --------- System Prompt (nguyên văn bạn cung cấp) ----------
SYSTEM_PROMPT = """# ROLE

Bạn là chuyên viên đào tạo hỗ trợ các công việc:

- Biên soạn câu hỏi, đề thi từ tài liệu có sẵn

- Chuyển đổi bộ câu hỏi có sẵn thành dạng bảng có cấu trúc

- Dịch bộ câu hỏi có sẵn sang một ngôn ngữ khác



# Context

Một bài quiz là tập hợp nhiều câu hỏi trắc nghiệm với 4 đáp án (A, B, C, D) trong đó có một đáp án đúng và 3 lựa chọn gây nhiễu.



## Biên soạn câu hỏi từ tài liệu có sẵn

Nếu người dùng gửi cho bạn một tệp tài liệu, bạn hãy dựa vào nội dung tài liệu để tạo ra bộ câu hỏi trắc nghiệm tương ứng.

Các quy tắc cần tuân thủ:

- Đối với trường hợp tài liệu trình bày dạng Q&A, với mỗi câu hỏi, bạn cần tạo ra ít nhất 1 câu hỏi trắc nghiệm tương ứng

- Đối với các tài liệu truyền thống, hãy dựa vào nội dung của mỗi chương, mỗi đầu mục, mỗi luận điểm, ... để tạo thành ít nhất 1 câu hỏi trắc nghiệm tương ứng.

- Đối với yêu cầu dịch thuật, bạn hãy dựa vào nội dung của câu hỏi và ngữa nghĩa của các đáp án để dịch một cách chính xác nhất có thể. Bạn cần ưu tiên các thuật ngữ khoa học, logic dựa trên mục tiêu của câu hỏi. Đối với các câu hỏi thông thường, bạn hãy sử dụng những từ ngữ phổ biến trong văn hóa của ngôn ngữ đích.

- Nếu không được yêu cầu dịch, bạn hãy giữ nguyên ngôn ngữ gốc của tài liệu ban đầu.

- Cần giữ đúng thứ tự các câu hỏi



# Output format

Kết quả cần được trình bày dạng bảng Markdown với các cột sau:



- STT (Số thứ tự)

- Câu hỏi

- Đáp án A

- Đáp án B

- Đáp án C

- Đáp án D

- Đáp án đúng

- Ghi chú: trích dẫn vị trí, đoạn văn, đầu mục ... trong tài liệu gốc để người dùng có thể xác thực tính chính xác của đáp án, bỏ trống nếu không cần thiết.



Lưu ý: bạn không cần giải thích gì thêm. Hãy chỉ tạo đúng bảng câu hỏi kết quả.
"""

# --------- FastAPI ----------
app = FastAPI(title="Quiz Sheet → Gemini → XLSX (per language)")

class ProcessBody(BaseModel):
    sheet_url: str
    sheet_name: str


# --------- Helpers ----------
def _gc_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
    return gspread.Client(auth=creds).authorize()


def _read_sheet_columns(sheet_url: str, sheet_name: str) -> List[List[str]]:
    """
    Trả về danh sách các cột (tối đa 3).
    Mỗi cột là list các ô theo thứ tự hàng (row1 = header/language, tiếp theo là nội dung).
    """
    gc = _gc_client()
    sh = gc.open_by_url(sheet_url)
    ws = sh.worksheet(sheet_name)
    # Lấy toàn bộ vùng có dữ liệu
    values = ws.get_all_values()  # 2D list [row][col]
    if not values:
        return []

    # Xoay ma trận để lấy theo cột
    # Giới hạn tối đa 3 cột có dữ liệu thực
    max_cols = min(3, max(len(r) for r in values))
    cols = []
    for c in range(max_cols):
        col_vals = []
        for r in values:
            val = r[c] if c < len(r) else ""
            col_vals.append(val)
        # Cắt bớt ô trống cuối cột
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
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{
                    "text": (
                        f"Ngôn ngữ đầu vào: {language}\n\n"
                        "Dữ liệu cột (plain text) bên dưới. Hãy CHỈ trả về một bảng Markdown đúng theo Output format ở system prompt, giữ nguyên thứ tự câu hỏi.\n\n"
                        "---\n"
                        f"{raw_text}\n"
                        "---"
                    )
                }]
            }
        ]
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=body)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Gemini API error: {resp.text}")
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
async def process(body: ProcessBody):
    """
    Input: {"sheet_url": "...", "sheet_name": "..."}
    Output: ZIP chứa các file <Language>.xlsx
    """
    try:
        cols = _read_sheet_columns(body.sheet_url, body.sheet_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không đọc được Google Sheet: {e}")

    payloads = _columns_to_payloads(cols)
    if not payloads:
        return JSONResponse(status_code=200, content={"message": "Không tìm thấy dữ liệu hợp lệ trong tối đa 3 cột."})

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

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="quiz_exports.zip"'}
    )

