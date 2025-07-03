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

        if "Logout" not in response.text:
            return "[Login to Xpert Eleven failed.]"

        match_response = session.get(matches_url)
        soup = BeautifulSoup(match_response.text, "html.parser")

        def extract_lineup(table_id):
            table = soup.find("table", {"id": table_id})
            players = []
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) == 2:
                        pos = cells[0].get_text(strip=True)
                        player_tag = cells[1].find("a")
                        if player_tag:
                            name = player_tag.get_text(strip=True)
                            title = player_tag.get("title", "")
                            players.append(f"{pos} - {name} ({title})")
            return players

        home_team = soup.select_one("table td span[style*='font-weight:bold']").get_text(strip=True)
        away_team = soup.select("table td span[style*='font-weight:bold']")[1].get_text(strip=True)

        home_lineup = extract_lineup("ctl00_cphMain_dgHomeLineUp")
        away_lineup = extract_lineup("ctl00_cphMain_dgAwayLineUp")

        venue = soup.find("span", id="ctl00_cphMain_lblArena").get_text(strip=True)
        referee = soup.find("span", id="ctl00_cphMain_lblReferee").get_text(strip=True)
        league = soup.find("span", id="ctl00_cphMain_lblLeaguename").get_text(strip=True)
        score = soup.find("span", id="ctl00_cphMain_lblResult").get_text(strip=True)

        event_table = soup.find("table", class_="eventlist") or soup.find("table", class_="eventlist ItemStyle2")
        match_events = []
        if event_table:
            rows = event_table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 3:
                    minute = cells[0].get_text(strip=True)
                    event = cells[1].get_text(strip=True)
                    player = cells[2].get_text(strip=True)
                    match_events.append(f"{minute} - {event}: {player}")

        return f"""
Match Summary
League: {league}
Venue: {venue}
Referee: {referee}
Final Score: {score} ({home_team} vs {away_team})

Home Team: {home_team}
Lineup:
- """ + "\n- ".join(home_lineup) + "\n\n" + f"Away Team: {away_team}\nLineup:\n- " + "\n- ".join(away_lineup) + "\n\nMatch Events:\n" + "\n".join(match_events)


def generate_gemini_summary(match_data):
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    prompt = f"You are a studio analyst for FoxSportsGoon (FSG). Summarize this match like you are doing a quick segment showing highlights of matches from around the league.\n\nHere is the data:\n\n{match_data}"
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

        if any(err in match_info.lower() for err in ["failed", "no match", "no events", "login"]):
            fallback_message = (
                "Alright folks, we're experiencing some technical difficulties "
                "with our Xpert Eleven feed, so no detailed match summary is available at the moment. "
                "Stay tuned to FoxSportsGoon for updates!"
            )
            send_groupme_message(fallback_message)
        else:
            response = generate_gemini_summary(match_info)
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
