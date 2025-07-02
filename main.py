# main.py

from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

def login(session):
    # GET login page to retrieve hidden form fields
    response = session.get(LOGIN_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    viewstate = soup.find('input', {'id': '__VIEWSTATE'})['value']
    viewstategenerator = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})['value']
    eventvalidation = soup.find('input', {'id': '__EVENTVALIDATION'})['value']
    
    payload = {
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstategenerator,
        "__EVENTVALIDATION": eventvalidation,
        "ctl00$cphMain$FrontControl$lwLogin$tbUsername": X11_USERNAME,
        "ctl00$cphMain$FrontControl$lwLogin$tbPassword": X11_PASSWORD,
        "ctl00$cphMain$FrontControl$lwLogin$btnLogin": "Login"
    }
    
    login_response = session.post(LOGIN_URL, data=payload)
    return login_response

@app.route('/scrape')
def scrape():
    with requests.Session() as session:
        login_response = login(session)
        
        if "logout" not in login_response.text.lower():
            return "Login failed. Check credentials."
        
        match_page = session.get(MATCH_URL)
        soup = BeautifulSoup(match_page.text, 'html.parser')
        
        events = soup.find_all("tr", class_="ItemStyle2")
        summary = []
        
        for event in events:
            try:
                minute = event.find("span", class_="brotext10").text.strip()
                desc = event.find("span", {"id": lambda x: x and "lblEventDesc" in x})
                if desc:
                    summary.append(f"{minute}': {desc.text.strip()}")
            except:
                continue
        
        match_text = "\n".join(summary)
        return ask_gemini(match_text)

def send_groupme_message(message):
    requests.post("https://api.groupme.com/v3/bots/post", json={
        "bot_id": GROUPME_BOT_ID,
        "text": message
    })

@app.route('/')
def home():
    return "FSGBot is running."

@app.route('/webhook', methods=['POST'])
def groupme_webhook():
    data = request.get_json()

    # Ignore bot's own messages
    if data['sender_type'] == "bot":
        return "ok", 200

    message_text = data.get("text", "").lower()

    if "fsgbot" in message_text and "last match" in message_text:
        summary = scrape_match_summary()
        send_groupme_message(summary)

    return "ok", 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
