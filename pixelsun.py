import os
# FORCEER XORG BACKEND: Dit moet absoluut op regel 1 en 2 staan, vóór elke andere import!
# Dit voorkomt dat pystray zoekt naar ontbrekende Linux Ayatana/AppIndicator3 libraries.
os.environ['PYSTRAY_BACKEND'] = 'xorg'

import threading
import time
import tkinter as tk
from tkinter import ttk
from flask import Flask, jsonify
from PIL import Image, ImageDraw, ImageFont
from pypixelcolor import Client
import requests
import pystray

app = Flask(__name__)

# --- CONFIGURATIE EN BESTANDEN ---
CONFIG_FILE = "config.txt"
SETTINGS_FILE = "settings.txt"
TEMP_FILE = "/tmp/weer_display.bmp"
FONT_PATH = "tom-thumb.ttf" 

AVAILABLE_OPTIONS = [
    # Actueel (Nu)
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "rain", "showers", "snowfall", "snow_depth", "weather_code",
    "pressure_msl", "surface_pressure", "cloud_cover", "visibility", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m", "shortwave_radiation", "soil_temperature_6cm", "is_day", "uv_index",
    
    # Verwachting voor Morgen
    "tomorrow_temperature_2m_max", "tomorrow_temperature_2m_min",
    "tomorrow_apparent_temperature_max", "tomorrow_apparent_temperature_min",
    "tomorrow_precipitation_sum", "tomorrow_rain_sum", "tomorrow_showers_sum",
    "tomorrow_snowfall_sum", "tomorrow_precipitation_hours",
    "tomorrow_precipitation_probability_max", "tomorrow_weather_code",
    "tomorrow_wind_speed_10m_max", "tomorrow_wind_gusts_10m_max",
    "tomorrow_wind_direction_10m_dominant", "tomorrow_shortwave_radiation_sum",
    "tomorrow_uv_index_max"
]

DEFAULT_SETTINGS = [
    "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
    "tomorrow_temperature_2m_max", "tomorrow_wind_speed_10m_max"
]

# --- BRONFUNCTIES & UTILS ---
def kmh_naar_beaufort(kmh):
    """Zet windsnelheid in km/h om naar de schaal van Beaufort"""
    if kmh is None: return 0
    limieten = [2, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
    for bft, limiet in enumerate(limieten):
        if kmh < limiet:
            return bft
    return 12

def laad_configuratie():
    """Leest het MAC-adres, land en plaats in uit config.txt"""
    if not os.path.exists(CONFIG_FILE):
        print(f"FOUT: Het bestand '{CONFIG_FILE}' is niet gevonden!")
        exit(1)
        
    try:
        with open(CONFIG_FILE, "r") as f:
            regels = [r.strip() for r in f if r.strip()]
            
        if len(regels) < 3:
            print(f"FOUT: '{CONFIG_FILE}' moet minimaal 3 regels bevatten (MAC, Landcode, Plaatsnaam)!")
            exit(1)
            
        return regels[0], regels[1], regels[2]
    except Exception as e:
        print(f"Fout bij het lezen van {CONFIG_FILE}: {e}")
        exit(1)

def haal_coordinaten_op(landcode, plaatsnaam):
    """Zoekt de latitude en longitude op via de Open-Meteo Geocoding API"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": plaatsnaam, "count": 5, "language": "nl", "format": "json"}
    
    try:
        response = requests.get(url, params=params).json()
        if 'results' not in response:
            print(f"FOUT: Kon de locatie '{plaatsnaam}' niet vinden bij Open-Meteo.")
            exit(1)
            
        for resultaat in response['results']:
            if resultaat.get('country_code', '').upper() == landcode.upper():
                return resultaat['latitude'], resultaat['longitude']
                
        eerste = response['results'][0]
        return eerste['latitude'], eerste['longitude']
    except Exception as e:
        print(f"Fout bij het ophalen van coördinaten: {e}")
        exit(1)

def laad_instellingen():
    """Laadt de dropdown instellingen uit settings.txt of pakt de defaults"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                regels = [r.strip() for r in f if r.strip()]
                if len(regels) == 5 and all(r in AVAILABLE_OPTIONS for r in regels):
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

# Initialisatie basisconfiguratie
MAC_ADRES, LANDCODE, PLAATSNAAM = laad_configuratie()
LATITUDE, LONGITUDE = haal_coordinaten_op(LANDCODE, PLAATSNAAM)
actieve_keuzes = laad_instellingen()
laatste_data = None

# --- CORE LOGICA & API ---
def genereer_korte_naam(sleutel):
    """Maakt een compacte prefix voor op het 32x32 display"""
    is_morgen = sleutel.startswith("tomorrow_")
    schoon = sleutel.replace("tomorrow_", "")
    
    MAPPING = {
        "temperature": "T", "apparent_temperature": "AT", "humidity": "H",
        "wind_speed": "W", "wind_gusts": "G", "wind_direction": "D",
        "precipitation": "PRC", "rain": "R", "showers": "SHO", "snow": "SNO",
        "cloud": "CLD", "radiation": "RAD", "surface_pressure": "P",
        "uv_index": "UV", "weather_code": "COD"
    }
    
    base = next((v for k, v in MAPPING.items() if k in schoon), schoon.split('_')[0][:3].upper())
    return f"M{base[:3]}" if is_morgen else base[:4]

def formatteer_eenheid(eenheid):
    """Zet standaard eenheden om naar een korter display-alternatief"""
    VERVANGINGEN = {"°C": "C", "km/h": "kh", "m/s": "ms", "%": "%"}
    return VERVANGINGEN.get(eenheid, eenheid)

def get_weer():
    """Haalt zowel actuele als voorspellende data dynamisch op uit de API"""
    global actieve_keuzes
    
    current_params = []
    daily_params = []
    
    for keuze in actieve_keuzes:
        if keuze.startswith("tomorrow_"):
            om_naam = keuze.replace("tomorrow_", "")
            if om_naam not in daily_params: daily_params.append(om_naam)
        else:
            if keuze not in current_params: current_params.append(keuze)
                
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE, "longitude": LONGITUDE, "timezone": "auto",
        "current": ",".join(current_params) if current_params else None,
        "daily": ",".join(daily_params) if daily_params else None
    }
    
    try:
        response = requests.get(url, params={k: v for k, v in params.items() if v is not None}).json()
        resultaten = []
        
        for keuze in actieve_keuzes:
            if keuze.startswith("tomorrow_"):
                om_naam = keuze.replace("tomorrow_", "")
                waarde = response['daily'][om_naam][1]
                eenheid = response['daily_units'][om_naam]
            else:
                waarde = response['current'][keuze]
                eenheid = response['current_units'][keuze]
            
            # Windkracht Beaufort omrekening
            if ("wind_speed" in keuze or "wind_gusts" in keuze) and eenheid == "km/h":
                waarde = kmh_naar_beaufort(waarde)
                eenheid = "Bft"
            
            eenheid = formatteer_eenheid(eenheid)
            korte_naam = genereer_korte_naam(keuze)
            resultaten.append(f"{korte_naam}:{waarde}{eenheid}")
            
        return resultaten
    except Exception as e:
        print(f"Weer API Fout: {e}")
        return None

