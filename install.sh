#!/usr/bin/env bash
# Установка Job Finder одной командой:
#   curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/install.sh | bash
# Папку можно сменить: ... | JOBFINDER_DIR=~/apps/job-finder bash
# Если программа уже стоит, скрипт её обновит.
set -euo pipefail

REPO="https://github.com/Postopol/job-finder.git"
DIR="${JOBFINDER_DIR:-$HOME/job-finder}"
BIN="$HOME/.local/bin"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "нужен git. Поставь его (например: sudo dnf install git или sudo apt install git) и запусти команду снова."
command -v curl >/dev/null || die "нужен curl."

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

mkdir -p "$BIN"
cat > "$BIN/jobfinder" <<EOF
#!/usr/bin/env bash
exec uv run --project "$DIR" --no-dev jobfinder "\$@"
EOF
chmod +x "$BIN/jobfinder"

say "Готово"
echo "Запуск:      jobfinder serve   (потом открой http://127.0.0.1:8000)"
echo "Обновление:  curl -LsSf https://raw.githubusercontent.com/Postopol/job-finder/main/update.sh | bash"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Команда jobfinder лежит в $BIN, а этой папки нет в PATH. Перезапусти терминал или добавь в ~/.bashrc строку:"
     echo "  export PATH=\"$BIN:\$PATH\"" ;;
esac
