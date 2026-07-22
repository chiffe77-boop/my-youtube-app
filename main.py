import re
import streamlit as st
import requests
from openai import OpenAI

# 기본 설정
st.set_page_config(page_title="유튜브 댓글 AI앱", page_icon="🤖")
st.title("🤖 유튜브 댓글 AI앱")

YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
# Solar(업스테이지) AI를 openai 라이브러리로 부르기
client = OpenAI(
    api_key=st.secrets["SOLAR_API_KEY"],
    base_url="https://api.upstage.ai/v1",
)

# 예시 영상 두 개 (버튼으로 골라 넣기)
DEFAULT_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"   # 딥마인드 다큐 (영어)
KOREAN_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"    # 2002 월드컵 추억 (한국어)

if "video_url" not in st.session_state:
    st.session_state.video_url = DEFAULT_URL

col1, col2 = st.columns(2)
if col1.button("🎬 예시 1 · 딥마인드 다큐 (영어 댓글)"):
    st.session_state.video_url = DEFAULT_URL
if col2.button("⚽ 예시 2 · 2002 월드컵 추억"):
    st.session_state.video_url = KOREAN_URL

video_url = st.text_input("유튜브 영상 링크를 붙여넣으세요", key="video_url")


def extract_video_id(url):
    """youtu.be 짧은 주소, watch 주소에서 영상 ID(11글자)를 뽑는다."""
    match = re.search(r"(?:youtu\.be/|v=|shorts/)([A-Za-z0-9_-]{11})", url)
    return match.group(1) if match else None


if st.button("댓글 가져오기 💬"):
    video_id = extract_video_id(video_url.strip())
    if not video_id:
        st.error("링크에서 영상 ID를 찾지 못했어요. 유튜브 영상 링크가 맞는지 확인해 주세요.")
    else:
        api_url = "https://www.googleapis.com/youtube/v3/commentThreads"
        params = {"part": "snippet", "videoId": video_id, "maxResults": 100, "order": "relevance", "key": YOUTUBE_KEY}
        res = requests.get(api_url, params=params)
        if res.status_code != 200:
            st.error(
                "댓글을 가져오지 못했어요 😢 댓글이 막힌 영상은 아닌지 확인해 주세요. "
                f"(상태코드: {res.status_code})"
            )
        else:
            items = res.json().get("items", [])
            rows = []
            for it in items:
                snip = it["snippet"]["topLevelComment"]["snippet"]
                rows.append((snip["textOriginal"], snip.get("likeCount", 0)))
            rows.sort(key=lambda r: r[1], reverse=True)   # 좋아요 많은 순 정렬
            st.session_state.comments = [text for text, _ in rows]
            st.session_state.likes = [n for _, n in rows]

# 댓글이 준비되면 요약 버튼과 목록 표시
if "comments" in st.session_state:
    comments = st.session_state.comments
    st.metric("가져온 댓글 수", f"{len(comments)}개")

    # ── AI 세 줄 요약 + 긍·부정 비율 ──────────────────
    if st.button("🤖 AI 세 줄 요약"):
        joined = "\n".join(comments)
        with st.spinner("AI가 댓글을 읽고 있어요..."):
            try:
                resp = client.chat.completions.create(
                    model="solar-open2",     # 모델 이름은 그대로 유지
                    messages=[
                        {"role": "system", "content": "너는 댓글 분석가야. 받은 댓글 전체의 전반적인 반응을 한국어 세 줄로 요약하고, 마지막 줄에 긍정과 부정의 대략적인 비율(백분율)을 덧붙여. 반드시 순수 한국어로만 답해."},
                        {"role": "user", "content": joined},
                    ],
                    reasoning_effort="none",  # 추론 끄기 -> 즉시 답변
                )
                st.info(resp.choices[0].message.content)
            except Exception:
                st.error("요약을 받지 못했어요 😢 잠시 후 다시 시도해 주세요.")

    st.dataframe({"좋아요": st.session_state.likes, "댓글": comments}, use_container_width=True)
