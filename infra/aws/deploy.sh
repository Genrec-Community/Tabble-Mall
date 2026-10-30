#!/usr/bin/env bash
# One-command AWS deployment for a v1/demo setup (spec §: "v1 runs on EC2"):
#   CloudFront (HTTPS, WebSockets) -> EC2 running nginx + web + api via docker compose -> RDS Postgres 17.
# Images: a private S3 bucket served through a second CloudFront distribution.
# App settings and secrets live in SSM Parameter Store under $PREFIX and are written to the
# instance's .env at boot. Safe to re-run: existing resources are reused, and the source is
# re-uploaded and redeployed through SSM Run Command.
#
# Needs: aws CLI v2 with credentials for the target account, git, openssl.
# Usage: infra/aws/deploy.sh            (from the repo root)
set -euo pipefail

REGION=${AWS_DEFAULT_REGION:-ap-south-1}
NAME=${NAME:-tabble-mall}
PREFIX="/$NAME/env"
INSTANCE_TYPE=${INSTANCE_TYPE:-t3.small}
DB_CLASS=${DB_CLASS:-db.t4g.micro}
export AWS_DEFAULT_REGION=$REGION AWS_PAGER=""

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="$NAME-$ACCOUNT-$REGION"
MEDIA_BUCKET="$NAME-media-$ACCOUNT-$REGION"
TAG="ResourceType=%s,Tags=[{Key=Name,Value=$NAME},{Key=app,Value=$NAME}]"
log() { printf '\n== %s\n' "$*"; }

param_exists() { aws ssm get-parameter --name "$PREFIX/$1" >/dev/null 2>&1; }
put_param() { aws ssm put-parameter --name "$PREFIX/$1" --type "${3:-String}" --value "$2" --overwrite >/dev/null; }
put_secret_once() { param_exists "$1" || put_param "$1" "$(openssl rand -base64 48 | tr -d '\n/+=')" SecureString; }

log "Account $ACCOUNT, region $REGION"

log "Buckets"
for b in "$BUCKET" "$MEDIA_BUCKET"; do
  aws s3api head-bucket --bucket "$b" 2>/dev/null ||
    aws s3api create-bucket --bucket "$b" --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$b" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
done
aws s3api put-bucket-cors --bucket "$MEDIA_BUCKET" --cors-configuration \
  '{"CORSRules":[{"AllowedMethods":["PUT","GET"],"AllowedOrigins":["*"],"AllowedHeaders":["*"],"MaxAgeSeconds":3000}]}'

log "Network"
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
sg() {
  local id
  id=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$1" "Name=vpc-id,Values=$VPC" \
    --query 'SecurityGroups[0].GroupId' --output text)
  if [ "$id" = "None" ]; then
    id=$(aws ec2 create-security-group --group-name "$1" --description "$2" --vpc-id "$VPC" --query GroupId --output text)
  fi
  echo "$id"
}
WEB_SG=$(sg "$NAME-web" "HTTP from CloudFront only")
DB_SG=$(sg "$NAME-db" "Postgres from the app instance")
CF_PL=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$WEB_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$CF_PL}]" >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --group-id "$DB_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=$WEB_SG}]" >/dev/null 2>&1 || true

log "Database (RDS PostgreSQL 17)"
DB_ID="$NAME-db"
put_secret_once DB_PASSWORD_RAW
if ! aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  aws rds create-db-instance --db-instance-identifier "$DB_ID" --engine postgres --engine-version 17 \
    --db-instance-class "$DB_CLASS" --allocated-storage 20 --storage-type gp3 \
    --master-username mallt \
    --master-user-password "$(aws ssm get-parameter --name "$PREFIX/DB_PASSWORD_RAW" --with-decryption --query Parameter.Value --output text)" \
    --db-name mallt --vpc-security-group-ids "$DB_SG" --no-publicly-accessible \
    --backup-retention-period 7 --storage-encrypted --tags "Key=app,Value=$NAME" >/dev/null
fi

