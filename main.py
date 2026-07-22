"""
유튜브 댓글 분석 + AI 세줄요약 앱
--------------------------------
이 앱이 하는 일:
1) 사용자가 유튜브 영상 링크를 입력하면
2) 링크에서 '영상 ID'만 뽑아내고
3) YouTube Data API v3로 댓글(최대 100개, 좋아요 많은 순)을 가져와서
4) 표와 지표 카드로 보여주고
5) 자주 나온 단어 TOP 20을 plotly 가로 막대그래프로 보여주고
6) 댓글 전체로 워드클라우드 이미지를 만들어 보여주고
7) 워드클라우드 바로 아래에서 'AI 세 줄 요약' 버튼을 누르면
   Solar API(solar-open2 모델)가 댓글 전체 반응을 한국어 세 줄로 요약해준다.

* 스트림릿 클라우드에 배포할 때는
  '설정(Settings) > Secrets' 메뉴에 아래처럼 두 개의 키를 등록해야 합니다.

  YOUTUBE_API_KEY = "여기에_유튜브_API_키"
  SOLAR_API_KEY = "여기에_업스테이지_Solar_API_키"

* 중요: 두 API 키 모두 '파일이 열리자마자'가 아니라
  '해당 버튼을 눌렀을 때'만, 그리고 st.secrets["..."] 처럼 대괄호로
  직접 읽지 않고 st.secrets.get("...", None) 방식으로 안전하게 읽어옵니다.
  이렇게 해야 키를 아직 등록하지 않았을 때도 앱이 통째로 죽지 않고
  화면에 친절한 한국어 안내만 나타납니다.
"""

import re
from collections import Counter
from urllib.parse import urlparse, parse_qs

import plotly.graph_objects as go
import requests
import streamlit as st
from openai import OpenAI
from wordcloud import WordCloud

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="커링클 유튜브 댓글 분석", page_icon="🤖", layout="centered")

# 예시로 사용할 두 개의 유튜브 링크
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# 유튜브 댓글 API 주소 (고정된 값)
YOUTUBE_COMMENT_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

# 워드클라우드용 한글 폰트 (나눔고딕) 다운로드 주소
NANUM_FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/"
    "NanumGothic-Regular.ttf"
)
NANUM_FONT_PATH = "/tmp/NanumGothic-Regular.ttf"

# Solar API(업스테이지) 관련 고정 값
SOLAR_BASE_URL = "https://api.upstage.ai/v1"
SOLAR_MODEL_NAME = "solar-open2"


# ------------------------------------------------------------
# 1. 유튜브 링크에서 '영상 ID'만 뽑아내는 함수
#    - youtu.be/영상ID?si=xxxx  (짧은 링크)
#    - youtube.com/watch?v=영상ID&si=xxxx (일반 링크)
#    - youtube.com/shorts/영상ID (쇼츠 링크)
#    처럼 뒤에 si= 같은 부가 정보가 붙어 있어도 무시하고 ID만 추출한다.
# ------------------------------------------------------------
def extract_video_id(url: str):
    if not url:
        return None

    url = url.strip()
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    # 1) youtu.be/영상ID  형태 (짧은 링크)
    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id or None

    # 2) youtube.com 계열
    if "youtube.com" in host:
        # 2-1) youtube.com/watch?v=영상ID
        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            if "v" in query and query["v"]:
                return query["v"][0]

        # 2-2) youtube.com/shorts/영상ID , youtube.com/embed/영상ID
        for prefix in ("/shorts/", "/embed/"):
            if parsed.path.startswith(prefix):
                rest = parsed.path[len(prefix):]
                return rest.split("/")[0] or None

    return None


