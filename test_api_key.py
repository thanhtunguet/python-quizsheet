#!/usr/bin/env python3
"""
Test script to verify Google Sheets API key authentication works.
This script tests the _extract_sheet_id function and makes a test API call.
"""

import os
import asyncio
import httpx
from urllib.parse import quote
from main import _extract_sheet_id

# Test URLs
TEST_URLS = [
    "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0",
    "https://docs.google.com/spreadsheets/ccc?key=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms&output=html",
]

def test_sheet_id_extraction():
    """Test the sheet ID extraction function."""
    print("Testing sheet ID extraction...")
    
    for url in TEST_URLS:
        try:
            sheet_id = _extract_sheet_id(url)
            print(f"✅ URL: {url[:50]}...")
            print(f"   Sheet ID: {sheet_id}")
        except Exception as e:
            print(f"❌ URL: {url[:50]}...")
            print(f"   Error: {e}")
        print()

async def test_api_call():
    """Test actual API call to Google Sheets."""
    print("Testing Google Sheets API call...")
    
    # This is a public sample sheet from Google
    sheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    sheet_name = "Class Data"
    
    # You would need to set GOOGLE_SHEETS_API_KEY in your environment
    api_key = os.getenv("GOOGLE_SHEETS_API_KEY")
    
    if not api_key:
        print("❌ GOOGLE_SHEETS_API_KEY not set. Cannot test API call.")
        print("   Set the environment variable and try again.")
        return
    
    encoded_sheet_name = quote(sheet_name)
    api_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{encoded_sheet_name}?key={api_key}"
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            
            if resp.status_code == 200:
                data = resp.json()
                values = data.get("values", [])
                print(f"✅ Successfully read {len(values)} rows from sheet '{sheet_name}'")
                
                if values:
                    print(f"   First row: {values[0]}")
                    print(f"   Total columns in first row: {len(values[0])}")
                else:
                    print("   Sheet appears to be empty")
                    
            else:
                print(f"❌ API call failed with status {resp.status_code}")
                print(f"   Response: {resp.text}")
                
    except Exception as e:
        print(f"❌ Error making API call: {e}")

if __name__ == "__main__":
    test_sheet_id_extraction()
    asyncio.run(test_api_call())
