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
        # Get login page to extract hidden fields
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
            sys.stderr.write("⚠️ Login failed. Response didn't include 'Logout'.\n")
            return "[Login to Xpert Eleven failed.]"

        # Fetch match page after login
        match_response = session.get(matches_url)
        html = match_response.text

        soup = BeautifulSoup(html, "html.parser")

        # Get league info (round, league name)
        round_info = soup.find("span", id="ctl00_cphMain_lblOmgang")
        round_text = round_info.get_text(strip=True) if round_info else "Unknown Round"

        league_link = soup.find("a", id="ctl00_cphMain_hplDivision")
        league_text = league_link.get_text(strip=True) if league_link else "Unknown League"

        # Get season info
        season_info = soup.find("span", id="ctl00_cphMain_lblSeason")
        season_text = season_info.get_text(strip=True) if season_info else "Unknown Season"

        # Get venue and date
        venue = soup.find("span", id="ctl00_cphMain_lblArena")
        venue_text = venue.get_text(strip=True) if venue else "Unknown Venue"

        match_date = soup.find("span", id="ctl00_cphMain_lblMatchDate")
        date_text = match_date.get_text(strip=True) if match_date else "Unknown Date"

        # Get referee
        referee = soup.find("span", id="ctl00_cphMain_lblReferee")
        referee_text = referee.get_text(strip=True) if referee else "Unknown Referee"

        # Scrape match events (rows with class ItemStyle or ItemStyle2)
        event_rows = soup.find_all("tr", class_=["ItemStyle", "ItemStyle2"])
        events = []
        for row in event_rows:
            cells = row.find_all("td")
            if len(cells) >= 3:
                minute = cells[0].get_text(strip=True)
                event = cells[1].get_text(strip=True)
                player = cells[2].get_text(strip=True)
                events.append(f"{minute} - {event}: {player}")

        events_text = "\n".join(events) if events else "[No events recorded.]"

        # Helper function to parse lineup table
        def parse_lineup(table_id_prefix):
            lineup = []
            idx = 3  # Starting index from your example (ctl03, ctl04, etc.)
            while True:
                pos_id = f"ctl00_cphMain_dg{table_id_prefix}LineUp_ctl{idx:02d}_lbl{table_id_prefix}pos"
                name_id = f"ctl00_cphMain_dg{table_id_prefix}LineUp_ctl{idx:02d}_hpl{table_id_prefix}PlayerName"

                pos_tag = soup.find("span", id=pos_id)
                name_tag = soup.find("a", id=name_id)
                if not pos_tag or not name_tag:
                    break

                position = pos_tag.get_text(strip=True)
                name = name_tag.get_text(strip=True)

                # Extract rating and special icons from the title attribute or nearby img tags
                title_text = name_tag.get("title", "")
                rating = "N/A"
                if "Grade:" in title_text:
                    try:
                        rating = title_text.split("Grade:")[1].split()[0]
                    except IndexError:
                        rating = "N/A"

                # Look for assist, goal, booked, injured icons (via img with title attribute inside same td)
                player_td = name_tag.parent
                icons = []
                for img in player_td.find_all("img"):
                    icons.append(img.get("title"))

                status = ", ".join(icons) if icons else ""

                lineup.append(f"{position} {name} (Rating: {rating}" + (f"; {status}" if status else "") + ")")
                idx += 1

            return lineup

        home_lineup = parse_lineup("Home")
        away_lineup = parse_lineup("Away")

        # Combine all info into a full match summary text for Gemini prompt
        summary = (
            f"Round: {round_text}\n"
            f"League: {league_text}\n"
            f"Season: {season_text}\n"
            f"Venue: {venue_text}\n"
            f"Date: {date_text}\n"
            f"Referee: {referee_text}\n\n"
            f"Home Lineup:\n" + "\n".join(home_lineup) + "\n\n"
            f"Away Lineup:\n" + "\n".join(away_lineup) + "\n\n"
            f"Match Events:\n{events_text}"
        )

        return summary


def generate_gemini_summary(match_data):
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    prompt = (
        "You are a studio analyst for soccer channel FoxSportsGoon. "
        "Summarize this soccer match like you are reporting the highlights to viewers, including lineups, player ratings, venue, league, referee, and match events:\n\n"
        + match_data
    )
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
