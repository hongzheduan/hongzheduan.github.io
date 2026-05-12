import requests
from bs4 import BeautifulSoup

# Browser headers
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# Function to scrape symbols
def get_symbols(url):
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Failed to retrieve {url}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")

    symbols = []

    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")

        if len(cols) > 2:
            symbol = cols[2].text.strip()
            symbols.append(symbol)

    return symbols


# URLs
sp500_url = "https://www.slickcharts.com/sp500"
nasdaq100_url = "https://www.slickcharts.com/nasdaq100"

# Get symbols
sp500_symbols = get_symbols(sp500_url)
nasdaq100_symbols = get_symbols(nasdaq100_url)

# Save S&P 500
with open("sp500_symbols.txt", "w") as f:
    for symbol in sp500_symbols:
        f.write(symbol + "\n")

# Save Nasdaq-100
with open("nasdaq100_symbols.txt", "w") as f:
    for symbol in nasdaq100_symbols:
        f.write(symbol + "\n")

print(f"Saved {len(sp500_symbols)} S&P 500 symbols")
print(f"Saved {len(nasdaq100_symbols)} Nasdaq-100 symbols")