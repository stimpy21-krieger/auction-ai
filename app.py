import streamlit as st
import requests
import uuid
import time
import json
import re
import pandas as pd
import datetime
import google.generativeai as genai
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from io import BytesIO

# =====================================================================
# 🎨 1. 스트림릿 기본 설정 & 2030 타겟 감성 디자인 (CSS)
# =====================================================================
st.set_page_config(page_title="AI 경매 권리분석 마법사", page_icon="🧙‍♂️", layout="centered")

st.markdown("""
<style>
    /* 트렌디한 Pretendard 폰트 적용 및 부드러운 배경색 */
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, sans-serif !important;
        background-color: #FDFBF7; /* 따뜻한 아이보리 톤 */
        color: #4A4A4A;
    }
    
    /* 제목 및 텍스트 크기 조정 (너무 크지 않게) */
    h1 { font-size: 26px !important; color: #333333; font-weight: 700; margin-bottom: 5px !important;}
    h2, h3 { font-size: 20px !important; color: #4A4A4A; font-weight: 600; }
    p, li, span { font-size: 15px !important; line-height: 1.6; }
    
    /* 코랄 핑크빛 둥근 메인 버튼 */
    .stButton > button[kind="primary"] {
        background-color: #FF9B9B;
        color: white;
        border-radius: 25px;
        border: none;
        padding: 10px 20px;
        font-size: 16px;
        font-weight: 600;
        box-shadow: 0 4px 10px rgba(255, 155, 155, 0.3);
        transition: all 0.3s ease;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #FF8282;
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(255, 155, 155, 0.4);
    }

    /* 파일 업로드 창 커스텀 (영어 텍스트 완벽 한글화 및 숨김) */
    [data-testid="stFileUploadDropzone"] {
        background-color: #FFFFFF;
        border: 2px dashed #FF9B9B;
        border-radius: 20px;
        padding: 30px;
    }
    
    /* 기본 "Drag and drop files here" 및 "Limit 200MB..." 숨기기 */
    [data-testid="stFileUploadDropzone"] > div > div > span,
    [data-testid="stFileUploadDropzone"] > div > div > small {
        display: none !important;
    }
    
    /* 새로운 한글 안내 문구 삽입 */
    [data-testid="stFileUploadDropzone"] > div > div::before {
        content: '📸 터치해서 등기부등본 사진 올리기';
        color: #A0968C;
        font-size: 16px;
        font-weight: 600;
        display: block;
        margin-bottom: 15px;
    }

    /* "Browse files" 버튼 텍스트 변경을 위한 CSS 해킹 */
    [data-testid="stFileUploadDropzone"] button {
        color: transparent !important;
        border-color: #E0D4C3 !important;
        background-color: white !important;
        position: relative;
    }
    [data-testid="stFileUploadDropzone"] button::after {
        content: "사진 선택하기";
        color: #4A4A4A !important;
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        font-weight: 600;
        font-size: 14px;
        visibility: visible;
    }
</style>
""", unsafe_allow_html=True)

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
"""

def ask_gemini_for_rights(record_text, base_date, model):
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

    [지시사항]
    1. 위 등기 권리가 경매 낙찰 시 매수인에게 인수되는지, 아니면 말소되는지 판단해.
    2. 만약 등기부등본 내용만으로 확정할 수 없는 항목이라면 "추가확인 필요"라고 답변해.
    3. 출력 형식은 반드시 첫 줄에 "결과: 인수", "결과: 말소", "결과: 추가확인" 중 하나만 적고, 두 번째 줄에 "이유: (간략한 1~2줄 설명)"을 적어줘.
    """
    return model.generate_content(prompt).text

# =====================================================================
# 🔄 4. 화면 자동 전환 로직 (세션 상태 관리)
# =====================================================================
if 'step' not in st.session_state:
    st.session_state.step = 1  
if 'final_df' not in st.session_state:
    st.session_state.final_df = None
if 'malso_df' not in st.session_state:
    st.session_state.malso_df = None