def update_led_weer():
    """Genereert en verzendt de bitmap naar het LED-scherm via Bluetooth"""
    global laatste_data
    
    huidige_regels = get_weer()
    if not huidige_regels or huidige_regels == laatste_data:
        return

    img = Image.new('RGB', (32, 32), color=(0, 0, 0))
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT_PATH, 16)
    except: font = ImageFont.load_default()

    # Kleurenpallet per regel
    KLEUREN = [(255, 255, 120), (255, 255, 60), (200, 200, 0), (255, 120, 255), (255, 60, 255)]
    for idx, regel_tekst in enumerate(huidige_regels):
        d.text((1, idx * 6), regel_tekst, fill=KLEUREN[idx], font=font)
    
    img.save(TEMP_FILE, "BMP")
    
    try:
        with Client(address=MAC_ADRES) as device:
            if hasattr(device, 'send_image'): device.send_image(TEMP_FILE)
            else: device.send_file(TEMP_FILE)
        laatste_data = huidige_regels
    except Exception as e:
        print(f"Bluetooth fout: {e}")

def herhaalde_update_loop():
    while True:
        update_led_weer()
        time.sleep(60)

# --- SYSTEM TRAY (TRAYBAR) LOGICA ---
globale_tray = None

def maak_tray_icoon(root):
    """Genereert een dynamisch icoontje in het geheugen voor de traybar"""
    global globale_tray
    
    # Maak een 64x64 icoontje dat matcht met de roze/magenta kleur uit de GUI
    image = Image.new('RGB', (64, 64), color=(255, 60, 255))
    d = ImageDraw.Draw(image)
    d.text((20, 18), "W", fill=(255, 255, 255))
    
    def toon_applicatie(icon, item):
        icon.stop()
        # Herstel het Tkinter venster veilig in de hoofdthread
        root.after(0, lambda: (root.deiconify(), root.lift()))

    def afsluiten_applicatie(icon, item):
        icon.stop()
        # Sluit Tkinter volledig af
        root.after(0, root.destroy)

    menu = pystray.Menu(
        pystray.MenuItem('Openen', toon_applicatie, default=True),
        pystray.MenuItem('Afsluiten', afsluiten_applicatie)
    )
    
    globale_tray = pystray.Icon("weerstation", image, "Weerstation Settings", menu)
    globale_tray.run()

def verklein_naar_tray(root):
    """Verbergt het Tkinter venster en start de tray-thread"""
    root.withdraw()
    tray_thread = threading.Thread(target=maak_tray_icoon, args=(root,), daemon=True)
    tray_thread.start()

# --- GUI LOGICA (TKINTER) ---
def on_dropdown_select(event, index, combo):
    global actieve_keuzes, laatste_data
    nieuwe_waarde = combo.get()
    actieve_keuzes[index] = nieuwe_waarde
    sla_instellingen_op(actieve_keuzes)
    laatste_data = None
    threading.Thread(target=update_led_weer, daemon=True).start()

def bouw_gui():
    root = tk.Tk()
    root.title("Weerstation Settings")
    root.geometry("400x340")  # Hoogte vergroot voor de extra knop
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

    # Knop om handmatig te verkleinen naar de traybar
    btn_tray = tk.Button(root, text="Verklein naar Tray", command=lambda: verklein_naar_tray(root))
    btn_tray.pack(pady=10)

    lbl_info = tk.Label(root, text="Wijzigingen worden direct opgeslagen.", fg="gray")
    lbl_info.pack(side="bottom", pady=5)

    # Zorg dat het kruisje (X) rechtsboven het venster ook verbergt ipv afsluit
    root.protocol('WM_DELETE_WINDOW', lambda: verklein_naar_tray(root))

    root.mainloop()

if __name__ == "__main__":
    weer_thread = threading.Thread(target=herhaalde_update_loop, daemon=True)
    weer_thread.start()
    bouw_gui()