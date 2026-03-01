import logging
import requests
from urllib.parse import urlparse, parse_qs, urljoin, quote_plus
from typing import Tuple, Optional

USER_ID = "69420"
JOB_ROLE = "PM"
COMPANY = "Money Making Machine"
COMPANY_TYPE = "Hedge Fund"

INITIAL_TOOL = "AboutCMEHistory"

logger = logging.getLogger(__name__)


def extract_insid_qsid(url: str) -> Tuple[str, str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return qs.get("insid", [None])[0], qs.get("qsid", [None])[0]


def print_query_params(url: str):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if not qs:
        logger.debug("Query Parameters: (none)")
    else:
        logger.debug("Query Parameters:")
        for key, vals in qs.items():
            logger.debug("  %s = %s", key, vals)


def walk_quikstrike_auth_flow(log_level: Optional[int] = logging.NOTSET) -> Tuple[int, str]:
    if log_level is not None and log_level != logging.NOTSET:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        logger.setLevel(log_level)
    else:
        logger.disabled = True

    session = requests.Session()
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "DNT": "1",
        "Host": "cmegroup-tools.quikstrike.net",
        "Referer": "https://www.cmegroup.com/tools-information/quikstrike/pricing-volatility-strategy-tools/quikvol-tool.html",
        "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Storage-Access": "none",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"),
    }

    params = {
        "viewitemid": INITIAL_TOOL,
        "userId": USER_ID,
        "jobRole": JOB_ROLE,
        "company": COMPANY,
        "companyType": COMPANY_TYPE,
    }
    qs = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    current_url = f"https://cmegroup-tools.quikstrike.net/User/QuikStrikeTools.aspx?{qs}"

    stage = 1
    no_302_hits = 0 
    while True:
        logger.info("Stage %d → GET %s", stage, current_url)
        logger.debug("Request Headers: %s", headers)
        print_query_params(current_url)

        resp = session.get(current_url, headers=headers, allow_redirects=False)
        logger.info("Received %d", resp.status_code)

        location = resp.headers.get("location")
        if not location and no_302_hits > 1:
            logger.info("No more redirects; final resource reached.")
            return int(insid), str(qsid)
        elif not location:
            no_302_hits += 1

        logger.debug("Location header: %s", location)
        next_url = urljoin(resp.url, location)
        insid, qsid = extract_insid_qsid(next_url)
        logger.info("Redirect → insid=%s, qsid=%s", insid, qsid)

        current_url = next_url
        stage += 1

        if stage == 5:
            headers["Referer"] = current_url

        if stage == 10:
            raise ValueError("CME changed QuikStrike's auth flow --- function is broken")

# def 