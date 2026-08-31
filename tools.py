# tools.py

import sqlite3


def get_crop_info(crop_name):

    conn = sqlite3.connect("agrisense.db")

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM crops
        WHERE crop_name=?
        """,
        (crop_name,)
    )

    result = cursor.fetchone()

    conn.close()

    return result
# print(
#     get_crop_info("Rice")
# )
import requests

def get_weather(lat, lon):

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        f"&current=temperature_2m"
    )

    response = requests.get(url, timeout=10)

    return response.json()

