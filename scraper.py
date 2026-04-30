import os
import smtplib
import logging
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime

# Configure logging with file output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
KEYWORDS = ["办公室装修需求", "餐厅开店设计", "展厅设计求推荐", "零售工装需求"]
EXCLUDE_WORDS = ["承接", "施工队", "厂家", "案例分享", "纯��享", "效果图代做"]
INCLUDE_WORDS = ["求", "找", "准备", "开店", "坐标", "推荐"]

RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "2324403985@qq.com")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASS = os.getenv("SENDER_PASS")

if not SENDER_EMAIL or not SENDER_PASS:
    logger.error("Missing SENDER_EMAIL or SENDER_PASS environment variables")
    exit(1)

def filter_content(title, desc=""):
    """Filter posts by keywords"""
    full_text = (title + desc).lower()
    
    if any(word in full_text for word in EXCLUDE_WORDS):
        return False
    
    if not any(word in full_text for word in INCLUDE_WORDS):
        return False
    
    return True

def scrape_xhs():
    """Scrape Xiaohongshu for design opportunities"""
    results = []
    seen_links = set()
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            for kw in KEYWORDS:
                try:
                    logger.info(f"Searching keyword: {kw}")
                    page.goto(f"https://www.xiaohongshu.com/search_result?keyword={kw}", 
                             wait_until="networkidle", timeout=10000)
                    
                    try:
                        page.wait_for_selector(".note-item", timeout=5000)
                    except PlaywrightTimeoutError:
                        logger.warning(f"No results found for keyword: {kw}")
                        continue
                    
                    items = page.locator(".note-item").all()[:10]
                    logger.info(f"Found {len(items)} posts for keyword: {kw}")
                    
                    for item in items:
                        try:
                            title = item.locator(".title").inner_text().strip()
                            link_elem = item.locator("a.cover")
                            href = link_elem.get_attribute("href") if link_elem.count() > 0 else None
                            
                            if not href:
                                continue
                            
                            full_link = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"
                            
                            if full_link in seen_links:
                                continue
                            
                            if filter_content(title):
                                seen_links.add(full_link)
                                results.append({
                                    'title': title,
                                    'link': full_link,
                                    'keyword': kw
                                })
                                logger.info(f"✓ Matched: {title[:50]}")
                        
                        except Exception as e:
                            logger.debug(f"Error extracting post: {e}")
                            continue
                
                except PlaywrightTimeoutError:
                    logger.warning(f"Timeout while processing keyword: {kw}")
                except Exception as e:
                    logger.error(f"Error processing keyword {kw}: {e}")
                    continue
            
            browser.close()
    
    except Exception as e:
        logger.error(f"Browser error: {e}")
    
    return results

def send_mail(results):
    """Send email with results"""
    if not results:
        logger.info("No valid requirements found today")
        return
    
    html_items = "\n".join([
        f"<li><a href='{r['link']}'>{r['title']}</a> <small>[{r['keyword']}]</small></li>"
        for r in results
    ])
    
    html = f"""
    <h3>🎨 Today's Xiaohongshu Design Opportunities ({datetime.now().strftime('%Y-%m-%d')})</h3>
    <p>Found <strong>{len(results)}</strong> potential leads:</p>
    <ul>{html_items}</ul>
    """
    
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = f"【Auto】Design Leads Alert - {len(results)} opportunities"
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        logger.info("✓ Email sent successfully")
    except Exception as e:
        logger.error(f"Email send failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Xiaohongshu scraper...")
    results = scrape_xhs()
    logger.info(f"Found {len(results)} results")
    send_mail(results)
    logger.info("Scraper completed")
