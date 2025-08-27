# Python 3.10+ khuyến nghị
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)

pip install -r requirements.txt

# Tạo file .env từ mẫu
cp .env.example .env
# Sửa .env: GEMINI_API_KEY và GOOGLE_APPLICATION_CREDENTIALS (đường dẫn tuyệt đối tới sa.json)

# Chạy
uvicorn main:app --reload --port 8000

