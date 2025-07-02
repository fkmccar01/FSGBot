from flask import Flask, request
import os
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# Load these from environment variables for security
XPERT_USERNAME = os.environ.get("XPERT_USERNAME")
XPERT_PASSWORD = os.environ.get("XPERT_PASSWORD")
GROUPME_BOT_ID = os.environ.get("GROUPME_BOT_ID")

LOGIN_URL = "https://www.xperteleven.com/front_new3.aspx"
MATCH_URL_TEMPLATE = "https://www.xperteleven.com/gameDetails.aspx?GameID=322737050&dh=2"  # you will update match_id dynamically

session = requests.Session()

def login_xpert():
    """Logs into Xpert Eleven and maintains the session cookies"""
    # First get the login page to grab any hidden inputs if needed
    r = session.get(LOGIN_URL)
    r.raise_for_status()

    # Prepare login payload - might need to adjust keys according to form fields
    login_data = {
        "ctl00$cphMain$txtUsername": XPERT_USERNAME,
        "ctl00$cphMain$txtPassword": XPERT_PASSWORD,
        "ctl00$cphMain$btnLogin": "Login",
        # You may need to add __VIEWSTATE, __EVENTVALIDATION, etc. from r.text if required by the site
    }

    # Use BeautifulSoup to grab hidden fields __VIEWSTATE etc.
    soup = BeautifulSoup(r.text, "html.parser")
    for hidden_input in soup.select("input[type=hidden]"):
        name = hidden_input.get("name")
        value = hidden_input.get("value", "")
        if name not in login_data:
            login_data[name] = value

    # Post login form
    post_resp = session.post(LOGIN_URL, data=login_data)
    post_resp.raise_for_status()

    # Check if login succeeded by presence of some known element in response (like "Lobby")
    if "Lobby" not in post_resp.text:
        raise Exception("Login failed - could not find 'Lobby' in response")

    return True

def scrape_match_events(match_html):
    """Scrapes match events from the match HTML, using updated <tr class='ItemStyle2'> parsing"""
    soup = BeautifulSoup(match_html, "html.parser")

    events = []
    for row in soup.find_all("tr", class_="ItemStyle2"):
        tds = row.find_all("td")
        if len(tds) < 4:
            continue

        # Event time
        event_time_span = tds[0].find("span")
        event_time = event_time_span.get_text(strip=True) if event_time_span else ""

        # Team shirt image url
        team_img = tds[1].find("img")
        team_img_url = team_img["src"] if team_img else ""

        # Score or icon
        score_cell = tds[2]
        score_text = score_cell.get_text(strip=True)
        score_img = score_cell.find("img")
        score_icon = score_img["src"] if score_img else None

        # Description text
        desc_span = tds[3].find("span")
        desc_text = desc_span.get_text(strip=True) if desc_span else ""

        event = {
            "time": event_time,
            "team_img_url": team_img_url,
            "score_text": score_text,
            "score_icon": score_icon,
            "description": desc_text,
        }
        events.append(event)

    return events

def format_match_summary(events):
    """Formats the scraped events into a plain text summary"""
    if not events:
        return "No match events were found."

    lines = []
    for e in events:
        # Build a simple string per event: "[time] score description"
        line = f"[{e['time']}] {e['score_text']} - {e['description']}"
        lines.append(line)

    return "\n".join(lines)

def get_last_match_id():
    """Stub function to get the last match id for the logged-in user
    
    You should implement this according to your league setup or scrape the correct match ID.
    For now, I’ll just hardcode a sample ID for demonstration.
    """
    return "1234567"  # Replace with actual logic or config

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook data received:", data)

    if "text" not in data:
        return "No text in webhook", 400

    text = data["text"].strip()

    if text.lower().startswith("fsgbot tell me about the last match"):
        try:
            # Login
            login_xpert()
            # Get last match id
            match_id = get_last_match_id()

            # Fetch match page
            match_url = MATCH_URL_TEMPLATE.format(match_id=match_id)
            match_resp = session.get(match_url)
            match_resp.raise_for_status()

            # Scrape events
            events = scrape_match_events(match_resp.text)
            summary = format_match_summary(events)

        except Exception as e:
            print("Error during match scraping:", e)
            summary = ("Alright folks, we're experiencing some technical difficulties with "
                       "our Xpert Eleven feed, so no detailed match summary is available at the moment. "
                       "Stay tuned to FoxSportsGoon for updates!")

        # Send message back to GroupMe
        send_groupme_message(summary)
        return "", 200

    # Ignore other messages
    return "", 200

def send_groupme_message(message):
    """Send a message back to GroupMe using the bot ID"""
    bot_id = GROUPME_BOT_ID
    if not bot_id:
        print("GROUPME_BOT_ID not set!")
        return

    post_url = "https://api.groupme.com/v3/bots/post"
    payload = {
        "bot_id": bot_id,
        "text": message
    }

    resp = requests.post(post_url, json=payload)
    if resp.status_code != 202:
        print("Failed to send message to GroupMe:", resp.status_code, resp.text)
    else:
        print("Message sent to GroupMe successfully.")

@app.route("/")
def home():
    return "FSGBot is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