# ------------------------------------------------------------
# 2. YouTube Data API로 댓글을 가져오는 함수
#    - part=snippet, order=relevance(좋아요 많은 순 우선), 최대 100개
#    - 성공하면 (댓글 리스트, None) 을 반환
#    - 실패하면 (None, "친절한 한국어 오류 메시지") 를 반환
# ------------------------------------------------------------
def fetch_comments(video_id: str, api_key: str):
    params = {
        "part": "snippet",
        "videoId": video_id,
        "order": "relevance",   # 최신순이 아니라 '관련성(좋아요 등) 높은 순'
        "maxResults": 100,      # 한 번에 가져올 수 있는 최대 개수
        "textFormat": "plainText",
        "key": api_key,
    }

    try:
        response = requests.get(YOUTUBE_COMMENT_API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return None, "🌐 인터넷 연결에 문제가 있는 것 같아요. 잠시 후 다시 시도해 주세요."

    data = response.json()

    # 응답이 정상(200)이 아닌 경우 -> 원인별로 친절한 메시지 안내
    if response.status_code != 200:
        reason = ""
        try:
            reason = data["error"]["errors"][0].get("reason", "")
        except (KeyError, IndexError):
            pass

        if reason == "commentsDisabled":
            return None, "🚫 이 영상은 댓글 기능이 꺼져 있어서 댓글을 가져올 수 없어요."
        elif reason == "videoNotFound":
            return None, "❓ 영상을 찾을 수 없어요. 링크가 올바른지 다시 확인해 주세요."
        elif reason in ("quotaExceeded", "dailyLimitExceeded"):
            return None, "📛 오늘의 API 사용량을 다 써버렸어요. 내일 다시 시도해 주세요."
        elif reason == "keyInvalid" or response.status_code == 400:
            return None, "🔑 유튜브 API 키가 올바르지 않은 것 같아요. Secrets 설정을 확인해 주세요."
        else:
            message = data.get("error", {}).get("message", "알 수 없는 오류가 발생했어요.")
            return None, f"⚠️ 댓글을 가져오지 못했어요. (사유: {message})"

    items = data.get("items", [])
    if not items:
        return None, "📭 아직 댓글이 없는 영상이에요."

    comments = []
    for item in items:
        snippet = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "댓글": snippet.get("textOriginal", ""),
            "좋아요": snippet.get("likeCount", 0),
        })

    return comments, None


# ------------------------------------------------------------
# 3. 댓글 전체에서 단어를 세는 함수 (막대그래프 + 워드클라우드 공용)
#    - 한글/영문/숫자만 '단어'로 인정 (특수문자, 이모지 등은 무시)
#    - 한 글자짜리 단어는 결과에서 제외
#    - 영어는 대소문자를 구분하지 않도록 소문자로 통일
# ------------------------------------------------------------
def get_word_counter(comments):
    word_counter = Counter()

    for comment in comments:
        text = comment["댓글"]
        # 한글, 영문, 숫자로 이루어진 덩어리만 '단어'로 추출
        words = re.findall(r"[가-힣a-zA-Z0-9]+", text)

        for word in words:
            word = word.lower()          # 영어 대소문자 통일
            if len(word) >= 2:           # 한 글자짜리 단어는 제외
                word_counter[word] += 1

    return word_counter


# ------------------------------------------------------------
# 4. 워드클라우드에 쓸 한글 폰트(나눔고딕)를 다운로드하는 함수
#    - @st.cache_resource 덕분에 앱이 켜져 있는 동안 한 번만 다운로드함
#    - 성공하면 폰트 파일 경로를 반환, 실패하면 None을 반환
# ------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def download_korean_font():
    try:
        response = requests.get(NANUM_FONT_URL, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    with open(NANUM_FONT_PATH, "wb") as f:
        f.write(response.content)

    return NANUM_FONT_PATH


# ------------------------------------------------------------
# 5. Solar API(solar-open2)로 댓글 전체를 세 줄 요약하는 함수
#    - openai 라이브러리를 그대로 쓰되, 접속 주소만 Solar API로 바꿔서 사용
#    - reasoning_effort="none" 으로 줘서 생각(추론) 기능을 꺼서 빠르게 응답받음
#    - 성공하면 (요약 텍스트, None) 을 반환
#    - 실패하면 (None, "친절한 한국어 오류 메시지") 를 반환
# ------------------------------------------------------------
def summarize_comments(comments, api_key):
    # 댓글 목록을 AI에게 보여줄 하나의 긴 텍스트로 합치기
    comments_text = "\n".join(
        f"- {c['댓글']} (좋아요 {c['좋아요']}개)" for c in comments
    )

    system_prompt = (
        "너는 유튜브 댓글 반응을 분석하는 도우미야. "
        "아래에 주어지는 댓글들을 모두 읽고, 시청자들의 전체 반응을 "
        "한국어로 정확히 세 줄로 요약해줘. "
        "1~2번째 줄에는 댓글에서 드러나는 주요 의견이나 분위기를 요약하고, "
        "마지막 3번째 줄에는 전체 댓글의 긍정적인 반응과 부정적인 반응의 "
        "비율을 대략적으로 추정해서 '긍정 OO% / 부정 OO%' 형식으로 적어줘."
    )

    try:
        client = OpenAI(api_key=api_key, base_url=SOLAR_BASE_URL)
        response = client.chat.completions.create(
            model=SOLAR_MODEL_NAME,          # 모델 이름은 반드시 solar-open2
            reasoning_effort="none",         # 추론(생각) 기능 끄기
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": comments_text},
            ],
        )
    except Exception as e:
        return None, f"⚠️ AI 요약 요청 중 오류가 발생했어요. (사유: {e})"

    try:
        summary = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None, "⚠️ AI가 응답을 제대로 주지 않았어요. 잠시 후 다시 시도해 주세요."

    if not summary or not summary.strip():
        return None, "⚠️ AI가 빈 응답을 줬어요. 잠시 후 다시 시도해 주세요."

    return summary.strip(), None


