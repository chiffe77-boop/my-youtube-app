
"""
유튜브 댓글 분석 앱 - 1단계
--------------------------------
이 앱이 하는 일:
1) 사용자가 유튜브 영상 링크를 입력하면
2) 링크에서 '영상 ID'만 뽑아내고
3) YouTube Data API v3로 댓글(최대 100개, 좋아요 많은 순)을 가져와서
4) 표와 지표 카드로 보여준다.

* 스트림릿 클라우드에 배포할 때는
  '설정(Settings) > Secrets' 메뉴에 아래처럼 API 키를 등록해야 합니다.

  YOUTUBE_API_KEY = "여기에_발급받은_API_키"
"""

import re
from urllib.parse import urlparse, parse_qs

import requests
import streamlit as st

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="유튜브 댓글 분석기", page_icon="💬", layout="centered")

# 예시로 사용할 두 개의 유튜브 링크
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# 유튜브 댓글 API 주소 (고정된 값)
YOUTUBE_COMMENT_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"


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
            return None, "🔑 API 키가 올바르지 않은 것 같아요. Secrets 설정을 확인해 주세요."
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
# 3. 화면 구성 시작
# ------------------------------------------------------------
st.title("💬 유튜브 댓글 분석기 (1단계)")
st.caption("유튜브 링크를 넣으면 좋아요가 많은 순으로 댓글을 가져와서 보여줘요.")

# 입력창의 값을 미리 저장해 둘 공간(session_state)을 준비
# -> 예시 버튼을 누르면 이 값을 바꿔서 입력창에 자동으로 채워지게 함
if "url_input" not in st.session_state:
    st.session_state.url_input = EXAMPLE_1_URL


def _use_example_1():
    st.session_state.url_input = EXAMPLE_1_URL


def _use_example_2():
    st.session_state.url_input = EXAMPLE_2_URL


# 3-1. 예시 버튼 두 개를 나란히 배치
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

# 3-2. 유튜브 링크 입력창 (key로 session_state.url_input과 연결됨)
video_url = st.text_input(
    "유튜브 영상 링크를 붙여넣어주세요",
    key="url_input",
)

# 3-3. 댓글 가져오기 버튼
fetch_clicked = st.button("📥 댓글 가져오기", type="primary")

# ------------------------------------------------------------
# 4. 버튼을 눌렀을 때의 처리 흐름
# ------------------------------------------------------------
if fetch_clicked:
    # (1) 링크에서 영상 ID 추출
    video_id = extract_video_id(video_url)

    if not video_id:
        st.error("🔗 링크에서 영상 ID를 찾지 못했어요. 유튜브 링크가 맞는지 확인해 주세요.")
    else:
        # (2) Secrets에서 API 키 불러오기
        api_key = st.secrets.get("YOUTUBE_API_KEY", None)

        if not api_key:
            st.error(
                "🔑 YouTube API 키가 설정되어 있지 않아요. "
                "스트림릿 클라우드의 'Settings > Secrets'에 "
                "YOUTUBE_API_KEY 값을 추가해 주세요."
            )
        else:
            # (3) 로딩 스피너를 보여주며 댓글 요청
            with st.spinner("댓글을 불러오는 중이에요..."):
                comments, error_message = fetch_comments(video_id, api_key)

            if error_message:
                # (4) 실패 시 친절한 안내 메시지 표시
                st.warning(error_message)
            else:
                # (5) 성공 시: 좋아요 많은 순으로 정렬
                comments_sorted = sorted(
                    comments, key=lambda c: c["좋아요"], reverse=True
                )

                # (6) 가져온 댓글 개수를 큰 지표 카드로 표시
                st.metric("가져온 댓글 개수", f"{len(comments_sorted)}개")

                # (7) 댓글 목록을 표로 표시 (좋아요 많은 순)
                st.dataframe(
                    comments_sorted,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "댓글": st.column_config.TextColumn("댓글", width="large"),
                        "좋아요": st.column_config.NumberColumn("👍 좋아요", width="small"),
                    },
                )
