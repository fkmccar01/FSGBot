from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# Environment variables
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")

# URLs
LOGIN_URL = "https://www.xperteleven.com/front_new3.aspx"
MATCH_URL = "https://xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"  # Replace with dynamic if needed

# Gemini function
def ask_gemini(text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{
            "parts": [{
                "text": f"You are a studio analyst for soccer channel FoxSportsGoon. Summarize this football match:\n{text}"
            }]
        }]
    }

    res = requests.post(url, json=payload, headers=headers)
    try:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"[Gemini error] {str(e)}"

# Scraper function
def scrape_match_summary():
    with requests.Session() as session:
        payload = {
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        # Login to Xpert Eleven
        login_res = session.post(LOGIN_URL, data=payload)
        if "logout" not in login_res.text.lower():
            return "Login to Xpert Eleven failed."

        # Get match page
        match_res = session.get(MATCH_URL)
        soup = BeautifulSoup(match_res.text, "html.parser")

        # Extract match events
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

# GroupMe POST message
def post_to_groupme(text):
    url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": text
    }
    requests.post(url, json=payload)

# Routes
@app.route('/')
def home():
    return "FSGBot is live."

@app.route('/scrape')
def scrape_direct():
    return scrape_match_summary()

@app.route('/webhook', methods=['POST'])
def groupme_webhook():
    data = request.get_json()
    if not data:
        return "No data", 400

    sender_type = data.get("sender_type")
    text = data.get("text", "")

    # Avoid replying to itself
    if sender_type == "bot":
        return "OK", 200

    # Trigger on specific phrase
    if "fsgbot tell me about the last match" in text.lower():
        summary = scrape_match_summary()
        post_to_groupme(summary)

    return "OK", 200

# Run the server
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
