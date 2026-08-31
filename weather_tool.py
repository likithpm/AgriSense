import requests


def get_weather(latitude, longitude):

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}"
        f"&longitude={longitude}"
        f"&current=temperature_2m,relative_humidity_2m"
    )

    response = requests.get(url, timeout=10)

    return response.json()