# =====================================================================
# 📱 [1단계 화면] 메인 화면 및 사진 업로드
# =====================================================================
if st.session_state.step == 1:
    st.title("🧙‍♂️ AI 경매 권리분석 마법사")
    st.markdown("스마트폰으로 등기부등본을 찍어 올리면, AI가 자동으로 권리를 분석해 줍니다.")
    
    # CSS로 영어 문구가 완벽히 숨겨진 업로드 창
    uploaded_files = st.file_uploader(" ", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'], label_visibility="collapsed")

    if st.button("🚀 권리분석 시작", type="primary", use_container_width=True):
        if not uploaded_files:
            st.warning("사진을 먼저 업로드해주세요.")
        else:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                with st.spinner('문서를 스캔하고 있습니다... (약 10~20초)'):
                    all_clean_rows = []
                    for file in sorted(uploaded_files, key=lambda x: x.name):
                        file_bytes = file.getvalue()
                        request_json = {'images': [{'format': file.name.split('.')[-1], 'name': 'demo'}], 'requestId': str(uuid.uuid4()), 'version': 'V2', 'timestamp': int(round(time.time() * 1000))}
                        payload = {'message': json.dumps(request_json).encode('UTF-8')}
                        file_data = [('file', (file.name, file_bytes, file.type))]
                        headers = {'X-OCR-SECRET': NAVER_SECRET_KEY}
                        
                        response = requests.request("POST", NAVER_API_URL, headers=headers, data=payload, files=file_data)
                        if response.status_code == 200:
                            fields = response.json()['images'][0]['fields']
                            current_row, last_y, page_rows = [], -1, []
                            sorted_fields = sorted(fields, key=lambda x: x['boundingPoly']['vertices'][0]['y'])

                            for field in sorted_fields:
                                text = field['inferText']
                                y_pos = field['boundingPoly']['vertices'][0]['y']
                                x_pos = field['boundingPoly']['vertices'][0]['x']
                                text = re.sub(r'(\d{6})\s*-\s*\d{7}', r'\1-*******', text) 

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
                            all_clean_rows.extend(page_rows)
                        else:
                            st.error("OCR 스캔 중 오류가 발생했습니다.")
                            st.stop()

                with st.spinner('파이썬 엔진이 권리를 분류하고 있습니다...'):
                    records, current_record, current_gu = [], {}, None
                    rank_pattern = re.compile(r'^([1-9]\d*[-]?\d*)(?:\s+|번|(?=[가-힣]))') 
                    date_pattern = re.compile(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일')

                    for row in all_clean_rows:
                        clean_row = row.replace(" ", "")
                        
                        # 🌟 꼬리말 필터: 쓸데없는 안내문 쓰레기통으로!
                        if any(kw in clean_row for kw in ignore_keywords):
                            continue
                            
                        if "갑구" in clean_row and "소유권" in clean_row: current_gu = "갑구"; continue
                        if "을구" in clean_row and "소유권" in clean_row: current_gu = "을구"; continue
                        if current_gu is None or "순위번호" in row or "등기목적" in row or "접수" in row: continue

                        match = rank_pattern.match(row)
                        is_new_record = False
                        
                        if match:
                            rank_str = match.group(1)
                            rest_of_line = row[match.end():].strip()
                            
                            # 🌟 가짜 순위번호 방지 3중 철통 방어 필터 (2022년, 277-2 등 방지)
                            if "-" in rank_str: 
                                pass # 277-2 같은 바코드/지번 번호 패스
                            elif len(rank_str) >= 4 or int(rank_str) > 200: 
                                pass # 2022, 2024 같은 연도 패스
                            elif rest_of_line.startswith(('호', '동', '층', '길', '번지', 'm', '㎡', '전', '년', '월', '일')):
                                pass # 주소나 날짜로 이어지는 경우 패스
                            else:
                                is_new_record = True # 진짜 순위번호일 때만 새 기록 생성!

                        if is_new_record: 
                            if current_record: records.append(current_record)
                            current_record = {'구분': current_gu, '순위번호': rank_str, '전체내용': row}
                        else: 
                            if current_record: current_record['전체내용'] += " " + row
                    
                    if current_record: records.append(current_record)

                    parsed_records = []
                    for rec in records:
                        content = rec['전체내용'].replace(" ", "")
                        date_match = date_pattern.search(rec['전체내용'])
                        rec['접수일자_기준'] = None
                        
                        if date_match:
                            y, m, d = date_match.groups()
                            rec['접수일자_기준'] = datetime.date(int(y), int(m), int(d))
                            receipt_match = re.search(r'제\s*(\d+)\s*호', rec['전체내용'])
                            rec['접수일자_표시'] = f"{y}년 {m}월 {d}일" + (f" 제{receipt_match.group(1)}호" if receipt_match else "")
                            
                            raw_target = rec['전체내용'][:date_match.start()].replace(rec['순위번호'], '', 1).strip()
                            clean_target = re.sub(r'^번\s*|(가압|임의|강제|전부|근저당권|압류|경매개시결정)$', '', raw_target).strip()
                            
                            action = ""
                            if '임의경매개시결정' in content: action = "임의경매개시결정"
                            elif '강제경매개시결정' in content: action = "강제경매개시결정"
                            elif '가압류' in content: action = "가압류"
                            elif '근저당권설정' in content: action = "전부근저당권설정" if '전부근저당권설정' in content else "근저당권설정"
                            elif '압류' in content: action = "압류"
                            rec['등기목적'] = f"{clean_target} {action}".strip()
                        else:
                            rec['접수일자_표시'], rec['등기목적'] = "확인불가", "확인불가"

                        rec['말소후보'] = any(kw in content for kw in base_keywords)
                        rec['절대인수'] = any(kw in content for kw in always_keep_keywords)
                        rec['AI해석필요'] = any(kw in content for kw in ai_check_keywords)
                        rec['소유권이전'] = '이전' in content and not rec['말소후보'] and not rec['절대인수']
                        parsed_records.append(rec)

                    df = pd.DataFrame(parsed_records)
                    candidates = df[df['말소후보'] == True].dropna(subset=['접수일자_기준'])
                    base_date = candidates.sort_values(by='접수일자_기준').iloc[0]['접수일자_기준'] if not candidates.empty else None

                    def determine_status(row):
                        if row['절대인수']: return "🚨 절대 인수"
                        elif row['AI해석필요']: return "🤖 AI 정밀해석"
                        elif row['소유권이전']: return "➖ 기본등기"
                        elif pd.notnull(row['접수일자_기준']) and base_date and row['접수일자_기준'] >= base_date: return "❌ 말소"
                        elif pd.notnull(row['접수일자_기준']) and base_date and row['접수일자_기준'] < base_date: return "✅ 인수"
                        else: return "기타"

                    df['결과'] = df.apply(determine_status, axis=1)

                with st.spinner('Gemini AI가 복잡한 권리를 정밀 해석 중입니다...'):
                    df['AI_상세이유'] = ""
                    for index, row in df.iterrows():
                        if "🤖 AI 정밀해석" in str(row['결과']):
                            try:
                                ai_answer = ask_gemini_for_rights(row['전체내용'], base_date, model)
                                if "결과: 인수" in ai_answer: df.at[index, '결과'] = "✅ 인수 (AI판단)"
                                elif "결과: 말소" in ai_answer: df.at[index, '결과'] = "❌ 말소 (AI판단)"
                                elif "결과: 추가확인" in ai_answer: df.at[index, '결과'] = "⚠️ 서류확인 요망"
                                
                                df.at[index, 'AI_상세이유'] = ai_answer.split("이유:")[-1].strip() if "이유:" in ai_answer else ai_answer
                                time.sleep(1)
                            except Exception as e:
                                df.at[index, 'AI_상세이유'] = "API 통신 오류"

                    malso_df = df[df['결과'].str.contains('말소')][['구분', '순위번호', '등기목적', '접수일자_표시']]
                    malso_df.columns = ['구분', '순위번호', '등기목적', '접수일자']
                    malso_df.index = range(1, len(malso_df) + 1)

                    st.session_state.final_df = df
                    st.session_state.malso_df = malso_df
                    
                    # 🌟 모든 분석 완료 시 2단계 화면으로 자동 전환
                    st.session_state.step = 2
                    st.rerun()

            except Exception as e:
                st.error(f"분석 중 오류가 발생했습니다: {e}")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 수정된 주의사항 텍스트
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
    
    st.subheader("📑 법원 제출용: 말소할 등기 목록")
    st.table(st.session_state.malso_df)
    
    # 워드 문서 자동 생성
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
    
    st.download_button(
        label="📥 워드 문서(.docx) 다운로드",
        data=doc_io,
        file_name="말소할_등기_목록.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
        use_container_width=True
    )

    st.markdown("<br><hr><br>", unsafe_allow_html=True)
    
    with st.expander("🤖 AI 상세 판독 내역 및 이유 보기 (클릭)"):
        st.dataframe(st.session_state.final_df[['구분', '순위번호', '등기목적', '결과', 'AI_상세이유']], use_container_width=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("🔄 처음으로 돌아가기", use_container_width=True):
        st.session_state.step = 1
        st.rerun()