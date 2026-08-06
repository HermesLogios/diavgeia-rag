import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql://rag:ragpass@localhost:5432/diavgeia"
)
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-dummy-for-tests")