#!/bin/bash
#--------------------------------------------------------
# upload-github.sh
# Folder တစ်ခုကို GitHub repo အသစ်အဖြစ် တင်ပေးမယ်။
#
# Usage:
#   export GITHUB_TOKEN=ghp_xxxxxxxx        # repo scope ပါတဲ့ token
#   bash upload-github.sh <folder> [repo-name] [public|private]
#
# ဥပမာ:
#   bash upload-github.sh ./zvpn zvpn private
#
# Token ကို git config / remote URL ထဲ မသိမ်းပါ (env ထဲမှာပဲ)။
#--------------------------------------------------------
set -euo pipefail

RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
die() { echo -e "${RED}[x] $*${NC}" >&2; exit 1; }
info() { echo -e "${YELLOW}[*] $*${NC}"; }

FOLDER="${1:-}"
REPO="${2:-}"
VIS="${3:-private}"

[[ -n "$FOLDER" && -d "$FOLDER" ]] || die "Folder မတွေ့ပါ. Usage: bash upload-github.sh <folder> [repo] [public|private]"
[[ -n "${GITHUB_TOKEN:-}" ]] || die "GITHUB_TOKEN မသတ်မှတ်ရသေး. export GITHUB_TOKEN=ghp_... လုပ်ပါ"
command -v git  >/dev/null || die "git မတပ်ရသေး: sudo apt install -y git"
command -v curl >/dev/null || die "curl မတပ်ရသေး: sudo apt install -y curl"
command -v python3 >/dev/null || die "python3 မတပ်ရသေး: sudo apt install -y python3"

[[ "$VIS" == "public" || "$VIS" == "private" ]] || die "visibility က public သို့ private ဖြစ်ရမယ်"

cd "$FOLDER"
FOLDER_ABS="$(pwd)"
[[ -z "$REPO" ]] && REPO="$(basename "$FOLDER_ABS")"
[[ "$REPO" =~ ^[A-Za-z0-9._-]+$ ]] || die "repo နာမည် မှားနေပါတယ် (a-z A-Z 0-9 . _ - သာ)"

# 2) Secret ဖိုင်တွေ ပါမပါ စစ်
SECRETS="$(find . -path ./.git -prune -o \( -name '*.key' -o -name '*.pem' -o -name 'users.json' -o -name 'online.json' -o -name '.env' \) -print)"
if [[ -n "$SECRETS" ]]; then
  echo "$SECRETS"
  die "အထက်က ဖိုင်တွေ secret ဖြစ်နိုင်လို့ ရပ်လိုက်ပါပြီ. ဖယ်ပြီး ပြန်run ပါ (သို့) .gitignore ထည့်ပါ"
fi

# 1) GitHub username
info "GitHub user ကို စစ်နေပါတယ်..."
USER_JSON="$(curl -fsS -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/user)" \
  || die "Token မမှန်ပါ (သို့) network ပြဿနာ"
GH_USER="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["login"])' <<<"$USER_JSON")"
info "User: $GH_USER"

# 3) .gitignore မရှိရင် အခြေခံတစ်ခု ထည့်
if [[ ! -f .gitignore ]]; then
  cat > .gitignore <<'GI'
__pycache__/
*.pyc
*.key
*.pem
*.bak
*.tmp
.env
users.json
online.json
GI
  info ".gitignore ဖန်တီးပြီး"
fi

# 4) Repo ရှိပြီးသားလား စစ်၊ မရှိရင် ဖန်တီး
EXISTS_CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/$GH_USER/$REPO")"
if [[ "$EXISTS_CODE" == "200" ]]; then
  info "Repo '$GH_USER/$REPO' ရှိပြီးသား — ဒီကို push လုပ်မယ်"
else
  info "Repo '$GH_USER/$REPO' ($VIS) ဖန်တီးနေပါတယ်..."
  PRIVATE=$([[ "$VIS" == "private" ]] && echo true || echo false)
  CREATE_RES="$(curl -fsS -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO\",\"private\":$PRIVATE,\"auto_init\":false}")" \
    || die "Repo ဖန်တီးလို့ မရပါ (token မှာ repo scope ရှိလား စစ်ပါ)"
fi

# 5) git init + commit
if [[ ! -d .git ]]; then
  git init -q -b main
fi
git config user.name  >/dev/null 2>&1 || git config user.name  "$GH_USER"
git config user.email >/dev/null 2>&1 || git config user.email "$GH_USER@users.noreply.github.com"
git add -A
if git diff --cached --quiet && git rev-parse HEAD >/dev/null 2>&1; then
  info "ပြောင်းလဲမှု မရှိပါ"
else
  git commit -q -m "Upload $REPO $(date '+%Y-%m-%d %H:%M')" || true
fi

# 6) remote (token မပါ URL) + push (token ကို header နဲ့ပဲ ပို့)
REMOTE_URL="https://github.com/$GH_USER/$REPO.git"
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"
AUTH_B64="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
info "Push လုပ်နေပါတယ်..."
git -c http.extraheader="AUTHORIZATION: basic $AUTH_B64" push -u origin main --force-with-lease \
  || die "Push မအောင်မြင်ပါ"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  GitHub upload ပြီးပါပြီ${NC}"
echo -e "${GREEN}  $REMOTE_URL${NC}"
echo -e "${GREEN}=========================================${NC}"
