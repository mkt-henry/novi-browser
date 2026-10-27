# X 게시물 작성 벤치마크 시나리오 (방식 코드: {M})

X(https://x.com)의 @bitpro_kr(비트프로 BitPro) 계정에서 게시물을 **게시 직전까지만** 작성한다.

## 절대 금지
- "게시하기"·"Post"·"모두 게시"·"Post all"·"예약하기"·"Schedule" 버튼을 누르지 않는다.
- Ctrl+Enter(Cmd+Enter)를 누르지 않는다(바로 게시된다). 글 칸에서 Enter만 누르는 것은 줄바꿈이라 괜찮다.
- 이미 있는 게시물·임시저장 글을 고치거나 지우지 않는다. 좋아요·리포스트·답글·팔로우를 하지 않는다.
- 작성 창을 닫거나 "삭제/Discard"·"저장/Save"를 누르지 않는다. 다 채운 작성 창을 그대로 열어 둔다(시험 감독이 확인한 뒤 직접 지운다).

## 할 일
1. x.com 홈에서 로그인한 계정이 @bitpro_kr인지 확인한다.
2. 새 게시물 작성 창을 연다(왼쪽 "게시하기/Post" 버튼으로 여는 작성 창 또는 x.com/compose/post).
3. 첫 번째 글에 아래 글을 줄바꿈까지 그대로 넣는다(두 줄):
   ```
   [BENCH-{M}] 브라우저 비교 시험 글입니다. 게시하지 않습니다.
   #bench https://bit-pro.app/?utm_source=x&utm_campaign=bench_{m}
   ```
4. 첫 번째 글에 이미지 `<이 폴더의 sg_vc_ad.png 절대 경로>`를 붙인다.
5. 그 이미지에 대체 텍스트(ALT·설명)를 `BENCH-{M} test image: Singapore VC ad draft`로 넣고 저장한다.
6. 스레드로 두 번째 글을 더한다("+" 게시물 추가 버튼). 두 번째 글: `[BENCH-{M}] 두 번째 글 (스레드) ✅`
7. 답글 설정을 "모든 사람" 대신 "내가 팔로우하는 계정"(Accounts you follow)으로 바꾼다.
8. 작성 창 전체를 캡처하고, 게시 버튼은 누르지 않은 채 작성 창을 열어 둔 상태로 끝낸다.

## 보고 (마지막에 이 형식 그대로)
```
RESULT
account: <로그인 계정 @아이디>
post1_text: <첫 번째 글 칸에 실제로 들어간 글, 줄바꿈은 \n>
image_attached: yes/no
image_alt: <저장된 대체 텍스트>
post2_text: <두 번째 글 칸에 실제로 들어간 글>
reply_setting: <바뀐 답글 설정 이름>
composer_left_open: yes/no
posted: no
issues: <막혔던 점·못 한 항목>
screenshot: <작성 창 캡처 파일 경로>
```