# ------------------------------------------------------------
# 6. 화면 구성 시작
# ------------------------------------------------------------
st.title("커링클 유튜브 댓글 분석")
st.caption("댓글을 가져와서 표·단어그래프·워드클라우드로 보여주고, AI가 세 줄로 요약해줘요.")

# 입력창의 값을 미리 저장해 둘 공간(session_state)을 준비
# -> 예시 버튼을 누르면 이 값을 바꿔서 입력창에 자동으로 채워지게 함
if "url_input" not in st.session_state:
    st.session_state.url_input = EXAMPLE_1_URL

# 댓글 목록과 요약 결과를 세션에 저장해 둘 공간도 미리 준비
# (버튼을 눌러 화면이 다시 그려져도 값이 사라지지 않도록 하기 위함)
if "comments" not in st.session_state:
    st.session_state.comments = None       # 정렬된 댓글 목록
if "fetch_error" not in st.session_state:
    st.session_state.fetch_error = None    # 댓글 가져오기 실패 메시지
if "ai_summary" not in st.session_state:
    st.session_state.ai_summary = None     # AI 요약 결과
if "ai_error" not in st.session_state:
    st.session_state.ai_error = None       # AI 요약 실패 메시지


def _use_example_1():
    st.session_state.url_input = EXAMPLE_1_URL


def _use_example_2():
    st.session_state.url_input = EXAMPLE_2_URL


# 6-1. 예시 버튼 두 개를 나란히 배치
col1, col2 = st.columns(2)
with col1:
    st.button(
        "예시 1 · 딥마인드 다큐(영어 댓글)",
        on_click=_use_example_1,
        use_container_width=True,
    )
with col2:
    st.button(
        "예시 2 · 2002 월드컵 추억(한국어 댓글)",
        on_click=_use_example_2,
        use_container_width=True,
    )

# 6-2. 유튜브 링크 입력창 (key로 session_state.url_input과 연결됨)
video_url = st.text_input(
    "유튜브 영상 링크를 붙여넣어주세요",
    key="url_input",
)

# 6-3. 댓글 가져오기 버튼
fetch_clicked = st.button("📥 댓글 가져오기", type="primary")

# ------------------------------------------------------------
# 7. '댓글 가져오기' 버튼을 눌렀을 때의 처리
# ------------------------------------------------------------
if fetch_clicked:
    # 새로 가져오기를 시도하는 것이므로, 이전 결과는 일단 초기화
    st.session_state.comments = None
    st.session_state.fetch_error = None
    st.session_state.ai_summary = None
    st.session_state.ai_error = None

    # (1) 링크에서 영상 ID 추출
    video_id = extract_video_id(video_url)

    if not video_id:
        st.session_state.fetch_error = (
            "🔗 링크에서 영상 ID를 찾지 못했어요. 유튜브 링크가 맞는지 확인해 주세요."
        )
    else:
        # (2) Secrets에서 유튜브 API 키 불러오기
        #     -> st.secrets["..."] 대신 .get()을 써서,
        #        키가 없어도 앱이 죽지 않고 None을 받도록 함
        youtube_api_key = st.secrets.get("YOUTUBE_API_KEY", None)

        if not youtube_api_key:
            st.session_state.fetch_error = (
                "🔑 유튜브 API 키가 설정되어 있지 않아요. "
                "스트림릿 클라우드의 'Settings > Secrets'에 "
                "YOUTUBE_API_KEY 값을 추가해 주세요."
            )
        else:
            # (3) 로딩 스피너를 보여주며 댓글 요청
            with st.spinner("댓글을 불러오는 중이에요..."):
                comments, error_message = fetch_comments(video_id, youtube_api_key)

            if error_message:
                st.session_state.fetch_error = error_message
            else:
                # (4) 좋아요 많은 순으로 정렬해서 세션에 저장
                st.session_state.comments = sorted(
                    comments, key=lambda c: c["좋아요"], reverse=True
                )

