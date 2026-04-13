"""Provider selection and readiness checks. Contract: contracts/s-1-foundation.contract.md"""

import requests

from src.core.config import Config

_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 5


def select_provider(config: Config) -> str:
    if config.default_provider in ("gemini", "lmstudio"):
        return config.default_provider

    while True:
        choice = input("Select provider:\n  [1] Gemini\n  [2] LM Studio\nChoice: ").strip()
        if choice == "1":
            return "gemini"
        if choice == "2":
            return "lmstudio"
        print(f"Invalid choice: '{choice}'. Enter 1 or 2.")


def check_lmstudio(endpoint: str) -> bool:
    url = f"{endpoint}/models"
    try:
        resp = requests.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
        return resp.status_code == 200
    except (requests.ConnectionError, requests.Timeout, requests.RequestException):
        return False


def ensure_provider_ready(provider: str, config: Config) -> str:
    if provider == "gemini":
        return "gemini"

    if check_lmstudio(config.lmstudio_endpoint):
        return "lmstudio"

    while True:
        user_input = input(
            f"LM Studio is not reachable at {config.lmstudio_endpoint}. "
            f"Start it and press Enter to retry, or type 'switch' to use Gemini instead.\n"
        ).strip()

        if user_input.lower() == "switch":
            return "gemini"

        if user_input == "":
            if check_lmstudio(config.lmstudio_endpoint):
                return "lmstudio"
        else:
            print(f"Unrecognized input: '{user_input}'. Press Enter to retry or type 'switch'.")
