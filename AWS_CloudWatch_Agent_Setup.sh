#!/bin/bash
# Download and install the Amazon CloudWatch Agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
rpm -U ./amazon-cloudwatch-agent.rpm

# Create the CloudWatch Agent configuration file
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << EOF
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "cwagent"
  },
  "metrics": {
    "append_dimensions": {
      "InstanceId": "\${aws:InstanceId}",
      "InstanceType": "\${aws:InstanceType}",
      "AutoScalingGroupName": "\${aws:AutoScalingGroupName}",
      "DiskId": "\${aws:ResourceTag/DiskId}"
    },
    "metrics_collected": {
      "disk": {
        "measurement": [
          "used_percent"
        ],
        "resources": [
          "/"
        ],
        "include_fs": ["/dev/xvda1"]
      }
    }
  }
}
EOF

# Start and enable the CloudWatch Agent service
systemctl start amazon-cloudwatch-agent
systemctl enable amazon-cloudwatch-agent
