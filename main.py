import io
import os
import re
import zipfile
import json
from typing import List, Dict, Optional
from datetime import datetime

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, Form, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv
import docx
import PyPDF2

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

# --------- Data Models ----------
class QuizQuestion:
    def __init__(self, id: str, question: str, options: List[str], correct_answers: List[str], explanation: str):
        self.id = id
        self.question = question
        self.options = options
        self.correct_answers = correct_answers
        self.explanation = explanation

class QuizResponse:
    def __init__(self, questions: List[QuizQuestion]):
        self.questions = questions

# --------- FastAPI ----------
app = FastAPI(title="Quiz Sheet → Gemini → XLSX (per language)")

# Removed ProcessBody BaseModel - using Form parameters instead


# --------- Document Processing Helpers ----------
def _extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text from uploaded document files"""
    try:
        if filename.lower().endswith('.pdf'):
            return _extract_text_from_pdf(file_content)
        elif filename.lower().endswith(('.doc', '.docx')):
            return _extract_text_from_docx(file_content)
        elif filename.lower().endswith('.txt'):
            return file_content.decode('utf-8')
        else:
            raise ValueError(f"Unsupported file type: {filename}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error extracting text from file: {e}")

def _extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading PDF: {e}")

def _extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from DOCX file"""
    try:
        doc = docx.Document(io.BytesIO(file_content))
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading DOCX: {e}")

def _generate_document_prompt(target_language: str) -> str:
    """Generate the prompt for document-based quiz generation (matching C# version)"""
    return f"""You are an expert quiz creator tasked with generating high-quality multiple-choice questions based on document content provided either as plain text or as a file in one of the following formats: .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pdf, or .txt.

Your responsibilities:
- Analyze the entire content of the document (text or file)
- Generate up to 100 relevant, non-duplicate multiple-choice questions that collectively cover as much of the content as possible
- Questions should cover the entire document content but do not need to follow the original order — feel free to shuffle topics for variety
- Ensure all content must be consistently written in {target_language}

**Difficulty Distribution:**
- ~20% easy questions
- ~40% medium and hard questions
- ~40% very hard / advanced application-level questions. These should combine multiple concepts or present realistic problem-solving scenarios that require applied understanding
- A deviation of +-5% is acceptable

CRITICAL REQUIREMENTS:
1. Each question must:
   - Have 4–6 logically distinct options (A–D or A–E/F), max 200 characters each
   - Be no more than 300 characters in length
   - Have 1 or more correct answers selected by their letter (e.g., "A", "C") (all of which must be present in the options array)
   - Include a brief explanation (max 500 characters)
2. Option labeling must follow:  
   - First option = "A", second = "B", third = "C", etc.
   - `correctAnswers` must list only these letter labels (e.g., "B", "D")
3. Distribute correct answers evenly across options (A–D or A–E), with no more than 10% deviation between frequencies

OUTPUT FORMAT:
{{
  "questions": [
    {{
      "id": "1",
      "question": "What is...",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correctAnswers": ["A", "C"],
      "explanation": "This is correct because...",
    }}
  ]
}}

VALIDATION RULES:
- correctAnswers must contain only option letters corresponding to their index (e.g., "A", "B", etc.)
- All values in correctAnswers must map to actual options
- No duplicate or overlapping questions
- All parts (question, options, explanation) must be consistently written in {target_language}
- Maintain correct difficulty distribution across the question set
- Ensure fair distribution of correct answer positions (e.g., avoid clustering on "A" or "B")
- Output must be valid raw JSON with no markdown formatting, no code blocks, and no extra commentary

INPUT VARIABLES:
- documentContent or uploadedFile (only one of them will be provided)
- targetLanguage: {target_language} (e.g., "en", "vi", "id")"""

def _parse_llm_response(response: str) -> Optional[QuizResponse]:
    """Parse LLM response into QuizResponse object (matching C# version)"""
    try:
        clean_response = response.strip()
        
        # Remove markdown code blocks if present
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        if clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]
        
        clean_response = clean_response.strip()
        
        # Parse JSON
        data = json.loads(clean_response)
        
        questions = []
        for q_data in data.get("questions", []):
            question = QuizQuestion(
                id=str(q_data.get("id", "")),
                question=q_data.get("question", ""),
                options=q_data.get("options", []),
                correct_answers=q_data.get("correctAnswers", []),
                explanation=q_data.get("explanation", "")
            )
            questions.append(question)
        
        return QuizResponse(questions)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error parsing LLM response: {e}")

async def _call_gemini_for_document(document_content: str, target_language: str) -> str:
    """Call Gemini API for document-based quiz generation"""
    prompt = _generate_document_prompt(target_language)
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{prompt}\n\nDocument Content:\n{document_content}"
                    }
                ],
            }
        ],
    }
    
    async with httpx.AsyncClient(timeout=120) as client:  # Longer timeout for document processing
        resp = await client.post(url, json=body)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502, detail=f"Gemini API error: {resp.text}"
            )
        data = resp.json()
    
    try:
        candidates = data.get("candidates", [])
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts).strip()
        return text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini response parse error: {e}")

