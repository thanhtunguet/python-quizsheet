#!/usr/bin/env bash
# Usage: ./quiz_export.sh <google_sheet_url> <sheet_name> [output.zip]
# Example: ./quiz_export.sh "https://docs.google.com/spreadsheets/d/xxxxx/edit#gid=0" "Sheet1" quizzes.zip

if [ $# -lt 2 ]; then
  echo "Usage: $0 <google_sheet_url> <sheet_name> [output.zip]"
  exit 1
fi

SHEET_URL="$1"
SHEET_NAME="$2"
OUTPUT="${3:-quiz_exports.zip}"

API_URL="http://127.0.0.1:8000/process"

echo "Sending request to $API_URL ..."
echo "Sheet URL: $SHEET_URL"
echo "Sheet Name: $SHEET_NAME"
echo "Output: $OUTPUT"

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "{\"sheet_url\": \"$SHEET_URL\", \"sheet_name\": \"$SHEET_NAME\"}" \
  --output "$OUTPUT"

if [ $? -eq 0 ]; then
  echo "✅ Done. Saved to $OUTPUT"
else
  echo "❌ Failed"
fi

