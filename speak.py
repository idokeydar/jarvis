import requests
import pygame

KEY_RAW = "Sk-fish-SHkf8Dm-U-RWq1r5JmWsqRw0qOxG4BF0jZdVHbBgVOo"
MODEL_ID = "05b36da8574341d0803391491850db20"

# We test both lowercase 'sk-' and capital 'Sk-'
keys_to_test = [
    KEY_RAW.replace("Sk-fish-", "sk-fish-"),
    KEY_RAW
]

success = False

for key in keys_to_test:
    print(f"Testing with key prefix: {key[:8]}...")
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "model": "s2.1-pro-free"
    }
    
    payload = {
        "text": "Mark 57 systems online. All diagnostics green, sir.",
        "reference_id": MODEL_ID,
        "format": "mp3"
    }
    
    res = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)
    print(f"Server Response Code: {res.status_code}")
    
    if res.status_code == 200:
        print("Success! Audio received. Playing...")
        with open("jarvis.mp3", "wb") as f:
            f.write(res.content)
            
        pygame.mixer.init()
        pygame.mixer.music.load("jarvis.mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pass
        pygame.mixer.quit()
        success = True
        break
    else:
        print(f"Details: {res.text}\n")

if not success:
    print("Neither key worked. Please verify the key string on fish.audio/app/api-keys.")