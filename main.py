from flask import Flask, request
import os
import requests
from bs4 import BeautifulSoup
import sys
import re

app = Flask(__name__)

GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def parse_lineup(soup, team_prefix):
    lineup = []
    # Grab all rows for lineup (both "ItemStyle" and "AlternatingItemStyle")
    rows = soup.find_all("tr", class_=["ItemStyle", "AlternatingItemStyle"])
    for row in rows:
        pos_span = row.find("span", id=lambda x: x and team_prefix in x and "pos" in x)
        name_a = row.find("a", id=lambda x: x and team_prefix in x and "PlayerName" in x)
        if pos_span and name_a:
            position = pos_span.text.strip()
            name = name_a.text.strip()
            title = name_a.get("title", "")
            grade = None
            grade_match = re.search(r"Grade:\s*(\d+)", title)
            if grade_match:
                grade = int(grade_match.group(1))
            lineup.append({
                "position": position,
                "name": name,
                "grade": grade
            })
    return lineup

def scrape_match_summary():
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    matches_url = "https://www.xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"

    with requests.Session() as session:
        # Get login page for hidden fields
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
            sys.stderr.write("⚠️ Login failed.\n")
            return "[Login to Xpert Eleven failed.]"

        match_response = session.get(matches_url)
        html = match_response.text
        soup = BeautifulSoup(html, "html.parser")

        # Extract team names
        home_team_tag = soup.find(id="ctl00_cphMain_hplHomeTeam")
        home_team = home_team_tag.text.strip() if home_team_tag else "Unknown"

        away_team_tag = soup.find(id="ctl00_cphMain_hplAwayTeam")
        away_team = away_team_tag.text.strip() if away_team_tag else "Unknown"

        # Extract scores
        home_score_tag = soup.find(id="ctl00_cphMain_lblHomeScore")
        home_score = home_score_tag.text.strip() if home_score_tag else "?"

        away_score_tag = soup.find(id="ctl00_cphMain_lblAwayScore")
        away_score = away_score_tag.text.strip() if away_score_tag else "?"

        final_score = f"{home_score} - {away_score}"

        # Extract venue, date, referee, league
        venue_tag = soup.find(id="ctl00_cphMain_lblArena")
        venue = venue_tag.text.strip() if venue_tag else "Unknown"

        match_date_tag = soup.find(id="ctl00_cphMain_lblMatchDate")
        match_date = match_date_tag.text.strip() if match_date_tag else "Unknown date/time"

        referee_tag = soup.find(id="ctl00_cphMain_lblReferee")
        referee = referee_tag.text.strip() if referee_tag else "Unknown"

        league_tag = soup.find(id="ctl00_cphMain_hplDivision")
        league = league_tag.text.strip() if league_tag else ""

        # Parse event table
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

        events_summary = "\n".join(summary_lines) if summary_lines else "[No events to summarize.]"

        # Compose full summary
        full_summary = (
            f"Match: {home_team} vs {away_team}\n"
            f"Final Score: {final_score}\n"
            f"Venue: {venue}\n"
            f"Date: {match_date}\n"
            f"{referee}\n"
            f"League info: {league}\n\n"
            f"Events:\n{events_summary}"
        )

        return full_summary

def generate_gemini_summary(match_data):
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    prompt = f"You are a studio analyst for soccer channel FoxSportsGoon (FSG). Summarize this soccer match in the style of a SportsCenter recap:\n\n{match_data}"
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
    sys.stderr.write(f"Webhook data received: {data}\n")  # Log incoming request

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
