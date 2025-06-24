# streamlit_app.py
import streamlit as st
import pandas as pd
import urllib.parse
import requests
import shutil
import os
import time
import zipfile
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import tempfile
import re

def create_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920x1080')
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scroll_to_load_all_ads(driver, pause_time=2, max_scrolls=50):
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(max_scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def download_file(url, save_path):
    try:
        r = requests.get(url, stream=True, timeout=10)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
    except Exception as e:
        st.error(f"다운로드 실패: {url}\n오류: {e}")

def extract_metadata(driver, url, options, content_dir):
    driver.get(url)
    time.sleep(5)
    scroll_to_load_all_ads(driver)

    ad_roots = driver.find_elements(By.XPATH, "//div[contains(@class, 'xh8yej3') and descendant::span[contains(text(), '게재 시작함')]]")
    seen_ids = set()
    metadata = []
    previews = []

    for container in ad_roots:
        try:
            lines = container.text.split('\n')
            lib_id_line = next((line for line in lines if '라이브러리 ID:' in line), 'N/A')
            lib_id = lib_id_line.replace("라이브러리 ID:", "").strip()
            start_info = next((line for line in lines if '게재 시작함' in line), 'N/A')

            if lib_id in seen_ids or lib_id == 'N/A':
                continue
            seen_ids.add(lib_id)

            try:
                link_el = container.find_element(By.XPATH, ".//a[contains(@href, 'l.php?u=')]")
                full_href = link_el.get_attribute("href")
                parsed_url = urllib.parse.parse_qs(urllib.parse.urlparse(full_href).query)
                landing_href = parsed_url.get("u", ["N/A"])[0]
            except:
                landing_href = 'N/A'

            try:
                page_name_el = container.find_element(By.XPATH, ".//a[contains(@href, 'facebook.com')]/span")
                page_name = page_name_el.text.strip()
            except:
                page_name = 'N/A'

            ad_url = f"https://www.facebook.com/ads/library/?id={lib_id}"

            content_type = 'N/A'
            preview_path = None
            if options['content']:
                try:
                    video_el = container.find_element(By.XPATH, ".//video")
                    video_src = video_el.get_attribute("src")
                    if video_src:
                        preview_path = os.path.join(content_dir, f"{lib_id}.mp4")
                        download_file(video_src, preview_path)
                        content_type = '영상'
                except:
                    pass
                if content_type == 'N/A':
                    try:
                        img_el = container.find_element(By.XPATH, ".//img[contains(@class, 'xh8yej3')]")
                        img_src = img_el.get_attribute("src")
                        if img_src:
                            preview_path = os.path.join(content_dir, f"{lib_id}.jpg")
                            download_file(img_src, preview_path)
                            content_type = '이미지'
                    except:
                        pass

            row = {}
            if options['page']: row['페이지명'] = page_name
            if options['type']: row['컨텐츠 유형'] = content_type
            if options['id']: row['라이브러리 ID'] = lib_id
            if options['ad_url']: row['광고 링크'] = ad_url
            if options['start']: row['게재 시작'] = start_info
            if options['landing']: row['랜딩 링크'] = landing_href
            metadata.append(row)

            if preview_path:
                previews.append((content_type, preview_path))

        except Exception as e:
            st.warning(f"광고 파싱 중 오류 발생: {e}")

    return metadata, previews

def zip_content_dir(content_dir, excel_data):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(content_dir):
            for file in files:
                file_path = os.path.join(root, file)
                zip_file.write(file_path, arcname=os.path.relpath(file_path, content_dir))
        zip_file.writestr("metadata.csv", excel_data)
    zip_buffer.seek(0)
    return zip_buffer

def main():
    st.title("📊 Meta 광고 라이브러리 크롤러")

    url = st.text_input("광고 라이브러리 URL을 입력하세요:")

    options = {
        'id': st.checkbox("라이브러리 ID", value=True),
        'ad_url': st.checkbox("광고 링크", value=True),
        'start': st.checkbox("게재 시작일", value=True),
        'landing': st.checkbox("랜딩 링크", value=True),
        'page': st.checkbox("페이지명", value=True),
        'content': st.checkbox("컨텐츠 저장", value=False),
        'type': st.checkbox("컨텐츠 유형", value=True),
    }

    if st.button("크롤링 시작"):
        if not re.match(r"^https://www\.facebook\.com/ads/library/.*", url):
            st.error("❗ 올바른 URL 형식이 아닙니다.\n예: https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=KR&q=...")
            return

        with st.spinner("크롬 드라이버 실행 중..."):
            temp_dir = tempfile.mkdtemp()
            content_dir = os.path.join(temp_dir, "contents")
            if options['content']:
                os.makedirs(content_dir, exist_ok=True)
            driver = create_driver()

        with st.spinner("데이터 크롤링 중..."):
            metadata, previews = extract_metadata(driver, url, options, content_dir)
            driver.quit()

        df = pd.DataFrame(metadata)
        st.success(f"✅ 크롤링 완료! {len(df)}개의 광고 수집됨.")
        st.dataframe(df)

        if not df.empty:
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 엑셀 다운로드",
                data=csv,
                file_name=f"ad_data_{now}.csv",
                mime='text/csv',
            )

            if options['content']:
                zip_buffer = zip_content_dir(content_dir, csv)
                st.download_button(
                    label="📦 전체 컨텐츠 ZIP 다운로드 (엑셀 포함)",
                    data=zip_buffer,
                    file_name=f"contents_{now}.zip",
                    mime="application/zip",
                )

                st.subheader("🔍 콘텐츠 미리보기")
                for ctype, path in previews[:10]:
                    if ctype == '이미지':
                        st.image(path, width=300)
                    elif ctype == '영상':
                        st.video(path)

        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == '__main__':
    main()
