#!/usr/bin/env bash
# Установка Job Finder одной командой:
#   curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/install.sh | bash
# Папку можно сменить: ... | JOBFINDER_DIR=~/apps/job-finder bash
# Скрипт спросит, что ставить: только Job Finder или Job Finder + Resume Studio.
# Без вопроса: ... | JOBFINDER_WITH_RESUME_STUDIO=1 bash   (0 — только Job Finder)
# Если программа уже стоит, скрипт её обновит.
set -euo pipefail

REPO="${JOBFINDER_REPO:-https://github.com/Postopol/job-finder.git}"
DIR="${JOBFINDER_DIR:-$HOME/job-finder}"
BIN="$HOME/.local/bin"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "нужен git. Поставь его (например: sudo dnf install git или sudo apt install git) и запусти команду снова."
command -v curl >/dev/null || die "нужен curl."

# What to install: env, then the earlier choice, then a question (the script itself comes
# through a pipe, so the answer is read from the terminal), else Job Finder alone.
choice="${JOBFINDER_WITH_RESUME_STUDIO:-}"
if [ -z "$choice" ] && [ -f "$DIR/.install-choice" ]; then
  choice=$(cat "$DIR/.install-choice")
fi
if [ -z "$choice" ] && { : </dev/tty; } 2>/dev/null; then
  echo "Что поставить?"
  echo "  1 — только Job Finder (сбор вакансий)"
  echo "  2 — Job Finder + Resume Studio (резюме и сравнение с вакансией; нужен Node.js 20.9+)"
  printf "Введи 1 или 2 [1]: "
  read -r answer </dev/tty || answer=""
  case "$answer" in 2) choice=1 ;; *) choice=0 ;; esac
fi
case "$choice" in 1|yes|да) choice=1 ;; *) choice=0 ;; esac

if [ "$choice" = 1 ]; then
  command -v node >/dev/null && command -v npm >/dev/null \
    || die "для Resume Studio нужен Node.js 20.9 или новее (например: sudo dnf install nodejs или sudo apt install nodejs npm). Или поставь только Job Finder: ... | JOBFINDER_WITH_RESUME_STUDIO=0 bash"
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=9)?0:1)' \
    || die "для Resume Studio нужен Node.js 20.9 или новее, а стоит $(node -v)."
fi

if ! command -v uv >/dev/null; then
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null; then
  say "Ставлю uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null || die "uv не установился. Поставь его вручную: https://docs.astral.sh/uv/"
fi

if [ -d "$DIR/.git" ]; then
  say "Job Finder уже стоит в $DIR — обновляю"
  git -C "$DIR" pull --ff-only --autostash
elif [ -e "$DIR" ]; then
  die "папка $DIR уже есть, но это не Job Finder. Укажи другую: JOBFINDER_DIR=путь"
else
  say "Скачиваю Job Finder в $DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi

say "Ставлю зависимости"
uv sync --project "$DIR" --no-dev

if [ -f "$DIR/data/jobs.db" ]; then
  say "Пересчитываю собранные вакансии по новым правилам"
  uv run --project "$DIR" --no-dev jobfinder reparse \
    || echo "Пересчёт не удался. Повтори вручную: jobfinder reparse"
fi

mkdir -p "$BIN"
cat > "$BIN/jobfinder" <<EOF
#!/usr/bin/env bash
exec uv run --project "$DIR" --no-dev jobfinder "\$@"
EOF
chmod +x "$BIN/jobfinder"

if [ "$choice" = 1 ]; then
  say "Ставлю Resume Studio (несколько минут)"
  (cd "$DIR/resume-studio" && npm ci --no-audit --no-fund && npm run build)
  say "Ставлю браузер для PDF-экспорта"
  (cd "$DIR/resume-studio" && npx --no-install playwright-core install chromium) \
    || echo "Браузер не поставился, резюме в PDF выгружаться не будет. Повтори: cd $DIR/resume-studio && npx playwright-core install chromium"
  printf '#!/usr/bin/env bash\ncd "%s/resume-studio" && exec npm start -- "$@"\n' "$DIR" > "$BIN/resume-studio"
  chmod +x "$BIN/resume-studio"
fi
echo "$choice" > "$DIR/.install-choice"

say "Готово"
echo "Запуск:      jobfinder serve   (потом открой http://127.0.0.1:8000)"
if [ "$choice" = 1 ]; then
  echo "             resume-studio     (в другом терминале; открой http://127.0.0.1:3000)"
else
  echo "Resume Studio не ставил. Поставить позже: ... | JOBFINDER_WITH_RESUME_STUDIO=1 bash"
fi
echo "Обновление:  curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/update.sh | bash"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Команда jobfinder лежит в $BIN, а этой папки нет в PATH. Перезапусти терминал или добавь в ~/.bashrc строку:"
     echo "  export PATH=\"$BIN:\$PATH\"" ;;
esac
