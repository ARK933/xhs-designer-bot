import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime, timedelta
import json

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
# 六大设计需求类别的关键词
DESIGN_CATEGORIES = {
    "办公室设计": ["办公室", "办公装修", "工装", "办公空间", "office"],
    "餐厅设计": ["餐厅", "饭店", "餐饮", "美食", "cafe", "restaurant"],
    "服装店设计": ["服装店", "衣服店", "衣店", "shop", "店铺装修"],
    "美容店设计": ["美容", "美发", "理发", "spa", "美甲", "美睫"],
    "展厅设计": ["展厅", "展示厅", "showroom", "展览", "展示"],
    "咖啡店设计": ["咖啡", "咖啡厅", "coffee", "cafe"]
}

# 广告词过滤 - 排除这些词
EXCLUDE_WORDS = [
    "承接", "施工队", "厂家", "案例分享", "纯分享", "效果图代做",
    "装修公司", "设计公司", "工程队", "包工包料", "招聘", "求职",
    "二手", "转让", "出租", "招商", "代理", "加盟", "团购",
    "优惠", "促销", "打折", "便宜", "购买", "购物", "商品",
    "课程", "培训", "教程", "学习", "教学", "付费"
]

# 意向词 - 必须包含至少一个
INCLUDE_WORDS = [
    "求", "找", "准备", "开店", "想要", "需要", "坐标", "推荐",
    "有没有", "怎么样", "咨询", "合作", "接单", "设计", "装修",
    "改造", "翻新", "重新装", "请问", "请教"
]

RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "2324403985@qq.com")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASS = os.getenv("SENDER_PASS")

if not SENDER_EMAIL or not SENDER_PASS:
    logger.error("Missing SENDER_EMAIL or SENDER_PASS environment variables")
    exit(1)

def filter_content(title, desc=""):
    """
    综合过滤：
    1. 排除广告词
    2. 必须包含意向词
    3. 必须包含设计类别词
    """
    full_text = (title + desc).lower()
    
    # 排除广告
    for exclude_word in EXCLUDE_WORDS:
        if exclude_word in full_text:
            logger.debug(f"Excluded (ad word '{exclude_word}'): {title[:40]}")
            return False, None
    
    # 检查是否包含意向词
    has_intent = any(word in full_text for word in INCLUDE_WORDS)
    if not has_intent:
        logger.debug(f"Excluded (no intent word): {title[:40]}")
        return False, None
    
    # 检查是否属于六大类别
    matched_category = None
    for category, keywords in DESIGN_CATEGORIES.items():
        if any(kw in full_text for kw in keywords):
            matched_category = category
            break
    
    if not matched_category:
        logger.debug(f"Excluded (not in target categories): {title[:40]}")
        return False, None
    
    logger.info(f"✓ Matched [{matched_category}]: {title[:50]}")
    return True, matched_category

