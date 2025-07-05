import unidecode
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
GOONDESLIGA_URL = os.environ.get("GOONDESLIGA_URL")
SPOONDESLIGA_URL = os.environ.get("SPOONDESLIGA_URL")

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

def get_logged_in_session():
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    session = requests.Session()
    login_page = session.get(login_url)
    login_soup = BeautifulSoup(login_page.text, "html.parser")
    try:
        viewstate = login_soup.find("input", {"id": "__VIEWSTATE"})["value"]
        viewstategen = login_soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
        eventvalidation = login_soup.find("input", {"id": "__EVENTVALIDATION"})["value"]
    except Exception:
        sys.stderr.write("⚠️ Could not find login form hidden fields.\n")
        return None

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
        return None
    return session

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
    impactful_players = set()
    substitute_events = []

    # Collect all event rows
    event_rows = soup.find_all("tr", class_="ItemStyle2")

    for row in event_rows:
        minute_td = row.find("span", id=lambda x: x and "lblEventTime" in x)
        minute = minute_td.text.strip() if minute_td else "?"

        desc_td = row.find("span", id=lambda x: x and "lblEventDesc" in x)
        desc = desc_td.text.strip() if desc_td else ""

        score_td = row.find_all("td")[2] if len(row.find_all("td")) > 2 else None
        score = score_td.text.strip() if score_td else ""

        # Clean grades from description
        desc = re.sub(r"\(Grade:\s*\d+\)", "", desc)

        event_text = f"{minute}' - {desc.strip()}"
        if score:
            event_text += f" (Score: {score})"

        # Check if it's a sub — temporarily hold it
        if "subbed in" in desc.lower() or "substituted" in desc.lower():
            substitute_events.append((desc, event_text))
            continue

        # Check if it's an impactful event
        if any(keyword in desc.lower() for keyword in ["goal", "assist", "injured", "red card", "sent off"]):
            # Extract player names from description
            for word in desc.split():
                if word[0].isupper():
                    impactful_players.add(word)
            events.append(event_text)
        else:
            events.append(event_text)

    # Reinsert only the sub events where the sub made an impact
    for desc, event_text in substitute_events:
        subbed_in_player = extract_player_name_from_desc(desc)
        if subbed_in_player and subbed_in_player in impactful_players:
            events.append(event_text)

    return events

def extract_player_name_from_desc(desc):
    # crude way to pull a name from a substitution string
    match = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", desc)
    return match.group(1).strip() if match else None

def format_gemini_prompt(match_data, events, player_grades):
    events_text = "\n".join(events)
    referee_events = [e for e in events if any(keyword in e.lower() for keyword in ["yellow card", "red card", "penalty", "disallowed goal"])]
    referee_events_text = "\n".join(referee_events) if referee_events else "No significant referee interventions."

    # Build the player grades section
    ratings_lines = []
    for p in player_grades:
        if p["grade"]:  # only include rated players
            line = f"{p['name']} ({p['position']}, {p['grade']} 📊)"
            ratings_lines.append(line)
    ratings_text = "\n".join(ratings_lines) if ratings_lines else "No player ratings available."

    # Prompt Gemini with instruction to annotate the first mention only
    prompt = (
        f"You are a TV analyst for soccer channel FoxSportsGoon. You give exciting post-match recaps focusing on key match events.\n\n"
        f"Describe goals in detail.\n"
        f"Include who was the man of the match for the winning team.\n"
        f"Keep it short and exciting, as if you were presenting highlights on TV. Remeber to speak about the events in the past-tense and highlight shifts in momentum and drama."
        f"Refer to the timing of moments using phrases like 'in the 36th minute', 'just before halftime', 'early in the second half', etc.\n"
        f"Only annotate players the first time they are mentioned using this format: Name (Position, Grade 📊).\n"
        f"Don't repeat the annotations. Don't mention 'Grade:' or use rating scales like 8/10.\n\n"
        f"Match: {match_data['home_team']} vs {match_data['away_team']}\n"
        f"Score: {match_data['home_score']} - {match_data['away_score']}\n\n"
        f"Match Events:\n{events_text}\n\n"
        f"Referee: {match_data['referee']}\n"
        f"Referee-related events:\n{referee_events_text}\n\n"
        f"Player Grades (use this info to annotate players the FIRST time they are mentioned only):\n{ratings_text}\n\n"
    )

    return prompt

def call_gemini_api(prompt):
    import json  # make sure this is imported at the top
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GEMINI_API_KEY,
    }
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    response = requests.post(GEMINI_API_URL, headers=headers, json=body)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Gemini API error {response.status_code}: {response.text}\n")
        return "[Failed to generate summary.]"

    try:
        data = response.json()
        sys.stderr.write(f"Gemini API response JSON:\n{json.dumps(data, indent=2)}\n")
        
        # ✅ Correct way to extract the summary
        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        sys.stderr.write(f"⚠️ Failed to parse Gemini API response: {e}\n")
        return "[Failed to generate summary.]"

