"""
유튜브 댓글 AI 분석 앱 - 메인 페이지 (댓글 가져오기)
--------------------------------
이 페이지가 하는 일:
1) 사용자가 유튜브 영상 링크를 입력하면
2) 링크에서 '영상 ID'만 뽑아내고
3) YouTube Data API v3로 댓글(최대 100개, 좋아요 많은 순)을 가져와서
4) 표와 지표 카드로 보여준다.

AI 세 줄 요약 기능은 왼쪽 사이드바의 'pages/00_세줄요약' 페이지에서 이어서 할 수 있다.
(여기서 가져온 댓글은 st.session_state에 저장되어 다른 페이지에서도 그대로 사용된다.)

* 스트림릿 클라우드에 배포할 때는
  '설정(Settings) > Secrets' 메뉴에 아래처럼 두 개의 키를 등록해야 합니다.

  YOUTUBE_API_KEY = "여기에_유튜브_API_키"
  SOLAR_API_KEY = "여기에_업스테이지_Solar_API_키"
"""

import streamlit as st

from utils import extract_video_id, fetch_comments

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="유튜브 댓글 AI 분석기", page_icon="🤖", layout="centered")

# 예시로 사용할 두 개의 유튜브 링크
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# ------------------------------------------------------------
# 1. 화면 구성 시작
# ------------------------------------------------------------
st.title("🤖 유튜브 댓글 AI 분석기")
st.caption("댓글을 가져온 뒤, 왼쪽 사이드바의 'AI 세줄요약' 페이지에서 요약을 볼 수 있어요.")

# 입력창의 값을 미리 저장해 둘 공간(session_state)을 준비
# -> 예시 버튼을 누르면 이 값을 바꿔서 입력창에 자동으로 채워지게 함
if "url_input" not in st.session_state:
    st.session_state.url_input = EXAMPLE_1_URL

# 댓글 목록을 세션에 저장해 둘 공간도 미리 준비
# (다른 페이지로 이동해도 값이 사라지지 않도록 하기 위함)
if "comments" not in st.session_state:
    st.session_state.comments = None       # 정렬된 댓글 목록
if "fetch_error" not in st.session_state:
    st.session_state.fetch_error = None    # 댓글 가져오기 실패 메시지


def _use_example_1():
    st.session_state.url_input = EXAMPLE_1_URL


def _use_example_2():
    st.session_state.url_input = EXAMPLE_2_URL


# 1-1. 예시 버튼 두 개를 나란히 배치
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

# 1-2. 유튜브 링크 입력창 (key로 session_state.url_input과 연결됨)
video_url = st.text_input(
    "유튜브 영상 링크를 붙여넣어주세요",
    key="url_input",
)

# 1-3. 댓글 가져오기 버튼
fetch_clicked = st.button("📥 댓글 가져오기", type="primary")

# ------------------------------------------------------------
# 2. '댓글 가져오기' 버튼을 눌렀을 때의 처리
# ------------------------------------------------------------
if fetch_clicked:
    # 새로 가져오기를 시도하는 것이므로, 이전 결과는 일단 초기화
    st.session_state.comments = None
    st.session_state.fetch_error = None
    # 다른 페이지에 있던 이전 AI 요약 결과도 초기화
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
# 3. 댓글 가져오기 실패 메시지 표시
# ------------------------------------------------------------
if st.session_state.fetch_error:
    st.warning(st.session_state.fetch_error)

# ------------------------------------------------------------
# 4. 댓글이 세션에 저장되어 있다면 항상 화면에 표시
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

    st.success("👈 왼쪽 사이드바에서 'AI 세줄요약' 페이지로 이동해서 요약을 확인해 보세요.")
