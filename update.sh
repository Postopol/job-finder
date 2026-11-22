#!/usr/bin/env bash
# Обновление Job Finder одной командой:
#   curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/update.sh | bash
# База (data/jobs.db), статусы и настройки сохраняются.
set -euo pipefail

DIR="${JOBFINDER_DIR:-$HOME/job-finder}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

[ -d "$DIR/.git" ] || die "Job Finder не найден в $DIR. Сначала установи:
  curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/install.sh | bash
Если ставил в другую папку: ... | JOBFINDER_DIR=путь bash"
command -v uv >/dev/null || die "не найден uv. Запусти установку заново, она его поставит."

old=$(git -C "$DIR" rev-parse --short HEAD)
say "Скачиваю обновления"
git -C "$DIR" pull --ff-only --autostash
new=$(git -C "$DIR" rev-parse --short HEAD)

if [ "$old" = "$new" ]; then
  say "Уже последняя версия ($new)"
  exit 0
fi

say "Обновляю зависимости"
uv sync --project "$DIR" --no-dev

if [ "$(cat "$DIR/.install-choice" 2>/dev/null)" = 1 ] \
   && ! git -C "$DIR" diff --quiet "$old" "$new" -- resume-studio; then
  say "Пересобираю Resume Studio"
  (cd "$DIR/resume-studio" && npm ci --no-audit --no-fund && npm run build) \
    || echo "Resume Studio не пересобрался. Повтори: cd $DIR/resume-studio && npm ci && npm run build"
fi

if [ -f "$DIR/data/jobs.db" ]; then
  say "Пересчитываю собранные вакансии по новым правилам"
  uv run --project "$DIR" --no-dev jobfinder reparse \
    || echo "Пересчёт не удался. Повтори вручную: jobfinder reparse"
fi

say "Обновлено: $old → $new"
git -C "$DIR" log --oneline "$old..$new" | sed 's/^/  /'
echo "Если сервер запущен, перезапусти его: Ctrl+C и снова jobfinder serve (и resume-studio, если он стоит)"
