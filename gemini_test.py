# gemini_test.py

import logging
from services.llm_service import get_llm, invoke_llm, invoke_json_llm

logging.basicConfig(level=logging.INFO)

print("Testing Gemini text invocation:")
response = invoke_llm("Say hello and confirm you are running on Gemini.")
print("Response:", response)

print("\nTesting Gemini JSON invocation:")
json_response = invoke_json_llm("Return ONLY valid JSON with key 'status' and value 'operational': {\"status\": \"operational\"}")
print("JSON Response:", json_response)