def _quiz_response_to_xlsx_bytes(quiz_response: QuizResponse, language: str) -> bytes:
    """Convert QuizResponse to XLSX bytes"""
    if not quiz_response.questions:
        return _rows_to_xlsx_bytes(language, [])
    
    rows = []
    for q in quiz_response.questions:
        row = {
            "STT": q.id,
            "Câu hỏi": q.question,
            "Explanation": q.explanation,
            "Correct Answers": ", ".join(q.correct_answers),
        }
        
        # Add options A-F
        for i, option in enumerate(q.options):
            if i == 0:
                row["Đáp án A"] = option
            elif i == 1:
                row["Đáp án B"] = option
            elif i == 2:
                row["Đáp án C"] = option
            elif i == 3:
                row["Đáp án D"] = option
            elif i == 4:
                row["Đáp án E"] = option
            elif i == 5:
                row["Đáp án F"] = option
        
        rows.append(row)
    
    return _rows_to_xlsx_bytes(language, rows)

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
    
    # Tìm header + separator - more flexible approach
    header_idx = -1
    for i in range(len(lines) - 1):
        if lines[i].startswith("|") and lines[i].endswith("|"):
            # Check if next line is a separator
            if i + 1 < len(lines):
                sep = lines[i + 1]
                if re.match(r"^\|?\s*[:\-\|\s]+$", sep):
                    header_idx = i
                    break
    
    # If no standard separator found, try to find any table-like structure
    if header_idx < 0:
        for i, line in enumerate(lines):
            if "|" in line and any(keyword in line.lower() for keyword in ["no", "question", "option", "correct", "answer", "stt", "câu hỏi", "đáp án"]):
                header_idx = i
                break
    
    if header_idx < 0:
        raise ValueError("Không tìm thấy header của bảng Markdown.")

    header_cells = [c.strip() for c in lines[header_idx].split("|")][1:-1]

    def canon(h: str) -> str:
        t = h.lower().strip()
        # Handle both English and Vietnamese column names
        if "no" in t or "stt" in t or t == "#":
            return "STT"
        if "question" in t or "câu hỏi" in t:
            return "Câu hỏi"
        if "option a" in t or t.endswith("a") or t.endswith(" a") or "đáp án a" in t:
            return "Đáp án A"
        if "option b" in t or t.endswith("b") or t.endswith(" b") or "đáp án b" in t:
            return "Đáp án B"
        if "option c" in t or t.endswith("c") or t.endswith(" c") or "đáp án c" in t:
            return "Đáp án C"
        if "option d" in t or t.endswith("d") or t.endswith(" d") or "đáp án d" in t:
            return "Đáp án D"
        if "correct" in t or "đúng" in t or "answer" in t:
            return "Đáp án đúng"
        if "note" in t or "ghi chú" in t or "notes" in t:
            return "Ghi chú"
        return h.strip()

    keys = [canon(h) for h in header_cells]

    rows = []
    # Start from header_idx + 1 (skip separator if exists) or header_idx + 2
    start_idx = header_idx + 2 if header_idx + 1 < len(lines) and re.match(r"^\|?\s*[:\-\|\s]+$", lines[header_idx + 1]) else header_idx + 1
    
    for i in range(start_idx, len(lines)):
        if not (lines[i].startswith("|") and lines[i].endswith("|")):
            continue
        cells = [c.strip() for c in lines[i].split("|")][1:-1]
        if len(cells) < len(keys):
            # Pad with empty strings if cells are missing
            while len(cells) < len(keys):
                cells.append("")
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


@app.post("/generate-quiz-from-document")
async def generate_quiz_from_document(
    file: UploadFile = File(..., description="Document file (PDF, DOCX, TXT)"),
    target_language: str = Form(..., description="Target language code (e.g., 'en', 'vi', 'id')", examples=["en"]),
):
    """
    Generate quiz from uploaded document using Gemini API.
    
    This endpoint mimics the C# QuizGeneratorService functionality to test
    whether issues are with Gemini or the C# implementation.
    
    - **file**: Document file (PDF, DOCX, TXT supported)
    - **target_language**: Language code for the generated quiz (e.g., 'en', 'vi', 'id')
    
    Returns an XLSX file with generated quiz questions.
    """
    try:
        # Validate file type
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Read file content
        file_content = await file.read()
        if not file_content:
            raise HTTPException(status_code=400, detail="Empty file")
        
        # Extract text from document
        document_text = _extract_text_from_file(file_content, file.filename)
        if not document_text.strip():
            raise HTTPException(status_code=400, detail="No text content found in document")
        
        # Call Gemini API
        llm_response = await _call_gemini_for_document(document_text, target_language)
        if not llm_response:
            raise HTTPException(status_code=502, detail="No response from Gemini API")
        
        # Parse response
        quiz_response = _parse_llm_response(llm_response)
        if not quiz_response or not quiz_response.questions:
            raise HTTPException(status_code=502, detail="No valid quiz questions generated")
        
        # Convert to XLSX
        xlsx_bytes = _quiz_response_to_xlsx_bytes(quiz_response, target_language)
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"quiz_generated_{target_language}_{timestamp}.xlsx"
        
        return StreamingResponse(
            io.BytesIO(xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(xlsx_bytes)),
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/process")
async def process(
    sheet_url: str = Form(
        ...,
        description="Google Sheets URL (must be public)",
        examples=["https://docs.google.com/spreadsheets/d/your-sheet-id/edit"],
    ),
    sheet_name: str = Form(
        ..., description="Name of the worksheet/tab", examples=["Sheet1"]
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
        try:
            md = await _call_gemini(p["language"], p["rawText"])
            rows = _parse_markdown_table(md)
            xlsx_bytes = _rows_to_xlsx_bytes(p["language"], rows)
            results.append((p["language"], xlsx_bytes))
        except ValueError as e:
            # If table parsing fails, create an empty file with error info
            error_rows = [{"Error": f"Failed to parse Gemini response: {str(e)}"}]
            xlsx_bytes = _rows_to_xlsx_bytes(p["language"], error_rows)
            results.append((p["language"], xlsx_bytes))
        except Exception as e:
            # For other errors, create an empty file with error info
            error_rows = [{"Error": f"Processing error: {str(e)}"}]
            xlsx_bytes = _rows_to_xlsx_bytes(p["language"], error_rows)
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
