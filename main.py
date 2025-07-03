import os
import sys
import requests
import json
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

# Environment variables
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

def scrape_match_html(session, url):
    response = session.get(url)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Failed to get match page: {response.status_code}\n")
        return None
    return response.text

def parse_match_data(soup):  # 💡 Changed from HTML string to BeautifulSoup object
    try:
        home_team = soup.find("a", id="ctl00_cphMain_hplHomeTeam").text.strip()
        away_team = soup.find("a", id="ctl00_cphMain_hplAwayTeam").text.strip()
        home_score = soup.find("span", id="ctl00_cphMain_lblHomeScore").text.strip()
        away_score = soup.find("span", id="ctl00_cphMain_lblAwayScore").text.strip()
    except Exception:
        sys.stderr.write("⚠️ Failed to parse teams and score\n")
        home_team = away_team = home_score = away_score = "N/A"

    try:
        round_info = soup.find("span", id="ctl00_cphMain_lblOmgang").text.strip()
        league = soup.find("a", id="ctl00_cphMain_hplDivision").text.strip()
        venue = soup.find("span", id="ctl00_cphMain_lblArena").text.strip()
        referee = soup.find("span", id="ctl00_cphMain_lblReferee").text.strip()
    except Exception:
        sys.stderr.write("⚠️ Failed to parse match info\n")
        round_info = league = venue = referee = "N/A"

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "round_info": round_info,
        "league": league,
        "venue": venue,
        "referee": referee,
    }

def parse_match_events(soup):
    events = []
    event_rows = soup.find_all("tr", class_="ItemStyle2")
    for row in event_rows:
        minute_td = row.find("span", id=lambda x: x and "lblEventTime" in x)
        minute = minute_td.text.strip() if minute_td else "?"

        desc_td = row.find("span", id=lambda x: x and "lblEventDesc" in x)
        desc = desc_td.text.strip() if desc_td else ""

        score_td = row.find_all("td")[2] if len(row.find_all("td")) > 2 else None
        score = score_td.text.strip() if score_td else ""

        event_text = f"{minute}' - {desc}"
        if score:
            event_text += f" (Score: {score})"
        events.append(event_text)
    return events

def parse_player_grades(soup):
    players = []

    # Home team
    home_rows = soup.select('#ctl00_cphMain_dgHomeLineUp tr.ItemStyle, #ctl00_cphMain_dgHomeLineUp tr.AlternatingItemStyle')
    for row in home_rows:
        pos_tag = row.find("span", id=lambda x: x and "lblHomepos" in x)
        name_tag = row.find("a", id=lambda x: x and "hplHomePlayerName" in x)
        if name_tag and pos_tag:
            title = name_tag.get("title", "")
            match = re.search(r"Grade:\s*(\d+)", title)
            grade = int(match.group(1)) if match else None
            players.append({
                "team": "home",
                "position": pos_tag.text.strip(),
                "name": name_tag.text.strip(),
                "grade": grade
            })

    # Away team
    away_rows = soup.select('#ctl00_cphMain_dgAwayLineUp tr.ItemStyle, #ctl00_cphMain_dgAwayLineUp tr.AlternatingItemStyle')
    for row in away_rows:
        pos_tag = row.find("span", id=lambda x: x and "lblAwaypos" in x)
        name_tag = row.find("a", id=lambda x: x and "hplAwayPlayerName" in x)
        if name_tag and pos_tag:
            title = name_tag.get("title", "")
            match = re.search(r"Grade:\s*(\d+)", title)
            grade = int(match.group(1)) if match else None
            players.append({
                "team": "away",
                "position": pos_tag.text.strip(),
                "name": name_tag.text.strip(),
                "grade": grade
            })

    return players

def format_gemini_prompt(match_data, events, player_grades):
    def annotate(text, player_grades):
        sorted_players = sorted(player_grades, key=lambda p: len(p["name"]), reverse=True)
        annotated = set()

        for player in sorted_players:
            name = player["name"]
            pos = player["position"]
            grade = player["grade"]
            if not grade:
                continue

            # Annotate only the first occurrence
            def replacer(match):
                matched_name = match.group(0)
                if matched_name.lower() not in annotated:
                    annotated.add(matched_name.lower())
                    return f"{matched_name} ({pos}, {grade} 📊)"
                return matched_name

            text = re.sub(rf'\b{re.escape(name)}\b', replacer, text, flags=re.IGNORECASE)

        return text

    # Build the core prompt
    prompt = f"""You are a witty and insightful football analyst summarizing the match between {match_data['home_team']} and {match_data['away_team']}. The game ended {match_data['home_score']} - {match_data['away_score']}.

Venue: {match_data.get('venue', 'N/A')}
Referee: {match_data.get('referee', 'N/A')}
Man of the Match: {match_data['motm_home']} (home), {match_data['motm_away']} (away). Winner: {match_data['motm_winner']}

Key Match Events:
"""

    for e in events:
        prompt += f"\n- {e}"

    prompt += "\n\nWrite an energetic and engaging match summary, focusing on key moments, player impact, drama, and fan excitement. Use vivid language and a fun tone. Include goal scorers, assists, and key performances.\n"

    # Annotate player names directly in the prompt
    prompt = annotate(prompt, player_grades)

    return prompt
    
def scrape_and_summarize():
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
            return "[Login to Xpert Eleven failed.]"

        match_html = scrape_match_html(session, match_url)
        if not match_html:
            return "[Failed to retrieve match page.]"

        soup = BeautifulSoup(match_html, "html.parser")
        player_grades = parse_player_grades(soup)
        match_data = parse_match_data(soup)
        events = parse_match_events(soup)

        motm_home = soup.find(id="ctl00_cphMain_hplBestHome")
        motm_away = soup.find(id="ctl00_cphMain_hplBestAway")
        match_data["motm_home"] = motm_home.text.strip() if motm_home else "N/A"
        match_data["motm_away"] = motm_away.text.strip() if motm_away else "N/A"

        if match_data["home_score"].isdigit() and match_data["away_score"].isdigit():
            if int(match_data["home_score"]) > int(match_data["away_score"]):
                match_data["motm_winner"] = match_data["motm_home"]
            elif int(match_data["away_score"]) > int(match_data["home_score"]):
                match_data["motm_winner"] = match_data["motm_away"]
            else:
                match_data["motm_winner"] = "Match drawn, no MoTM winner"
        else:
            match_data["motm_winner"] = "N/A"

        prompt = format_gemini_prompt(match_data, events, player_grades)
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
        return "Ignoring bot message"

    if "FSGBot tell me" in text:
        sys.stderr.write("🔁 Received trigger phrase, generating match summary\n")
        summary = scrape_and_summarize()
        sys.stderr.write(f"Generated summary: {summary}\n")
        send_groupme_message(summary)

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
