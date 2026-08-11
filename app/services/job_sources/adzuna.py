import os

import requests
from dotenv import load_dotenv


load_dotenv()

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")


BASE_URL = "https://api.adzuna.com/v1/api/jobs"


def search_jobs(
    keyword: str,
    location: str,
    page: int = 1,
    results_per_page: int = 20
):

    if not ADZUNA_APP_ID:
        raise RuntimeError(
            "ADZUNA_APP_ID is not configured."
        )

    if not ADZUNA_APP_KEY:
        raise RuntimeError(
            "ADZUNA_APP_KEY is not configured."
        )

    url = (
        f"{BASE_URL}/in/search/"
        f"{page}"
    )

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": keyword,
        "where": location,
        "results_per_page": results_per_page,
        "content-type": "application/json"
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()
