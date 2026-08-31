from services.soil_service import get_soil_data

result = get_soil_data(
    11.0168,   # Coimbatore latitude
    76.9558    # Coimbatore longitude
)

print(result)