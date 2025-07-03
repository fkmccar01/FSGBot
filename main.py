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


def parse_match_events(soup):
    events = []
    event_rows = soup.find_all("tr", class_="ItemStyle2")
    for row in event_rows:
        minute_td = row.find("span", id=lambda x: x and "lblEventTime" in x)
        minute = minute_td.text.strip() if minute_td else "?"

        desc_td = row.find("span", id=lambda x: x and "lblEventDesc" in x)
        desc = desc_td.text.strip() if desc_td else ""

        tds = row.find_all("td")
        score_td = tds[2] if len(tds) > 2 else None
        score = score_td.text.strip() if score_td else ""

        event_text = f"{minute}' - {desc}"
        if score:
            event_text += f" (Score: {score})"
        events.append(event_text)
    return events


def scrape_match_html(session, url):
    response = session.get(url)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Failed to get match page: {response.status_code}\n")
        return None
    return response.text


def parse_match_data(html):
    soup = BeautifulSoup(html, "html.parser")

    # Teams and scores
    try:
        home_team = soup.find("a", id="ctl00_cphMain_hplHomeTeam").text.strip()
        away_team = soup.find("a", id="ctl00_cphMain_hplAwayTeam").text.strip()
        home_score = soup.find("span", id="ctl00_cphMain_lblHomeScore").text.strip()
        away_score = soup.find("span", id="ctl00_cphMain_lblAwayScore").text.strip()
        halftime_score = soup.find("span", id="ctl00_cphMain_lblHTScore").text.strip()
    except Exception:
        sys.stderr.write("⚠️ Failed to parse teams and score\n")
        home_team = away_team = home_score = away_score = halftime_score = "N/A"

    # Match info
    try:
        round_info = soup.find("span", id="ctl00_cphMain_lblOmgang").text.strip()
        league = soup.find("a", id="ctl00_cphMain_hplDivision").text.strip()
        season = soup.find("span", id="ctl00_cphMain_lblSeason").text.strip()
        venue = soup.find("span", id="ctl00_cphMain_lblArena").text.strip()
        match_date = soup.find("span", id="ctl00_cphMain_lblMatchDate").text.strip()
        referee = soup.find("span", id="ctl00_cphMain_lblReferee").text.strip()
    except Exception:
        sys.stderr.write("⚠️ Failed to parse match info\n")
        round_info = league = season = venue = match_date = referee = "N/A"

    # Parse lineups
    def parse_lineup(table_id):
        lineup = []
        table = soup.find("table", id=table_id)
        if not table:
            return lineup
        rows = table.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            position = cells[0].text.strip()
            player_link = cells[1].find("a")
            if player_link:
                player_name = player_link.text.strip()
                title = player_link.get("title", "")
                grade = "N/A"
                goal = assist = booked = injured = False
                for line in title.split("\n"):
                    line = line.strip()
                    if line.startswith("Grade:"):
                        grade = line.replace("Grade:", "").strip()
                    if "Goal:" in line:
                        goal = True
                    if "Assist:" in line:
                        assist = True
                    if "Booked" in line:
                        booked = True
                    if "Injured" in line:
                        injured = True
                lineup.append({
                    "position": position,
                    "name": player_name,
                    "grade": grade,
                    "goal": goal,
                    "assist": assist,
                    "booked": booked,
                    "injured": injured
                })
        return lineup

    home_lineup = parse_lineup("ctl00_cphMain_dgHomeLineUp")
    away_lineup = parse_lineup("ctl00_cphMain_dgAwayLineUp")

    # Parse events and extra stats
    match_events = parse_match_events(soup)
    possession = soup.find(id="ctl00_cphMain_lblPoss")
    chances = soup.find(id="ctl00_cphMain_lblChance")
    motm_home = soup.find(id="ctl00_cphMain_hplBestHome")
    motm_away = soup.find(id="ctl00_cphMain_hplBestAway")

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "halftime_score": halftime_score,
        "round_info": round_info,
        "league": league,
        "season": season,
        "venue": venue,
        "match_date": match_date,
        "referee": referee,
        "home_lineup": home_lineup,
        "away_lineup": away_lineup,
        "match_events": match_events,
        "possession": possession.text.strip() if possession else "N/A",
        "chances": chances.text.strip() if chances else "N/A",
        "motm_home": motm_home.text.strip() if motm_home else "N/A",
        "motm_away": motm_away.text.strip() if motm_away else "N/A",
    }


