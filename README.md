# Music Passport

음악으로 떠나는 새로운 여행을 제안하는 Streamlit 웹 애플리케이션입니다.

## 실행

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

현재는 외부 API 연동이나 페이지 이동 없이 AI 여행 컨시어지와 대화하며
기분, 상황, 도시를 차례로 선택할 수 있습니다. 선택 내용과 진행 단계는
Streamlit 세션에 유지되며, 언제든 대화를 다시 시작할 수 있습니다.
