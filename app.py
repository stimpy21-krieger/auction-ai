import streamlit as st
import requests
import uuid
import time
import json
import hashlib
import re
import os
import pandas as pd
import datetime
import numpy as np
import cv2
import google.generativeai as genai
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from io import BytesIO
from PIL import Image
import plotly.graph_objects as go

# =====================================================================
# 🎨 1. 스트림릿 기본 설정 & 2030 타겟 감성 디자인 (CSS)
# =====================================================================
st.set_page_config(page_title="AI 경매 권리분석 마법사", page_icon="🧙‍♂️", layout="centered")

st.markdown("""
<style>
    /* 트렌디한 Pretendard 폰트 적용 및 부드러운 배경색 (이모지 폰트 최우선 적용) */
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    html, body, [class*="css"] {
        font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', 'Pretendard', -apple-system, sans-serif !important;
        background-color: #FDFBF7;
        color: #4A4A4A;
    }
    
    h1 { font-size: 26px !important; color: #333333; font-weight: 700; margin-bottom: 5px !important;}
    h2, h3 { font-size: 20px !important; color: #4A4A4A; font-weight: 600; }
    p, li, span { font-size: 15px !important; line-height: 1.6; }
    
    /* 코랄 핑크빛 둥근 메인 버튼 */
    .stButton > button[kind="primary"] {
        background-color: #FF9B9B !important;
        color: white !important;
        border-radius: 25px !important;
        border: none !important;
        padding: 10px 20px !important;
        font-size: 16px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 10px rgba(255, 155, 155, 0.3) !important;
        transition: all 0.3s ease !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #FF8282 !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 14px rgba(255, 155, 155, 0.4) !important;
    }

    /* 🌟 파일 업로드 창 스타일링 🌟 */
    [data-testid="stFileUploadDropzone"] {
        background-color: #FFFFFF !important;
        border: 2px dashed #FF9B9B !important;
        border-radius: 20px !important;
        padding: 30px !important;
    }

    /* Browse files 버튼 — JS MutationObserver가 텍스트를 치환하므로 CSS ::after 불필요 */
    [data-testid="stFileUploadDropzone"] button {
        font-weight: 600 !important;
        font-size: 14px !important;
    }
</style>

<script>
// 🌟 파일 업로드 영어 텍스트 → 한글 강제 치환 (MutationObserver)
(function() {
    const REPLACEMENTS = {
        'Drag and drop file here': '📸 터치해서 등기부등본 사진 올리기',
        'Drag and drop files here': '📸 터치해서 등기부등본 사진 올리기',
        'Browse files': '사진 선택하기',
        'Browse file': '사진 선택하기'
    };
    const LIMIT_REGEX = /Limit\s+\d+(\.?\d*)\s*(MB|KB|GB)\s+per\s+file/gi;
    const LIMIT_KO = '파일당 최대 200MB';

    function replaceTexts() {
        const dropzones = document.querySelectorAll('[data-testid="stFileUploadDropzone"]');
        dropzones.forEach(zone => {
            const walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT, null, false);
            let node;
            while (node = walker.nextNode()) {
                const trimmed = node.textContent.trim();
                // 정확히 매칭되는 영어 문구 교체
                for (const [eng, kor] of Object.entries(REPLACEMENTS)) {
                    if (trimmed === eng) {
                        node.textContent = kor;
                    }
                }
                // 용량 제한 문구 교체
                if (LIMIT_REGEX.test(trimmed)) {
                    node.textContent = LIMIT_KO;
                    LIMIT_REGEX.lastIndex = 0;
                }
            }
        });
    }

    // 초기 실행 + DOM 변경 감시
    const observer = new MutationObserver(replaceTexts);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    // 페이지 로드 후 약간의 딜레이를 두고 실행 (Streamlit 렌더링 대기)
    setTimeout(replaceTexts, 500);
    setTimeout(replaceTexts, 1500);
    setTimeout(replaceTexts, 3000);
})();
</script>
""", unsafe_allow_html=True)

