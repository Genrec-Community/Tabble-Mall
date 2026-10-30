#!/bin/bash
# EC2 boot script (Amazon Linux 2023). deploy.sh substitutes __REGION__, __BUCKET__, __PREFIX__.
set -euxo pipefail
REGION=__REGION__ BUCKET=__BUCKET__ PREFIX=__PREFIX__

dnf install -y docker git
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# The Next.js build needs more memory than a small instance has.
if [ ! -f /swapfile ]; then fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile; fi
systemctl enable --now docker

cat > /usr/local/bin/tabble-deploy <<SCRIPT
#!/bin/bash
# Pull the latest source bundle and app settings, then rebuild and restart the stack.
set -euo pipefail
mkdir -p /opt/tabble && cd /opt/tabble
aws s3 cp "s3://$BUCKET/source.tar.gz" /tmp/source.tar.gz --region "$REGION"
find /opt/tabble -mindepth 1 -maxdepth 1 ! -name .env -exec rm -rf {} +
tar -xzf /tmp/source.tar.gz -C /opt/tabble
aws ssm get-parameters-by-path --region "$REGION" --path "$PREFIX/" --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text \
  | while IFS=\$'\t' read -r name value; do echo "\${name##*/}=\$value"; done > /opt/tabble/.env
chmod 600 /opt/tabble/.env
FILES="-f docker-compose.yml -f infra/aws/docker-compose.aws.yml"
grep -q '^LOCAL_DB=true$' .env && FILES="\$FILES -f infra/aws/docker-compose.localdb.yml"
docker compose \$FILES up -d --build nginx web api
docker image prune -f
SCRIPT
chmod +x /usr/local/bin/tabble-deploy
# deploy.sh writes DATABASE_URL once RDS is up; wait for it rather than boot without a database.
until aws ssm get-parameter --region "$REGION" --name "$PREFIX/DATABASE_URL" >/dev/null 2>&1; do sleep 20; done
/usr/local/bin/tabble-deploy
