from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os
import json

app = Flask(__name__)

# ENV VARIABLES
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")

# CONSTANTS
LOGIN_URL = "https://www.xperteleven.com/front_new3.aspx"
MATCH_URL = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"  # Replace with your match link

# GEMINI REQUEST
def ask_gemini(text):
    if not text.strip():
        return "[No match summary to analyze.]"
    
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{
            "parts": [{
                "text": f"You are a FoxSportsGoon studio analyst. Summarize this football match for viewers:\n\n{text}"
            }]
        }]
    }

    print("=== Sending to Gemini ===")
    print(payload["contents"][0]["parts"][0]["text"])

    res = requests.post(url, json=payload, headers=headers)
    try:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print("Gemini error:", e)
        print("Gemini response text:", res.text)
        return "[Gemini response error]"

# SCRAPE + SUMMARIZE MATCH
def scrape_match_summary():
    with requests.Session() as session:
        login_page = session.get(LOGIN_URL)
        soup = BeautifulSoup(login_page.text, 'html.parser')

        # Extract hidden login inputs
        viewstate = soup.find("input", {"name": "__VIEWSTATE"})["value"]
        viewstate_gen = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"]
        event_validation = soup.find("input", {"name": "__EVENTVALIDATION"})["value"]

        payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_gen,
            "__EVENTVALIDATION": event_validation,
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        login_response = session.post(LOGIN_URL, data=payload)
        if "logout" not in login_response.text.lower():
            print("=== Login Failed ===")
            return "Login to Xpert Eleven failed."

        match_page = session.get(MATCH_URL)

        print("=== First 1000 chars of match page ===")
        print(match_page.text[:1000])

        soup = BeautifulSoup(match_page.text, 'html.parser')
        events = soup.find_all("tr", class_="ItemStyle2")

        summary = []
        for event in events:
            try:
                minute = event.find("span", class_="brotext10").text.strip()
                desc = event.find("span", {"id": lambda x: x and "lblEventDesc" in x})
                if desc:
                    summary.append(f"{minute}': {desc.text.strip()}")
            except:
                continue

        match_text = "\n".join(summary)

        print("=== Extracted Match Summary ===")
        print(match_text)

        if not match_text.strip():
            return "[No match events were found. Maybe the page layout changed.]"

        return ask_gemini(match_text)

# ROUTES
@app.route('/')
def home():
    return "X11 Scraper Bot is live!"

@app.route('/webhook', methods=['POST'])
def groupme_webhook():
    data = request.get_json()
    print("Webhook received:", data)

    if data.get("sender_type") == "user":
        text = data.get("text", "")
        if "FSGBot tell me about the last match" in text:
            summary = scrape_match_summary()
            post_to_groupme(summary)

    return "OK", 200

def post_to_groupme(message):
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": message
    }
    res = requests.post("https://api.groupme.com/v3/bots/post", json=payload)
    print("Sent message to GroupMe:", res.status_code)

# MAIN
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
