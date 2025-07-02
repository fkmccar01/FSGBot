# main.py

from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# ENV VARS
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")

# URLs
LOGIN_URL = "https://www.xperteleven.com/front_new3.aspx"
MATCH_URL = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"  # Replace with your own

def ask_gemini(text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{
            "parts": [{
                "text": f"You are a studio analyst for FoxSportsGoon. Summarize this football match as exciting highlights:\n{text}"
            }]
        }]
    }

    res = requests.post(url, json=payload, headers=headers)
    try:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "[Gemini response error]"

def scrape_match_summary():
    with requests.Session() as session:
        # Log in
        payload = {
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        response = session.post(LOGIN_URL, data=payload)

        if "logout" not in response.text.lower():
            return "Login to Xpert Eleven failed."

        # Scrape match
        match_page = session.get(MATCH_URL)
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
        return ask_gemini(match_text)

def send_groupme_message(message):
    requests.post("https://api.groupme.com/v3/bots/post", json={
        "bot_id": GROUPME_BOT_ID,
        "text": message
    })

@app.route('/')
def home():
    return "FSGBot is running."

@app.route('/groupme', methods=['POST'])
def groupme_webhook():
    data = request.get_json()

    # Ignore bot's own messages
    if data['sender_type'] == "bot":
        return "ok", 200

    message_text = data.get("text", "").lower()

    if "fsgbot" in message_text and "last match" in message_text:
        summary = scrape_match_summary()
        send_groupme_message(summary)

    return "ok", 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