def scrape_xhs():
    """Scrape Xiaohongshu for design opportunities"""
    results = []
    seen_links = set()
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_viewport_size({"width": 1280, "height": 720})
            
            # 搜索所有六大类别
            for category, keywords in DESIGN_CATEGORIES.items():
                for kw in keywords:
                    try:
                        logger.info(f"Searching [{category}] keyword: {kw}")
                        page.goto(f"https://www.xiaohongshu.com/search_result?keyword={kw}&sort=general", 
                                 wait_until="networkidle", timeout=15000)
                        
                        try:
                            page.wait_for_selector(".note-item", timeout=5000)
                        except PlaywrightTimeoutError:
                            logger.warning(f"No results found for keyword: {kw}")
                            continue
                        
                        # 获取前20个结果
                        items = page.locator(".note-item").all()[:20]
                        logger.info(f"Found {len(items)} posts for keyword: {kw}")
                        
                        for item in items:
                            try:
                                title_elem = item.locator(".title")
                                if title_elem.count() == 0:
                                    continue
                                    
                                title = title_elem.inner_text().strip()
                                
                                # 尝试获取描述
                                desc = ""
                                try:
                                    desc_elem = item.locator(".desc")
                                    if desc_elem.count() > 0:
                                        desc = desc_elem.inner_text().strip()
                                except:
                                    pass
                                
                                # 获取链接
                                link_elem = item.locator("a.cover")
                                href = link_elem.get_attribute("href") if link_elem.count() > 0 else None
                                
                                if not href:
                                    continue
                                
                                full_link = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"
                                
                                if full_link in seen_links:
                                    continue
                                
                                # 过滤内容
                                is_valid, matched_category = filter_content(title, desc)
                                if is_valid:
                                    seen_links.add(full_link)
                                    results.append({
                                        'title': title,
                                        'description': desc,
                                        'link': full_link,
                                        'category': matched_category,
                                        'search_keyword': kw,
                                        'scraped_time': datetime.now().isoformat()
                                    })
                            
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
        # 即使没有结果也发送通知
        send_empty_notification()
        return
    
    # 按分类组织结果
    categorized = {}
    for r in results:
        cat = r['category']
        if cat not in categorized:
            categorized[cat] = []
        categorized[cat].append(r)
    
    # 生成HTML内容
    html_items = ""
    for category in sorted(categorized.keys()):
        items = categorized[category]
        html_items += f"<h4 style='color: #2c3e50; margin-top: 20px; border-bottom: 2px solid #3498db; padding-bottom: 10px;'>{category} ({len(items)})</h4>"
        for r in items:
            html_items += f"""
            <div style='margin: 10px 0; padding: 10px; border-left: 3px solid #3498db;'>
                <p><strong><a href='{r['link']}' style='color: #3498db; text-decoration: none;'>{r['title']}</a></strong></p>
                <small style='color: #7f8c8d;'>搜索关键词: {r['search_keyword']} | 时间: {r['scraped_time']}</small>
            </div>
            """
    
    html = f"""
    <html>
    <head>
        <meta charset='UTF-8'>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .header {{ background-color: #3498db; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; }}
            .footer {{ background-color: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <div class='header'>
            <h2>🎨 小红书设计需求汇总 - {datetime.now().strftime('%Y年%m月%d日')}</h2>
        </div>
        <div class='content'>
            <p>亲爱的用户，</p>
            <p>共发现 <strong style='font-size: 18px; color: #e74c3c;'>{len(results)}</strong> 条潜在设计需求：</p>
            {html_items}
            <hr style='border: none; border-top: 1px solid #bdc3c7; margin: 30px 0;'>
            <p style='color: #7f8c8d; font-size: 12px;'>
                ✓ 已自动过滤广告内容<br>
                ✓ 仅展示合法的设计需求<br>
                ✓ 点击链接可查看原文详情
            </p>
        </div>
        <div class='footer'>
            <p>本邮件由小红书设计需求爬虫自动生成，每天早上8点准时发送。</p>
            <p>如有问题，请勿回复此邮件。</p>
        </div>
    </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"【小红书爬虫】{len(results)}条设计需求 - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        logger.info(f"✓ Email sent successfully to {RECEIVER_EMAIL} with {len(results)} results")
    except Exception as e:
        logger.error(f"Email send failed: {e}")

def send_empty_notification():
    """Send notification when no results found"""
    html = f"""
    <html>
    <head>
        <meta charset='UTF-8'>
    </head>
    <body>
        <h3>小红书设计需求爬虫 - {datetime.now().strftime('%Y年%m月%d日')}</h3>
        <p>亲爱的用户，</p>
        <p>今日扫描已完成，但未发现符合条件的设计需求。</p>
        <p>请继续关注，我们会每天准时为您发送最新的设计需求。</p>
        <hr>
        <p style='color: #999; font-size: 12px;'>本邮件由爬虫自动生成，请勿回复。</p>
    </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"【小红书爬虫】今日无新需求 - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        logger.info(f"✓ Empty notification sent to {RECEIVER_EMAIL}")
    except Exception as e:
        logger.error(f"Notification send failed: {e}")

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Starting Xiaohongshu scraper...")
    logger.info(f"Target email: {RECEIVER_EMAIL}")
    logger.info("=" * 50)
    
    results = scrape_xhs()
    logger.info(f"Found {len(results)} valid results")
    
    send_mail(results)
    
    logger.info("Scraper completed")
    logger.info("=" * 50)
    send_mail(results)
    logger.info("Scraper completed")
