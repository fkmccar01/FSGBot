
import re
import unicodedata
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

bot_aliases = ["@taycan a. schitt", "@taycan a schitt", "@taycan", "@taycan a", "@taycan a."]

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

with open("profiles.json", "r") as f:
    profiles = json.load(f)

def normalize(text):
    """Lowercases, removes accents, and strips special characters for reliable comparison."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ASCII', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-z0-9 ]+', '', text.lower())
    return text

def build_team_name_mapping(profiles):
    mapping = {}
    for profile in profiles.values():
        team = profile.get("team")
        aliases = profile.get("team_alias", [])
        if team:
            mapping[normalize(team.lower())] = team
            for alias in aliases:
                mapping[normalize(alias.lower())] = team
    return mapping

team_mapping = build_team_name_mapping(profiles)

def resolve_team_name(text, team_mapping):
    text = text.strip().lower()
    for alias, official_name in team_mapping.items():
        if alias in normalize(text):
            return official_name
    return None

def send_groupme_message(text):
    url = "https://api.groupme.com/v3/bots/post"
    
    # ✅ Enforce 1000 character limit
    if len(text) > 1000:
        text = text[:997] + "..."

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
        f"You are Taycan A. Schitt, a studio TV analyst for soccer channel FoxSportsGoon. You give exciting post-match recaps focusing on key match events.\n\n"
        f"Talk in a slight african american accent.\n"
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

def parse_player_grades(soup, home_team_name, away_team_name):
    players = []
    # Home team players
    home_rows = soup.select('#ctl00_cphMain_dgHomeLineUp tr.ItemStyle, #ctl00_cphMain_dgHomeLineUp tr.AlternatingItemStyle')
    for row in home_rows:
        pos_tag = row.find("span", id=lambda x: x and "lblHomepos" in x)
        name_tag = row.find("a", id=lambda x: x and "hplHomePlayerName" in x)
        if name_tag and pos_tag:
            title = name_tag.get("title", "")
            match = re.search(r"Grade:\s*(\d+)", title)
            grade = int(match.group(1)) if match else None
            players.append({
                "team": home_team_name,
                "position": pos_tag.text.strip(),
                "name": name_tag.text.strip(),
                "grade": grade
            })

    # Away team players
    away_rows = soup.select('#ctl00_cphMain_dgAwayLineUp tr.ItemStyle, #ctl00_cphMain_dgAwayLineUp tr.AlternatingItemStyle')
    for row in away_rows:
        pos_tag = row.find("span", id=lambda x: x and "lblAwaypos" in x)
        name_tag = row.find("a", id=lambda x: x and "hplAwayPlayerName" in x)
        if name_tag and pos_tag:
            title = name_tag.get("title", "")
            match = re.search(r"Grade:\s*(\d+)", title)
            grade = int(match.group(1)) if match else None
            players.append({
                "team": away_team_name,
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
        
        # FIXED: Parse match_data first before player grades
        match_data = parse_match_data(soup)
        player_grades = parse_player_grades(soup, match_data["home_team"], match_data["away_team"])
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

        # FIXED: Parse match_data before player_grades
        match_data = parse_match_data(soup)
        player_grades = parse_player_grades(soup, match_data["home_team"], match_data["away_team"])
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

import sys  # Make sure this is imported at the top

def scrape_league_standings_with_login(session, league_url):
    response = session.get(league_url)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Failed to fetch league table with login: {response.status_code}\n")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    standings_table = soup.find("table", id="ctl00_cphMain_dgStandings")
    if not standings_table:
        sys.stderr.write("⚠️ Standings table not found in logged-in page.\n")
        return []

    rows = standings_table.find_all("tr")[1:]  # Skip header row
    standings = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 12:  # adjust if your table has 12+ columns
            continue
        # Debug print all columns for this row
        sys.stderr.write(f"STANDINGS ROW COLS: {[col.text.strip() for col in cols]}\n")
        try:
            place = int(cols[0].text.strip().strip("."))
            team_link = cols[2].find("a")
            team_name = team_link.text.strip() if team_link else cols[2].text.strip()
            
            wins = int(cols[6].text.strip())
            draws = int(cols[7].text.strip())
            losses = int(cols[8].text.strip())
            
            gf_ga = cols[9].text.strip()  # e.g. "9 - 5"
            gf, ga = [int(x.strip()) for x in gf_ga.split("-")]
            
            diff_text = cols[10].text.strip().replace("+", "")
            diff = int(diff_text)
            
            points = int(cols[11].text.strip())
            
            standings.append({
                "place": place,
                "team": team_name,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "gf": gf,
                "ga": ga,
                "diff": diff,
                "points": points
            })

        except Exception as e:
            sys.stderr.write(f"⚠️ Error parsing standings row: {e}\n")
            continue

    return standings

def generate_standings_summary(standings, league_name):
    if not standings:
        return "Standings data is missing."

    # Sort by points (desc), then goal diff (desc), then name
    standings = sorted(standings, key=lambda x: (-x["points"], -x["diff"], x["team"]))
    summary = ""

    # 🏆 True leader based on tiebreakers
    leader = standings[0]
    summary += f"🏆 {leader['team']} lead the league with {leader['points']} points.\n\n"

    # ⚔️ In the Hunt: teams within 4 points of leader, excluding leader
    hunt_pack = []
    for team in standings[1:]:
        if leader["points"] - team["points"] <= 4:
            hunt_pack.append(f"{team['team']} ({team['points']} pts)")

    if hunt_pack:
        summary += f"⚔️ In the Hunt: {', '.join(hunt_pack)}\n"

    # 📉 Relegation / 🪨 Rock Bottom Watch
    if "goondesliga" in league_name.lower():
        bottom_watch_label = "📉 Relegation watch"
    else:
        bottom_watch_label = "🪨 Rock Bottom Watch"
    relegation = []
    if len(standings) >= 6:
        sixth_place_points = standings[5]["points"]
        for team in standings[5:]:
            if team["points"] <= sixth_place_points + 4:
                relegation.append(f"{team['team']} ({team['points']} pts)")
    if relegation:
        summary += f"\n{bottom_watch_label}: {', '.join(relegation)}"

    return summary.strip()

def scrape_upcoming_fixtures_from_standings_page(session, url):
    """Scrapes upcoming fixtures from the same page as standings."""
    response = session.get(url)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Failed to fetch standings + fixtures page: {response.status_code}\n")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    fixtures = []
    rows = soup.select("#ctl00_cphMain_dgUpcoming tr")
    for row in rows:
        onclick = row.get("onclick", "")
        match = re.search(r"GameID=(\d+)", onclick)
        if not match:
            continue
        game_id = match.group(1)
        tds = row.find_all("td")
        if len(tds) >= 4:
            home = tds[1].get_text(strip=True)
            away = tds[3].get_text(strip=True)
            fixtures.append({
                "home_team": home,
                "away_team": away,
                "game_id": game_id
            })
    return fixtures

def generate_tv_schedule_from_upcoming(goon_fixtures, spoon_fixtures, goon_standings, spoon_standings):
    channels = ["FSG", "FSG2", "FSG3", "FSG+", "FSG Radio 📻", "FSG Kids 🧸"]
    points_map = {normalize(team["team"]): team["points"] for team in goon_standings + spoon_standings}
    all_matches = []
    for match in goon_fixtures + spoon_fixtures:
        home = normalize(match["home_team"])
        away = normalize(match["away_team"])
        home_points = points_map.get(home, 0)
        away_points = points_map.get(away, 0)
        combined = home_points + away_points
        all_matches.append({
            "match": f"{match['home_team']} vs {match['away_team']}",
            "combined_points": combined,
            "division": "Goondesliga" if match in goon_fixtures else "Spoondesliga"
        })
    sorted_matches = sorted(all_matches, key=lambda x: -x["combined_points"])
    if not sorted_matches:
        return "⚠️ No upcoming matches found."
    marquee = next((m for m in sorted_matches if m["division"] == "Goondesliga"), None)
    
    output = ["📺 FoxSportsGoon TV Kzhedule ⚽\n"]
    if marquee:
        output.append("🌟FSG Marquee Matchup🌟")
        output.append(marquee["match"])
        output.append("")  # blank line
    
    used = {marquee["match"]} if marquee else set()
    i = 1
    for match in sorted_matches:
        if match["match"] in used or i >= len(channels):
            continue
        output.append(channels[i])
        output.append(match["match"])
        output.append("")  # blank line
        i += 1
    return "\n".join(output)

def get_last_match_for_team(team_name, league_urls):
    """
    Given a normalized team_name and list of league URLs,
    returns the most recent match dict with keys home_team, away_team, game_id.
    """
    normalized_team = normalize(team_name)
    for league_url in league_urls:
        matches = get_latest_game_ids_from_league(league_url)
        # Find matches where this team was involved, assume matches are sorted most recent first
        for match in matches:
            if normalize(match["home_team"]) == normalized_team or normalize(match["away_team"]) == normalized_team:
                return match
    return None

def find_team_standing(team_name, standings):
    normalized_team = normalize(team_name)
    # First try to resolve the normalized name to the official team name using your alias mapping
    official_name = resolve_team_name(normalized_team, team_mapping)
    if not official_name:
        official_name = team_name  # fallback to original if no alias mapping
    
    normalized_official = normalize(official_name)
    
    for entry in standings:
        if normalize(entry["team"]) == normalized_official:
            return entry
    return None

def format_gemini_match_preview_prompt(team1_standings, team2_standings, team1_last_match, team2_last_match):
    prompt = (
        f"You are Taycan A. Schitt, a studio TV analyst for FoxSportsGoon. You provide exciting, insightful **match previews** for upcoming soccer games.\n\n"
        f"Talk in a slight African American accent.\n"
        f"ALWAYS keep your previews between 990-1000 characters. NEVER go above 1000.\n"
        f"Use the current league standings (place, wins, draws, losses, goals for, goals against, goal difference, and points) as context for your analysis.\n"
        f"Include recent form based on the last match result and key player performances.\n"
        f"Make predictions and build excitement for the upcoming game.\n"
        f"Use full player names and their performance rating in the format (position, grade 📊) the first time they are mentioned when relevant.\n.\n"
        f"Keep it engaging as a TV preview.\n\n"
        f"If a team has no recent match, they had a bye round, just use standings in your analysis for them.\n\n"
    )

    # Team 1 info
    prompt += (
        f"Team 1: {team1_standings['team']}\n"
        f"Place: {team1_standings['place']}, W-D-L: {team1_standings['wins']}-{team1_standings['draws']}-{team1_standings['losses']}, "
        f"GF-GA-Diff: {team1_standings['gf']}-{team1_standings['ga']}-{team1_standings['diff']}, Points: {team1_standings['points']}\n"
    )
    if team1_last_match:
        prompt += (
            f"Last match result: {team1_last_match['match_data']['home_team']} "
            f"{team1_last_match['match_data']['home_score']}-{team1_last_match['match_data']['away_score']} "
            f"{team1_last_match['match_data']['away_team']}\n"
            f"Key players and ratings:\n"
        )
        for p in team1_last_match['player_grades']:
            prompt += f"- {p['name']} ({p['position']}, {p['grade']} 📊)\n"

    # Team 2 info
    prompt += (
        f"\nTeam 2: {team2_standings['team']}\n"
        f"Place: {team2_standings['place']}, W-D-L: {team2_standings['wins']}-{team2_standings['draws']}-{team2_standings['losses']}, "
        f"GF-GA-Diff: {team2_standings['gf']}-{team2_standings['ga']}-{team2_standings['diff']}, Points: {team2_standings['points']}\n"
    )
    if team2_last_match:
        prompt += (
            f"Last match result: {team2_last_match['match_data']['home_team']} "
            f"{team2_last_match['match_data']['home_score']}-{team2_last_match['match_data']['away_score']} "
            f"{team2_last_match['match_data']['away_team']}\n"
            f"Key players and ratings:\n"
        )
        for p in team2_last_match['player_grades']:
            prompt += f"- {p['name']} ({p['position']}, {p['grade']} 📊)\n"

    prompt += "\nGenerate a lively and insightful match preview considering the above.\n"
    return prompt.strip()

def filter_players_for_team(player_grades, team_name):
    return [p for p in player_grades if p['team'] == team_name]

def generate_match_preview(session, upcoming_match, goon_standings, spoon_standings):
    """
    session: logged-in requests.Session()
    upcoming_match: dict with home_team, away_team, game_id
    goon_standings/spoon_standings: lists of dicts from standings scraping
    """

    # Find standings for each team in either league
    all_standings = goon_standings + spoon_standings
    home_standings = find_team_standing(upcoming_match["home_team"], all_standings)
    away_standings = find_team_standing(upcoming_match["away_team"], all_standings)

    league_urls = [GOONDESLIGA_URL, SPOONDESLIGA_URL]

    # Get last match for each team
    home_last_match = get_last_match_for_team(upcoming_match["home_team"], league_urls)
    away_last_match = get_last_match_for_team(upcoming_match["away_team"], league_urls)

    # If neither team has a last match, abort
    if not home_last_match and not away_last_match:
        return "Sorry, couldn't find any recent match info for either team."

    team1_last_match = None
    team2_last_match = None

    # Get last match details for home team
    if home_last_match:
        summary_home, player_grades_home_all, match_data_home = get_match_summary_and_grades(home_last_match["game_id"])
        team1_name = home_standings['team']
        team1_player_grades = filter_players_for_team(player_grades_home_all, team1_name)
        team1_last_match = {
            "match_data": match_data_home,
            "player_grades": team1_player_grades
        }

    # Get last match details for away team
    if away_last_match:
        summary_away, player_grades_away_all, match_data_away = get_match_summary_and_grades(away_last_match["game_id"])
        team2_name = away_standings['team']
        team2_player_grades = filter_players_for_team(player_grades_away_all, team2_name)
        team2_last_match = {
            "match_data": match_data_away,
            "player_grades": team2_player_grades
        }

    # Format prompt — this function must be okay with one or both last_match dicts being None
    prompt = format_gemini_match_preview_prompt(home_standings, away_standings, team1_last_match, team2_last_match)

    # Call Gemini
    preview_text = call_gemini_api(prompt)
    return preview_text

def scrape_league_stat_category(session, league_id, lnr, category, top_n=5):
    sel_map = {
        "goals": "S",
        "assists": "A",
        "points": "P",
        "x11": "X"
    }

    sel = sel_map.get(category)
    if not sel:
        return []
    
    url = f"https://www.xperteleven.com/stats.aspx?Lid={league_id}&Sel={sel}&Lnr={lnr}&Period=S&dh=2"
    response = session.get(url)
    if response.status_code != 200:
        sys.stderr.write(f"⚠️ Failed to fetch {category} stats: {response.status_code}\n")
        return []
    
    sys.stderr.write(f"DEBUG: URL fetched: {url}\n")
    sys.stderr.write(f"DEBUG: Page snippet:\n{response.text[:1000]}\n")  # print first 1000 chars
    
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", id="ctl00_cphMain_dgStats")
    if not table:
        sys.stderr.write(f"⚠️ Could not find stats table for category: {category} at Lnr={lnr}\n")
        return []

    rows = table.find_all("tr")
    players = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
        name = cols[1].get_text(strip=True)
        pos = cols[2].get_text(strip=True)
        team = cols[3].get_text(strip=True)
        value_text = cols[4].get_text(strip=True)

        m = re.match(r"(\d+)", value_text)
        if not m:
            continue
        value_num = int(m.group(1))
    
        players.append({
            "player": name,
            "position": pos,
            "team": team,
            "value_text": value_text,
            "value_num": value_num
        })
    
        players_sorted = sorted(players, key=lambda x: x["value_num"], reverse=True)
        top_players = []

    for p in players_sorted[:top_n]:
        top_players.append(f"{p['player']}, {p['position']}, {p['team']} - {p['value_text']}")

    return top_players

@app.route("/tv", methods=["POST"])
def manual_tv_schedule():
    session = get_logged_in_session()
    if not session:
        send_groupme_message("⚠️ Couldn't log in to X11")
        return "ok", 200

    goon_standings = scrape_league_standings_with_login(session, GOONDESLIGA_URL)
    spoon_standings = scrape_league_standings_with_login(session, SPOONDESLIGA_URL)
    goon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, GOONDESLIGA_URL)
    spoon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, SPOONDESLIGA_URL)

    tv_schedule = generate_tv_schedule_from_upcoming(
        goon_fixtures, spoon_fixtures,
        goon_standings, spoon_standings
    )

    send_groupme_message(tv_schedule)
    return "ok", 200

@app.route("/", methods=["GET"])
def index():
    return "Taycan A. Schitt is alive!"

@app.route("/webhook", methods=["POST"])
def groupme_webhook():
    data = request.get_json()
    sys.stderr.write(f"Webhook data received: {data}\n")

    session = requests.Session()

    if not data:
        return "No data received", 400

    text = data.get("text", "")
    text_lower = text.lower()
    sender_type = data.get("sender_type", "")

    if sender_type == "bot":
        return "Ignoring bot message"

    # 🟢 1. Handle League Recap Requests
    if any(bot_name in text_lower for bot_name in bot_aliases) and any(k in text_lower for k in ["recap", "update"]) and ("goondesliga" in text_lower or "spoondesliga" in text_lower):
        if "goondesliga" in text_lower:
            league_url = GOONDESLIGA_URL
            send_groupme_message("Alright y'all! Taycan A. giving you an update on the Goondesliga...")
        elif "spoondesliga" in text_lower:
            league_url = SPOONDESLIGA_URL
            send_groupme_message("Alright y'all! Taycan A. giving you an update on the Spoondesliga...")
        else:
            send_groupme_message("Please specify which league you want a recap of (Goondesliga or Spoondesliga).")
            return "ok", 200

        matches = get_latest_game_ids_from_league(league_url)
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
                continue

            soup = BeautifulSoup(match_html, "html.parser")
            match_data = parse_match_data(soup)
            player_grades = parse_player_grades(soup, match_data["home_team"], match_data["away_team"])

            score_line = f"{match_data['home_team']} {match_data['home_score']}-{match_data['away_score']} {match_data['away_team']}"
            match_scores.append(score_line)

            rated_players = [p for p in player_grades if p["grade"] is not None]
            if rated_players:
                top_player = sorted(rated_players, key=lambda x: -x["grade"])[0]
                top_players.append(f"{top_player['name']} ({top_player['position']}, {top_player['grade']} 📊, {top_player['team']})")

        # Use the logged-in session to scrape standings
        standings = scrape_league_standings_with_login(session, league_url)

        league_name = "The Goondesliga 🏆" if "goondesliga" in text_lower else "The Spoondesliga 🥄"

        try:
            standings_summary = generate_standings_summary(standings, league_name)
        except Exception as e:
            sys.stderr.write(f"⚠️ Error parsing standings: {e}\n")
            standings_summary = "Standings data is missing."

        final_message = (
            f"{league_name}\n\n"
            f"⚽ Match Results:\n" + "\n".join(match_scores) + "\n\n"
            f"📊 Top Performers:\n" + "\n".join(f"- {p}" for p in top_players[:3]) + "\n\n"
            f"📈 Standings Update:\n{standings_summary}"
        )

        send_groupme_message(final_message[:1500])
        return "ok", 200

    # 🟠 2. Handle Specific Team Match Recap
    if any(bot_name in text_lower for bot_name in bot_aliases) and any(k in text_lower for k in ["highlight", "recap"]):
        resolved_team = resolve_team_name(text, team_mapping)
        if not resolved_team:
            return "ok", 200  # No team match, ignore

        league_urls = [GOONDESLIGA_URL, SPOONDESLIGA_URL]

        for league_url in league_urls:
            matches = get_latest_game_ids_from_league(league_url)
            for match in matches:
                if normalize(match["home_team"]) == normalize(resolved_team) or normalize(match["away_team"]) == normalize(resolved_team):
                    summary = scrape_and_summarize_by_game_id(match["game_id"])
                    send_groupme_message(summary)
                    return "ok", 200

    # 🟣 3. Handle TV Schedule Requests
    if any(bot_name in text_lower for bot_name in bot_aliases):
        if ("fsg" in text_lower or "tv" in text_lower) and any(
            kw in text_lower for kw in ["tv", "on", "kzhedule", "schedule", "guide", "games"]
        ):
            sys.stderr.write("✅ Triggered TV schedule command.\n")
            send_groupme_message("Ay y'all! Here's what's coming up on FoxSportsGoon...")
            
            session = get_logged_in_session()
            if not session:
                send_groupme_message("⚠️ I couldn't log in to Xpert Eleven.")
                return "ok", 200

            goon_standings = scrape_league_standings_with_login(session, GOONDESLIGA_URL)
            spoon_standings = scrape_league_standings_with_login(session, SPOONDESLIGA_URL)
    
            # FIXED: Scrape fixtures fully
            goon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, GOONDESLIGA_URL)
            spoon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, SPOONDESLIGA_URL)
    
            # Generate and send TV schedule
            tv_schedule = generate_tv_schedule_from_upcoming(
                goon_fixtures, spoon_fixtures,
                goon_standings, spoon_standings
            )
            send_groupme_message(tv_schedule)
            return "ok", 200

    # 🟠 4. Handle Match Preview Requests
    if any(bot_name in text_lower for bot_name in bot_aliases) and "preview" in text_lower:
        # Extract team name from message (attempt)
        resolved_team = resolve_team_name(text, team_mapping)
        send_groupme_message("Preview? We talkin' 'bout previews? Jk y'all, let's get it...")
        if not resolved_team:
            send_groupme_message("Ay yo, who?? I ain't never heard of that team.")
            return "ok", 200
    
        session = get_logged_in_session()
        if not session:
            send_groupme_message("⚠️ Failed to log in to Xpert Eleven to fetch match data.")
            return "ok", 200
    
        # Get standings for both leagues
        goon_standings = scrape_league_standings_with_login(session, GOONDESLIGA_URL)
        spoon_standings = scrape_league_standings_with_login(session, SPOONDESLIGA_URL)
    
        # Find upcoming fixtures
        goon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, GOONDESLIGA_URL)
        spoon_fixtures = scrape_upcoming_fixtures_from_standings_page(session, SPOONDESLIGA_URL)
    
        # Look for upcoming match involving resolved_team
        upcoming_match = None
        for match in goon_fixtures + spoon_fixtures:
            if normalize(match["home_team"]) == normalize(resolved_team) or normalize(match["away_team"]) == normalize(resolved_team):
                upcoming_match = match
                break
    
        if not upcoming_match:
            send_groupme_message(f"Hold on now...stay off the taaaaaar! {resolved_team} has a bye.")
            return "ok", 200
    
        # Generate preview
        preview_text = generate_match_preview(session, upcoming_match, goon_standings, spoon_standings)
        send_groupme_message(preview_text[:1500])  # limit message size to 1500 chars
        return "ok", 200

    # 🟢 5. Handle League Leaders
    if any(bot_name in text_lower for bot_name in bot_aliases):
        if any(kw in text_lower for kw in ["golden boot", "goals", "top scorers", "assists", "points", "x11", "mvp", "league leaders"]):
            sys.stderr.write("✅ Triggered stat leaderboard command.\n")
            send_groupme_message("Yo these dudes ain't my 🐐 Dougie Maradonut but...")
    
            session = get_logged_in_session()
            if not session:
                send_groupme_message("⚠️ I couldn't log in to Xpert Eleven.")
                return "ok", 200
    
            # Determine league and Lnr
            if "spoon" in text_lower:
                league_name = "Spoondesliga"
                league_id = 460905
                lnr = 2
            else:
                league_name = "Goondesliga"
                league_id = 460905
                lnr = 1
    
            # Determine which stat category
            if "golden boot" in text_lower or "goals" in text_lower or "top scorers" in text_lower:
                category = "goals"
                title = "Golden Boot 👟"
            elif "assists" in text_lower:
                category = "assists"
                title = "Assists 🎩🪄"
            elif "points" in text_lower:
                category = "points"
                title = "Points 💎"
            elif "x11" in text_lower or "mvp" in text_lower:
                category = "x11"
                title = "MVP 🏅"
            else:
                category = None
    
            # If a specific stat category was requested
            if category:
                top_players = scrape_league_stat_category(session, league_id, lnr, category, top_n=5)
                if not top_players:
                    send_groupme_message(f"Couldn't fetch {title} leaderboard right now yo")
                    return "ok", 200
                else:
                    message = f"{title} Leaders ({league_name}):\n\n"
                    for i, player in enumerate(top_players, 1):
                        message += f"{i}. {player}\n"
                    send_groupme_message(message.strip())
                    return "ok", 200
    
            # General "league leaders" summary if no specific category
            leaderboard = {
                "Golden Boot 👟": scrape_league_stat_category(session, league_id, lnr, "goals", top_n=1),
                "Assists 🎩🪄": scrape_league_stat_category(session, league_id, lnr, "assists", top_n=1),
                "Points 💎": scrape_league_stat_category(session, league_id, lnr, "points", top_n=1),
                "MVP 🏅": scrape_league_stat_category(session, league_id, lnr, "x11", top_n=1)
            }

            message = f"{league_name} Leaders:\n\n"
            for label, players in leaderboard.items():
                if players:
                    message += f"{label}\n{players[0]}\n\n"
            send_groupme_message(message.strip())
            return "ok", 200
    
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
