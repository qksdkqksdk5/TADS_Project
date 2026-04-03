Markdown
# 🤝 TADS 프로젝트 협업 가이드 (Contributing Guidelines)

TADS(Traffic Monitoring and Anomaly Detection) 프로젝트에 참여해 주셔서 감사합니다! 
우리 팀의 일관된 코드 관리와 안정적인 배포를 위해 아래 규칙을 반드시 준수해 주세요.

---

## 📍 1. 저장소 구조 (Repository Strategy)

우리 프로젝트는 **Fork & Pull Request** 모델을 사용합니다.

- **Upstream (팀장 저장소):** 최종 코드가 모이는 공식 본진 (배포용)
- **Origin (내 저장소):** 본인 계정으로 Fork한 개인 저장소 (백업/제출용)
- **Local (내 컴퓨터):** 실제로 코딩을 진행하는 작업 공간

---

## 🚀 2. 개발 워크플로우 (Step-by-Step)

### Step 1. 작업 시작 전 (최신화)
매일 작업을 시작하기 전, 팀장의 최신 코드를 내 컴퓨터로 가져와야 충돌을 방지할 수 있습니다.
```bash
# 메인 브랜치로 이동
git checkout main

# 팀장(upstream)의 최신 코드 pull
git pull upstream main
Step 2. 브랜치 생성 (Branching)
절대로 main 브랜치에서 직접 코딩하지 마세요. 반드시 기능별 브랜치를 생성합니다.

Bash
# 브랜치 이름 규칙: feature/기능명 또는 fix/버그명
git checkout -b feature/기능명
Step 3. 작업 및 커밋 (Commit)
작업 단위별로 자주 커밋해 주세요. 커밋 메시지는 한글로 작성해도 좋습니다.

Bash
git add .
git commit -m "feat: 기능 요약"
Step 4. 제출 (Push & PR)
작업이 완료되면 본인의 깃허브(origin)에 올리고 PR을 날립니다.

Bash
# 내 깃허브로 푸시
git push origin feature/기능명
GitHub 웹페이지 접속 후 [Compare & pull request] 클릭

변경 사항 요약 작성 후 [Create pull request] 클릭

⚠️ 3. 협업 골든 룰 (Golden Rules)
PR 전 Pull 필수: PR을 날리기 직전에 반드시 git pull upstream main을 실행하여 최신 상태인지 확인하세요.

공통 파일 수정 주의: .env, docker-compose.yml, requirements.txt, package.json 등 프로젝트 공통 설정 파일을 수정할 때는 반드시 팀장(이동훈)과 사전 협의가 필요합니다.

코드 리뷰: 팀장이 PR을 검토하고 Merge 버튼을 누르기 전까지는 배포되지 않습니다. 수정 요청이 오면 해당 브랜치에서 다시 수정 후 push 하세요.

망했을 땐 SOS: 로컬 코드가 심하게 꼬였다면 고민하지 말고 팀장에게 공유해 주세요.

🛠️ 4. 브랜치 네이밍 컨벤션
feature/ : 새로운 기능 추가

fix/ : 버그 수정

docs/ : 문서 수정

refactor/ : 코드 리팩토링

Happy Coding! 🚀


---

### 2단계: `README.md` 수정하기
기존에 있던 `README.md` 파일을 열어서 **맨 아랫줄**에 이 내용을 추가하세요.

```markdown

---
## 🤝 협업 가이드
우리 프로젝트의 협업 규칙(Fork, PR, 브랜치 전략)은 **[CONTRIBUTING.md](./CONTRIBUTING.md)**에서 확인하실 수 있습니다. 
작업 시작 전 반드시 숙지해 주세요!
3단계: 깃허브에 올리기 (터미널)
파일을 저장했다면 터미널에 아래 명령어를 쳐서 동훈님의 깃허브에 올리세요.

Bash
git add .
git commit -m "docs: 협업 가이드 및 CONTRIBUTING 파일 추가"
git push origin main