from flask import Flask, request
import os
import requests
from bs4 import BeautifulSoup
import sys
import json

app = Flask(__name__)

GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def send_groupme_message(text):
    url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": text
    }
    response = requests.post(url, json=payload)
    if response.status_code != 202:
        sys.stderr.write(f"⚠️ Failed to send message to GroupMe: {response.status_code} {response.text}\n")

def scrape_and_summarize():
    sys.stderr.write("🔍 scrape_and_summarize() called\n")

    login_url = "https://www.xperteleven.com/front_new3.aspx"
    match_id = "322737050"
    match_url = f"https://www.xperteleven.com/gameDetails.aspx?GameID={match_id}&dh=2"

    with requests.Session() as session:
        login_page = session.get(login_url)
        login_soup = BeautifulSoup(login_page.text, "html.parser")

        try:
            viewstate = login_soup.find("input", {"id": "__VIEWSTATE"})["value"]
            viewstategen = login_soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
            eventvalidation = login_soup.find("input", {"id": "__EVENTVALIDATION"})["value"]
        except Exception:
            sys.stderr.write("⚠️ Could not find login form hidden fields.\n")
            return "[Login form fields missing.]"

        login_payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
            "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
            "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
        }

        login_response = session.post(login_url, data=login_payload)
        if "Logout" not in login_response.text:
            sys.stderr.write("⚠️ Login to Xpert Eleven failed.\n")
            return "[Login to Xpert Eleven failed.]"

        sys.stderr.write("✅ Logged into Xpert Eleven\n")

        match_response = session.get(match_url)
        if match_response.status_code != 200:
            sys.stderr.write("⚠️ Failed to retrieve match page.\n")
            return "[Failed to retrieve match page.]"

        match_html = match_response.text
        sys.stderr.write("✅ Match HTML retrieved\n")

        soup = BeautifulSoup(match_html, "html.parser")
        try:
            home_team = soup.find("a", id="ctl00_cphMain_hplHomeTeam").text.strip()
            away_team = soup.find("a", id="ctl00_cphMain_hplAwayTeam").text.strip()
            home_score = soup.find("span", id="ctl00_cphMain_lblHomeScore").text.strip()
            away_score = soup.find("span", id="ctl00_cphMain_lblAwayScore").text.strip()
        except Exception:
            return "[Failed to parse team info.]"

        summary = f"Match: {home_team} {home_score} - {away_score} {away_team}"
        sys.stderr.write(f"✅ Summary composed: {summary}\n")
        return summary

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

    if "FSGBot tell me" in text:
        sys.stderr.write("🔁 Received trigger phrase, sending test message\n")
        send_groupme_message("✅ FSGBot received your message and is working!")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
