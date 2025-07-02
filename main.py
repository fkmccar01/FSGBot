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
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    match_url = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"

    with requests.Session() as session:
        # Step 1: Load login page and extract hidden fields
        login_page = session.get(login_url)
        soup = BeautifulSoup(login_page.text, "html.parser")

        try:
            viewstate = soup.find("input", {"name": "__VIEWSTATE"})["value"]
            viewstategen = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"]
            eventvalidation = soup.find("input", {"name": "__EVENTVALIDATION"})["value"]
        except Exception as e:
            print("❌ Failed to extract hidden fields:", e)
            return "[Login page missing required fields.]"

        # Step 2: Build form payload
        payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        # Step 3: Submit login form
        response = session.post(login_url, data=payload)

        print("=== LOGIN RESPONSE ===")
        print(response.text[:2000])
        print("======================")

        if "Logout" not in response.text:
            print("⚠️ Login failed: 'Logout' not in page.")
            return "[Login to Xpert Eleven failed.]"

        # Step 4: Fetch match page
        match_page = session.get(match_url)
        html = match_page.text
        print("=== MATCH PAGE ===")
        print(html[:1500])

        soup = BeautifulSoup(html, "html.parser")
        event_table = soup.find("table", {"class": "eventlist"})
        if not event_table:
            return "[No match events were found. Maybe the page layout changed.]"

        summary_lines = []
        for row in event_table.find_all("tr"):
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

        failure_phrases = [
            "failed",
            "no match",
            "no events",
            "login to xpert eleven failed",
            "no events to summarize"
        ]
        if any(phrase in match_info.lower() for phrase in failure_phrases):
            fallback_message = (
                "Alright folks, we're experiencing some technical difficulties "
                "with our Xpert Eleven feed, so no detailed match summary is available at the moment. "
                "Stay tuned to FoxSportsGoon for updates!"
            )
            print("Sending fallback message due to scraping failure.")
            send_groupme_message(fallback_message)
        else:
            response = generate_gemini_summary(match_info)
            print("Gemini summary:\n", response)
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
