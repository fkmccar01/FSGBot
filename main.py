from flask import Flask, request
import os
import requests
from bs4 import BeautifulSoup
import sys

app = Flask(__name__)

GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def scrape_match_summary():
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    matches_url = "https://www.xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"

    with requests.Session() as session:
        # Step 1: Load login page
        initial_response = session.get(login_url)
        soup_initial = BeautifulSoup(initial_response.text, "html.parser")

        viewstate = soup_initial.find("input", {"id": "__VIEWSTATE"})["value"]
        viewstategen = soup_initial.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
        eventvalidation = soup_initial.find("input", {"id": "__EVENTVALIDATION"})["value"]

        login_payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        response = session.post(login_url, data=login_payload)

        with open("login_debug.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        sys.stderr.write("✅ Saved login_debug.html\n")

        sys.stderr.write("=== LOGIN HTML (first 2000 chars) ===\n")
        sys.stderr.write(response.text[:2000] + "\n")
        sys.stderr.write("=== END LOGIN HTML ===\n")

        if "Logout" not in response.text:
            sys.stderr.write("⚠️ Login failed. Response didn't include 'Logout'.\n")
            return "[Login to Xpert Eleven failed.]"

        match_response = session.get(matches_url)
        html = match_response.text

        sys.stderr.write("=== Match Page HTML (first 1500 chars) ===\n")
        sys.stderr.write(html[:1500] + "\n")

        soup = BeautifulSoup(html, "html.parser")

        # ✅ Updated: Find events from rows with class="ItemStyle2"
        event_rows = soup.find_all("tr", class_="ItemStyle2")

        if not event_rows:
            sys.stderr.write("❌ Could not find any 'ItemStyle2' rows for match events.\n")
            return "[No match events were found. Maybe the page layout changed.]"

        summary_lines = []
        for row in event_rows:
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
    prompt = f"You are a studio analyst for soccer channel FoxSportsGoon (FSG). Summarize this soccer match in the style of a SportsCenter segment:\n\n{match_data}"
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
    sys.stderr.write(f"Webhook data received: {data}\n")

    if not data:
        return "No data received", 400

    text = data.get("text", "")
    sender_type = data.get("sender_type", "")

    if sender_type == "bot":
        return "Ignoring my own message"

    if "FSGBot tell me about the last match" in text:
        match_info = scrape_match_summary()
        sys.stderr.write(f"Scraper output:\n{match_info}\n")

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
            sys.stderr.write("Sending fallback message due to scraping failure.\n")
            send_groupme_message(fallback_message)
        else:
            response = generate_gemini_summary(match_info)
            sys.stderr.write(f"Gemini summary:\n{response}\n")
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
