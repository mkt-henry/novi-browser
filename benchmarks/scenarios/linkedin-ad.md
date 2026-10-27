# LinkedIn 광고 세팅 벤치마크 시나리오 (방식 코드: {M})

LinkedIn Campaign Manager(https://www.linkedin.com/campaignmanager)에서 아래 광고를 **초안으로만** 만든다.

## 절대 금지
- "캠페인 시작"·"Launch campaign"·"게시"·"광고 세트 시작" 등 집행 버튼을 누르지 않는다.
- 결제 방법 추가·결제 정보 입력 화면이 나오면 거기서 멈춘다.
- 다른 광고 계정, 이미 있는 캠페인·광고 세트·광고는 고치거나 지우지 않는다.
- 회사 페이지·프로필에 글을 올리지 않는다.

## 할 일
1. 광고 계정 목록에서 **bestpartner 광고 계정(Best Partner M&C)**을 찾아 연다.
2. 새 광고 세트(구 UI의 "캠페인")를 만든다. 캠페인 그룹(새 UI의 "캠페인")은 기본으로 생성되는 것을 그대로 써도 된다.
   - 이름: `[BENCH-{M}] SG VC Website Visits`
   - 목표: 웹사이트 방문 (Website visits)
   - 위치: Singapore (싱가포르)
   - 프로필 언어: English
   - 타겟팅(AND 조건):
     - 업종(Industry): Venture Capital and Private Equity Principals (벤처 캐피털·사모 펀드 주체)
     - 직급(Seniority): Partner, CXO, VP, Director
   - 타겟 확장(Audience Expansion / 오디언스 확장): 끔
   - LinkedIn Audience Network: 끔
   - 광고 형식: 단일 이미지 광고 (Single image ad)
   - 예산: 일일 예산 50 USD (계정 통화가 USD가 아니면 그 통화의 50 상당 또는 최소값으로 하고 보고에 적는다)
   - 일정: 2026-11-10 시작, 2026-11-30 종료
   - 입찰 전략: 기본값 그대로
   - 전환 추적: 설정하지 않음
3. 광고 1개를 만든다.
   - 광고 이름: `BENCH-{M} ad 1`
   - 소개 글(Introductory text): `Backing a startup that wants to grow in Korea & Asia? Best Partner M&C runs performance marketing, content and influencer campaigns for portfolio companies.`
   - 이미지: `<이 폴더의 sg_vc_ad.png 절대 경로>`
   - 헤드라인: `Scale your portfolio into Korea & Asia`
   - 목적지 URL: `https://bestpartner.bp-studio.com/?utm_source=linkedin&utm_campaign=bench_{m}`
   - CTA 버튼: 자세히 알아보기 (Learn more)
4. 검토(Review) 단계까지 가서 초안이 저장된 상태로 둔다. 집행 버튼은 누르지 않는다.

## 보고 (마지막에 이 형식 그대로)
```
RESULT
account: <광고 계정 이름과 ID>
campaign_name: ...
campaign_id_or_url: ...
objective: ...
location: ...
language: ...
industry: ...
seniority: ...
audience_expansion: on/off
audience_network: on/off
format: ...
budget: ...
schedule: ...
ad_name: ...
ad_headline: ...
ad_url: ...
ad_cta: ...
ad_image_uploaded: yes/no
launched: no
issues: <막혔던 점·못 한 항목>
screenshot: <검토 화면 캡처 파일 경로>
```
