import os
from functools import lru_cache
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")


@lru_cache(maxsize=4)
def _build_cached_fernet(key_str: str) -> Fernet:
    return Fernet(key_str.encode())


def get_fernet():
    key = ENCRYPTION_KEY or os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY not found in environment variables.")
    return _build_cached_fernet(key)

def encrypt_text(text: str) -> str:
    if not text:
        return ""
    f = get_fernet()
    return f.encrypt(text.encode()).decode()

def decrypt_text(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    f = get_fernet()
    return f.decrypt(cipher_text.encode()).decode()

if __name__ == "__main__":
    # If run directly, generate a new key for convenience
    key = Fernet.generate_key().decode()
    print("New Encryption Key Generated:")
    print(key)
    print("\nPaste this into your .env file as ENCRYPTION_KEY=...")