import re

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

import re

def get_latest_game_ids_from_league(url):
    from bs4 import BeautifulSoup
    import re

    with requests.Session() as session:
        page = session.get(url)
        if page.status_code != 200:
            sys.stderr.write(f"⚠️ Failed to fetch league table: {page.status_code}\n")
            return []

        soup = BeautifulSoup(page.text, "html.parser")
        game_links = soup.select('a[href*="gameDetails.aspx?GameID="]')
        
        matches = []
        for link in game_links:
            game_id_match = re.search(r"GameID=(\d+)", link["href"])
            if game_id_match:
                game_id = game_id_match.group(1)
                # Get the text content from the row that contains this link
                row = link.find_parent("tr")
                if not row:
                    continue
                cells = row.find_all("td")
                if len(cells) >= 3:
                    home = cells[1].text.strip()
                    away = cells[3].text.strip()
                    matches.append({
                        "home_team": home,
                        "away_team": away,
                        "game_id": game_id
                    })

        return matches

def scrape_and_summarize_by_game_id(game_id):
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    match_url = f"https://www.xperteleven.com/gameDetails.aspx?GameID={game_id}&dh=2"

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
        return call_gemini_api(prompt)

def get_match_summary_and_grades(game_id):
    login_url = "https://www.xperteleven.com/front_new3.aspx"
    match_url = f"https://www.xperteleven.com/gameDetails.aspx?GameID={game_id}&dh=2"

    with requests.Session() as session:
        login_page = session.get(login_url)
        login_soup = BeautifulSoup(login_page.text, "html.parser")
        try:
            viewstate = login_soup.find("input", {"id": "__VIEWSTATE"})["value"]
            viewstategen = login_soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
            eventvalidation = login_soup.find("input", {"id": "__EVENTVALIDATION"})["value"]
        except Exception:
            sys.stderr.write("⚠️ Could not find login form hidden fields.\n")
            return "[Login form fields missing.]", []

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
            return "[Login failed.]", []

        match_html = scrape_match_html(session, match_url)
        if not match_html:
            return "[Failed to retrieve match page.]", []

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
        return summary, player_grades, match_data

def scrape_league_standings(league_url):
    # Download the HTML from the URL
    response = requests.get(league_url)
    if response.status_code != 200:
        raise Exception(f"Failed to load standings page: {response.status_code}")

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

print(f"\n🛠️ DEBUG: Raw table has {len(rows)} rows")

for idx, row in enumerate(rows):
    cols = row.find_all("td")
    print(f"Row {idx + 1}: {len(cols)} columns")

    standings_table = soup.find("table", id="ctl00_cphMain_dgStandings")
    if not standings_table:
        raise ValueError("Standings table not found.")

    rows = standings_table.find_all("tr")[1:]  # skip header
    standings = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 10:
            continue

        try:
            place = cols[0].text.strip()
            team_link = cols[2].find("a")
            team_name = team_link.text.strip() if team_link else "Unknown"
            games_played = cols[3].text.strip()
            wins = cols[4].text.strip()
            draws = cols[5].text.strip()
            losses = cols[6].text.strip()
            goals_for_against = cols[7].text.strip()
            goal_diff = cols[8].text.strip()
            points = cols[9].text.strip()

            standings.append({
                "place": int(place),
                "team": team_name,
                "games": int(games_played),
                "wins": int(wins),
                "draws": int(draws),
                "losses": int(losses),
                "gf_ga": goals_for_against,
                "gd": int(goal_diff),
                "points": int(points),
            })
        except Exception as e:
            print(f"Skipping row due to error: {e}")
            continue

        print(f"\n✅ Total parsed teams: {len(standings)}")
        for team in standings:
            print(f"- {team['team']} ({team['points']} pts)")

        return standings

def summarize_league(league_url):
    send_groupme_message("Working on your recap... 📝")
    matches = get_latest_game_ids_from_league(league_url)
    if not matches:
        return "[Could not find recent matches in this league.]"

    recent_summaries = []
    all_players = []

    for m in matches:
        try:
            summary, players = get_match_summary_and_grades(m["game_id"])
            recent_summaries.append({
                "home": m["home_team"],
                "away": m["away_team"],
                "summary": summary
            })
            all_players.extend(players)
        except Exception as e:
            sys.stderr.write(f"⚠️ Failed to process game {m['game_id']}: {e}\n")

    # Sort players by grade and take top 3
    top_players = sorted([p for p in all_players if p["grade"]], key=lambda x: -x["grade"])[:3]

    # Extract standings
    standings = ague_standings(league_url)

    # Format prompt for Gemini
    return format_league_gemini_prompt(league_url, recent_summaries, top_players, standings)

