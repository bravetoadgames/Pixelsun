from flask import Flask, jsonify
from PIL import Image, ImageDraw, ImageFont
from pypixelcolor import Client
import requests
import time
import os
import tkinter as tk
from tkinter import ttk
import threading

app = Flask(__name__)

# Configuratie bestanden
CONFIG_FILE = "config.txt"
SETTINGS_FILE = "settings.txt"
TEMP_FILE = "/tmp/weer_display.bmp"
FONT_PATH = "tom-thumb.ttf" 

# Uitgebreide lijst met NU en MORGEN (tomorrow_) opties
AVAILABLE_OPTIONS = [
    # Actueel (Nu)
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "snow_depth",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "soil_temperature_6cm",
    "is_day",
    
    # Verwachting voor Morgen
    "tomorrow_temperature_2m_max",
    "tomorrow_temperature_2m_min",
    "tomorrow_apparent_temperature_max",
    "tomorrow_apparent_temperature_min",
    "tomorrow_precipitation_sum",
    "tomorrow_rain_sum",
    "tomorrow_showers_sum",
    "tomorrow_snowfall_sum",
    "tomorrow_precipitation_hours",
    "tomorrow_precipitation_probability_max",
    "tomorrow_weather_code",
    "tomorrow_wind_speed_10m_max",
    "tomorrow_wind_gusts_10m_max",
    "tomorrow_wind_direction_10m_dominant",
    "tomorrow_shortwave_radiation_sum",
    "tomorrow_uv_index_max"
]

# Standaardinstellingen voor de allereerste start
DEFAULT_SETTINGS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "tomorrow_temperature_2m_max",
    "tomorrow_wind_speed_10m_max"
]

def kmh_naar_beaufort(kmh):
    """Zet windsnelheid in km/h om naar de schaal van Beaufort"""
    if kmh is None: return 0
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
            
        # COMMENTED: print(f"Configuratie ingelezen: MAC={regels[0]}, Land={regels[1]}, Plaats={regels[2]}")
        return regels[0], regels[1], regels[2]
    except Exception as e:
        print(f"Fout bij het lezen van {CONFIG_FILE}: {e}")
        exit(1)

def haal_coordinaten_op(landcode, plaatsnaam):
    """Zoekt de latitude en longitude op via de Open-Meteo Geocoding API"""
    # COMMENTED: print(f"Coördinaten zoeken voor {plaatsnaam} ({landcode})...")
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={plaatsnaam}&count=5&language=nl&format=json"
    try:
        response = requests.get(url).json()
        if 'results' not in response:
            print(f"FOUT: Kon de locatie '{plaatsnaam}' niet vinden bij Open-Meteo.")
            exit(1)
            
        for resultaat in response['results']:
            if resultaat.get('country_code', '').upper() == landcode.upper():
                # COMMENTED: print(f"Locatie gevonden! Lat: {resultaat['latitude']}, Lon: {resultaat['longitude']}")
                return resultaat['latitude'], resultaat['longitude']
                
        eerste = response['results'][0]
        # COMMENTED: print(f"Waarschuwing: Geen exacte land-match, we pakken de eerste optie: {eerste['name']}")
        return eerste['latitude'], eerste['longitude']
    except Exception as e:
        print(f"Fout bij het ophalen van coördinaten: {e}")
        exit(1)

