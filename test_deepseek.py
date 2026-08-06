import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": "Απαντάς πάντα στα ελληνικά, σύντομα."},
        {"role": "user", "content": "Τι είναι ο ΑΔΑ στη Διαύγεια;"},
    ],
    max_tokens=200,
)

print(response.choices[0].message.content)
print("\n--- Κόστος ---")
print("Input tokens:", response.usage.prompt_tokens)
print("Output tokens:", response.usage.completion_tokens)