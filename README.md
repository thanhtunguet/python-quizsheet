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

#### Option 1: Direct Python
```bash
uvicorn main:app --reload --port 8000
```

#### Option 2: Docker
```bash
# Build the image
docker build -t quiz-processor .

# Run with environment variables
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_gemini_api_key \
  -e GOOGLE_SHEETS_API_KEY=your_google_sheets_api_key \
  quiz-processor

# Or use docker-compose (recommended)
# First create .env file with your API keys
docker-compose up --build
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

## Docker Deployment

### Prerequisites
- Docker and Docker Compose installed

### Environment Setup
1. Create a `.env` file in the project root:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_SHEETS_API_KEY=your_google_sheets_api_key_here
GEMINI_MODEL=gemini-1.5-pro
```

### Build and Run
```bash
# Using Docker Compose (recommended)
docker-compose up --build

# Or using Docker directly
docker build -t quiz-processor .
docker run -p 8000:8000 --env-file .env quiz-processor
```

### Production Deployment
For production, consider:
- Using a reverse proxy (nginx)
- Setting up proper logging
- Implementing monitoring and health checks
- Using container orchestration (Kubernetes, Docker Swarm)
