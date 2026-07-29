"""
Quick manual check that GEMINI_API_KEY (from .env) authenticates correctly
against the Gemini API. Not part of the test suite / not run automatically.

Usage:
    python dev-scripts/test_gemini_key.py
"""
import hashlib
import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    print("GEMINI_API_KEY not set in .env")
    sys.exit(1)

print("Key prefix:", GEMINI_API_KEY[:10])
print("Key hash (sha256):", hashlib.sha256(GEMINI_API_KEY.encode()).hexdigest())

client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello"
)
print(response.text)
