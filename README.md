# Quiz Sheet Processing API

## Setup

### Requirements
- Python 3.10+ recommended

### Installation
```bash
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
```

### Environment Variables
Create a `.env` file with:
```
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_SHEETS_API_KEY=your_google_sheets_api_key_here
GEMINI_MODEL=gemini-1.5-pro
```

### API Keys Setup
1. **Gemini API Key**: Get from [Google AI Studio](https://makersuite.google.com/app/apikey)
2. **Google Sheets API Key**: 
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Enable Google Sheets API
   - Create credentials > API Key
   - Restrict the key to Google Sheets API

### Running the Server
```bash
uvicorn main:app --reload --port 8000
```

### Usage
The API works with **public Google Sheets only**. Make sure your Google Sheet is shared with "Anyone with the link can view" permission.

#### API Endpoint
- **POST** `/process` - Process a Google Sheet and download quiz XLSX files
- **Parameters** (form-encoded for easy Swagger UI usage):
  - `sheet_url`: Google Sheets URL (e.g., `https://docs.google.com/spreadsheets/d/your-sheet-id/edit`)
  - `sheet_name`: Worksheet tab name (e.g., `Sheet1`)

#### Using Swagger UI
1. Start the server: `uvicorn main:app --reload --port 8000`
2. Open http://localhost:8000/docs in your browser
3. Click on the `/process` endpoint
4. Click "Try it out"
5. Fill in the form fields:
   - **sheet_url**: Paste your public Google Sheets URL
   - **sheet_name**: Enter the tab/worksheet name
6. Click "Execute"
7. Download the generated ZIP file containing XLSX files for each language
