#!/usr/bin/env bash
set -euo pipefail

revision="${1:-}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA.' >&2; exit 2; }
exec 9>/var/lock/deploy-article.lock
flock -w 900 9

cd /var/www/artikel
[[ "$(git remote get-url origin)" == 'https://github.com/PIRANUSA-AI/Article.git' ]]
[[ "$(git branch --show-current)" == 'main' ]]
git diff --quiet
git diff --cached --quiet
environment_file=/var/www/artikel/bot/.env
test -f "$environment_file"
environment_before="$(sha256sum "$environment_file")"
git fetch --no-tags origin main
latest="$(git rev-parse origin/main)"
if [[ "$revision" != "$latest" ]]; then
    echo 'Skipping a superseded deployment; a newer main commit exists.'
    exit 0
fi
git merge --ff-only "$revision"
[[ "$environment_before" == "$(sha256sum "$environment_file")" ]]

cd bot
docker compose build piranusa-bot
docker compose run --rm --no-deps -T \
    -e BOT_DATA_DIR=/tmp/article-offline-validation \
    -e QWEN_API_KEY=offline-tests \
    -e TELEGRAM_BOT_TOKEN=123456:offline-tests \
    --entrypoint sh piranusa-bot -c 'python selftest.py && python test_sources.py'
docker compose up -d --no-build piranusa-bot
for attempt in $(seq 1 20); do
    if [[ "$(docker inspect --format '{{.State.Running}}' piranusa-bot)" == 'true' ]]; then
        sleep 3
        if [[ "$(docker inspect --format '{{.State.Running}} {{.RestartCount}}' piranusa-bot)" == 'true 0' ]]; then
            [[ "$environment_before" == "$(sha256sum "$environment_file")" ]]
            install -m 0755 ../scripts/deploy-article.sh /usr/local/sbin/deploy-article
            echo "Deployed Artikel revision $revision; container is running."
            exit 0
        fi
    fi
    sleep 2
done
echo 'Container did not stabilize after deployment.' >&2
exit 1