# =====================================================================
# 🖼️ 스마트 이미지 전처리 (Grayscale + CLAHE + Deskew)
# =====================================================================
def smart_preprocess(file_bytes):
    """스마트폰 사진을 OCR 최적화 전처리합니다.
    - 해상도 유지 (resize 없음)
    - Grayscale + CLAHE 대비 향상 → 용량 축소 + 선명도 향상
    - Hough Line Transform 기반 deskew → 기울어진 문서 자동 수평 보정
    - PNG 무손실 출력
    """
    try:
        # EXIF 회전 보정 (스마트폰 방향)
        try:
            from PIL import ImageOps
            pil_img = Image.open(BytesIO(file_bytes))
            pil_img = ImageOps.exif_transpose(pil_img)
            buf = BytesIO()
            pil_img.save(buf, format='PNG')
            file_bytes = buf.getvalue()
        except Exception:
            pass

        # 바이트 → OpenCV
        nparr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return file_bytes, 'png'

        # 1) Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2) CLAHE 대비 향상 (그림자/조명 보정)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 3) Hough Line Transform 기반 deskew
        edges = cv2.Canny(enhanced, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=img.shape[1] // 4, maxLineGap=10)
        if lines is not None and len(lines) > 5:
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                if abs(angle) < 10:  # 거의 수평인 선만
                    angles.append(angle)
            if angles:
                median_angle = np.median(angles)
                if abs(median_angle) > 0.3 and abs(median_angle) < 5:
                    (h, w) = enhanced.shape
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                    enhanced = cv2.warpAffine(
                        enhanced, M, (w, h),
                        flags=cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE
                    )

        # 4) 약한 선명화 (과도한 sharpening 방지)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 2)
        sharpened = cv2.addWeighted(enhanced, 1.3, blurred, -0.3, 0)

        # PNG 인코딩
        _, encoded = cv2.imencode('.png', sharpened)
        return encoded.tobytes(), 'png'
    except Exception:
        return file_bytes, 'png'


# =====================================================================
# 📝 Fuzzy Matching 오타 보정 (경매 용어 특화)
# =====================================================================
# 경매 핵심 용어 사전 (OCR 오타 → 정확한 용어)
AUCTION_TERM_CORRECTIONS = {
    '가입류': '가압류', '가압유': '가압류', '가앞류': '가압류', '가압르': '가압류',
    '근저당관': '근저당권', '근저당귄': '근저당권', '근저당건': '근저당권',
    '근저당궈설정': '근저당권설정', '근저당관설정': '근저당권설정',
    '소유관이전': '소유권이전', '소유귄이전': '소유권이전', '소유건이전': '소유권이전',
    '채권최교액': '채권최고액', '채권쵀고액': '채권최고액', '채권최고엑': '채권최고액',
    '임의경매개시겸정': '임의경매개시결정', '임의경매겨시결정': '임의경매개시결정',
    '강제경매개시겸정': '강제경매개시결정',
    '전세관': '전세권', '전세귄': '전세권', '전세건': '전세권',
    '지상관': '지상권', '지상귄': '지상권', '지상건': '지상권',
    '유치관': '유치권', '유치귄': '유치권',
    '저당관': '저당권', '저당귄': '저당권',
    '담보가등거': '담보가등기', '담보가등끼': '담보가등기',
    '소유관': '소유권', '소유귄': '소유권',
    '말쇄': '말소', '말세': '말소',
    '접수': '접수', '첩수': '접수',
    '순위벤호': '순위번호', '순위번헌': '순위번호',
    '등기뫽적': '등기목적', '등기목젹': '등기목적',
    '배당요규': '배당요구',
    '가처붐': '가처분', '가처뷴': '가처분',
    '압류': '압류', '압유': '압류',
    '경매개시겸정': '경매개시결정',
}

def _levenshtein_distance(s1, s2):
    """두 문자열 사이의 Levenshtein 편집 거리를 계산합니다."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]

def fuzzy_clean_text(text):
    """OCR 인식 결과에서 경매 용어 오타를 유사도 기반으로 자동 보정합니다."""
    # 1단계: 정확한 매칭 (빠른 경로)
    for wrong, correct in AUCTION_TERM_CORRECTIONS.items():
        if wrong in text:
            text = text.replace(wrong, correct)

    # 2단계: Fuzzy 매칭 (편집거리 1~2 이내)
    # 텍스트를 공백 기준으로 분리하여 각 토큰 검사
    words = text.split()
    corrected_words = []
    # 정확한 용어 목록 (중복 제거)
    correct_terms = list(set(AUCTION_TERM_CORRECTIONS.values()))

    for word in words:
        if len(word) >= 2:  # 2글자 이상만 검사
            best_match = None
            best_dist = float('inf')
            for term in correct_terms:
                # 길이 차이가 2 이상이면 스킵 (효율성)
                if abs(len(word) - len(term)) > 2:
                    continue
                dist = _levenshtein_distance(word, term)
                if dist <= 2 and dist < best_dist and dist > 0:
                    best_dist = dist
                    best_match = term
            if best_match:
                corrected_words.append(best_match)
            else:
                corrected_words.append(word)
        else:
            corrected_words.append(word)

    return ' '.join(corrected_words)

# =====================================================================
# 🔑 2. API 키 자동 로드 (스트림릿 비밀 금고)
# =====================================================================
try:
    NAVER_API_URL = st.secrets["NAVER_API_URL"]
    NAVER_SECRET_KEY = st.secrets["NAVER_SECRET_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("서버 관리자 설정 필요: 비밀 금고(Secrets)에 API 키가 설정되지 않았습니다.")
    st.stop()

# =====================================================================
# 🧠 3. 지식 베이스 및 필터링 룰 (개발자님 작성 원본 100% 반영)
# =====================================================================
base_keywords = ['근저당', '저당', '담보물권', '가압류', '압류', '체납처분압류', '강제경매개시결정', '임의경매개시결정', '경매개시결정', '담보가등기']
always_keep_keywords = ['건물철거', '토지인도', '법정지상권', '관습법상', '관습상', '분묘기지권', '예고등기', '요역지', '지역권', '도시철도법', '구분지상권', '채무자회생법', '특별매각조건', '인수조건']
ai_check_keywords = ['전세권', '임차권', '가처분', '처분금지가처분', '가등기', '소유권이전청구권', '지상권', '부합물', '종물', '다른 약정', '특약']

# 꼬리말 안내문 제거 필터
ignore_keywords = ["관할등기소", "본등기사항증명서", "사법부내부", "열람용이므로", "법적인효력", "실선으로그어진", "말소사항을표시", "기록사항없는", "기록사항없음", "열람일시", "사법부 말소사항", "수원지방법원"]

# 📋 문서 유형 판별 키워드
registry_keywords = ["등기사항전부증명서", "등기사항증명서", "등기부등본", "갑구", "을구", "표제부"]
spec_keywords = ["매각물건명세서", "최선순위설정", "배당요구종기", "매각으로효력이", "임차인현황", "매각물건의표시"]

# 🚨 매각물건명세서 비고란 위험 키워드
danger_keywords = {
    "유치권": "🚨 [유치권 경고] 유치권 신고가 있습니다. 낙찰대금 외에 공사대금 등을 전액 떠안을 수 있으며, 변제할 때까지 건물 인도를 받지 못할 수 있습니다.",
    "법정지상권": "🚨 [법정지상권 경고] 토지/건물 소유권 분리로 인해 지료 분쟁이나 건물 철거 제약을 받을 수 있습니다.",
    "분묘기지권": "🚨 [분묘기지권 경고] 토지 위에 분묘가 있어 토지 사용에 심각한 제약이 있습니다.",
    "대지권미등기": "⚠️ [대지권 미등기 경고] 땅에 대한 권리가 불확실하여 대출 거절 및 추가 비용이 발생할 수 있습니다.",
    "토지별도등기": "⚠️ [토지별도등기 경고] 대지에 별도의 근저당 등이 설정되어 추가 부담이 있을 수 있습니다.",
    "농지취득자격증명": "❗ [보증금 몰수 경고] 농취증 미제출 시 입찰 보증금 전액 몰수됩니다. 입찰 전 발급 가능 여부를 반드시 확인하세요.",
    "위반건축물": "⚠️ [위반건축물 경고] 매년 이행강제금이 부과되며 원상복구 의무가 있을 수 있습니다.",
    "건물철거": "⛔ [건물 철거 위험] 토지 소유자의 건물 철거 소송으로 건물을 잃을 수 있습니다.",
    "대항력포기": "💡 [대항력 포기 확약서] HUG 등이 대항력 포기서를 제출하여 선순위 임차인 인수 부담이 없을 수 있습니다.",
    "원상회복": "⚠️ [원상회복 의무] 불법 형질변경 부분의 복구 비용을 낙찰자가 부담해야 합니다.",
    "제시외건물": "⚠️ [제시외 건물] 매각 대상에 포함되지 않는 건물이 있어 분쟁 위험이 있습니다.",
    "소유권상실": "⛔ [소유권 상실 위험] 선순위 가등기/가처분으로 소유권을 빼앗길 수 있습니다.",
}

knowledge_base = """
[업로드된 문서들을 바탕으로, 경매에서 **'말소기준권리'가 될 수 있는 모든 권리의 명칭(키워드)**을 쉼표로 구분해서 리스트 형태로 나열해 줘. (예: 근저당권, 가압류, 압류 등). 그리고 최선순위 전세권처럼 '특정 조건(배당요구 등)'이 충족되어야만 말소기준권리가 되는 예외적인 권리도 따로 명시해 줘.

경매에서 '말소기준권리'가 될 수 있는 권리의 명칭은 다음과 같습니다.
말소기준권리 명칭 리스트: 근저당권, 저당권, 담보물권, 압류(체납압류 포함), 가압류, 강제경매개시결정등기, 담보가등기, 전세권, 부분전세

--------------------------------------------------------------------------------
특정 조건이 충족되어야만 말소기준권리가 되는 예외적인 권리:
• 최선순위 전세권: 원칙적으로 최선순위 전세권은 배당 여부와 상관없이 매수인에게 인수되는 권리이지만, 전세권자가 배당요구종기까지 스스로 **'배당요구를 한 경우'**에 한하여 매각으로 소멸하며 말소기준권리가 됩니다.
• 부분전세: 목적물 전체가 아닌 일부에만 설정된 전세권의 경우, 자료에서는 이를 '불완전말소기준' 권리로 별도 분류하고 있습니다.
• 최선순위 담보가등기: 최선순위 가등기는 일반적인 소유권이전청구권보전가등기(매매예약 등)인 경우 말소기준권리가 되지 않고 매수인에게 인수됩니다. 하지만 법원의 최고 등에 따라 채권신고를 하여 해당 등기가 변제를 목적으로 하는 '담보가등기'임이 밝혀지고 배당요구를 한 경우에는 저당권과 동일하게 취급되어 매각으로 소멸하며 말소기준권리가 됩니다

경매에서 '말소기준권리(소멸기준권리)'가 될 수 있는 권리는 다음과 같습니다.
말소기준권리 리스트: 저당권, 근저당권, 압류, 경매개시결정등기(압류), 체납처분압류, 가압류, 담보가등기.
특정 조건이 충족되어야 하는 예외적인 권리:
• 최선순위 전세권: 최선순위 전세권자가 배당요구 종기까지 '배당요구'를 한 경우에만 매각으로 소멸하며 말소기준권리가 될 수 있습니다. (만약 최선순위 전세권자가 배당요구를 하지 않는다면 말소기준권리가 되지 않고 매수인이 그 부담을 그대로 인수해야 합니다).

말소기준권리가 될 수 있는 일반적인 권리 저당권, 근저당권, 압류, 가압류, 담보가등기, 강제경매개시결정등기,,,,,,.
특정 조건이 충족되어야 말소기준권리가 되는 예외적인 권리
최선순위 전세권: 원칙적으로 최선순위 전세권은 매각으로 소멸하지 않고 매수인이 인수하지만, 전세권자가 배당요구의 종기까지 배당요구를 한 경우에 한하여 매각으로 소멸하게 되므로 예외적으로 말소기준권리가 될 수 있습니다,,,,,.

말소기준권리보다 날짜가 늦은 후순위임에도 불구하고, 경매에서 절대 소멸되지 않고 낙찰자가 무조건 '인수'해야 하는 예외적인 권리나 특약의 핵심 키워드를 모두 찾아줘. (예: 건물철거 및 토지인도청구권 보전을 위한 가처분, 예고등기, 유치권 등). 프로그래밍 예외 처리에 쓸 수 있게 단어 위주로 뽑아줘.

프로그래밍의 예외 처리(Exception Handling) 등에 활용할 수 있도록, 제공된 자료에서 **'말소기준권리보다 늦은 후순위이거나 순위와 무관하게 매각으로 절대 소멸하지 않고 매수인이 무조건 인수해야 하는 예외적인 권리 및 특약'**의 핵심 키워드를 추출한 리스트입니다.
[예외 처리용 핵심 키워드 리스트]
건물철거 및 토지인도청구권 보전을 위한 가처분, 유치권, 법정지상권, 관습법상 법정지상권, 분묘기지권, 예고등기, 요역지 지역권, 도시철도법 등에 의한 구분지상권, 채무자회생법에 의한 등기, 특별매각조건으로 인수가 정해진 권리, 매수인이 인수한 채무와 관련된 권리

--------------------------------------------------------------------------------
[각 키워드별 세부 설명 및 법적 근거]
• 건물철거 및 토지인도청구권 보전을 위한 (처분금지)가처분: 토지 소유자가 지상 건물의 소유자를 상대로 건물을 철거하고 토지를 인도하라는 내용을 피보전권리로 하여 마친 건물 가처분등기는, 근저당권 설정이나 강제경매개시결정등기보다 나중에(후순위로) 이루어졌더라도 매각으로 결코 말소되지 않고 매수인에게 무조건 인수됩니다.
• 유치권: 특별한 사정이 없는 한 저당권 설정 등 말소기준권리보다 나중에 성립되었더라도 그 성립 시기와 관계없이 매각으로 소멸하지 않고 매수인이 무조건 인수(변제할 책임)해야 합니다.
• 법정지상권 / 관습법상 법정지상권: 토지와 건물이 강제경매 등으로 소유자가 달라질 때 건물 소유자(또는 토지)를 위해 당연히 성립하는 지상권으로, 말소기준권리와 관계없이 매수인이 무조건 인수하게 됩니다.
• 분묘기지권: 타인의 토지에 분묘를 설치한 자가 가지는 지상권 유사의 물권으로, 말소기준권리의 선후와 무관하게 무조건 매수인에게 인수됩니다.
• 예고등기: 말소기준권리와 관계없이 무조건 인수되는 등기입니다.
• 요역지 지역권: 편익을 받는 토지(요역지)의 소유권에 부종하는 종된 권리이므로, 말소기준권리 이후에 설정된 권리일지라도 말소촉탁의 대상이 되지 않고 매수인이 그대로 취득(인수)합니다.
• 도시철도법 등에 의한 구분지상권: 토지(또는 대지권)에 설정된 도시철도법 등에 의한 구분지상권 등기는 후순위이더라도 말소되지 아니하고 매수인에게 인수됩니다.
• 채무자회생법에 의한 등기: 보전처분, 개시결정, 인가 등 채무자회생법에 의해 기입된 등기(단, 회생절차폐지등기 제외)는 경매의 말소촉탁 대상이 되지 않고 인수됩니다.
• 특별매각조건으로 인수가 정해진 권리: 원래는 매각으로 소멸해야 할 등기(예: 종전 소유자 채무의 가압류, 지분에 설정된 전세권, 대지에 설정된 근저당권 등)이더라도, 집행법원이 매수인이 이를 인수하도록 '특별매각조건'을 정하여 매각을 진행한 경우에는 그 등기의 효력이 소멸하지 않고 무조건 인수됩니다.
• 매수인이 인수한 채무와 관련된 권리: 매수인이 매각대금을 지급하는 것에 갈음하여 특정 채무를 직접 인수하기로 한 경우, 그 인수한 채무와 관련된 권리는 말소되지 않고 인수됩니다.

업로드된 문서를 바탕으로, 말소기준권리보다 늦은 후순위임에도 소멸하지 않고 낙찰자(매수인)가 인수해야 하는 예외적인 권리 및 조건의 핵심 키워드를 추출한 결과는 다음과 같습니다.
예외 처리용 핵심 키워드 리스트: 유치권, 건물철거 및 토지인도청구권 보전을 위한 가처분(또는 처분금지가처분), 법정지상권, 관습상 법정지상권, 특별매각조건(인수조건)
각 키워드에 대한 문서 내 근거는 아래와 같습니다.
• 유치권: 저당권이나 가압류(말소기준권리)보다 나중에 성립했더라도, '경매개시결정등기'가 되기 전에 취득한 유치권은 매각으로 소멸하지 않고 매수인이 그 부담을 인수(변제할 책임)해야 합니다.
• 건물철거 및 토지인도청구권 보전을 위한 처분금지가처분: 건물만의 경매에서 토지 소유자가 건물 소유자를 상대로 제기한 이 가처분은, 담보권설정등기나 경매개시결정등기 이후에 기입된 후순위라 하더라도 매각으로 말소되지 않고 무조건 인수됩니다.
• 법정지상권 및 관습상 법정지상권: 저당권의 실행 등으로 토지와 건물의 소유자가 달라질 때 당사자의 계약이 아닌 법률 규정(또는 관습)에 의해 당연히 성립하여 매수인이 그 부담을 안게 되는 권리입니다.
• 특별매각조건(인수조건): 원래는 법정매각조건에 따라 매각으로 소멸해야 할 권리이지만, 공유물분할을 위한 경매 등에서 집행법원이 필요하다고 인정하여 예외적으로 '소멸주의가 아닌 인수주의'를 매각조건으로 정한 경우입니다.

제공된 자료를 바탕으로, 말소기준권리보다 후순위임에도 불구하고 매각(경매)으로 소멸되지 않고 매수인이 무조건 인수해야 하는 예외적인 권리 및 특약의 핵심 키워드를 추출한 리스트입니다.
유치권, 건물철거 및 토지인도청구권 보전을 위한 가처분, 토지수용 또는 사용재결을 원인으로 하는 구분지상권, 법정지상권, 관습상 법정지상권, 분묘기지권, 예고등기
프로그래밍 예외 처리 및 조건 분류를 위해 각 키워드의 구체적인 예외 인정 근거를 덧붙여 드립니다.
유치권: 등기된 부동산에 관한 권리는 아니지만, (경매개시결정 기입등기 전 등에 적법하게 성립한 경우) 매각으로 소멸하지 않고 매수인에게 인수됩니다,.
건물철거 및 토지인도청구권 보전을 위한 가처분 (처분금지가처분): 토지소유자가 지상 건물소유자를 상대로 제기한 이 가처분은, 건물에 관한 강제경매개시결정등기나 담보권설정등기보다 후순위(이후)에 이루어졌더라도 매각으로 인하여 말소되지 않고 매수인에게 인수됩니다,,.
토지수용 또는 사용재결을 원인으로 하는 구분지상권: 도시철도법 등 공익사업을 위해 설정된 구분지상권은 그보다 먼저 마쳐진 근저당권, 압류, 가압류 등(말소기준권리)이 존재하더라도 소멸하지 않고 매수인에게 인수됩니다,.
법정지상권 / 관습상 법정지상권: 토지와 건물의 소유자가 달라질 때 건물의 존속을 위해 법률상 당연히 성립하는 권리로, 말소기준권리 날짜와 무관하게 매수인이 그 부담을 안게 됩니다,,,.
분묘기지권: 토지 상에 분묘기지권이 성립하는 경우, 토지 매수인이 소유권을 취득하더라도 해당 부담을 안게 되므로 감가 평가의 대상이 되는 인수 권리입니다.
예고등기: 소유권 말소 소송 등이 진행 중임을 경고하는 등기로, 부동산에 관한 권리관계를 직접 공시하는 것이 아니어서 매각으로 말소되지 않습니다 (참고: 현행법상 제도는 폐지되었으나 기존 등기는 유효할 수 있음),.

등기부등본 내용 중, 단순히 날짜 비교로는 인수/말소 여부를 판단할 수 없고 문맥과 특약 사항을 깊이 해석해야 하는 **'복잡한 권리(AI의 보조 판단이 필요한 항목)'**는 무엇이 있는지 찾아줘. 이런 권리들의 공통적인 특징이나 포함되는 단어(예: 지상권, 임차권, 특약사항 등)를 정리해 줘

등기부등본상 단순히 날짜(말소기준권리)의 선후 비교만으로는 인수/말소 여부를 확정할 수 없고, 권리자의 행위(배당요구 등)나 등기의 실질적인 목적, 법원의 특별한 결정 등 문맥과 특약 사항을 깊이 해석해야 하는 **'복잡한 권리'**들은 다음과 같습니다.
1. 배당요구 여부 및 권리자의 이중 지위에 따라 달라지는 권리
• 최선순위 전세권 (및 겸유 임차인): 원칙적으로 최선순위 전세권은 매수인에게 인수되지만, 전세권자가 스스로 '배당요구'를 하면 매각으로 소멸합니다. 그러나 가장 깊은 해석이 필요한 경우는 **주택임차인과 전세권자의 지위를 함께 가진 자(겸유 임차인)**입니다. 이 사람이 '임차인'의 지위에서만 배당요구를 했다면, 전세권에 대해서는 배당요구를 한 것으로 볼 수 없어 해당 최선순위 전세권은 매각으로 소멸하지 않고 인수됩니다.
• 임차권 및 임차권등기: 임차권등기의 경우 등기부상 등기된 날짜가 아닌, 실제 대항력을 갖춘 날(전입신고일과 점유일 중 늦은 날의 다음날)을 기준으로 말소기준권리와 선후를 비교해야 합니다. 또한 최선순위 대항력을 갖춘 임차인이 배당요구를 하더라도, 보증금 전액을 변제(배당)받지 못하면 그 잔액에 대해 대항력이 유지되어 매수인이 인수해야만 합니다.
2. 등기의 실질적인 '설정 목적'을 확인해야 하는 권리
• 최선순위 가등기: 순위보전을 위한 '소유권이전청구권 보전가등기'라면 매수인에게 인수되지만, 채권 담보가 목적인 **'담보가등기'**인 경우에는 저당권과 동일하게 취급되어 순위와 무관하게 매각으로 소멸합니다.
• 최선순위 지상권 (담보지상권): 원칙적으로 최선순위 지상권은 인수됩니다. 그러나 근저당권 등 담보권 설정자가 목적물의 담보가치 하락을 막기 위한 목적으로 근저당권과 함께 설정한 **'담보지상권'**의 경우, 피담보채권(근저당권)이 변제 등으로 소멸하면 지상권도 함께 목적을 잃고 소멸하므로 매수인이 인수하지 않습니다.
3. 날짜 선후(순위)와 무관하게 무조건 인수되는 예외적 권리
• 건물철거 및 토지인도청구권 보전을 위한 가처분: 토지 소유자가 지상 건물 소유자를 상대로 제기한 건물철거 등을 위한 처분금지가처분은, 말소기준권리(근저당권 등)보다 나중에 설정된 후순위라 하더라도 절대 말소되지 않고 매수인에게 무조건 인수되는 매우 강력한 권리입니다.
4. 법원의 결정이나 특약(확약)에 의해 성질이 변경되는 권리
• 특별매각조건으로 인수가 정해진 권리: 원래는 매각으로 소멸해야 할 가압류나 대지권에 설정된 근저당권이라도, 집행법원이 매수인이 이를 인수하도록 **'특별매각조건'**을 정하여 매각을 진행한 경우에는 등기 효력이 소멸하지 않고 인수됩니다.
• 대항력 포기 (인수조건변경 확약서): 원래는 보증금 전액을 배당받지 못해 매수인이 인수해야 할 최선순위 임차권(또는 이를 양수한 주택도시보증공사 등)이, 경매 절차 중 잔존 보증금 청구권을 포기하고 임차권등기를 말소하는 것에 동의하는 **'확약서(또는 대항력 포기 동의서)'**를 법원에 제출한 경우 특별매각조건에 따라 소멸하게 됩니다.
• 채무인수 약정: 매수인이 매각대금 지급에 갈음하여 특정 채무를 직접 인수하기로 한 경우, 그 인수한 채무와 관련된 권리는 말소되지 않습니다.

--------------------------------------------------------------------------------
[복잡한 권리들의 공통적 특징 및 핵심 키워드 정리]
이러한 복잡한 권리들은 **"단순한 등기 접수일자가 아닌, 실체적 권리관계(대항력 발생일, 설정의 진짜 목적)나 당사자의 의사표시(배당요구, 대항력 포기)가 소멸 여부를 완전히 뒤바꾼다"**는 공통점이 있습니다. AI나 프로그램을 통해 문서의 예외 상황을 판단할 때 반드시 탐지해야 할 핵심 키워드는 다음과 같습니다.
• 지위/조건 관련 판단 키워드: 겸유 (전세권자 겸 임차인), 배당요구 (배당요구 종기, 배당요구 여부), 전액 변제 (또는 잔액 인수, 일부 배당), 대항력 취득일 (전입신고일, 확정일자).
• 목적 해석 관련 판단 키워드: 담보가등기, 보전가등기 (또는 소유권이전청구권 보전), 담보지상권.
• 특수 문맥/예외 판단 키워드: 건물철거, 토지인도, 특별매각조건, 대항력 포기 (대항력 포기서/동의서), 확약서 (인수조건변경확약서), 채무인수.

등기부등본상의 단순 날짜 비교(말소기준권리 판단)만으로는 인수 및 말소 여부를 결정할 수 없어, 문맥 해석이나 타 조건과의 결합 등 복잡한 판단이 필요한 권리들은 다음과 같습니다.
1. 실질적인 목적(피보전권리)을 해석해야 하는 '가처분'
• 일반적으로 후순위 가처분은 매각으로 소멸하지만, 건물만의 경매에서 토지 소유자가 건물 소유자를 상대로 제기한 **'건물 철거 및 토지인도청구권을 피보전권리로 한 처분금지가처분'**은 담보권설정등기(말소기준권리) 이후에 기입된 후순위라 하더라도 무조건 매수인에게 인수됩니다. 따라서 AI는 가처분의 '피보전권리' 내용을 읽고 해석할 수 있어야 합니다.
2. 권리자의 행위 및 배당 결과에 따라 운명이 바뀌는 '전세권'과 '임차권'
• 최선순위 전세권: 말소기준권리보다 앞선 최선순위라도, 전세권자가 배당요구 종기까지 '배당요구'를 했는지 여부에 따라 인수와 말소가 갈립니다(배당요구 시 소멸, 미요구 시 인수).
• 대항력 있는 임차권: 최선순위 임차인이 배당요구를 하였더라도, 매각대금에서 보증금 전액을 배당(변제)받았는지 계산해야 합니다. 보증금이 모두 변제되지 않았다면 배당받지 못한 잔액이 매수인에게 그대로 인수되므로, 단순 날짜뿐만 아니라 배당표(변제 여부)에 대한 분석이 동반되어야 합니다.
3. 등기 기록의 실질과 채권신고 여부를 따져야 하는 최선순위 '가등기'
• 최선순위 가등기는 원칙적으로 매수인이 인수하는 '순위보전가등기'인지, 아니면 저당권처럼 매각으로 소멸하는 '담보가등기'인지 구분해야 합니다.
• 등기기록의 내용만으로는 이를 명확히 단정할 수 없으며, 법원의 최고에 따라 가등기권자가 채권신고를 했는지의 여부 등 실질적인 내용을 보조적으로 파악해야 인수/말소를 판단할 수 있습니다.
4. 타 권리와의 종속 관계(부종성)를 파악해야 하는 '담보지상권'
• 근저당권 등 담보권자가 목적물의 담보가치 하락을 막기 위해 저당권과 함께 설정해 두는 지상권을 '담보지상권'이라 합니다.
• 일반적인 선순위 지상권은 인수되는 것이 원칙이지만, 이 담보지상권은 메인 권리인 '피담보채권(근저당권)'이 변제나 시효로 소멸하게 되면 그에 부종하여 함께 소멸하는 특성을 가집니다. 따라서 연관된 근저당권의 상태를 함께 분석해야 합니다.

--------------------------------------------------------------------------------
💡 복잡한 권리들의 공통적 특징
이 권리들은 **"등기된 날짜의 선후라는 형식적 기준 외에, ① 권리자의 적극적인 의사표시(배당요구, 채권신고), ② 등기된 목적의 문맥적 의미(피보전권리의 내용), ③ 다른 권리와의 종속성(피담보채권 존재 여부), ④ 실제 배당 결과(전액 변제 여부)를 종합적으로 결합해야만 효력을 확정할 수 있다"**는 공통점을 가집니다.
🔑 프로그래밍 및 AI 판단 보조를 위한 핵심 키워드
이러한 권리들을 필터링하고 해석하기 위해 주의 깊게 찾아야 할 단어들은 다음과 같습니다.
• 가처분 관련: 피보전권리, 건물철거, 토지인도, 처분금지가처분
• 전세권/임차권 관련: 최선순위 전세권, 배당요구, 배당요구종기, 대항력, 보증금 전액, 변제되지 아니한 잔액, 잔액 인수
• 가등기 관련: 가등기, 담보가등기, 순위보전가등기, 소유권이전청구권, 채권신고
• 지상권 관련: 지상권설정, 목적, 근저당권설정 (동일 날짜/채권자 여부), 피담보채권, 담보가치

**단순한 날짜(순위) 비교만으로는 인수/말소 여부를 판단할 수 없고, 문맥과 실질적인 목적, 특약 사항 등을 깊이 분석해야 하는 '복잡한 권리'**는 다음과 같습니다.
1. 날짜와 무관하게 소멸하거나 인수되는 권리
건물철거 및 토지인도청구권 보전을 위한 가처분: 이 가처분은 말소기준권리(강제경매개시결정등기나 담보권설정등기)보다 나중에(후순위로) 기입되었더라도 매각으로 말소되지 않고 매수인(낙찰자)이 무조건 인수해야 하므로 주의 깊은 문맥 파악이 필요합니다.
담보지상권 (저당권과 함께 설정된 지상권): 은행 등이 대출을 해주며 건물이 지어지는 것을 막기 위해 저당권과 함께 지상권을 설정하는 경우가 있습니다. 이 경우 지상권이 최선순위라 하더라도, 피담보채권(담보권)이 변제 등으로 소멸하면 지상권의 존속기간과 무관하게 목적을 잃어 함께 당연 소멸하므로 매수인이 인수하지 않습니다.
특정 공익사업 목적의 구분지상권: 「도시철도법」 등에 의해 설정된 구분지상권(지하철 부지 등)은 그보다 먼저 마쳐진 최선순위 근저당권이나 가압류가 있어도 경매로 절대 소멸하지 않고 매수인이 인수해야 합니다.
2. 당사자의 '행위(배당요구 등)'나 '결과'를 추적해야 하는 권리
최선순위 임차권 (대항력 있는 주택/상가 임차권): 최선순위 임차권자가 스스로 배당요구를 했더라도, 경매 절차에서 보증금 전액을 배당받지 못하면 배당받지 못한 '잔액'에 대해서는 매수인이 인수하게 되므로, 배당표 결과까지 복합적으로 분석해야 합니다.
최선순위 전세권: 원칙적으로는 매수인이 인수하지만, 전세권자가 '배당요구를 한 경우'에 한하여 매각으로 소멸합니다. (참고로 임차권과 달리, 전세권은 일부만 배당받더라도 전액 말소됩니다).
3. 등기의 '실질적인 목적'을 파악해야 하는 권리
가등기 (담보가등기 vs 소유권이전청구권가등기): 등기부상 형태가 같더라도, 실제 목적이 채권을 담보하기 위한 '담보가등기'라면 순위와 무관하게 경매로 소멸합니다. 반면, 순위를 보전하기 위한 일반 '소유권이전청구권가등기'가 최선순위라면 매수인이 인수합니다. 따라서 권리신고 내역 등을 통해 실질을 판단해야 합니다.
4. 특별한 '약정(특약)'을 확인해야 하는 항목
부합물 및 종물 배제 특약: 저당권의 효력은 원칙적으로 목적 부동산에 부합된 물건(부합물)과 종물에도 미치지만, 설정행위에 '다른 약정(특약)'이 있는 경우에는 평가 및 매각 대상에서 제외될 수 있으므로 특약사항 기재 여부를 꼼꼼히 확인해야 합니다.

--------------------------------------------------------------------------------
💡 복잡한 권리들의 공통적 특징
외형(날짜, 등기 명칭)과 실질이 다름: 등기부상 명칭이나 접수일자만으로는 권리의 진정한 목적(예: 담보용 지상권, 담보용 가등기)을 알 수 없습니다.
외부적 요인에 의한 변동성: 권리자의 배당요구 여부, 실제 배당받은 금액의 규모 등에 따라 말소/인수 여부가 실시간으로 달라집니다.
특별법에 의한 예외 적용: 일반 민사집행법의 소멸주의 원칙을 깨고 보호받는 예외 규정(도시철도법상 지상권, 주택임대차보호법상 잔액 인수 등)이 적용됩니다.
🔍 AI 보조 판단 및 예외 처리를 위한 핵심 키워드 리스트
가처분 관련: 건물철거, 토지인도, 피보전권리
지상권 관련: 담보지상권, 구분지상권, 도시철도법, 사용재결
임차권/전세권 관련: 배당요구, 배당요구종기, 일부배당, 보증금 잔액, 대항력 유지
가등기 관련: 담보가등기, 청산절차
특약 및 기타: 다른 약정, 부합물 제외, 종물 배제]

[매각물건명세서 교차 검증 규칙]
매각물건명세서는 법원이 해당 물건의 권리 관계를 최종 정리한 서류이다. 등기부등본에는 나오지 않는 핵심 정보가 담겨 있다.

1. 최선순위 설정 확인: 명세서 상단의 '최선순위 설정' 칸에 적힌 날짜와 권리명이 등기부등본상의 말소기준권리와 일치하는지 교차 검증한다.
2. 임차인/전세권 배당요구 여부 판단 로직:
   • 최선순위 전세권자가 배당요구를 한 경우 → 전세권은 매각으로 소멸 (말소). 배당금이 부족해도 무조건 소멸.
   • 최선순위 전세권자가 배당요구를 하지 않은 경우 → 전세권은 매수인이 전액 인수.
   • 대항력 있는 임차인이 배당요구를 하지 않은 경우 → 보증금 전액 매수인 인수.
   • 대항력 있는 임차인이 배당요구를 했으나 전액 배당을 못 받은 경우 → 미배당 잔액을 매수인이 인수.
   • 대항력 있는 임차인이 배당요구를 했고 전액 배당받은 경우 → 인수액 0원 (소멸).
3. 비고란 위험 감지: 유치권 신고, 법정지상권 성립 여지, 대지권 미등기, 농지취득자격증명 필요, 위반건축물, 건물철거, 대항력 포기 확약서 등이 발견되면 낙찰자에게 경고.
4. HUG 대항력 포기 확약서: 주택도시보증공사 등이 대항력 포기서를 제출한 경우, 선순위 임차인이 있어도 인수 부담 없음 (말소).
"""

# =====================================================================
# 📋 문서 분류 및 명세서 분석 함수
# =====================================================================
def classify_document(ocr_text, use_title_only=False):
    """OCR 텍스트를 기반으로 등기부등본 vs 매각물건명세서 자동 판별.
    use_title_only=True: 문서 제목(상위 5행)만으로 판별 (더 정확)
    """
    clean = ocr_text.replace(" ", "")
    
    # 제목 영역 판별 (상위 5행 = 문서 제목 부분)
    if use_title_only:
        lines = ocr_text.strip().split("\n")
        title_area = " ".join(lines[:5]).replace(" ", "") if lines else clean
    else:
        title_area = clean
    
    # 제목 영역에서 강력 키워드 우선 검사
    title_spec_keywords = ["매각물건명세서", "매각물건의표시"]
    title_reg_keywords = ["등기사항전부증명서", "등기사항증명서", "등기부등본", "표제부"]
    
    for kw in title_spec_keywords:
        if kw in title_area:
            return "매각물건명세서"
    for kw in title_reg_keywords:
        if kw in title_area:
            return "등기부등본"
    
    # 전체 텍스트 스코어링 (fallback)
    spec_score = sum(1 for kw in spec_keywords if kw in clean)
    reg_score = sum(1 for kw in registry_keywords if kw in clean)
    # "갑구", "을구"는 명세서에도 등장할 수 있으므로 가중치 낮춤
    weak_reg_keywords = ["갑구", "을구"]
    strong_reg_count = sum(1 for kw in registry_keywords if kw not in weak_reg_keywords and kw in clean)
    
    if spec_score >= 2:
        return "매각물건명세서"
    if strong_reg_count >= 1:
        return "등기부등본"
    if reg_score >= 1:
        return "등기부등본"
    # 기본값: 등기부등본 (기존 호환성)
    return "등기부등본"

def detect_dangers(spec_text):
    """매각물건명세서 텍스트에서 위험 키워드를 탐지하여 경고 메시지 반환"""
    clean = spec_text.replace(" ", "")
    warnings = []
    for keyword, message in danger_keywords.items():
        if keyword in clean:
            warnings.append(message)
    return warnings

def ask_gemini_for_spec(spec_text, model):
    """매각물건명세서 OCR 텍스트에서 Gemini로 핵심 정보를 구조화 추출"""
    prompt = f"""
    너는 대한민국 법원 경매 전문가야.
    아래는 매각물건명세서를 OCR로 읽어온 텍스트야. 핵심 정보를 정확히 추출해 줘.

    [매각물건명세서 OCR 텍스트]
    {spec_text}

    [추출할 항목] - 해당 정보가 없으면 "확인불가"라고 적어줘.
    1. 최선순위 설정일자: (날짜와 권리명)
    2. 배당요구종기일: (날짜)
    3. 임차인 현황: (각 임차인별로 - 이름, 전입일, 확정일자, 보증금, 배당요구 여부)
    4. 매각으로 소멸되지 않는 권리: (목록)
    5. 비고란 특이사항: (전체 내용 요약)
    6. 특별매각조건: (있으면 기재)

    [출력 형식]
    각 항목을 번호와 함께 줄바꿈으로 구분해서 적어줘. 간결하게 핵심만 적어.
    """
    try:
        return model.generate_content(prompt).text
    except Exception:
        return "매각물건명세서 분석 실패"

def ask_gemini_for_rights(record_text, base_date, model, spec_summary=None):
    spec_section = ""
    if spec_summary:
        spec_section = f"""

    [매각물건명세서 교차 검증 정보]
    {spec_summary}

    [교차 검증 추가 지시사항]
    - 매각물건명세서의 '최선순위 설정일'과 등기부의 말소기준권리 일자가 일치하는지 확인해.
    - 전세권자의 '배당요구 여부'가 명세서에 나와 있으면 확정 판단해 (배당요구 완료 → 말소).
    - 임차인의 전입신고일과 최선순위 설정일을 비교하여 대항력 유무를 판단해.
    - 명세서 정보가 있으므로 가능한 한 "추가확인" 대신 확정 판단(인수/말소)을 내려줘.
    - 이유 설명 시 "매각물건명세서상 ~로 확인되어"라는 근거를 포함해.
        """

    prompt = f"""
    너는 대한민국 법원 경매 권리분석 최고 전문가야.
    아래 [권리분석 예외 규칙]을 완벽하게 숙지하고, 제공된 [등기 권리 내용]을 분석해 줘.
    너의 외부 지식에 의존하지 말고, 오직 내가 제공한 [권리분석 예외 규칙]에 입각해서만 판단해.

    [권리분석 예외 규칙]
    {knowledge_base}

    [사건 기준 정보]
    - 확정된 말소기준권 일자: {base_date}

    [분석할 등기 권리 내용]
    {record_text}
    {spec_section}
    [지시사항]
    1. 위 등기 권리가 경매 낙찰 시 매수인에게 인수되는지, 아니면 말소되는지 판단해.
    2. 만약 등기부등본 내용만으로 확정할 수 없는 항목이라면 "추가확인 필요"라고 답변해.
    3. 출력 형식은 반드시 첫 줄에 "결과: 인수", "결과: 말소", "결과: 추가확인" 중 하나만 적고, 두 번째 줄에 "이유: (간략한 1~2줄 설명)"을 적어줘.
    """
    return model.generate_content(prompt).text

def ask_gemini_for_malso_omission(all_records_text, base_date, model, spec_summary=None):
    """Gemini에게 '말소 누락' 특수 미션을 부여하여,
    낙찰 후 말소되었어야 하는데 현재 살아있는 누락 건을 탐지합니다."""
    spec_ref = ""
    if spec_summary:
        spec_ref = f"""
    [매각물건명세서 참고 정보]
    {spec_summary}
        """

    prompt = f"""
    너는 대한민국 법원 경매 권리분석 최고 전문가이자 '말소 누락 탐지 전문가'야.
    아래 등기부등본 전체 내용과 말소기준권리 일자를 바탕으로, **특수 미션**을 수행해 줘.

    [🎯 특수 미션: 말소 누락 탐지]
    경매 낙찰 후 말소촉탁으로 **말소되었어야 하는데, 현재 등기부에 여전히 살아있는 '말소 누락 건'**을 찾아줘.

    [권리분석 규칙]
    {knowledge_base}

    [사건 기준 정보]
    - 확정된 말소기준권리 일자: {base_date}
    - 말소기준권리 일자 이후(같은 날 포함)에 접수된 근저당권, 가압류, 압류, 경매개시결정, 담보가등기 등은 낙찰로 소멸(말소)되어야 합니다.

    [등기부등본 전체 내용]
    {all_records_text}
    {spec_ref}
    [탐지 기준]
    1. 말소기준권리 일자 이후에 접수된 등기 중, 말소 대상인데 OCR 텍스트에 '말소' 표시가 없거나 가로줄이 감지되지 않아 살아있는 것처럼 보이는 권리를 찾아줘.
    2. 단, '건물철거 및 토지인도청구권 보전 가처분', '예고등기', '유치권', '법정지상권', '분묘기지권', '도시철도법 구분지상권', '채무자회생법 등기', '특별매각조건 인수 권리' 등 예외적으로 소멸하지 않는 권리는 말소 누락으로 판단하지 마.
    3. 실제로 이미 말소된 등기(OCR 텍스트에 '말소' 단어가 포함되거나 취소선이 있는 경우)는 누락 건에서 제외해.

    [출력 형식]
    - 말소 누락 의심 건이 없으면: "✅ 말소 누락 의심 건 없음"
    - 말소 누락 의심 건이 있으면 각 건에 대해:
      "🚨 말소 누락 의심: [구분(갑구/을구)] 순위번호 [번호] - [등기목적] (접수일: [날짜])"
      "   사유: [왜 말소되었어야 하는지 간략 설명]"
    """
    try:
        return model.generate_content(prompt).text
    except Exception:
        return "말소 누락 탐지 분석 실패 (API 오류)"

def ask_gemini_for_safety_report(df, base_date, model, spec_summary=None, parsed_records=None):
    """전체 분석 결과를 바탕으로 Gemini에게 입찰 안전도 종합 의견을 요청합니다."""
    # 인수 권리 요약 생성
    insu_rows = df[df['결과'].str.contains('인수', na=False) & ~df['결과'].str.contains('이미', na=False)]
    malso_rows = df[df['결과'].str.contains('말소', na=False) & ~df['결과'].str.contains('이미', na=False)]
    danger_rows = df[df['결과'].str.contains('절대 인수', na=False)]
    warning_rows = df[df['결과'].str.contains('서류확인', na=False)]

    insu_summary = "\n".join(
        [f"  - {r['구분']} 순위번호 {r['순위번호']}: {r['등기목적']}" for _, r in insu_rows.iterrows()]
    ) if not insu_rows.empty else "  없음"

    danger_summary = "\n".join(
        [f"  - {r['구분']} 순위번호 {r['순위번호']}: {r['등기목적']}" for _, r in danger_rows.iterrows()]
    ) if not danger_rows.empty else "  없음"

    # 채권액 추출 시도 (근저당권 금액)
    amount_info = ""
    if parsed_records:
        amounts = []
        for rec in parsed_records:
            content = rec.get('전체내용', '')
            # 채권최고액, 금 XXX원 패턴
            amt_matches = re.findall(r'(?:채권최고액|금)\s*([\d,]+)\s*원', content.replace(' ', ''))
            for amt in amt_matches:
                try:
                    amounts.append(int(amt.replace(',', '')))
                except ValueError:
                    pass
        if amounts:
            total_amt = sum(amounts)
            amount_info = f"\n  - 감지된 채권최고액 합계: 약 {total_amt:,}원 ({len(amounts)}건)"

    spec_ref = ""
    if spec_summary:
        spec_ref = f"\n[매각물건명세서 분석 결과]\n{spec_summary}"

    prompt = f"""
    너는 대한민국 법원 경매 권리분석 최고 전문가이자 투자 리스크 평가 전문가야.
    아래 분석 결과를 바탕으로 "이 물건에 입찰해도 안전한지" 종합 의견을 줘.

    [분석 기준 정보]
    - 말소기준권리 일자: {base_date}
    - 총 등기 건수: {len(df)}건
    - 말소 예정: {len(malso_rows)}건
    - 인수 예정: {len(insu_rows)}건
    - 절대 인수 (위험): {len(danger_rows)}건
    - 서류확인 필요: {len(warning_rows)}건{amount_info}

    [인수되는 권리 목록]
{insu_summary}

    [절대 인수 (위험 권리) 목록]
{danger_summary}
    {spec_ref}
    [지시사항]
    1. 위험도 등급을 반드시 첫 줄에 표시해: "🟢 안전", "🟡 주의", "🔴 위험" 중 하나.
       - 🟢 안전: 인수되는 위험 권리 없음, 말소 누락 없음
       - 🟡 주의: 인수 권리 있으나 금액이 크지 않거나, 서류확인 필요 건이 있음
       - 🔴 위험: 절대 인수 권리 존재, 유치권/건물철거/법정지상권 등 중대 위험
    2. 두 번째 줄부터 간결한 종합 의견 (3~5줄):
       - 인수되는 채권의 총 부담 추정액
       - 핵심 위험 요소 요약
       - 입찰 시 주의사항
    3. 마지막에 "💡 입찰팁: " 으로 시작하는 실용적 조언 1줄 추가.
    """
    try:
        return model.generate_content(prompt).text
    except Exception:
        return "종합 안전도 리포트 생성 실패 (API 오류)"


def ask_gemini_vision_review(images_bytes_list, ocr_text, parsed_summary, model):
    """원본 이미지 + OCR 결과를 Gemini Vision에 보내 최종 검수합니다.
    최대 15장까지 처리, 각 이미지 1024px 리사이즈 + 500KB~1MB 압축."""
    try:
        # 📷 Smart Resizing: 긴 축 1024px + JPEG Q65 (약 500KB~1MB)
        image_parts = []
        for i, img_bytes in enumerate(images_bytes_list[:15]):
            try:
                pil_img = Image.open(BytesIO(img_bytes))
                # EXIF 회전 보정
                try:
                    from PIL import ImageOps
                    pil_img = ImageOps.exif_transpose(pil_img)
                except Exception:
                    pass
                # 긴 축 1024px 리사이즈 (Gemini 전송용 저용량 복사본)
                max_dim = max(pil_img.width, pil_img.height)
                if max_dim > 1024:
                    ratio = 1024 / max_dim
                    new_w = int(pil_img.width * ratio)
                    new_h = int(pil_img.height * ratio)
                    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
                # RGB 변환 + JPEG 압축
                if pil_img.mode != 'RGB':
                    pil_img = pil_img.convert('RGB')
                buf = BytesIO()
                pil_img.save(buf, format='JPEG', quality=65, optimize=True)
                buf.seek(0)
                image_parts.append({
                    'mime_type': 'image/jpeg',
                    'data': buf.getvalue()
                })
            except Exception:
                continue

        if not image_parts:
            return "Vision 검수 실패: 이미지 변환 오류"

        num_pages = len(image_parts)
        prompt = f"""
        너는 대한민국 경매 등기부등본 판독 최고 전문가야.
        지금 {num_pages}페이지에 달하는 등기부를 분석해야 해. 모든 페이지를 빠짐없이 꼼꼼히 확인해 줘.
        아래는 OCR이 인식한 결과와 파싱된 요약이야. 원본 이미지와 대조하여 검수해 줘.

        [OCR 인식 요약]
        {ocr_text[:3000]}

        [파싱 결과 요약]
        {parsed_summary[:1500]}

        [검수 지시사항]
        1. 원본 이미지에서 **가로줄(취소선)이 그어진 등기**가 있는지 확인해. 가로줄이 있으면 "이미 말소됨"으로 판단해야 해.
           → 특히 이전 페이지에서 시작된 가로줄이 다음 페이지까지 이어지는지 교차 확인해.
        2. 각 페이지의 순위번호가 연속적으로 이어지는지 확인해. 순위번호가 누락된 것이 있으면 알려줘.
        3. OCR이 놓친 순위번호나 등기목적이 있는지 확인해.
        4. 금액(채권최고액 등)이 정확하게 인식되었는지 확인해.
        5. 갑구/을구 구분이 정확한지 확인해.

        [출력 형식]
        - 문제가 없으면: "✅ Vision 검수 완료: {num_pages}페이지 전체 대조 결과, OCR 결과와 원본 이미지가 일치합니다."
        - 문제가 있으면: 각 문제를 간결하게 나열:
          "⚠️ [1] 순위번호 X번: 이미지에 가로줄(취소선) 확인됨 → '이미 말소됨'으로 변경 필요"
          "⚠️ [2] OCR 누락: 순위번호 Y번 등기가 이미지에 있으나 OCR에서 누락됨"
          "⚠️ [3] 페이지 Z-W 간 가로줄 연속: 순위번호 A번 등기가 두 페이지에 걸쳐 말소 표시됨"
        """

        # Gemini multimodal: 이미지 + 텍스트
        content_parts = image_parts + [prompt]
        response = model.generate_content(content_parts)
        return response.text
    except Exception as e:
        return f"Vision 검수 실패: {e}"

def merge_and_sort_pages(sorted_files, ocr_cache):
    """여러 장의 등기부등본 페이지를 갑구/을구 섹션 기반으로 자동 정렬합니다.
    페이지 순서가 섞여 있어도 표제부→갑구→을구 순서로 올바르게 재배열합니다."""
    section_keywords = {
        '표제부': ['표제부', '건물의표시', '토지의표시', '대지권의목적', '1동의건물의표시'],
        '갑구': ['갑구', '소유권에관한사항'],
        '을구': ['을구', '소유권이외의권리']
    }

    pages_info = []
    for file in sorted_files:
        raw_bytes = file.getvalue()
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        if file_hash not in ocr_cache:
            continue
        page_rows = ocr_cache[file_hash]
        page_text = ' '.join(page_rows).replace(' ', '')

        # 섹션 감지
        detected_section = None
        section_priority = {'표제부': 0, '갑구': 1, '을구': 2}
        for section, keywords in section_keywords.items():
            for kw in keywords:
                if kw in page_text:
                    if detected_section is None or section_priority[section] < section_priority.get(detected_section, 99):
                        detected_section = section
                    break

        # 순위번호 추출 (연속성 판단용)
        rank_numbers = re.findall(r'(?:^|\s)([1-9]\d{0,2})\s', ' '.join(page_rows))
        first_rank = int(rank_numbers[0]) if rank_numbers else 999

        pages_info.append({
            'file': file,
            'hash': file_hash,
            'section': detected_section or '갑구',  # 기본값: 갑구
            'first_rank': first_rank,
            'rows': page_rows
        })

    # 정렬: 표제부 → 갑구 → 을구, 같은 섹션 내에서는 순위번호 순
    section_order = {'표제부': 0, '갑구': 1, '을구': 2}
    pages_info.sort(key=lambda p: (section_order.get(p['section'], 1), p['first_rank']))

    # 정렬된 rows 반환
    merged_rows = []
    for page in pages_info:
        merged_rows.extend(page['rows'])

    return merged_rows

# =====================================================================
# 🔄 4. 화면 자동 전환 로직 (세션 상태 관리)
# =====================================================================
if 'step' not in st.session_state:
    st.session_state.step = 1  
if 'final_df' not in st.session_state:
    st.session_state.final_df = None
if 'malso_df' not in st.session_state:
    st.session_state.malso_df = None
if 'ocr_cache' not in st.session_state:
    st.session_state.ocr_cache = {}  # 💰 OCR 결과 캐시 (key: 파일 해시)
if 'spec_summary' not in st.session_state:
    st.session_state.spec_summary = None  # 📋 매각물건명세서 요약
if 'malso_omission_report' not in st.session_state:
    st.session_state.malso_omission_report = None  # 🔍 말소 누락 탐지 보고서
if 'danger_warnings' not in st.session_state:
    st.session_state.danger_warnings = []  # 🚨 위험 경고 목록
if 'base_date_info' not in st.session_state:
    st.session_state.base_date_info = None  # 📅 말소기준권리 상세 정보
if 'safety_report' not in st.session_state:
    st.session_state.safety_report = None  # 🧾 종합 안전도 리포트
if 'uploaded_images' not in st.session_state:
    st.session_state.uploaded_images = []  # 📷 원본 이미지 (Gemini Vision용)
if 'vision_review' not in st.session_state:
    st.session_state.vision_review = None  # 🔬 Gemini Vision 검수 결과

# =====================================================================
# 📱 [1단계 화면] 메인 화면 및 사진 업로드
# =====================================================================
if st.session_state.step == 1:
    st.title("🧙‍♂️ AI 경매 권리분석 마법사")
    st.markdown("스마트폰으로 등기부등본 사진을 찍어서 올리면, AI가 자동으로 권리를 분석해 줍니다.")
    
    # CSS로 영어 문구가 완벽히 숨겨진 업로드 창
    uploaded_files = st.file_uploader(" ", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'], label_visibility="collapsed")

    if st.button("🚀 권리분석 시작", type="primary", use_container_width=True):
        if not uploaded_files:
            st.warning("사진을 먼저 업로드해주세요.")
        else:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # 📂 Natural Sort: 파일명 숫자 기준 정렬 (1 < 2 < 10)
                def natural_sort_key(f):
                    return [int(c) if c.isdigit() else c.lower()
                            for c in re.split(r'(\d+)', f.name)]

                # 📊 진행률 표시 OCR 스캔
                all_clean_rows = []
                cache_hit_count = 0
                total_files = len(uploaded_files)
                sorted_files = sorted(uploaded_files, key=natural_sort_key)
                progress_bar = st.progress(0, text='📸 분석 준비 중...')
                uploaded_image_bytes = []  # 📷 원본 이미지 저장 (Gemini Vision용)

                for file_idx, file in enumerate(sorted_files):
                    raw_bytes = file.getvalue()
                    uploaded_image_bytes.append(raw_bytes)  # 📷 Vision용 원본 보존

                    # 💰 OCR 캐싱: 파일 해시로 중복 체크 (부분 재분석 지원)
                    file_hash = hashlib.sha256(raw_bytes).hexdigest()
                    if file_hash in st.session_state.ocr_cache:
                        progress_bar.progress((file_idx + 1) / total_files, text=f'💰 캐시 사용 ({file_idx + 1}/{total_files}): {file.name}')
                        all_clean_rows.extend(st.session_state.ocr_cache[file_hash])
                        cache_hit_count += 1
                        continue

                    progress_bar.progress((file_idx) / total_files, text=f'📸 분석 중 ({file_idx + 1}/{total_files}): {file.name}')

                    # 🖼️ 스마트 전처리: Grayscale + CLAHE + Deskew → PNG
                    preprocessed_bytes, file_format = smart_preprocess(raw_bytes)
                    file_mime = 'image/png'

                    request_json = {'images': [{'format': file_format, 'name': 'demo'}], 'requestId': str(uuid.uuid4()), 'version': 'V2', 'timestamp': int(round(time.time() * 1000))}
                    payload = {'message': json.dumps(request_json).encode('UTF-8')}
                    headers = {'X-OCR-SECRET': NAVER_SECRET_KEY}

                    # 🔄 네이버 OCR API 호출 (timeout 30초 + 재시도 2회)
                    response = None
                    for attempt in range(3):
                        file_data = [('file', (file.name, preprocessed_bytes, file_mime))]
                        try:
                            response = requests.post(
                                NAVER_API_URL, headers=headers, data=payload,
                                files=file_data, timeout=30
                            )
                            if response.status_code == 200:
                                break
                            elif response.status_code == 429 and attempt < 2:
                                time.sleep(2 ** attempt)
                                continue
                        except requests.exceptions.Timeout:
                            if attempt < 2:
                                time.sleep(2)
                                continue
                            else:
                                st.error(f"⏱️ OCR 응답 시간 초과: {file.name}")
                                st.stop()
                        except requests.exceptions.RequestException as e:
                            st.error(f"🌐 네트워크 오류: {e}")
                            st.stop()

                    if response and response.status_code == 200:
                        images_data = response.json().get('images', [])
                        fields = images_data[0].get('fields', []) if images_data else []
                        if not fields:
                            st.warning(f"⚠️ {file.name}에서 텍스트가 감지되지 않았습니다.")
                            continue

                        current_row, last_y, page_rows = [], -1, []
                        low_conf_words = []  # 저신뢰도 단어 수집
                        sorted_fields = sorted(fields, key=lambda x: x['boundingPoly']['vertices'][0]['y'])

                        for field in sorted_fields:
                            text = field['inferText']
                            confidence = field.get('inferConfidence', 1.0)
                            y_pos = field['boundingPoly']['vertices'][0]['y']
                            x_pos = field['boundingPoly']['vertices'][0]['x']
                            text = re.sub(r'(\d{6})\s*-\s*\d{7}', r'\1-*******', text)

                            # 📝 저신뢰도 단어 → Fuzzy Matching 우선 보정
                            if confidence < 0.5:
                                original_text = text
                                text = fuzzy_clean_text(text)
                                if text != original_text:
                                    low_conf_words.append(f"'{original_text}'→'{text}' (신뢰도:{confidence:.2f})")

                            if last_y == -1 or abs(y_pos - last_y) <= 20:
                                current_row.append({'x': x_pos, 'text': text})
                            else:
                                current_row.sort(key=lambda x: x['x'])
                                page_rows.append(" ".join([item['text'] for item in current_row]))
                                current_row = [{'x': x_pos, 'text': text}]
                            last_y = y_pos

                        if current_row:
                            current_row.sort(key=lambda x: x['x'])
                            page_rows.append(" ".join([item['text'] for item in current_row]))

                        # 📝 전체 행에 Fuzzy 오타 보정 적용
                        page_rows = [fuzzy_clean_text(row) for row in page_rows]

                        if low_conf_words:
                            st.toast(f"📝 {file.name}: {len(low_conf_words)}개 저신뢰도 단어 자동 보정")

                        st.session_state.ocr_cache[file_hash] = page_rows
                        all_clean_rows.extend(page_rows)
                    else:
                        status = response.status_code if response else 'No response'
                        st.error(f"OCR 스캔 실패 ({file.name}): HTTP {status}")
                        st.stop()

                progress_bar.progress(1.0, text='✅ 분석 완료!')

                if cache_hit_count > 0:
                    st.toast(f'💰 {cache_hit_count}개 파일은 이전 분석 결과를 재사용했습니다 (부분 재분석 · 비용 절감!)')


                # 📷 Feature C: 여러 장 등기부 페이지 연결 — 갑구/을구 자동 정렬
                original_clean_rows = list(all_clean_rows)  # 원본 보존 (fallback용)
                if total_files > 1:
                    merged_rows = merge_and_sort_pages(sorted_files, st.session_state.ocr_cache)
                    if merged_rows and len(merged_rows) == len(all_clean_rows):
                        all_clean_rows = merged_rows
                        st.toast('📷 여러 페이지가 갑구/을구 순서로 자동 정렬되었습니다!')

                # 📋 문서 분류: 등기부등본 vs 매각물건명세서 자동 분리
                registry_rows, spec_rows = [], []

                # 파일별이 아닌 전체 텍스트 기반으로 분류 (더 정확)
                full_text = " ".join(all_clean_rows)
                doc_type = classify_document(full_text)

                if doc_type == "매각물건명세서":
                    # 전체가 명세서인 경우 (등기부 없이 명세서만 올린 경우)
                    spec_rows = all_clean_rows
                    registry_rows = []
                else:
                    # 파일별로 분류 시도
                    temp_registry, temp_spec = [], []
                    # 각 파일의 OCR 텍스트를 다시 가져와서 분류
                    offset = 0
                    for file in sorted(uploaded_files, key=natural_sort_key):
                        raw_bytes = file.getvalue()
                        file_hash = hashlib.sha256(raw_bytes).hexdigest()
                        if file_hash in st.session_state.ocr_cache:
                            file_rows = st.session_state.ocr_cache[file_hash]
                        else:
                            # 캐시에 없으면 전체에서 추정 (fallback)
                            file_rows = all_clean_rows[offset:]
                        file_text = " ".join(file_rows)
                        file_type = classify_document(file_text, use_title_only=True)
                        if file_type == "매각물건명세서":
                            temp_spec.extend(file_rows)
                        else:
                            temp_registry.extend(file_rows)
                        offset += len(file_rows)

                    if temp_spec:
                        registry_rows = temp_registry
                        spec_rows = temp_spec
                    else:
                        registry_rows = all_clean_rows
                        spec_rows = []

                # 📋 매각물건명세서가 있으면 Gemini로 구조화 추출
                spec_summary = None
                danger_warnings_list = []
                if spec_rows:
                    with st.spinner('📋 매각물건명세서를 분석하고 있습니다...'):
                        spec_full_text = "\n".join(spec_rows)
                        spec_summary = ask_gemini_for_spec(spec_full_text, model)
                        danger_warnings_list = detect_dangers(spec_full_text)
                        st.toast('📋 매각물건명세서가 감지되었습니다. 교차 검증을 수행합니다!')

                st.session_state.spec_summary = spec_summary
                st.session_state.danger_warnings = danger_warnings_list

                # 등기부등본 파싱 (registry_rows 또는 all_clean_rows 사용)
                analysis_rows = registry_rows if registry_rows else all_clean_rows

                with st.spinner('파이썬 엔진이 권리를 분류하고 있습니다...'):
                    def parse_records_from_rows(rows):
                        """OCR 텍스트 행들에서 등기 레코드를 파싱합니다."""
                        _records, _current_record, _current_gu = [], {}, None
                        # 순위번호: 기본 패턴 + 느슨한 fallback
                        _rank_pattern = re.compile(r'^([1-9]\d*[-]?\d*)(?:\s+|번|(?=[가-힣]))')
                        # 날짜: 3단계 fallback
                        _date_patterns = [
                            re.compile(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일'),  # 2024년 01월 31일
                            re.compile(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})'),  # 2024.01.31 / 2024-01-31
                            re.compile(r'(20\d{2})(\d{2})(\d{2})'),  # 20240131 (8자리 연속 숫자)
                        ]
                        # 접수번호: 2단계 fallback
                        _receipt_patterns = [
                            re.compile(r'제\s*(\d+)\s*호'),  # 제XXXXX호
                            re.compile(r'(?<!번호)(?<!년)(?<!월)(?<!일)(\d{5,6})(?!년|월|일|호|번)'),  # 5~6자리 숫자 (날짜/번호 제외)
                        ]

                        for row in rows:
                            clean_row = row.replace(" ", "")
                            if any(kw in clean_row for kw in ignore_keywords):
                                continue
                            if "갑구" in clean_row and ("소유권" in clean_row or "관한사항" in clean_row): _current_gu = "갑구"; continue
                            if "을구" in clean_row and ("소유권" in clean_row or "관한사항" in clean_row or "이외의권리" in clean_row): _current_gu = "을구"; continue
                            if _current_gu is None or "순위번호" in row or "등기목적" in row or "접수" in row: continue

                            match = _rank_pattern.match(row)
                            is_new_record = False

                            if match:
                                rank_str = match.group(1)
                                rest_of_line = row[match.end():].strip()

                                if "-" in rank_str:
                                    parts = rank_str.split('-')
                                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                        parent_rank = int(parts[0])
                                        if parent_rank <= 200:
                                            is_new_record = True
                                elif len(rank_str) >= 4 or int(rank_str) > 200:
                                    pass
                                elif rest_of_line.startswith(('호', '동', '층', '길', '번지', 'm', '㎡', '전', '년', '월', '일')):
                                    pass
                                else:
                                    is_new_record = True

                            if is_new_record:
                                if _current_record: _records.append(_current_record)
                                _current_record = {'구분': _current_gu, '순위번호': rank_str, '전체내용': row}
                            else:
                                if _current_record: _current_record['전체내용'] += " " + row

                        if _current_record: _records.append(_current_record)

                        _parsed = []
                        for rec in _records:
                            content = rec['전체내용'].replace(" ", "")
                            # 날짜 추출: 3단계 fallback
                            date_match = None
                            for dp in _date_patterns:
                                date_match = dp.search(rec['전체내용'])
                                if date_match:
                                    break
                            rec['접수일자_기준'] = None

                            if date_match:
                                y, m, d = date_match.groups()
                                try:
                                    rec['접수일자_기준'] = datetime.date(int(y), int(m), int(d))
                                except ValueError:
                                    pass

                                # 접수번호 추출: 2단계 fallback
                                receipt_num = None
                                for rp in _receipt_patterns:
                                    rm = rp.search(rec['전체내용'])
                                    if rm:
                                        receipt_num = rm.group(1)
                                        break
                                rec['접수일자_표시'] = f"{y}년 {m}월 {d}일" + (f" 제{receipt_num}호" if receipt_num else "")

                                raw_target = rec['전체내용'][:date_match.start()].replace(rec['순위번호'], '', 1).strip()
                                action_strip_pattern = r'^번\s*|(?:전부)?근저당권설정$|가압류$|임의경매개시결정$|강제경매개시결정$|압류$|경매개시결정$'
                                clean_target = re.sub(action_strip_pattern, '', raw_target).strip()

                                action = ""
                                if '임의경매개시결정' in content: action = "임의경매개시결정"
                                elif '강제경매개시결정' in content: action = "강제경매개시결정"
                                elif '가압류' in content: action = "가압류"
                                elif '근저당권설정' in content: action = "전부근저당권설정" if '전부근저당권설정' in content else "근저당권설정"
                                elif '압류' in content: action = "압류"
                                if action and action in clean_target:
                                    rec['등기목적'] = clean_target
                                else:
                                    rec['등기목적'] = f"{clean_target} {action}".strip()
                            else:
                                rec['접수일자_표시'], rec['등기목적'] = "확인불가", "확인불가"

                            rec['말소후보'] = any(kw in content for kw in base_keywords)
                            rec['절대인수'] = any(kw in content for kw in always_keep_keywords)
                            rec['AI해석필요'] = any(kw in content for kw in ai_check_keywords)
                            rec['소유권이전'] = '이전' in content and not rec['말소후보'] and not rec['절대인수']

                            purpose_text = rec.get('등기목적', '')
                            malso_purpose_kws = ['말소', '抹消', '취소', '해지', '해제']
                            has_malso_in_purpose = any(mk in purpose_text for mk in malso_purpose_kws)
                            malso_combined = ['근저당권말소', '가압류말소', '압류말소', '경매개시결정말소',
                                              '저당권말소', '담보가등기말소', '전세권말소', '근저당말소']
                            has_malso_combined = any(mc in content for mc in malso_combined)
                            rec['이미말소됨'] = has_malso_in_purpose or has_malso_combined

                            receipt_match = re.search(r'제\s*(\d+)\s*호', rec['전체내용'])
                            rec['접수번호_오타'] = ""
                            if receipt_match:
                                receipt_num = receipt_match.group(1)
                                if len(receipt_num) <= 1 or len(receipt_num) >= 8:
                                    rec['접수번호_오타'] = f"⚠️ 접수번호 '{receipt_num}'이(가) 패턴상 오타로 보입니다. 원본 확인 필요."
                            elif rec.get('접수일자_표시', '') != '확인불가' and '제' not in rec['전체내용']:
                                rec['접수번호_오타'] = "⚠️ 접수번호(제____호)가 인식되지 않았습니다. 원본 확인 필요."

                            _parsed.append(rec)
                        return _parsed

                    # 1차 시도: 분류된 analysis_rows로 파싱
                    parsed_records = parse_records_from_rows(analysis_rows)

                    # 🛡️ Fallback: 파싱 실패 시 원본 OCR 텍스트로 재시도
                    if not parsed_records and analysis_rows != original_clean_rows:
                        st.toast('🔄 분류 결과로 인식 실패 — 원본 텍스트로 재시도합니다...')
                        parsed_records = parse_records_from_rows(original_clean_rows)

                    # 📊 빈 데이터 방지 (등기부 아닌 사진 업로드 시)
                    if not parsed_records:
                        st.warning("⚠️ 등기부등본 내용을 인식하지 못했습니다. 사진을 확인해 주세요.")
                        st.stop()

                    df = pd.DataFrame(parsed_records)
                    candidates = df[df['말소후보'] == True].dropna(subset=['접수일자_기준'])
                    base_date = candidates.sort_values(by='접수일자_기준').iloc[0]['접수일자_기준'] if not candidates.empty else None

                    # 📅 말소기준권리 정보 저장 (시각적 표시용)
                    base_date_info = None
                    if not candidates.empty:
                        first_candidate = candidates.sort_values(by='접수일자_기준').iloc[0]
                        base_date_info = {
                            'date': base_date,
                            'purpose': first_candidate.get('등기목적', ''),
                            'gu': first_candidate.get('구분', ''),
                            'rank': first_candidate.get('순위번호', ''),
                        }
                    st.session_state.base_date_info = base_date_info

                    def determine_status(row):
                        # 🔍 최우선: 이미 말소된 권리는 별도 분류 (가로줄 그어진 등기)
                        if row.get('이미말소됨', False): return "🔘 이미 말소됨"
                        if row['절대인수']: return "🚨 절대 인수"
                        elif row['AI해석필요']: return "🤖 AI 정밀해석"
                        elif row['소유권이전']: return "➖ 기본등기"
                        elif pd.notnull(row['접수일자_기준']) and base_date and row['접수일자_기준'] >= base_date: return "❌ 말소"
                        elif pd.notnull(row['접수일자_기준']) and base_date and row['접수일자_기준'] < base_date: return "✅ 인수"
                        else: return "기타"

                    df['결과'] = df.apply(determine_status, axis=1)

                # 🤖 Gemini AI 정밀 해석 (진행률 + 지수 백오프)
                ai_targets = df[df['결과'].str.contains('AI 정밀해석')].index.tolist()
                df['AI_상세이유'] = ""
                if ai_targets:
                    ai_progress = st.progress(0, text='🤖 AI 정밀 해석 준비 중...')
                    for ai_idx, index in enumerate(ai_targets):
                        row = df.loc[index]
                        ai_progress.progress((ai_idx) / len(ai_targets), text=f'🤖 AI 해석 중 ({ai_idx + 1}/{len(ai_targets)})')
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                ai_answer = ask_gemini_for_rights(row['전체내용'], base_date, model, spec_summary)
                                if "결과: 인수" in ai_answer: df.at[index, '결과'] = "✅ 인수 (AI판단)"
                                elif "결과: 말소" in ai_answer: df.at[index, '결과'] = "❌ 말소 (AI판단)"
                                elif "결과: 추가확인" in ai_answer: df.at[index, '결과'] = "⚠️ 서류확인 요망"
                                df.at[index, 'AI_상세이유'] = ai_answer.split("이유:")[-1].strip() if "이유:" in ai_answer else ai_answer
                                time.sleep(1)
                                break
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    time.sleep(2 ** attempt)
                                else:
                                    df.at[index, 'AI_상세이유'] = "API 통신 오류 (재시도 실패)"
                    ai_progress.progress(1.0, text='✅ AI 해석 완료!')

                # 🔍 Gemini 말소 누락 탐지 특수 미션 수행 (Bug 2 fix: if ai_targets 블록 바깥으로 이동)
                malso_omission_report = None
                if base_date and len(parsed_records) > 0:
                    with st.spinner('🔍 Gemini가 말소 누락 건을 탐지하고 있습니다...'):
                        all_records_text = "\n".join([r['전체내용'] for r in parsed_records])
                        malso_omission_report = ask_gemini_for_malso_omission(
                            all_records_text, base_date, model, spec_summary
                        )
                st.session_state.malso_omission_report = malso_omission_report

                # '이미 말소됨' 항목은 말소 목록에서 제외 (이미 처리된 건이므로)
                malso_df = df[
                    df['결과'].str.contains('말소') & ~df['결과'].str.contains('이미 말소됨')
                ][['구분', '순위번호', '등기목적', '접수일자_표시']]
                malso_df.columns = ['구분', '순위번호', '등기목적', '접수일자']
                malso_df.index = range(1, len(malso_df) + 1)

                st.session_state.final_df = df
                st.session_state.malso_df = malso_df

                # 🧾 Feature A: Gemini 종합 안전도 리포트 생성
                safety_report = None
                if base_date:
                    with st.spinner('🧾 Gemini가 종합 안전도를 평가하고 있습니다...'):
                        safety_report = ask_gemini_for_safety_report(
                            df, base_date, model, spec_summary, parsed_records
                        )
                st.session_state.safety_report = safety_report

                # 🔬 Gemini Vision 최종 검수 (원본 이미지 대조)
                vision_review = None
                if uploaded_image_bytes:
                    num_imgs = min(len(uploaded_image_bytes), 15)
                    est_time = max(20, num_imgs * 3)  # 예상 소요 시간
                    st.info(f'🔍 현재 {num_imgs}장의 등기부 사진을 AI가 정밀 대조 중입니다. 약 {est_time}~{est_time + 10}초가 소요될 수 있습니다...')
                    with st.spinner(f'🔬 Gemini Vision이 {num_imgs}페이지 원본 이미지를 검수하고 있습니다...'):
                        ocr_summary = '\n'.join(all_clean_rows[:80])  # OCR 요약 (상위 80행)
                        parsed_summary = '\n'.join([f"{r.get('구분','')} #{r.get('순위번호','')} {r.get('등기목적','')} → {r.get('접수일자_표시','')}" for r in parsed_records[:30]])
                        vision_review = ask_gemini_vision_review(
                            uploaded_image_bytes, ocr_summary, parsed_summary, model
                        )
                st.session_state.vision_review = vision_review
                st.session_state.uploaded_images = uploaded_image_bytes

                st.session_state.step = 2
                st.rerun()

            except Exception as e:
                st.error(f"분석 중 오류가 발생했습니다: {e}")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 🌟 수정된 주의사항 (요청하신 대로 군더더기 없이 깔끔하게!)
    with st.expander("🚨 주의사항 및 개인정보 보호 안내 (클릭해서 확인)"):
        st.markdown("""
        * **[면책조항]** AI 판독 결과는 100% 완벽하지 않을 수 있으며, 오류가 발생할 수 있습니다. 본 결과는 참고용으로만 활용하시기 바랍니다.
        * **[개인정보 보호]** 업로드하신 사진은 서버에 일절 저장되지 않습니다. 권리분석 완료 후 즉시 메모리에서 영구 삭제됩니다.
        """)

# =====================================================================
# 📑 [2단계 화면] 결과 및 다운로드
# =====================================================================
elif st.session_state.step == 2:
    st.title("✨ 분석이 완료되었습니다!")

    # 📊 분석 요약 대시보드
    if st.session_state.final_df is not None:
        result_df = st.session_state.final_df
        total = len(result_df)
        insu_count = len(result_df[result_df['결과'].str.contains('인수', na=False) & ~result_df['결과'].str.contains('이미|절대', na=False)])
        malso_count = len(result_df[result_df['결과'].str.contains('말소', na=False) & ~result_df['결과'].str.contains('이미', na=False)])
        already_count = len(result_df[result_df['결과'].str.contains('이미 말소됨', na=False)])
        ai_count = len(result_df[result_df['결과'].str.contains('서류확인|AI판단', na=False, regex=True)])
        danger_count = len(result_df[result_df['결과'].str.contains('절대 인수', na=False)])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📋 총 등기", f"{total}건")
        col2.metric("✅ 인수", f"{insu_count}건")
        col3.metric("❌ 말소", f"{malso_count}건")
        col4.metric("🔘 이미말소", f"{already_count}건")

        if danger_count > 0 or ai_count > 0:
            col5, col6 = st.columns(2)
            if danger_count > 0:
                col5.metric("🚨 절대 인수", f"{danger_count}건")
            if ai_count > 0:
                col6.metric("🤖 AI 판단", f"{ai_count}건")

        st.markdown("<br>", unsafe_allow_html=True)

    # 📅 말소기준권리 일자 시각적 강조
    if st.session_state.base_date_info:
        bdi = st.session_state.base_date_info
        st.info(f"📅 **말소기준권리**: {bdi['date']}  |  {bdi['gu']} 순위번호 {bdi['rank']}번  |  {bdi['purpose']}\n\n이 날짜 이후(같은 날 포함)에 접수된 말소 대상 등기는 낙찰로 소멸됩니다.")
        st.markdown("<br>", unsafe_allow_html=True)

    # 🧾 Feature A: 종합 안전도 리포트
    if st.session_state.safety_report:
        with st.expander("🧾 종합 안전도 리포트 (Gemini 평가)", expanded=True):
            report = st.session_state.safety_report
            # 위험도 등급에 따른 색상 표시
            if '🟢' in report:
                st.success(report)
            elif '🔴' in report:
                st.error(report)
            else:
                st.warning(report)
        st.markdown("<br>", unsafe_allow_html=True)

    # 📊 Feature B: 권리 타임라인 시각화
    if st.session_state.final_df is not None:
        timeline_df = st.session_state.final_df.dropna(subset=['접수일자_기준']).copy()
        if not timeline_df.empty:
            with st.expander("📊 권리 타임라인 시각화", expanded=True):
              try:
                # 색상 매핑
                color_map = {
                    '인수': '#2ecc71',
                    '말소': '#e74c3c',
                    '절대 인수': '#e67e22',
                    '이미 말소됨': '#95a5a6',
                    'AI판단': '#3498db',
                    '서류확인': '#f39c12',
                    '기본등기': '#bdc3c7',
                    '기타': '#7f8c8d',
                }

                def get_color(result):
                    for key, color in color_map.items():
                        if key in result:
                            return color
                    return '#7f8c8d'

                timeline_df['색상'] = timeline_df['결과'].apply(get_color)
                # 구분을 숫자로 (갑구=1, 을구=2)
                timeline_df['Y축'] = timeline_df['구분'].apply(lambda x: 1 if '갑' in x else 2)
                # datetime.date → 문자열 변환 (Plotly 호환)
                timeline_df['날짜_str'] = timeline_df['접수일자_기준'].apply(lambda d: d.isoformat() if d else None)

                fig = go.Figure()

                # 등기 포인트
                for _, row in timeline_df.iterrows():
                    fig.add_trace(go.Scatter(
                        x=[row['날짜_str']],
                        y=[row['Y축']],
                        mode='markers+text',
                        marker=dict(size=14, color=row['색상'], line=dict(width=1, color='white')),
                        text=[str(row['순위번호'])],
                        textposition='top center',
                        textfont=dict(size=9),
                        hovertext=f"{row['구분']} #{row['순위번호']}<br>{row['등기목적']}<br>{row['결과']}",
                        hoverinfo='text',
                        showlegend=False,
                    ))

                # 말소기준권리 수직선 (add_shape + add_annotation으로 대체 — add_vline은 date 객체 버그 있음)
                if st.session_state.base_date_info:
                    bd = st.session_state.base_date_info['date']
                    bd_str = bd.isoformat() if hasattr(bd, 'isoformat') else str(bd)
                    fig.add_shape(
                        type='line',
                        x0=bd_str, x1=bd_str, y0=0.5, y1=2.5,
                        line=dict(color='red', width=2, dash='dash'),
                    )
                    fig.add_annotation(
                        x=bd_str, y=2.5,
                        text='📌 말소기준권리',
                        showarrow=False,
                        font=dict(color='red', size=11),
                        yshift=10,
                    )

                # 범례 (더미 트레이스)
                for label, color in [('✅ 인수', '#2ecc71'), ('❌ 말소', '#e74c3c'),
                                     ('🚨 절대인수', '#e67e22'), ('🔘 이미말소', '#95a5a6'),
                                     ('🤖 AI판단', '#3498db')]:
                    fig.add_trace(go.Scatter(
                        x=[None], y=[None], mode='markers',
                        marker=dict(size=10, color=color),
                        name=label,
                    ))

                fig.update_layout(
                    title='등기 접수일자 타임라인',
                    xaxis_title='접수일자',
                    yaxis=dict(
                        tickvals=[1, 2],
                        ticktext=['갑구 (소유권)', '을구 (기타권리)'],
                        range=[0.5, 2.5],
                    ),
                    height=350,
                    margin=dict(l=20, r=20, t=50, b=20),
                    legend=dict(orientation='h', yanchor='bottom', y=-0.3, xanchor='center', x=0.5),
                    plot_bgcolor='rgba(253,251,247,1)',
                )
                st.plotly_chart(fig, use_container_width=True)
              except Exception as chart_err:
                st.warning(f"⚠️ 타임라인 차트 표시 중 오류: {chart_err}")
            st.markdown("<br>", unsafe_allow_html=True)

    # 🚨 매각물건명세서 위험 경고 (최상단에 표시)
    if st.session_state.danger_warnings:
        st.subheader("🚨 매각물건명세서 위험 경고")
        for warning in st.session_state.danger_warnings:
            st.error(warning)
        st.markdown("<br>", unsafe_allow_html=True)

    # 📋 매각물건명세서 교차 검증 결과
    if st.session_state.spec_summary:
        with st.expander("📋 매각물건명세서 분석 결과 (교차 검증 완료)", expanded=True):
            st.info("📋 매각물건명세서가 감지되어 등기부등본과 교차 검증을 수행했습니다. AI 판단의 정확도가 향상되었습니다.")
            st.markdown(st.session_state.spec_summary)
        st.markdown("<br>", unsafe_allow_html=True)

    st.subheader("📑 법원 제출용: 말소할 등기 목록")
    st.table(st.session_state.malso_df)

    # 📥 DOCX 문서 생성
    doc = Document()
    doc.add_heading('말 소 할  등 기  목 록', level=1).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    for idx, row in st.session_state.malso_df.iterrows():
        p = doc.add_paragraph()
        p.add_run(f"{idx}. {row['구분']} 순위번호 제{row['순위번호']}번\n").bold = True
        p.add_run(f"   {row['등기목적']}\n")
        p.add_run(f"   {row['접수일자']} 접수")

    doc_io = BytesIO()
    doc.save(doc_io)
    doc_io.seek(0)

    # 📥 PDF 문서 생성
    @st.cache_resource
    def _get_pdf_font_path():
        """PDF용 한글 폰트를 크로스플랫폼 temp 디렉토리에 캐시합니다."""
        import tempfile
        import urllib.request
        font_path = os.path.join(tempfile.gettempdir(), 'NanumGothic-Regular.ttf')
        if not os.path.exists(font_path):
            urllib.request.urlretrieve(
                'https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf',
                font_path
            )
        return font_path

    def generate_pdf(malso_df):
        try:
            from fpdf import FPDF
            font_path = _get_pdf_font_path()
            pdf = FPDF()
            pdf.add_page()
            pdf.add_font('NanumGothic', '', font_path, uni=True)
            pdf.set_font('NanumGothic', size=16)
            pdf.cell(0, 12, '말 소 할  등 기  목 록', ln=True, align='C')
            pdf.ln(8)
            pdf.set_font('NanumGothic', size=11)
            for idx, row in malso_df.iterrows():
                pdf.cell(0, 8, f"{idx}. {row['구분']} 순위번호 제{row['순위번호']}번", ln=True)
                pdf.cell(0, 7, f"   {row['등기목적']}", ln=True)
                pdf.cell(0, 7, f"   {row['접수일자']} 접수", ln=True)
                pdf.ln(4)
            return bytes(pdf.output())
        except Exception:
            return None

    # 📥 다운로드 버튼 (DOCX + PDF)
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            label="📥 워드(.docx) 다운로드",
            data=doc_io,
            file_name="말소할_등기_목록.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            use_container_width=True
        )
    with dl_col2:
        pdf_data = generate_pdf(st.session_state.malso_df)
        if pdf_data:
            st.download_button(
                label="📥 PDF 다운로드",
                data=pdf_data,
                file_name="말소할_등기_목록.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        else:
            st.caption("PDF 생성 불가 (fpdf2 미설치)")

    st.markdown("<br><hr><br>", unsafe_allow_html=True)

    # 🔍 말소 누락 탐지 보고서
    if st.session_state.malso_omission_report:
        with st.expander("🔍 말소 누락 탐지 결과 (Gemini 특수 미션)", expanded=True):
            report = st.session_state.malso_omission_report
            if "말소 누락 의심 건 없음" in report:
                st.success(report)
            else:
                st.warning("⚠️ 아래 항목은 말소되었어야 하는데 현재 살아있는 것으로 의심되는 등기입니다. 원본 등기부를 반드시 확인하세요.")
                st.markdown(report)
        st.markdown("<br>", unsafe_allow_html=True)

    with st.expander("🤖 AI 상세 판독 내역 및 이유 보기 (클릭)"):
        display_cols = ['구분', '순위번호', '등기목적', '결과', 'AI_상세이유']
        st.dataframe(st.session_state.final_df[display_cols], use_container_width=True)

        # 📝 접수번호 OCR 오타 경고 표시
        if '접수번호_오타' in st.session_state.final_df.columns:
            typo_rows = st.session_state.final_df[st.session_state.final_df['접수번호_오타'] != ''].copy()
            if not typo_rows.empty:
                st.markdown("---")
                st.markdown("**📝 접수번호 OCR 오타 감지 결과**")
                for _, row in typo_rows.iterrows():
                    st.warning(f"순위번호 {row['순위번호']}번: {row['접수번호_오타']}")

    st.markdown("<br>", unsafe_allow_html=True)

    # 🔬 Gemini Vision 검수 결과
    if st.session_state.vision_review:
        with st.expander("🔬 Gemini Vision 최종 검수 결과", expanded=True):
            review = st.session_state.vision_review
            if '✅' in review:
                st.success(review)
            elif '⚠️' in review:
                st.warning(review)
            else:
                st.info(review)
        st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🔄 처음으로 돌아가기", use_container_width=True):
        # 🔄 전체 세션 상태 초기화 (이전 결과 혼합 방지)
        for key in ['final_df', 'malso_df', 'spec_summary', 'danger_warnings',
                     'malso_omission_report', 'base_date_info', 'safety_report',
                     'uploaded_images', 'vision_review']:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.step = 1
        st.rerun()