log "Instance role"
ROLE="$NAME-ec2"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name app --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject"],"Resource":"arn:aws:s3:::$BUCKET/*"},
  {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::$MEDIA_BUCKET/*"},
  {"Effect":"Allow","Action":["ssm:GetParametersByPath","ssm:GetParameter"],"Resource":"arn:aws:ssm:$REGION:$ACCOUNT:parameter$PREFIX*"}
]}
JSON
)"

log "Source bundle"
git archive --format=tar.gz -o /tmp/$NAME-source.tar.gz HEAD
aws s3 cp /tmp/$NAME-source.tar.gz "s3://$BUCKET/source.tar.gz" >/dev/null

log "Instance"
INSTANCE=$(aws ec2 describe-instances --filters "Name=tag:app,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
NEW_INSTANCE=false
if [ "$INSTANCE" = "None" ]; then
  NEW_INSTANCE=true
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
  USER_DATA=$(sed -e "s|__REGION__|$REGION|" -e "s|__BUCKET__|$BUCKET|" -e "s|__PREFIX__|$PREFIX|" "$(dirname "$0")/user-data.sh")
  sleep 10  # a just-created instance profile takes a moment to become usable
  INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
    --iam-instance-profile "Name=$ROLE" --security-group-ids "$WEB_SG" \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3}' \
    --metadata-options HttpTokens=required \
    --tag-specifications "$(printf "$TAG" instance)" --user-data "$USER_DATA" \
    --query 'Instances[0].InstanceId' --output text)
fi
aws ec2 wait instance-running --instance-ids "$INSTANCE"
ORIGIN=$(aws ec2 describe-instances --instance-ids "$INSTANCE" --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

log "CloudFront"
CACHING_DISABLED=4135ea2d-6df8-44a3-9df3-4b5a84be39ad
CACHING_OPTIMIZED=658327ea-f89d-4fab-a63d-7e88639e58f6
ALL_VIEWER=216adef6-5c7f-47e4-b989-5492eafa07d3
dist_id() { aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='$1'].Id | [0]" --output text; }

# App: everything goes to the instance uncached (pages, API, WebSockets).
DIST=$(dist_id "$NAME")
if [ "$DIST" = "None" ] || [ -z "$DIST" ]; then
  DIST=$(aws cloudfront create-distribution --distribution-config "$(cat <<JSON
{"CallerReference":"$NAME-$(date +%s)","Comment":"$NAME","Enabled":true,"PriceClass":"PriceClass_200",
 "Origins":{"Quantity":1,"Items":[{"Id":"app","DomainName":"$ORIGIN",
  "CustomOriginConfig":{"HTTPPort":80,"HTTPSPort":443,"OriginProtocolPolicy":"http-only","OriginReadTimeout":60}}]},
 "DefaultCacheBehavior":{"TargetOriginId":"app","ViewerProtocolPolicy":"redirect-to-https","Compress":true,
  "AllowedMethods":{"Quantity":7,"Items":["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],"CachedMethods":{"Quantity":2,"Items":["GET","HEAD"]}},
  "CachePolicyId":"$CACHING_DISABLED","OriginRequestPolicyId":"$ALL_VIEWER"}}
JSON
)" --query Distribution.Id --output text)
fi
DOMAIN=$(aws cloudfront get-distribution --id "$DIST" --query Distribution.DomainName --output text)

# Media: the private image bucket, read through Origin Access Control and cached at the edge.
MEDIA_DIST=$(dist_id "$NAME-media")
if [ "$MEDIA_DIST" = "None" ] || [ -z "$MEDIA_DIST" ]; then
  OAC=$(aws cloudfront create-origin-access-control --origin-access-control-config \
    "Name=$NAME-media,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
    --query OriginAccessControl.Id --output text)
  MEDIA_DIST=$(aws cloudfront create-distribution --distribution-config "$(cat <<JSON
{"CallerReference":"$NAME-media-$(date +%s)","Comment":"$NAME-media","Enabled":true,"PriceClass":"PriceClass_200",
 "Origins":{"Quantity":1,"Items":[{"Id":"media","DomainName":"$MEDIA_BUCKET.s3.$REGION.amazonaws.com",
  "S3OriginConfig":{"OriginAccessIdentity":""},"OriginAccessControlId":"$OAC"}]},
 "DefaultCacheBehavior":{"TargetOriginId":"media","ViewerProtocolPolicy":"redirect-to-https","Compress":true,
  "AllowedMethods":{"Quantity":2,"Items":["GET","HEAD"],"CachedMethods":{"Quantity":2,"Items":["GET","HEAD"]}},
  "CachePolicyId":"$CACHING_OPTIMIZED"}}
JSON
)" --query Distribution.Id --output text)
  aws s3api put-bucket-policy --bucket "$MEDIA_BUCKET" --policy "$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"cloudfront.amazonaws.com"},"Action":"s3:GetObject",
 "Resource":"arn:aws:s3:::$MEDIA_BUCKET/*","Condition":{"StringEquals":{"AWS:SourceArn":"arn:aws:cloudfront::$ACCOUNT:distribution/$MEDIA_DIST"}}}]}
JSON
)"
fi
MEDIA_DOMAIN=$(aws cloudfront get-distribution --id "$MEDIA_DIST" --query Distribution.DomainName --output text)

log "Waiting for the database"
aws rds wait db-instance-available --db-instance-identifier "$DB_ID"
DB_HOST=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --query 'DBInstances[0].Endpoint.Address' --output text)
DB_PASSWORD=$(aws ssm get-parameter --name "$PREFIX/DB_PASSWORD_RAW" --with-decryption --query Parameter.Value --output text)

log "App settings ($PREFIX)"
put_param DATABASE_URL "postgresql://mallt:$DB_PASSWORD@$DB_HOST:5432/mallt?sslmode=require" SecureString
unset DB_PASSWORD
put_secret_once JWT_SECRET
put_secret_once OTP_PEPPER
put_param ENV "${APP_ENV:-dev}"
put_param COOKIE_SECURE true
put_param CORS_ORIGINS "[\"https://$DOMAIN\"]"
put_param SMS_BACKEND "${SMS_BACKEND:-console}"
put_param S3_REGION "$REGION"
put_param S3_BUCKET "$MEDIA_BUCKET"
put_param S3_PUBLIC_BASE_URL "https://$MEDIA_DOMAIN"
# Optional, only when provided by the caller.
[ -n "${FAST2SMS_API_KEY:-}" ] && put_param FAST2SMS_API_KEY "$FAST2SMS_API_KEY" SecureString
[ -n "${GOOGLE_CLIENT_ID:-}" ] && put_param GOOGLE_CLIENT_ID "$GOOGLE_CLIENT_ID"

if [ "$NEW_INSTANCE" = false ]; then
  log "Redeploying on $INSTANCE"
  aws ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
    --parameters 'commands=["/usr/local/bin/tabble-deploy"]' --query Command.CommandId --output text
else
  log "First boot builds the images (about 10 minutes). Re-run this script later to redeploy."
fi

log "Done"
echo "Site:      https://$DOMAIN"
echo "Instance:  $INSTANCE ($ORIGIN)"
echo "Database:  $DB_HOST"