def summarize_standings(standings):
    if len(standings) < 4:
        return "Not enough teams in the league to determine relegation or chase pack."

    leader = standings[0]
    leader_points = int(leader["points"])
    sixth_place_points = int(standings[5]["points"]) if len(standings) > 5 else 0

    chasing_teams = []
    relegation_threat = []

    for i, team in enumerate(standings[1:], start=1):  # skip leader
        points = int(team["points"])
        if points >= leader_points - 6:
            chasing_teams.append(team)
        if i >= 5 and points <= sixth_place_points + 4:
            relegation_threat.append(team)

    summary = f"🏆 Current leader: {leader['team']} with {leader['points']} points.\n"

    if chasing_teams:
        summary += "\n💥 Chasing pack:\n"
        for team in chasing_teams:
            summary += f"- {team['team']} ({team['points']} pts)\n"

    summary += "\n⚠️ Relegation danger zone:\n"
    if len(standings) >= 4:
        summary += f"- 7th: {standings[6]['team']} ({standings[7]['points']} pts)\n"
        summary += f"- 6th: {standings[5]['team']} ({standings[6]['points']} pts)\n"
    for team in relegation_threat:
        if team not in standings[4:6]:  # avoid repeating 6th/7th
            summary += f"- {team['team']} ({team['points']} pts)\n"

    return summary.strip()

def normalize(text):
    return unidecode.unidecode(text.strip().lower())

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

    text_lower = text.lower()

    # 🟢 1. Handle League Recap Requests
    if "fsgbot" in text_lower and any(k in text_lower for k in ["recap", "update"]):
        if "goondesliga" in text_lower:
            league_url = GOONDESLIGA_URL
            send_groupme_message("Working on your Goondesliga recap... 📝")
            matches = get_latest_game_ids_from_league(league_url)
        elif "spoondesliga" in text_lower:
            league_url = SPOONDESLIGA_URL
            send_groupme_message("Working on your Spoondesliga recap... 📝")
            matches = get_latest_game_ids_from_league(league_url)
        else:
            send_groupme_message("Please specify which league you want a recap of (Goondesliga or Spoondesliga).")
            return "ok", 200

        if not matches:
            send_groupme_message("Sorry, I couldn't find any recent matches in that league.")
            return "ok", 200

        session = get_logged_in_session()
        if not session:
            send_groupme_message("⚠️ Failed to log in to Xpert Eleven to fetch match data.")
            return "ok", 200

        match_scores = []
        top_players = []

        for match in matches:
            match_html = scrape_match_html(session, f"https://www.xperteleven.com/gameDetails.aspx?GameID={match['game_id']}&dh=2")
            if not match_html:
                sys.stderr.write(f"⚠️ Failed to retrieve match page for game {match['game_id']}\n")
                continue  # skip this match

            soup = BeautifulSoup(match_html, "html.parser")
            match_data = parse_match_data(soup)
            player_grades = parse_player_grades(soup)

            score_line = f"{match_data['home_team']} {match_data['home_score']}-{match_data['away_score']} {match_data['away_team']}"
            match_scores.append(score_line)

            rated_players = [p for p in player_grades if p["grade"] is not None]
            if rated_players:
                top_player = sorted(rated_players, key=lambda x: -x["grade"])[0]
                top_players.append(f"{top_player['name']} ({top_player['position']}, {top_player['grade']} 📊)")

        standings = ague_standings(league_url)
        standings_summary = summarize_standings(standings)

        final_message = (
            f"📋 **{text.strip()}**\n\n"
            f"⚽ **Match Results:**\n" + "\n".join(match_scores) + "\n\n"
            f"📊 Top performers:\n" + "\n".join(f"- {p}" for p in top_players[:3]) + "\n\n"
            f"📈 **Standings Update:**\n{standings_summary}"
        )

        send_groupme_message(final_message[:1500])
        return "ok", 200

    # 🟠 2. Handle Specific Team Match Recap
    if "fsgbot" in text_lower and any(k in text_lower for k in ["highlight", "recap"]):
        team_query = normalize(text)

        league_urls = [
            GOONDESLIGA_URL,
            SPOONDESLIGA_URL
        ]

        for league_url in league_urls:
            if not league_url:
                continue

            matches = get_latest_game_ids_from_league(league_url)
            for match in matches:
                if normalize(match["home_team"]) in team_query or normalize(match["away_team"]) in team_query:
                    summary = scrape_and_summarize_by_game_id(match["game_id"])
                    send_groupme_message(summary)
                    return "ok", 200

    # 🔴 Fallback
    send_groupme_message("Sorry, I couldn’t find a recent match for any team in your message.")
    return "ok", 200
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
