# gemini_test.py (formerly openai_test.py)

import os
from dotenv import load_dotenv
from services.llm_service import invoke_llm, invoke_json_llm

load_dotenv()

print("Testing Google Gemini LLM:")
response = invoke_llm("Say hello and confirm Gemini is active.")
print("Text response:", response)

json_response = invoke_json_llm("Return JSON: {\"status\": \"active\", \"provider\": \"Google Gemini\"}")
print("JSON response:", json_response)