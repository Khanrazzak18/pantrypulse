#!/usr/bin/env bash
# Tears down everything PantryPulse created on AWS. Never touches the clausecompass service, the shared
# load balancer or the default cluster. Run via `make aws-down CONFIRM=yes`.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_REGION=us-east-1 AWS_PAGER=
[ "${CONFIRM:-}" = yes ] || { echo "This deletes the PantryPulse service, database, uploads and secrets. Re-run with CONFIRM=yes."; exit 1; }
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="pantrypulse-uploads-${ACCOUNT}-${AWS_REGION}"

echo "1/5 deleting the ECS Express service (removes its target group and listener rule)"
aws ecs delete-express-gateway-service --service-arn "arn:aws:ecs:${AWS_REGION}:${ACCOUNT}:service/default/pantrypulse" >/dev/null 2>&1 || echo "  (no service)"
echo "2/5 emptying the uploads bucket"
aws s3 rm "s3://${BUCKET}" --recursive >/dev/null 2>&1 || true
echo "3/5 deleting images in ECR"
aws ecr batch-delete-image --repository-name pantrypulse \
  --image-ids "$(aws ecr list-images --repository-name pantrypulse --query 'imageIds[*]' --output json 2>/dev/null || echo '[]')" >/dev/null 2>&1 || true
echo "4/5 deleting the base stack (RDS, bucket, roles, security groups, log groups, ECR, OIDC role)"
aws cloudformation delete-stack --stack-name pantrypulse-base
aws cloudformation wait stack-delete-complete --stack-name pantrypulse-base
echo "5/5 deleting the SecureString parameters"
for p in $(aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/pantrypulse --query 'Parameters[].Name' --output text); do
  aws ssm delete-parameter --name "$p"
done
echo "Done. The clausecompass service and the shared load balancer were left alone."
