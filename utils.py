"""
공통 함수 모음
--------------------------------
main.py(메인 페이지)와 pages/00_세줄요약.py(AI 요약 페이지)가
똑같이 가져다 쓰는 함수들을 여기 한 곳에 모아둡니다.

이렇게 함수를 한 곳에 모아두면, 나중에 오류를 고치거나
로직을 바꿀 때 이 파일 하나만 고치면 되므로
main.py와 pages 파일이 서로 다르게 동작하는 문제를 막을 수 있습니다.
"""

from urllib.parse import urlparse, parse_qs

import requests
from openai import OpenAI

# 유튜브 댓글 API 주소 (고정된 값)
YOUTUBE_COMMENT_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

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
# 3. Solar API(solar-open2)로 댓글 전체를 세 줄 요약하는 함수
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
