#!/usr/bin/env bash
# Runs the one-off bootstrap task (migrate, seed, backtest, forecast, allocation) at 2 vCPU / 4 GB.
# It only does the steps whose data is missing, so running it again is safe. `make aws-bootstrap`.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_REGION=us-east-1 AWS_PAGER=
SG=$(aws cloudformation describe-stacks --stack-name pantrypulse-base --query "Stacks[0].Outputs[?OutputKey=='ServiceSecurityGroup'].OutputValue" --output text)
SUBNETS=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true --query 'Subnets[:2].SubnetId' --output text | tr '\t' ',')
TASK=$(aws ecs run-task --cluster default --launch-type FARGATE --task-definition pantrypulse-bootstrap \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text)
echo "started ${TASK##*/}; logs: aws logs tail /pantrypulse/bootstrap --follow"
aws ecs wait tasks-stopped --cluster default --tasks "$TASK"
aws ecs describe-tasks --cluster default --tasks "$TASK" --query 'tasks[0].containers[0].exitCode' --output text
