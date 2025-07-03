from flask import Flask, request
import os
import requests
import json
import re
from bs4 import BeautifulSoup

app = Flask(__name__)

GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")
X11_USERNAME = os.environ.get("X11_USERNAME")
X11_PASSWORD = os.environ.get("X11_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

session = requests.Session()

# Send message to GroupMe
def send_groupme_message(text):
    requests.post("https://api.groupme.com/v3/bots/post", json={"bot_id": GROUPME_BOT_ID, "text": text})

# Extract metadata: venue, referee, league
def get_match_metadata(soup):
    venue = referee = league = "Unknown"
    try:
        bold_tags = soup.find_all("b")
        for b in bold_tags:
            label = b.get_text(strip=True).lower()
            if label == "venue:":
                venue = b.find_next("td").get_text(strip=True)
            elif label == "referee:":
                referee = b.find_next("td").get_text(strip=True)
            elif label == "league:":
                league_link = b.find_next("td").find("a")
                league = league_link.get_text(strip=True) if league_link else "Unknown"
    except Exception:
        pass
    return venue, referee, league

# Scrape and summarize match

def scrape_match_summary():
    login_page = session.get("https://www.xperteleven.com/?lid=0", headers=HEADERS)
    soup = BeautifulSoup(login_page.text, "html.parser")

    viewstate = soup.find("input", {"name": "__VIEWSTATE"})
    eventvalidation = soup.find("input", {"name": "__EVENTVALIDATION"})

    payload = {
        "__VIEWSTATE": viewstate["value"] if viewstate else "",
        "__EVENTVALIDATION": eventvalidation["value"] if eventvalidation else "",
        "ctl00$ContentPlaceHolder1$txtUser": X11_USERNAME,
        "ctl00$ContentPlaceHolder1$txtPassword": X11_PASSWORD,
        "ctl00$ContentPlaceHolder1$btnLogin": "Login"
    }

    session.post("https://www.xperteleven.com/?lid=0", data=payload, headers=HEADERS)

    match_page = session.get("https://www.xperteleven.com/match.aspx?mid=LATEST", headers=HEADERS)
    soup = BeautifulSoup(match_page.text, "html.parser")

    event_rows = soup.find_all("tr", class_="ItemStyle2")
    event_lines = []
    for row in event_rows:
        minute_tag = row.find("span", id=re.compile(".*lblEventTime"))
        desc_tag = row.find("span", id=re.compile(".*lblEventDesc"))
        if minute_tag and desc_tag:
            minute = minute_tag.text.strip()
            desc = desc_tag.get_text(" ", strip=True)
            event_lines.append(f"{minute}' - {desc}")

    final_score_tag = soup.find("span", string=re.compile(r"\d+\s*-\s*\d+"))
    final_score = final_score_tag.text.strip() if final_score_tag else "Unknown"

    team_imgs = soup.find_all("img", src=re.compile("suits/shirts"))
    home_team_name = away_team_name = "Unknown"
    if len(team_imgs) >= 2:
        try:
            home_team_name = team_imgs[0].find_previous("a").text.strip()
            away_team_name = team_imgs[1].find_previous("a").text.strip()
        except:
            pass

    venue, referee, league = get_match_metadata(soup)

    possession = "Unknown"
    chances = "Unknown"
    try:
        possession = soup.find("span", id="ctl00_cphMain_lblPoss").text.strip()
        chances = soup.find("span", id="ctl00_cphMain_lblChance").text.strip()
    except:
        pass

    motm_home = motm_away = "Unknown"
    try:
        motm_home = soup.find("a", id="ctl00_cphMain_hplBestHome").text.strip()
        motm_away = soup.find("a", id="ctl00_cphMain_hplBestAway").text.strip()
    except:
        pass

    match_summary = (
        f"Match: {home_team_name} vs {away_team_name}\n"
        f"Final Score: {final_score}\n"
        f"Venue: {venue}\n"
        f"Referee: {referee}\n"
        f"League: {league}\n\n"
        f"--- Match Events ---\n" + "\n".join(event_lines) +
        f"\n\n--- Match Stats ---\nPossession: {possession}\nChances: {chances}\n\n"
        f"--- Man of the Match ---\n{home_team_name}: {motm_home}\n{away_team_name}: {motm_away}"
    )

    return match_summary

# Gemini call
def summarize_with_gemini(prompt):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}"
    }
    data = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }
    res = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(data))
    try:
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return "Error: Gemini response malformed."

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Webhook data received:", data)

    if data.get("name") != "FSGBot" and "last match" in data.get("text", "").lower():
        try:
            summary = scrape_match_summary()
            ai_response = summarize_with_gemini(summary)
            send_groupme_message(ai_response)
        except Exception as e:
            print("❌ Scraper error:", e)
            send_groupme_message("Alright folks, we're experiencing some technical difficulties with our Xpert Eleven feed, so no detailed match summary is available at the moment. Stay tuned to FoxSportsGoon for updates!")

    return "OK", 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