# ------------------------------------------------------------
# 8. 댓글 가져오기 실패 메시지 표시
# ------------------------------------------------------------
if st.session_state.fetch_error:
    st.warning(st.session_state.fetch_error)

# ------------------------------------------------------------
# 9. 댓글이 세션에 저장되어 있다면 항상 화면에 표시
#    (AI 요약 버튼을 눌러 화면이 다시 그려져도 계속 보이도록 함)
# ------------------------------------------------------------
if st.session_state.comments:
    comments_sorted = st.session_state.comments

    # (1) 가져온 댓글 개수를 큰 지표 카드로 표시
    st.metric("가져온 댓글 개수", f"{len(comments_sorted)}개")

    # (2) 댓글 목록을 표로 표시 (좋아요 많은 순)
    st.dataframe(
        comments_sorted,
        use_container_width=True,
        hide_index=True,
        column_config={
            "댓글": st.column_config.TextColumn("댓글", width="large"),
            "좋아요": st.column_config.NumberColumn("👍 좋아요", width="small"),
        },
    )

    # (3) 자주 나온 단어 상위 20개 -> 가로 막대그래프
    word_counter = get_word_counter(comments_sorted)
    top_words = word_counter.most_common(20)

    if top_words:
        st.subheader("📊 자주 나온 단어 TOP 20")

        # most_common()은 [(단어, 개수), ...] 형태로
        # '많이 나온 순서'로 이미 정렬되어 있음
        words = [w for w, _ in top_words]
        counts = [c for _, c in top_words]

        fig = go.Figure(
            go.Bar(
                x=counts,
                y=words,
                orientation="h",   # 가로 막대그래프
                text=counts,
                textposition="outside",
            )
        )

        # y축을 뒤집어서, 가장 많이 나온 단어가 맨 위로 오게 함
        fig.update_layout(
            yaxis=dict(autorange="reversed"),
            xaxis_title="언급 횟수",
            yaxis_title="단어",
            height=600,
            margin=dict(l=10, r=30, t=30, b=10),
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("분석할 수 있는 단어(두 글자 이상)가 없어요.")

    # (4) 댓글 전체로 워드클라우드 그리기
    st.subheader("☁️ 댓글 워드클라우드")

    with st.spinner("한글 폰트를 준비하는 중이에요..."):
        font_path = download_korean_font()

    if not font_path:
        st.warning(
            "🔤 워드클라우드용 한글 폰트를 내려받지 못했어요. "
            "인터넷 연결을 확인한 뒤 페이지를 새로고침해서 다시 시도해 주세요."
        )
    elif not word_counter:
        st.info("워드클라우드로 그릴 단어(두 글자 이상)가 없어요.")
    else:
        wordcloud = WordCloud(
            font_path=font_path,       # 한글이 깨지지 않도록 나눔고딕 폰트 지정
            background_color="white",  # 배경 흰색
            width=1000,
            height=600,
        ).generate_from_frequencies(word_counter)

        # matplotlib 없이, wordcloud가 만들어주는 이미지를 바로 화면에 표시
        wordcloud_image = wordcloud.to_image()
        st.image(wordcloud_image, use_container_width=True)

    # (5) 워드클라우드 바로 아래 -> AI 세 줄 요약
    st.divider()
    st.subheader("🧠 AI 세 줄 요약")

    ai_clicked = st.button("🧠 AI 세 줄 요약 보기")

    if ai_clicked:
        # -> 여기도 st.secrets["..."] 대신 .get()으로 안전하게 읽음
        solar_api_key = st.secrets.get("SOLAR_API_KEY", None)

        if not solar_api_key:
            st.session_state.ai_summary = None
            st.session_state.ai_error = (
                "🔑 Solar API 키가 설정되어 있지 않아요. "
                "스트림릿 클라우드의 'Settings > Secrets'에 "
                "SOLAR_API_KEY 값을 추가해 주세요."
            )
        else:
            with st.spinner("AI가 댓글을 읽고 요약하는 중이에요..."):
                summary, ai_error_message = summarize_comments(
                    comments_sorted, solar_api_key
                )

            st.session_state.ai_summary = summary
            st.session_state.ai_error = ai_error_message

    # (6) AI 요약 결과 또는 에러 메시지 표시
    if st.session_state.ai_error:
        st.warning(st.session_state.ai_error)
    elif st.session_state.ai_summary:
        st.info(st.session_state.ai_summary)
