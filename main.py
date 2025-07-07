for row in rows:
    cols = row.find_all("td")
    if len(cols) < 10:
        continue
    try:
        place = int(cols[0].text.strip().strip("."))
        team_link = cols[2].find("a")
        team_name = team_link.text.strip() if team_link else cols[2].text.strip()

        played = int(cols[3].text.strip())
        wins = int(cols[4].text.strip())
        draws = int(cols[5].text.strip())
        losses = int(cols[6].text.strip())

        # GF and GA are combined in cols[7], e.g. "9 - 5"
        gf_ga_text = cols[7].text.strip()
        gf_str, ga_str = gf_ga_text.split("-")
        gf = int(gf_str.strip())
        ga = int(ga_str.strip())

        diff_text = cols[8].text.strip().replace("+", "")
        diff = int(diff_text)

        points = int(cols[9].text.strip())

        standings.append({
            "place": place,
            "team": team_name,
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "gf": gf,
            "ga": ga,
            "diff": diff,
            "points": points,
        })
    except Exception as e:
        sys.stderr.write(f"⚠️ Error parsing standings row: {e}\n")
        continue
