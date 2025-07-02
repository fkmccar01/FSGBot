from flask import Flask, request
import os
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

def scrape_match_summary():
    login_url = "https://www.xperteleven.com/?p=login"
    matches_url = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"

    with requests.Session() as session:
        # Login payload
        login_payload = {
            "username": X11_USERNAME,
            "password": X11_PASSWORD,
            "Login": "Login"
        }

       # Perform login
        response = session.post(login_url, data=login_payload)

        # DEBUG: print login response to check if login worked
        print("=== LOGIN HTML (first 2000 chars) ===")
        print(response.text[:2000])
        print("=== END LOGIN HTML ===")

       # Check if login succeeded
        if "Logout" not in response.text:
            print("⚠️ Login failed. Response didn't include 'Logout'.")
            return "[Login to Xpert Eleven failed.]"

        # Fetch match page
        match_response = session.get(matches_url)
        html = match_response.text
    
        # Save for debugging
        print("=== Match Page HTML (first 1500 chars) ===")
        print(html[:1500])

        # Parse
        soup = BeautifulSoup(html, "html.parser")

        # Look for event table
        event_table = soup.find("table", {"class": "eventlist"})
        if not event_table:
            print("❌ Could not find 'eventlist' table in match page.")
            return "[No match events were found. Maybe the page layout changed.]"

        # Parse the HTML
        soup = BeautifulSoup(html, "html.parser")

        # Try to locate event list
        event_table = soup.find("table", {"class": "eventlist"})
        if not event_table:
            return "[No match events were found. Maybe the page layout changed.]"

        rows = event_table.find_all("tr")
        summary_lines = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 3:
                minute = cells[0].get_text(strip=True)
                event = cells[1].get_text(strip=True)
                player = cells[2].get_text(strip=True)
                summary_lines.append(f"{minute} - {event}: {player}")

        return "\n".join(summary_lines) if summary_lines else "[No events to summarize.]"

def generate_gemini_summary(match_data):
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    prompt = f"You are a studio analyst for soccer channel FoxSportsGoon. Summarize this soccer match like you are reporting the highlights to viewers:\n\n{match_data}"
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload)
    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return "[Gemini API failed to generate a summary.]"

@app.route("/", methods=["GET"])
def index():
    return "FSGBot is alive!"

@app.route("/webhook", methods=["POST"])
def groupme_webhook():
    data = request.get_json()
    print("Webhook data received:", data)  # Log incoming request

    if not data:
        return "No data received", 400

    text = data.get("text", "")
    sender_type = data.get("sender_type", "")

    if sender_type == "bot":
        return "Ignoring my own message"

    if "FSGBot tell me about the last match" in text:
        match_info = scrape_match_summary()
        print("Scraper output:\n", match_info)  # Log scraper output
        response = generate_gemini_summary(match_info)
        print("Gemini summary:\n", response)  # Log Gemini API response
        send_groupme_message(response)

    return "ok", 200

def send_groupme_message(text):
    url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": text
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