def format_gemini_prompt(match_data):
    prompt = (
        f"Write an exciting, brief summary of a soccer match with the following details:\n\n"
        f"Match: {match_data['home_team']} vs {match_data['away_team']}\n"
        f"Score: {match_data['home_score']} - {match_data['away_score']} (Halftime: {match_data['halftime_score']})\n"
        f"Round: {match_data['round_info']}, League: {match_data['league']}, Season: {match_data['season']}\n"
        f"Venue: {match_data['venue']}, Date: {match_data['match_date']}\n"
        f"Referee: {match_data['referee']}\n\n"

        f"Home Team Lineup:\n"
    )
    for player in match_data["home_lineup"]:
        details = []
        if player["goal"]:
            details.append("Goal")
        if player["assist"]:
            details.append("Assist")
        if player["booked"]:
            details.append("Booked")
        if player["injured"]:
            details.append("Injured")
        detail_str = f" ({', '.join(details)})" if details else ""
        prompt += f"- {player['name']} [{player['position']}, Grade: {player['grade']}{detail_str}]\n"

    prompt += "\nAway Team Lineup:\n"
    for player in match_data["away_lineup"]:
        details = []
        if player["goal"]:
            details.append("Goal")
        if player["assist"]:
            details.append("Assist")
        if player["booked"]:
            details.append("Booked")
        if player["injured"]:
            details.append("Injured")
        detail_str = f" ({', '.join(details)})" if details else ""
        prompt += f"- {player['name']} [{player['position']}, Grade: {player['grade']}{detail_str}]\n"

    prompt += "\nMatch Events:\n"
    if match_data["match_events"]:
        for event in match_data["match_events"]:
            prompt += f"- {event}\n"
    else:
        prompt += "No match events available.\n"

    prompt += (
        f"\nPossession: {match_data['possession']}\n"
        f"Chances: {match_data['chances']}\n"
        f"Man of the Match Home: {match_data['motm_home']}\n"
        f"Man of the Match Away: {match_data['motm_away']}\n"
    )

    prompt += "\nSummarize the key events, highlight top performers, and make it exciting."
    return prompt


def call_gemini_api(prompt):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GEMINI_API_KEY,
    }
    body = {
        "prompt": {
            "text": prompt
        },
        "temperature": 0.7,
        "candidate_count": 1,
        "max_output_tokens": 400,
        "top_p": 0.95,
        "top_k": 40,
    }

    response = requests.post(GEMINI_API_URL, headers=headers, json=body)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Gemini API error {response.status_code}: {response.text}\n")
        return "[Failed to generate summary.]"

    try:
        data = response.json()
        summary = data["candidates"][0]["output"]
        return summary.strip()
    except Exception as e:
        sys.stderr.write(f"⚠️ Failed to parse Gemini API response: {e}\n")
        return "[Failed to generate summary.]"


def scrape_and_summarize():
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    match_id = "322737050"  # Change or make dynamic as needed
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
            return "[Login to Xpert Eleven failed.]"

        match_html = scrape_match_html(session, match_url)
        if not match_html:
            return "[Failed to retrieve match page.]"

        match_data = parse_match_data(match_html)
        prompt = format_gemini_prompt(match_data)
        summary = call_gemini_api(prompt)
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

    if "FSGBot tell me about the last match" in text:
        match_summary = scrape_and_summarize()
        sys.stderr.write(f"Match summary:\n{match_summary}\n")

        failure_phrases = [
            "failed",
            "no match",
            "no events",
            "login to xpert eleven failed",
            "no events to summarize"
        ]
        if any(phrase in match_summary.lower() for phrase in failure_phrases):
            fallback_message = (
                "Alright folks, we're experiencing some technical difficulties "
                "with our Xpert Eleven feed, so no detailed match summary is available at the moment. "
                "Stay tuned to FoxSportsGoon for updates!"
            )
            sys.stderr.write("Sending fallback message due to scraping failure.\n")
            send_groupme_message(fallback_message)
        else:
            send_groupme_message(match_summary)

    return "ok", 200


def send_groupme_message(text):
    url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": GROUPME_BOT_ID,
        "text": text
    }
    response = requests.post(url, json=payload)
    if response.status_code != 202:
        sys.stderr.write(f"⚠️ Failed to send message to GroupMe: {response.status_code} {response.text}\n")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
