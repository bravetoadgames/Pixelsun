from flask import Flask, jsonify
from PIL import Image, ImageDraw, ImageFont
from pypixelcolor import Client
import requests
import time
import os

app = Flask(__name__)

# Configuratie bestanden
CONFIG_FILE = "config.txt"
TEMP_FILE = "/tmp/weer_display.bmp"
FONT_PATH = "tom-thumb.ttf" 

def laad_configuratie():
    """Leest het MAC-adres, land en plaats in uit config.txt"""
    if not os.path.exists(CONFIG_FILE):
        print(f"FOUT: Het bestand '{CONFIG_FILE}' is niet gevonden!")
        exit(1)
        
    try:
        with open(CONFIG_FILE, "r") as f:
            regels = [regel.strip() for regel in f.readlines() if regel.strip()]
            
        if len(regels) < 3:
            print(f"FOUT: '{CONFIG_FILE}' moet minimaal 3 regels bevatten (MAC, Landcode, Plaatsnaam)!")
            exit(1)
            
        mac = regels[0]
        land = regels[1]
        plaats = regels[2]
        
        print(f"Configuratie ingelezen: MAC={mac}, Land={land}, Plaats={plaats}")
        return mac, land, plaats
    except Exception as e:
        print(f"Fout bij het lezen van {CONFIG_FILE}: {e}")
        exit(1)

def haal_coordinaten_op(landcode, plaatsnaam):
    """Zoekt de latitude en longitude op via de Open-Meteo Geocoding API"""
    print(f"Coördinaten zoeken voor {plaatsnaam} ({landcode})...")
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={plaatsnaam}&count=5&language=nl&format=json"
    
    try:
        response = requests.get(url).json()
        if 'results' not in response:
            print(f"FOUT: Kon de locatie '{plaatsnaam}' niet vinden bij Open-Meteo.")
            exit(1)
            
        for resultaat in response['results']:
            if resultaat.get('country_code', '').upper() == landcode.upper():
                lat = resultaat['latitude']
                lon = resultaat['longitude']
                print(f"Locatie gevonden! Lat: {lat}, Lon: {lon}")
                return lat, lon
                
        eerste = response['results'][0]
        print(f"Waarschuwing: Geen exacte land-match, we pakken de eerste optie: {eerste['name']} (Lat: {eerste['latitude']}, Lon: {eerste['longitude']})")
        return eerste['latitude'], eerste['longitude']
        
    except Exception as e:
        print(f"Fout bij het ophalen van coördinaten: {e}")
        exit(1)

# 1. Laad de configuratie bij het opstarten
MAC_ADRES, LANDCODE, PLAATSNAAM = laad_configuratie()

# 2. Zoek eenmalig de coördinaten van de plaats op
LATITUDE, LONGITUDE = haal_coordinaten_op(LANDCODE, PLAATSNAAM)

# Variabele om de tekstregels van de vorige meting te onthouden
laatste_data = None

def kmh_naar_beaufort(kmh):
    """Zet windsnelheid in km/h om naar de schaal van Beaufort"""
    if kmh < 2: return 0
    elif kmh < 6: return 1
    elif kmh < 12: return 2
    elif kmh < 20: return 3
    elif kmh < 29: return 4
    elif kmh < 39: return 5
    elif kmh < 50: return 6
    elif kmh < 62: return 7
    elif kmh < 75: return 8
    elif kmh < 89: return 9
    elif kmh < 103: return 10
    elif kmh < 118: return 11
    else: return 12

def get_weer():
    """Haalt weerdata op met de dynamische coördinaten"""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
        "&daily=temperature_2m_max,wind_speed_10m_max&timezone=auto"
    )
    try:
        response = requests.get(url).json()
        current = response['current']
        daily = response['daily']
        
        bft_nu = kmh_naar_beaufort(current['wind_speed_10m'])
        bft_morgen = kmh_naar_beaufort(daily['wind_speed_10m_max'][1])
        
        return {
            "temp": f"{int(current['temperature_2m'])}C",
            "hum": f"{current['relative_humidity_2m']}%",
            "wind": f"{bft_nu}Bft",
            "temp_morgen": f"{int(daily['temperature_2m_max'][1])}C",
            "wind_morgen": f"{bft_morgen}Bft"
        }
    except Exception as e:
        print(f"Weer API Fout: {e}")
        return None

def update_led_weer():
    global laatste_data
    
    data = get_weer()
    if not data: return

    # Maak de exacte tekstregels aan die op het scherm komen
    regel1 = f"T:{data['temp']}"
    regel2 = f"H:{data['hum']}"
    regel3 = f"W:{data['wind']}"
    regel4 = f"MT:{data['temp_morgen']}"
    regel5 = f"MW:{data['wind_morgen']}"
    
    huidige_regels = [regel1, regel2, regel3, regel4, regel5]

    if huidige_regels == laatste_data:
        print("Weer gecontroleerd: De tekst op het scherm is exact gelijk. Update overgeslagen.")
        return

    img = Image.new('RGB', (32, 32), color=(0, 0, 0))
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT_PATH, 16)
    except: font = ImageFont.load_default()

    # Layout voor 32x32 display - RGB-waardes zijn teruggebracht naar ~10% helderheid
# Layout voor 32x32 display - Iets fellere RGB-waardes zodat het scherm niet zwart blijft
    d.text((1, 0),  regel1, fill=(120, 120, 60), font=font)    # Zacht Wit
    d.text((1, 6),  regel2, fill=(90, 90, 60), font=font)     # Zacht Cyaan
    d.text((1, 12), regel3, fill=(60, 60, 60), font=font)      # Zacht Groen
    d.text((1, 18), regel4, fill=(0, 60, 80), font=font)     # Zacht Oranje
    d.text((1, 24), regel5, fill=(0, 0, 80), font=font)     # Zacht Roze
    
    img.save(TEMP_FILE, "BMP")
    
    try:
        with Client(address=MAC_ADRES) as device:
            if hasattr(device, 'send_image'): device.send_image(TEMP_FILE)
            else: device.send_file(TEMP_FILE)
        print(f"Weer geüpdatet voor {PLAATSNAAM}: T:{data['temp']} W:{data['wind']} (Gedimde modus)")
        
        # Bugfix: 'kaikki_rivit' was een overgebleven typefout uit de vorige iteratie, nu netjes opgeschoond.
        laatste_data = huidige_regels
        
    except Exception as e:
        print(f"Bluetooth fout: {e}")

if __name__ == "__main__":
    print(f"Weerpaneel gestart voor {PLAATSNAAM} (Auto-update elke minuut, alleen bij wijziging)...")
    while True:
        update_led_weer()
        time.sleep(60)