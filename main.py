# main.py

from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# Load credentials from environment
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")

# URLs
LOGIN_URL = "https://www.xperteleven.com/front_new3.aspx"
MATCH_URL = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"  # Replace with your match URL

# Gemini summary request
def ask_gemini(text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{
            "parts": [{
                "text": f"You are a studio analyst for the FoxSportsGoon channel. Summarize the following football match:\n\n{text}"
            }]
        }]
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"[Gemini error: {str(e)}]"

# Scrape and summarize the match
def scrape_match_summary():
    with requests.Session() as session:
        # Step 1: GET login page to extract hidden form fields
        login_page = session.get(LOGIN_URL)
        soup = BeautifulSoup(login_page.text, "html.parser")

        viewstate = soup.find("input", {"name": "__VIEWSTATE"})["value"]
        viewstategen = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"]
        eventvalid = soup.find("input", {"name": "__EVENTVALIDATION"})["value"]

        # Step 2: POST with login + hidden fields
        payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalid,
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        response = session.post(LOGIN_URL, data=payload)

        if "logout" not in response.text.lower():
            return "Login to Xpert Eleven failed."

        # Step 3: Scrape match page
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

# Flask routes
@app.route('/')
def home():
    return "FSGBot is live."

@app.route('/webhook', methods=['POST'])
def groupme_webhook():
    data = request.get_json()
    text = data.get("text", "").lower()
    sender = data.get("name")

    if sender == "FSGBot":  # Prevent bot from responding to itself
        return "OK", 200

    if "fsgbot tell me about the last match" in text:
        summary = scrape_match_summary()
        send_groupme_message(summary)
    return "OK", 200

# Send response back to GroupMe
def send_groupme_message(text):
    url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": text
    }
    requests.post(url, json=payload)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