def laad_instellingen():
    """Laadt de dropdown instellingen uit settings.txt of pakt de defaults"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                regels = [regel.strip() for regel in f.readlines() if regel.strip()]
                if len(regels) == 5:
                    if all(r in AVAILABLE_OPTIONS for r in regels):
                        return regels
        except Exception as e:
            print(f"Fout bij laden settings.txt: {e}")
    return DEFAULT_SETTINGS

def sla_instellingen_op(keuzes):
    """Slaat de 5 keuzes op in settings.txt"""
    try:
        with open(SETTINGS_FILE, "w") as f:
            for keuze in keuzes:
                f.write(f"{keuze}\n")
    except Exception as e:
        print(f"Fout bij opslaan settings.txt: {e}")

# Laad basisconfiguratie
MAC_ADRES, LANDCODE, PLAATSNAAM = laad_configuratie()
LATITUDE, LONGITUDE = haal_coordinaten_op(LANDCODE, PLAATSNAAM)

# Globale variabele voor de actieve keuzes en cache
actieve_keuzes = laad_instellingen()
laatste_data = None

def genereer_korte_naam(sleutel):
    """Maakt een compacte prefix voor op het 32x32 display"""
    is_morgen = sleutel.startswith("tomorrow_")
    schoon = sleutel.replace("tomorrow_", "")
    
    if "temperature" in schoon: base = "T"
    elif "apparent_temperature" in schoon: base = "AT"
    elif "humidity" in schoon: base = "H"
    elif "wind_speed" in schoon: base = "W"
    elif "wind_gusts" in schoon: base = "G"
    elif "wind_direction" in schoon: base = "D"
    elif "precipitation" in schoon: base = "PRC"
    elif "rain" in schoon: base = "R"
    elif "showers" in schoon: base = "SHO"
    elif "snow" in schoon: base = "SNO"
    elif "cloud" in schoon: base = "CLD"
    elif "radiation" in schoon: base = "RAD"
    elif "surface_pressure" in schoon: base = "P"
    elif "uv_index" in schoon: base = "UVI"
    elif "weather_code" in schoon: base = "COD"
    else: base = schoon.split('_')[0][:3].upper()
    
    if is_morgen:
        return f"M{base[:3]}"
    return base[:4]

def get_weer():
    """Haalt zowel actuele als voorspellende data dynamisch op uit de API"""
    global actieve_keuzes
    
    current_params = []
    daily_params = []
    
    for keuze in actieve_keuzes:
        if keuze.startswith("tomorrow_"):
            om_naam = keuze.replace("tomorrow_", "")
            if om_naam not in daily_params:
                daily_params.append(om_naam)
        else:
            if keuze not in current_params:
                current_params.append(keuze)
                
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&timezone=auto"
    if current_params:
        url += f"&current={','.join(current_params)}"
    if daily_params:
        url += f"&daily={','.join(daily_params)}"
        
    try:
        response = requests.get(url).json()
        
        resultaten = []
        for keuze in actieve_keuzes:
            if keuze.startswith("tomorrow_"):
                om_naam = keuze.replace("tomorrow_", "")
                waarde = response['daily'][om_naam][1]
                eenheid = response['daily_units'][om_naam]
            else:
                waarde = response['current'][keuze]
                eenheid = response['current_units'][keuze]
            
            if ("wind_speed" in keuze or "wind_gusts" in keuze) and eenheid == "km/h":
                if waarde is not None:
                    waarde = kmh_naar_beaufort(waarde)
                eenheid = "Bft"
            
            if eenheid == "°C": eenheid = "C"
            elif eenheid == "km/h": eenheid = "kh"
            elif eenheid == "m/s": eenheid = "ms"
            elif eenheid == "%": eenheid = "%"
            
            korte_naam = genereer_korte_naam(keuze)
            resultaten.append(f"{korte_naam}:{waarde}{eenheid}")
            
        return resultaten
    except Exception as e:
        print(f"Weer API Fout: {e}")
        return None

def update_led_weer():
    global laatste_data
    
    huidige_regels = get_weer()
    if not huidige_regels: return

    if huidige_regels == laatste_data:
        # COMMENTED: print("Weer gecontroleerd: De tekst op het scherm is exact gelijk. Update overgeslagen.")
        return

    img = Image.new('RGB', (32, 32), color=(0, 0, 0))
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT_PATH, 16)
    except: font = ImageFont.load_default()

    d.text((1, 0),  huidige_regels[0], fill=(120, 200, 120), font=font)
    d.text((1, 6),  huidige_regels[1], fill=(100, 170, 100), font=font)
    d.text((1, 12), huidige_regels[2], fill=(80, 150, 80), font=font)
    d.text((1, 18), huidige_regels[3], fill=(0, 120, 200), font=font)
    d.text((1, 24), huidige_regels[4], fill=(0, 60, 150), font=font)
    
    img.save(TEMP_FILE, "BMP")
    
    try:
        with Client(address=MAC_ADRES) as device:
            if hasattr(device, 'send_image'): device.send_image(TEMP_FILE)
            else: device.send_file(TEMP_FILE)
        # COMMENTED: print(f"Weer geüpdatet voor {PLAATSNAAM} (Gedimde modus)")
        laatste_data = huidige_regels
    except Exception as e:
        print(f"Bluetooth fout: {e}")

def herhaalde_update_loop():
    while True:
        update_led_weer()
        time.sleep(60)

def on_dropdown_select(event, index, combo):
    global actieve_keuzes, laatste_data
    nieuwe_waarde = combo.get()
    actieve_keuzes[index] = nieuwe_waarde
    sla_instellingen_op(actieve_keuzes)
    # COMMENTED: print(f"Regel {index+1} aangepast naar: {nieuwe_waarde}. Opgeslagen.")
    laatste_data = None
    threading.Thread(target=update_led_weer, daemon=True).start()

def bouw_gui():
    root = tk.Tk()
    root.title("Weerstation Settings")
    root.geometry("400x300")
    root.resizable(False, False)

    label_titel = tk.Label(root, text=f"Display Opties - {PLAATSNAAM}", font=("Arial", 12, "bold"))
    label_titel.pack(pady=10)

    for i in range(5):
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=20, pady=5)
        
        lbl = tk.Label(frame, text=f"Regel {i+1}:", width=8, anchor="w")
        lbl.pack(side="left")
        
        combo = ttk.Combobox(frame, values=AVAILABLE_OPTIONS, state="readonly")
        combo.set(actieve_keuzes[i])
        combo.pack(side="left", fill="x", expand=True)
        
        combo.bind("<<ComboboxSelected>>", lambda event, idx=i, cb=combo: on_dropdown_select(event, idx, cb))

    lbl_info = tk.Label(root, text="Wijzigingen worden direct opgeslagen.", fg="gray")
    lbl_info.pack(side="bottom", pady=10)

    # COMMENTED: print(f"Weerpaneel gestart voor {PLAATSNAAM}...")
    root.mainloop()

if __name__ == "__main__":
    weer_thread = threading.Thread(target=herhaalde_update_loop, daemon=True)
    weer_thread.start()
    bouw_gui()