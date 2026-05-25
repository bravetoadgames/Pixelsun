import os
# FORCE XORG BACKEND: This must absolutely be on line 1 and 2, before any other import!
# This prevents pystray from searching for missing Linux Ayatana/AppIndicator3 libraries.
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

# --- CONFIGURATION AND FILES ---
CONFIG_FILE = "config.txt"
SETTINGS_FILE = "settings.txt"
TEMP_FILE = "/tmp/weather_display.bmp"
FONT_PATH = "tom-thumb.ttf"

AVAILABLE_OPTIONS = [
    # Current (Now)
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "rain", "showers", "snowfall", "snow_depth", "weather_code",
    "pressure_msl", "surface_pressure", "cloud_cover", "visibility", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m", "shortwave_radiation", "soil_temperature_6cm", "is_day", "uv_index",
    
    # Forecast for Tomorrow
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

# --- SOURCE FUNCTIONS & UTILS ---
def kmh_to_beaufort(kmh):
    """Converts wind speed in km/h to the Beaufort scale"""
    if kmh is None: 
        return 0
    limits = [2, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
    for bft, limit in enumerate(limits):
        if kmh < limit:
            return bft
    return 12

def load_config():
    """Reads the MAC address, country code, and city name from config.txt"""
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: The file '{CONFIG_FILE}' was not found!")
        exit(1)
        
    try:
        with open(CONFIG_FILE, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
            
        if len(lines) < 3:
            print(f"ERROR: '{CONFIG_FILE}' must contain at least 3 lines (MAC, Country Code, City Name)!")
            exit(1)
            
        return lines[0], lines[1], lines[2]
    except Exception as e:
        print(f"Error while reading {CONFIG_FILE}: {e}")
        exit(1)

def fetch_coordinates(country_code, city_name):
    """Looks up the latitude and longitude via the Open-Meteo Geocoding API"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city_name, "count": 5, "language": "en", "format": "json"}
    
    try:
        response = requests.get(url, params=params).json()
        if 'results' not in response:
            print(f"ERROR: Could not find the location '{city_name}' at Open-Meteo.")
            exit(1)
            
        for result in response['results']:
            if result.get('country_code', '').upper() == country_code.upper():
                return result['latitude'], result['longitude']
                
        first_result = response['results'][0]
        return first_result['latitude'], first_result['longitude']
    except Exception as e:
        print(f"Error while fetching coordinates: {e}")
        exit(1)

def load_settings():
    """Loads the dropdown settings from settings.txt or returns the defaults"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                lines = [line.strip() for line in f if line.strip()]
                if len(lines) == 5 and all(line in AVAILABLE_OPTIONS for line in lines):
                    return lines
        except Exception as e:
            print(f"Error while loading settings.txt: {e}")
    return DEFAULT_SETTINGS

def save_settings(choices):
    """Saves the 5 choices to settings.txt"""
    try:
        with open(SETTINGS_FILE, "w") as f:
            for choice in choices:
                f.write(f"{choice}\n")
    except Exception as e:
        print(f"Error while saving settings.txt: {e}")

# Core Configuration Initialization
MAC_ADDRESS, COUNTRY_CODE, CITY_NAME = load_config()
LATITUDE, LONGITUDE = fetch_coordinates(COUNTRY_CODE, CITY_NAME)
active_choices = load_settings()
last_data = None

# --- CORE LOGIC & API ---
def generate_short_name(key):
    """Creates a compact prefix for the 32x32 LED display"""
    is_tomorrow = key.startswith("tomorrow_")
    clean_key = key.replace("tomorrow_", "")
    
    MAPPING = {
        "temperature": "T", "apparent_temperature": "AT", "humidity": "H",
        "wind_speed": "W", "wind_gusts": "G", "wind_direction": "D",
        "precipitation": "PRC", "rain": "R", "showers": "SHO", "snow": "SNO",
        "cloud": "CLD", "radiation": "RAD", "surface_pressure": "P",
        "uv_index": "UV", "weather_code": "COD"
    }
    
    base = next((v for k, v in MAPPING.items() if k in clean_key), clean_key.split('_')[0][:3].upper())
    return f"M{base[:3]}" if is_tomorrow else base[:4]

def format_unit(unit):
    """Converts standard units to shorter alternatives optimized for the display"""
    REPLACEMENTS = {"°C": "C", "km/h": "kh", "m/s": "ms", "%": "%"}
    return REPLACEMENTS.get(unit, unit)

def fetch_weather_data():
    """Dynamically fetches both current and forecast data from the API"""
    global active_choices
    
    current_params = list({c for c in active_choices if not c.startswith("tomorrow_")})
    daily_params = list({c.replace("tomorrow_", "") for c in active_choices if c.startswith("tomorrow_")})
                
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE, 
        "longitude": LONGITUDE, 
        "timezone": "auto",
        "current": ",".join(current_params) if current_params else None,
        "daily": ",".join(daily_params) if daily_params else None
    }
    
    try:
        response = requests.get(url, params={k: v for k, v in params.items() if v is not None}).json()
        results = []
        
        for choice in active_choices:
            if choice.startswith("tomorrow_"):
                om_name = choice.replace("tomorrow_", "")
                value = response['daily'][om_name][1]
                unit = response['daily_units'][om_name]
            else:
                value = response['current'][choice]
                unit = response['current_units'][choice]
            
            # Convert wind speed from km/h to Beaufort scale
            if ("wind_speed" in choice or "wind_gusts" in choice) and unit == "km/h":
                value = kmh_to_beaufort(value)
                unit = "Bft"
            
            unit = format_unit(unit)
            short_name = generate_short_name(choice)
            results.append(f"{short_name}:{value}{unit}")
            
        return results
    except Exception as e:
        print(f"Weather API Error: {e}")
        return None

def update_led_display():
    """Generates and transmits the bitmap to the LED screen via Bluetooth"""
    global last_data
    
    current_lines = fetch_weather_data()
    if not current_lines or current_lines == last_data:
        return

    img = Image.new('RGB', (32, 32), color=(0, 0, 0))
    d = ImageDraw.Draw(img)
    try: 
        font = ImageFont.truetype(FONT_PATH, 16)
    except Exception: 
        font = ImageFont.load_default()

    # Color scheme per line
    COLORS = [(255, 255, 120), (255, 255, 60), (200, 200, 0), (255, 120, 255), (255, 60, 255)]
    for idx, line_text in enumerate(current_lines):
        d.text((1, idx * 6), line_text, fill=COLORS[idx], font=font)
    
    img.save(TEMP_FILE, "BMP")
    
    try:
        with Client(address=MAC_ADDRESS) as device:
            if hasattr(device, 'send_image'): 
                device.send_image(TEMP_FILE)
            else: 
                device.send_file(TEMP_FILE)
        last_data = current_lines
    except Exception as e:
        print(f"Bluetooth error: {e}")

def recurring_update_loop():
    while True:
        update_led_display()
        time.sleep(60)

# --- SYSTEM TRAY LOGIC ---
global_tray = None

def create_tray_icon(root):
    """Generates an in-memory dynamic system tray icon representing a shiny sun"""
    global global_tray
    
    image = Image.new('RGB', (64, 64), color=(50, 50, 50))
    d = ImageDraw.Draw(image)
    yellow = (255, 220, 0)
    
    # 1. Draw 8 sun rays around the center
    rays = [
        [32, 10, 32, 16],  # Top
        [32, 48, 32, 54],  # Bottom
        [10, 32, 16, 32],  # Left
        [48, 32, 54, 32],  # Right
        [16, 16, 22, 22],  # Top-Left diagonal
        [48, 16, 42, 22],  # Top-Right diagonal
        [16, 48, 22, 42],  # Bottom-Left diagonal
        [48, 48, 42, 42]   # Bottom-Right diagonal
    ]
    for ray in rays:
        d.line(ray, fill=yellow, width=2)
        
    # 2. Draw the core sun circle in the center (24x24 pixels)
    d.ellipse([20, 20, 44, 44], fill=yellow)
    
    def show_application(icon, item):
        icon.stop()
        root.after(0, lambda: (root.deiconify(), root.lift()))

    def quit_application(icon, item):
        icon.stop()
        root.after(0, root.destroy)

    menu = pystray.Menu(
        pystray.MenuItem('Open', show_application, default=True),
        pystray.MenuItem('Exit', quit_application)
    )
    
    global_tray = pystray.Icon("weatherstation", image, "Weather Station Settings", menu)
    global_tray.run()

def minimize_to_tray(root):
    """Hides the Tkinter window and launches the system tray thread"""
    root.withdraw()
    tray_thread = threading.Thread(target=create_tray_icon, args=(root,), daemon=True)
    tray_thread.start()

# --- GUI LOGICA (TKINTER) ---
def on_dropdown_select(event, index, combo):
    global active_choices, last_data
    new_value = combo.get()
    active_choices[index] = new_value
    save_settings(active_choices)
    last_data = None
    threading.Thread(target=update_led_display, daemon=True).start()

def build_gui():
    root = tk.Tk()
    root.title("Weather Station Settings")
    root.geometry("400x340")
    root.resizable(False, False)

    label_title = tk.Label(root, text=f"Display Options - {CITY_NAME}", font=("Arial", 12, "bold"))
    label_title.pack(pady=10)

    for i in range(5):
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=20, pady=5)
        
        lbl = tk.Label(frame, text=f"Line {i+1}:", width=8, anchor="w")
        lbl.pack(side="left")
        
        combo = ttk.Combobox(frame, values=AVAILABLE_OPTIONS, state="readonly")
        combo.set(active_choices[i])
        combo.pack(side="left", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", lambda event, idx=i, cb=combo: on_dropdown_select(event, idx, cb))

    btn_tray = tk.Button(root, text="Minimize to Tray", command=lambda: minimize_to_tray(root))
    btn_tray.pack(pady=10)

    lbl_info = tk.Label(root, text="Changes are saved instantly.", fg="gray")
    lbl_info.pack(side="bottom", pady=5)

    root.mainloop()

if __name__ == "__main__":
    weather_thread = threading.Thread(target=recurring_update_loop, daemon=True)
    weather_thread.start()
    build_gui()