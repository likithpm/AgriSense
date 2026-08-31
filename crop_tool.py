import requests
from bs4 import BeautifulSoup


def get_crop_recommendation(
    N,
    P,
    K,
    temperature,
    humidity,
    ph,
    rainfall
):

    url = "https://crop-recommendation-w330.onrender.com/predict"

    payload = {
        "N": N,
        "P": P,
        "K": K,
        "temperature": temperature,
        "humidity": humidity,
        "ph": ph,
        "rainfall": rainfall
    }

    response = requests.post(
        url,
        data=payload,
        timeout=8,
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    crop_boxes = soup.find_all(
        "div",
        class_="crop-box"
    )

    result = {}

    for box in crop_boxes:

        title = box.find("h3").text.strip()
        value = box.find("p").text.strip()

        result[title] = value

    return result


if __name__ == "__main__":

    result = get_crop_recommendation(
        N=90,
        P=42,
        K=43,
        temperature=25,
        humidity=80,
        ph=6.5,
        rainfall=120
    )

    print(result)