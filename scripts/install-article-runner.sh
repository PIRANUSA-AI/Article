#!/usr/bin/env bash
set -euo pipefail

# Registration token is read from stdin, never written into this repository.
read -r registration_token
read -r archive_url
read -r archive_digest
[[ "$archive_url" == https://github.com/actions/runner/releases/download/*/actions-runner-linux-x64-*.tar.gz ]]
[[ "$archive_digest" =~ ^[0-9a-f]{64}$ ]]

runner_user=artikel-runner
runner_dir=/opt/github-runners/artikel
if ! id "$runner_user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$runner_user"
fi
install -d -o "$runner_user" -g "$runner_user" -m 0750 "$runner_dir"
install -m 0755 "${1:-/var/www/artikel/scripts/deploy-article.sh}" /usr/local/sbin/deploy-article
printf '%s\n' 'artikel-runner ALL=(root) NOPASSWD: /usr/local/sbin/deploy-article' > /etc/sudoers.d/artikel-runner
chmod 0440 /etc/sudoers.d/artikel-runner
visudo -cf /etc/sudoers.d/artikel-runner

cd "$runner_dir"
if [[ ! -f .runner ]]; then
    archive="$(mktemp /tmp/artikel-runner.XXXXXX.tar.gz)"
    trap 'rm -f "$archive"' EXIT
    curl --fail --location --retry 3 --max-time 180 "$archive_url" --output "$archive"
    printf '%s  %s\n' "$archive_digest" "$archive" | sha256sum --check --status
    tar -xzf "$archive" -C "$runner_dir"
    chown -R "$runner_user:$runner_user" "$runner_dir"
    runuser -u "$runner_user" -- ./config.sh --unattended \
        --url https://github.com/PIRANUSA-AI/Article \
        --token "$registration_token" --name artikel-vps \
        --labels artikel-vps --work _work
fi
unset registration_token
if [[ ! -f .service ]]; then
    ./svc.sh install "$runner_user"
fi
./svc.sh start
./svc.sh status
